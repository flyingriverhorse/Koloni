"""The project's memory (`app.memory`): what an agent is briefed with and what it no longer
is given, remember / recall; and, beside them in the runner, the user's note on a turn's
notebook (`note_from_user`) and an agent's turn on a message (`_reply_turn`) - `MemoryMixin`.
"""

import re
from dataclasses import replace
from typing import TYPE_CHECKING

from sqlalchemy import func, literal_column, select
from sqlalchemy.orm import Session

from app import earlier, handoff, injection, knows, koloni, project_map
from app import memory as kept
from app.agent.cards import _at_a_step_limit
from app.agent.ctx import TERMINAL, Ctx, announce_memory
from app.agent.words import (
    ANSWER_TOOLS,
    GIVEN_ONCE,
    HOW_CONTINUE,
    HOW_RAISE,
    NO_GO_ON,
    NO_MORE_GO_ON,
    NO_STEPS_LEFT,
)
from app.db.models import Agent, Conversation, Merge, Message, Project, Run, ToolCall, now
from app.roles import find_role
from app.serialize import message_out
from app.tools import ToolError, parse_arguments
from app.workspace import Workspace, WorkspaceError

if TYPE_CHECKING:
    from app.agent import AgentRunner

NOBODY_FOR_THE_CORE = (
    "nothing is put forward for the core in a turn nobody is watching: nobody is here to "
    "ask. Leave propose out to keep it as a note."
)


class MemoryMixin:
    # --- the project's memory ---------------------------------------------------

    def _project(self: "AgentRunner", session, cid: str) -> Project | None:
        return session.scalar(
            select(Project)
            .join(Conversation, Conversation.project_id == Project.id)
            .where(Conversation.id == cid)
        )

    def _work_of(self: "AgentRunner", session: Session, ctx: Ctx) -> str | None:
        """What an agent is on: its task; the lead's is the user's message of the turn."""
        return ctx.task if ctx.depth > 0 else session.scalar(
            select(Message.content)
            .where(Message.run_id == ctx.run_id, Message.role.in_(("user", "trigger")))
            .order_by(Message.created_at, literal_column("messages.rowid"))
            .limit(1)
        )

    def _briefing(self: "AgentRunner", ctx: Ctx, can_recall: bool) -> tuple[str, list[str] | None]:
        """What the project's memory adds to this agent's instructions: the user's rules
        and the facts of the core that its work names the subject of, read when the agent
        takes its first step and the same from then on. Its work is its task; the lead's
        is the user's message of the turn. Looking the rest up is spoken of only to an
        agent that is offered `recall` in that request (`can_recall`). The first time it
        also returns the facts in it - for `_briefed_with`, once the request they are in
        has been built; None after that."""
        if ctx.agent_id in self._briefed:
            return self._briefed[ctx.agent_id], None
        with self._factory() as session:
            project = self._project(session, ctx.cid)
            if project is None:
                return "", []
            work = self._work_of(session, ctx)
            # (K-devir-2: a sub-agent's role names the work too, so that the user's words at
            # a card on a role's work reach its next agent - "feedback: Reviewer".)
            said, given = kept.briefing(
                session, project, f"{ctx.role} {work or ''}" if ctx.depth > 0 else work or "",
                can_recall)
            handed, from_ids = "", []
            # (Not to a speaker in a discussion: it has no task of its own there.)
            if not ctx.continues_id and not ctx.discussion and (ctx.depth > 0 or session.scalar(
                    select(Run.id).where(Run.conversation_id == ctx.cid,
                                         Run.id != ctx.run_id).limit(1)) is None):
                # K-devir-1: what the project's last agents on this work did and left, after
                # the user's rules and the memory's facts (data after instructions); a new
                # conversation's lead gets the last of them whatever they did. Not to an agent
                # that goes on from itself: its chain has it.
                handed, from_ids = handoff.earlier_on(
                    session, project, work if ctx.depth > 0 else None, ctx.part,
                    handoff.paths_in(work or ""), ctx.cid)
                if ctx.depth == 0:
                    # K-devir-3: and the project's last commits, read off git (no git: nothing).
                    handed = "\n\n".join(p for p in (
                        handed, handoff.commits(project.root_path)) if p)
            self._handed_from[ctx.agent_id] = from_ids
            noted = ""
            if ctx.depth == 1 and not ctx.continues_id and not ctx.discussion and (
                    team := self._team_of(session, ctx.cid, ctx.run_id, ctx.agent_id)
            ) and self._leads_teams(session, ctx):
                # K-devir-5: a team's new lead is given what the leads noted for its team in
                # the turn before, and what a room between teams decided then. Once: the
                # briefing is built once an agent (`_briefed`); a new turn's lead is a new agent.
                # shortcut: not in a plain chat (no project: nothing is briefed there at all);
                # lift it above the project check if teams are run in plain chats.
                noted = self._noted_for_team(session, ctx, team[0])
            said = "\n\n".join(p for p in (said, handed, noted) if p)
            if ctx.depth == 0 or ctx.part:
                # The lead is given the folder's AGENTS.md or CLAUDE.md, read only (slice 86c);
                # an agent in a part (K-buyuk-proje) that too, then the part's, and where it is.
                # shortcut: a CLI that reads the file itself is given it twice; leave it out
                # for that CLI if the doubled size is met.
                # shortcut: a part's test command is the map's only once the turn's map is made
                # (a Lead's first step does not wait for it), else "none known"; wait for it
                # if Leads in a part miss it.
                # K-belge-haritasi: the Lead is told which documents there are, to read on need;
                # a sub-agent has its task's context. (Their headings are the repository's.)
                docs = project_map.documents(project.root_path) if (
                    ctx.depth == 0 and "read_file" in ctx.tools) else ""
                said = "\n\n".join(p for p in (
                    koloni.instructions(project.root_path),
                    injection.noted(docs, "agent") if docs else "",
                    *((koloni.instructions(project.root_path, ctx.part),
                       project_map.told(ctx.part, self._map_now(ctx), self._watched(ctx.run_id)))
                      if ctx.part else ()),
                    said) if p)
            return said, given

    def _briefed_with(self: "AgentRunner", ctx: Ctx, said: str, given: list[str]) -> None:
        """The briefing is in a request for this agent: from here on it is what the agent
        was given, and its record says so - also when that is nothing, whatever the
        record said before."""
        self._briefed[ctx.agent_id] = said
        self._given[ctx.agent_id] = list(given)
        handed = self._handed_from.get(ctx.agent_id) or None
        with self._factory() as session:
            on_record = session.execute(
                select(Agent.facts_given, Agent.handed_from).where(Agent.id == ctx.agent_id)
            ).first()
        if on_record is None or tuple(on_record) != (given, handed):
            self._set_agent(ctx.cid, ctx.agent_id, facts_given=given, handed_from=handed)

    def _no_longer_given(self: "AgentRunner", ctx: Ctx) -> list[str]:
        """A briefing does not stay true by default, and neither does what `recall`
        returned. Before each step of an agent, the facts it was given and the records it
        looked up are looked at again - those and no others; nothing new is ever added to
        work that has begun. For each that no longer stands (its source changed, the
        user removed it) the agent is told so, once: the words go into its conversation
        and are returned as it will read them."""
        watched = self._given.get(ctx.agent_id) or []
        looked_up = self._looked_up.get(ctx.agent_id) or {}
        if not watched and not looked_up:
            return []
        with self._factory() as session:
            project = self._project(session, ctx.cid)
            # Looked at where the agent works: in its working copy, once it has one.
            told = kept.withdrawn(
                session, project, watched, looked_up, self._ws(ctx).root
            ) if project else {}
            if not told:
                return []
            rows = [
                Message(
                    conversation_id=ctx.cid, run_id=ctx.run_id, agent_id=ctx.agent_id,
                    role="memory", content=words, status="complete", delivered_at=now(),
                )
                for words in told.values()
            ]
            session.add_all(rows)
            session.commit()
            payloads = [message_out(row) for row in rows]
        if watched:
            self._given[ctx.agent_id] = [fact for fact in watched if fact not in told]
        for record_id in told:
            looked_up.pop(record_id, None)
        for payload in payloads:
            self.bus.emit(ctx.cid, ctx.run_id, "message.created", payload)
        return list(told.values())

    def _has_read(self: "AgentRunner", session, ctx: Ctx, ws: Workspace,
                  source: "kept.Source") -> bool:
        """Whether read_file showed this agent these lines of the file in this turn."""
        seen: set[int] = set()
        for arguments, result in session.execute(
            select(ToolCall.arguments, ToolCall.result).where(
                ToolCall.agent_id == ctx.agent_id, ToolCall.run_id == ctx.run_id,
                ToolCall.name == "read_file", ToolCall.status == "succeeded",
                ToolCall.origin == "koloni",
            )
        ):
            try:
                path = ws.rel(ws.resolve(parse_arguments(arguments).get("path") or ""))
            except (ToolError, WorkspaceError, OSError, ValueError):
                continue
            shown = re.search(
                r"\[showing lines (\d+)-(\d+) of \d+\]\s*(?:\[the file: [^\]]*\]\s*)?"
                r"(?:\[Counted by KOLONİ: [^\]]*\]\s*)?$",
                result or "")
            if shown and path.casefold() == source.path.casefold():
                seen.update(range(int(shown[1]), int(shown[2]) + 1))
        return all(line in seen for line in range(source.start, source.end + 1))

    def _remember(self: "AgentRunner", ctx: Ctx, ws: Workspace, args: dict) -> str:
        """An agent writes into the project's journal. The model's part is the words, the
        subject and the lines; who, when, in which turn and the digest are KOLONİ's.
        Nothing here waits (no await): the note is checked and written in one go."""
        if ctx.answering or ctx.in_turn:  # not offered there, and not taken either
            raise ToolError(
                "nothing is written into the memory in a turn taken on a message or in "
                "a discussion"
            )
        own_tools = bool(getattr(ctx.model, "native", False))
        unattended = not self._watched(ctx.run_id)
        try:
            asked = kept.plan_remember(args)
            if asked.propose and unattended:
                # Putting a note forward is asking the user: there is nobody to ask.
                raise ToolError(NOBODY_FOR_THE_CORE)
            source, checked = None, None
            with self._factory() as session:
                project_id = session.get_one(Conversation, ctx.cid).project_id
                if asked.file is not None:
                    source = kept.read_source(  # (`ws`: a job's copy at night, `execute`)
                        str(ws.root), asked.file, asked.start or 1, asked.end or asked.start or 1
                    )
                    read = self._has_read(session, ctx, ws, source)
                    if not read and not own_tools:
                        raise ToolError(
                            f"read lines {source.start}-{source.end} of {source.path} with "
                            "read_file first: a note can only rest on lines you have read "
                            "in this turn"
                        )
                    changed = kept.changed_in_turn(
                        session, ctx.folder, ctx.run_id, source.path
                    )
                    if changed and asked.propose:
                        raise ToolError(
                            f"{source.path} was changed by an agent in this turn, or "
                            "changed on disk in this turn, so it cannot back a fact for "
                            "the core: what was just written is not a source. Leave "
                            "propose out to keep it as a note."
                        )
                    # What a CLI reads with its own tools KOLONİ does not see.
                    checked = (kept.CHANGED_HERE if changed
                               else kept.READ_HERE if read else kept.NOT_SEEN)
                elif asked.propose:
                    raise ToolError(
                        "only a note that rests on lines of a project file can be put "
                        "forward for the core: give file, start_line and end_line, or "
                        "leave propose out"
                    )
                note = kept.keep_note(
                    session, project_id, asked, agent_id=ctx.agent_id, run_id=ctx.run_id,
                    conversation_id=ctx.cid, source=source, checked_how=checked,
                    unattended=unattended,
                )
                waits, wants = note.status == "proposed", note.wants_core
        except kept.Refused as exc:
            raise ToolError(str(exc)) from None
        self.bus.emit(ctx.cid, ctx.run_id, "memory.changed", {"project_id": project_id})
        announce_memory(self._factory, self.bus, project_id, but=ctx.cid)
        if waits:
            return (
                "noted, and it waits for the user: the project's core already has a fact "
                "on this subject, and only the user can change that. Until they decide, "
                "your note is given to nobody and recall does not find it."
            )
        if wants:
            return (
                "noted in the journal and put forward for the core: the user decides. "
                "Until then agents find it with recall, like any note."
            )
        return "noted in the journal: agents find it with recall; nobody is handed it unasked."

    def _recall(self: "AgentRunner", ctx: Ctx, args: dict) -> str:
        """An agent looks in the project's memory, and in what was said in the project's
        earlier turns (`app.earlier`: the turns that are over, so never this one). What it
        gets back is data - and a record of the memory is watched from here on like what
        the agent was given when it started (`_no_longer_given`)."""
        try:
            query = kept.plan_recall(args)
        except kept.Refused as exc:
            raise ToolError(str(exc)) from None
        with self._factory() as session:
            project = self._project(session, ctx.cid)
            if project is None:
                return kept.NOTHING
            # 22c: the linked projects too, and by meaning where a provider is chosen for it.
            also = kept.also(session, project, query)
            # (93-C5: the agent's work orders what is found, among equals; it never matches.)
            found, shown = kept.looked_up(
                session, project, query, self._work_of(session, ctx) or "", also)
            found += "\n\n" + earlier.told(session, project.id, query, also)
            if also.off:
                found += "\n\n" + also.off
        # As it was shown last. What the briefing gave is watched already.
        given = self._given.get(ctx.agent_id) or []
        self._looked_up.setdefault(ctx.agent_id, {}).update(
            {record: state for record, state in shown.items() if record not in given})
        return found

    def note_from_user(self: "AgentRunner", run_id: str, content: str) -> dict | str:
        """The user writes on a turn's notebook; the reason, when the turn is not one
        that can be written on. ToolError when the notebook is full."""
        with self._factory() as session:
            run = session.get_one(Run, run_id)
            cid, status = run.conversation_id, run.status
        if status in TERMINAL:
            return "this turn is over: its notebook is closed"
        if status == "queued":
            return "this turn has not started yet"
        return self._write_note(run_id, cid, None, content)

    async def _reply_turn(self: "AgentRunner", ctx: Ctx, target: Ctx, kind: str, body: str,
                          koloni: bool = False) -> tuple[str, str]:
        """The receiver's turn on a message: it works on, or answers; then its reply.
        `koloni`: the words are KOLONİ's own (G3's Go on), not the opener's - told as a
        nudge, no message between agents, not counted against the turn's."""
        with self._factory() as session:
            record = session.get_one(Agent, target.agent_id)
            previous, limited = record.status, _at_a_step_limit(record.error)
            # (K-uzman: an expert's web search is for answering - its only work.)
            searches = bool((knows.known_here(session, find_role(session, target.role), (
                session.get_one(Conversation, target.cid).project_id)) or {}).get(
                "search_answering"))
            last_call = session.scalar(
                select(func.max(ToolCall.seq)).where(ToolCall.run_id == ctx.run_id)
            )
            # (Its reply: what it says after its last message so far.)
            inbound_id = session.scalar(select(Message.id).where(
                Message.agent_id == target.agent_id).order_by(
                Message.created_at.desc(), literal_column("messages.rowid").desc()).limit(1)
            ) if koloni else None
        now_on = self._role_now(target)
        # Not sent where it could take no step on it: its kept card stays the user's. KOLONİ's
        # own Go on (a reset, Reconnect) is let through: its row then says why it stopped, and
        # not the card about its provider again.
        gives = ""
        key = (ctx.run_id, target.name.casefold())
        if kind == "continue" and not koloni:
            refused, gives = self._go_on_gate(ctx, target, now_on, previous == "failed" and limited)
            if refused is not None:
                return "failed", refused
        inbound_id = self._reply_turn_send(ctx, target, body, koloni, inbound_id)

        # A turn taken on somebody's message writes nothing into the project's memory,
        # whether it answers or carries on: what is kept is noted in an agent's own work.
        turn = replace(
            now_on, calls_from=last_call or 0, in_turn=True,
            tools=tuple(t for t in target.tools if t != "remember"),
        )
        if kind == "answer":
            turn = replace(
                turn, answering=True, own_calls=set(),
                tools=tuple(t for t in target.tools if t in ANSWER_TOOLS
                            or searches and t == "web_search"),
            )
        if kind == "answer":
            self._answering[target.agent_id] = previous
        # The sender goes nowhere until the turn is over (`app.claims`).
        self.claims.awaiting(ctx.agent_id, target.agent_id)
        try:
            if gives == "once":  # (B-397: it runs on a fresh app's limit, `_loop`)
                steps = self._app_steps()
                if now_on.role_steps is not None:  # (what its role still lets it take)
                    steps = min(steps, now_on.role_steps - self._role_before(now_on))
                self._budgeted[key] = steps
            async with self._working(turn):
                self._reply_turn_start(ctx, target, kind)
                self._in_reply.add(target.agent_id)
                status, error = await self._run_child(turn)
            reply = self._last_text(
                target.agent_id, final_only=status == "completed", after=inbound_id
            )
            left_out = ""
            if kind == "continue":
                done: dict = {"status": status, "error": error, "ended_at": now()}
                if reply:
                    done["report"] = reply
                # What it changed in this turn is taken into the project like the rest.
                left_out = await self._take_in(
                    target, status, lambda: self._set_agent(ctx.cid, target.agent_id, **done)
                )
        finally:
            self._in_reply.discard(target.agent_id)
            self.claims.returned(ctx.agent_id, target.agent_id)
            self._given_steps.pop(target.agent_id, None)  # (a budget is this turn's alone)
            if kind == "answer":
                # It only answered: it is what it was, also when Stop cut the answer short.
                self._answering.pop(target.agent_id, None)
                self._set_agent(ctx.cid, target.agent_id, status=previous)
        if left_out:
            reply = f"{reply}\n\n{left_out}" if reply else left_out

        return self._reply_turn_result(ctx, target, kind, status, error, reply)

    def _go_on_gate(self: "AgentRunner", ctx: Ctx, target: Ctx, now_on: Ctx,
                    limited: bool) -> tuple[str | None, str]:
        """`_reply_turn`: whether the opener's go on reaches `target` - why not, or None and what
        it is given: "once" (B-397: `limited`, its last stop was at a step limit - it goes on, on
        a fresh app's limit, its role's still holding), or "". Once a turn for an agent
        (`_budgeted`), with its card's Continue: past that more is the user's to give. B-401: an
        agent with no steps left under its role's own limit is the user's alone at every level,
        Full auto and a night too - their Continue on its kept card, or a raised limit."""
        key = (ctx.run_id, target.name.casefold())
        if key in self._stopped_here:
            return NO_GO_ON.format(name=target.name), ""  # (B-397: the user's Stop here)
        once = self._budgeted.get(key)
        if now_on.role_steps is not None and self._role_before(now_on) >= now_on.role_steps:
            with self._factory() as session:
                kept = session.scalar(select(Merge.id).where(
                    Merge.agent_id == target.agent_id, Merge.status == "interrupted",
                    Merge.kept_in.is_not(None)).limit(1)) is not None
            return NO_STEPS_LEFT.format(
                name=target.name, limit=now_on.role_steps,
                given=GIVEN_ONCE.format(steps=once) if once is not None else "",
                how=HOW_CONTINUE if kept else HOW_RAISE), ""
        if limited and once is not None:
            return NO_MORE_GO_ON.format(name=target.name, steps=once), ""
        return None, "once" if limited else ""

    def _reply_turn_send(self: "AgentRunner", ctx: Ctx, target: Ctx, body: str, koloni: bool,
                         inbound_id):
        """`_reply_turn`: the words handed to it - KOLONİ's as a nudge, else a message between
        agents (its id: where its reply begins)."""
        if koloni:
            self._nudge(target, body)
        else:
            inbound_id = self._send(ctx, target, body, delivered=True)
            self._channel(ctx, ctx.agent_id, target.agent_id, "message", body)
            # Read by it in its turn, with the note (`_from`): the user is told here (93-A4) -
            # but not of the word of the agent it works for.
            if not self._is_above(ctx.agent_id, target):
                self._orders(target, "agent", f"a message from {ctx.name}", body)
        return inbound_id

    def _reply_turn_start(self: "AgentRunner", ctx: Ctx, target: Ctx, kind: str) -> None:
        """`_reply_turn`, in its place: it is at work - going on, with its copy given back
        first where one is kept for it."""
        if kind == "continue":
            self._set_agent(
                ctx.cid, target.agent_id, status="running", error=None, ended_at=None
            )
            # (Only its own: a room's member or a recipe's agent leaves its lead's be.)
            owner = self._copy_owner(target) or target.agent_id
            if owner == target.agent_id and owner not in self._copies:
                if back := self._give_back(owner):
                    self._copies[owner] = back  # (B-322: before it reads anything)
                    self._given_back.add(owner)
                else:
                    self._branch_again(target, owner)  # (K-dal-takim: its branch, if on one)
        else:
            self._set_agent(ctx.cid, target.agent_id, status="running")

    def _reply_turn_result(self: "AgentRunner", ctx: Ctx, target: Ctx, kind: str, status: str,
                           error, reply) -> tuple[str, str]:
        """`_reply_turn`: its reply as its sender is told it - or why there is none."""
        if status == "completed":
            said = reply or "(it gave no answer)"
            self._channel(ctx, target.agent_id, ctx.agent_id, "reply", said)
            return "succeeded", f"{target.name} replied:\n\n{said}"
        if error == "step_limit":
            # (Its recipe's steps too, where it runs one: `_recipe_steps`.)
            result = (f"{target.name} stopped after "
                      f"{self._app_steps() + self._recipe_steps(target)} steps.")
        else:
            result = f"{target.name} could not reply: {self._told(target.agent_id, error)}"
        if reply:
            result += f"\n\nWhat it said last:\n{reply}"
        if kind == "continue":
            result += (self._left_undone(target) if _at_a_step_limit(error) else "") + self._room(
                target)
        self._channel(ctx, target.agent_id, ctx.agent_id, "reply", result)
        return "failed", result
