"""Agents talking to each other: message_agent and its delivery (into a CLI's turn too), what
an agent may reach and who its team is, offers and hand-ons of notes and files, report_git,
and the shared notebook (post_note / read_notes) - `TalkMixin`.
"""

import asyncio
from collections.abc import Callable, Collection
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import func, literal_column, select, update

from app import (
    backlog,
    board,
    copies,
    git,
    injection,
    mcp_client,
    models_dev,
    recipe_run,
    team_requests,
    topics,
    views,
)
from app import room as rooms
from app.agent.cards import _changes_nothing
from app.agent.ctx import Ctx, announce
from app.agent.summary import _lines_written_out
from app.agent.words import CANT_UNDO, FROM, HANDED, LEADS_LATER, NOT_HEARD
from app.db.models import (
    Agent,
    BoardPost,
    ChannelMessage,
    Conversation,
    Message,
    Recipe,
    Role,
    ShownFile,
    Team,
    now,
)
from app.discussion import MEMORY_HEAD
from app.providers import list_providers
from app.roles import LEAD, ORCHESTRATOR, agent_roles, closed, pickable, team_roles, tools_off
from app.serialize import board_post_out, message_out
from app.team import guide, quoted
from app.tools import (
    ATTACHMENTS_PROPERTY,
    ATTACHMENTS_UNREAD,
    CAN,
    FOLDER_PROPERTY,
    FOLLOW_SCHEMAS,
    MAX_MESSAGE_CHARS,
    ON_BRANCH_PROPERTY,
    READ_ATTACHMENT_SCHEMA,
    RECALL_OUTPUT_SCHEMA,
    REPORT_GIT_SCHEMA,
    ROOM_SCHEMAS,
    ToolError,
    away_schema,
    earlier_line,
    pick_schema,
    skill_schemas,
    tool_schemas_for,
    who_line,
)
from app.workspace import Workspace, WorkspaceError

if TYPE_CHECKING:
    from app.agent import AgentRunner

# 89d B: a message of the agent it works for, into a CLI's turn (a user line): not the user's.
AGENT_STEERED = "{message}\n\n(An agent's words, passed on by KOLONİ - not the user's.)"
SENT_WHILE_IT_WORKS = (
    "sent while it works: written into {name}'s current turn - not yet that it read it; if it "
    "finishes first, you are told. It does not reply unless it messages you; go on with your "
    "own work.")

# A Claude Code's or Codex's door that did not take it: its turn is over, or about to be.
TURN_ENDING = "{name}'s turn is ending; try again once it has finished"

# What a recipe's runner is told with where its recipe is (B-67: a Lead asked mid-recipe whether
# to copy the work into the project, then ended its turn).
# (K-r144, live: in Manual a Lead reviewed the work itself instead of running the chosen recipe.)
RECIPE_RULES = ("Work a chosen team's recipe covers runs through the recipe: open its step's "
                "roles - never do a step's work (writing, reviewing, testing) yourself in its "
                "place. "
                "While a recipe runs, do not ask the user yourself (no ask_user): the recipe "
                "asks at its Ask me steps and at its end. Its work goes into the project only "
                "by the user's Take in at Ready for you - never offer to copy it in another way. "
                "Go on step by step to its end. With findings left it goes back along its loop by "
                "itself: open the step it names - never end your turn to ask the user what to do "
                "with them; the user decides at Ready for you. A role the step does not name is "
                "refused: the way on is the step's own role, or the user's Finish now or Stop on "
                "the team - never offer the user a way round the recipe (you or another role "
                "doing the step's work). When the user says to stop, open no other agent")

MAX_MESSAGES_PER_TURN = 30


class TalkMixin:
    # --- agents talking to each other ----------------------------------------

    def _git_of(self: "AgentRunner", ctx: Ctx) -> dict | None:
        """The project's git as the turn began, for an agent that is a CLI (slice 70): what
        it is told of, and asked to report. None for any other agent, and with no git."""
        return self._git_at.get(ctx.run_id) if getattr(ctx.model, "command", "") else None

    def _reports_git(self: "AgentRunner", ctx: Ctx) -> bool:
        """Whether a CLI is offered report_git: one that sees KOLONİ's tools, at its own
        work. Not agy or Codex with tools of their own (as the design has it): what git
        shows is all that is said of theirs."""
        model = ctx.model
        return bool(self._git_of(ctx)) and not ctx.answering and getattr(
            model, "collaborates", True) and not (
            getattr(model, "native", False) and getattr(model, "command", "") in ("codex", "agy"))

    def _report_git(self: "AgentRunner", ctx: Ctx, args: dict) -> str:
        """What a CLI says it did in git (report_git): kept for the turn's end, where it is
        compared with what git shows (`git.turn_note`); its call's record is what the map
        shows as said by it - text only, and no folder that is not to be looked at
        (`git.reported`)."""
        try:
            said = git.reported(args, Path(ctx.root or "."))
        except ValueError as exc:
            raise ToolError(str(exc)) from None
        self._git_said.setdefault(ctx.run_id, []).append((ctx.name, said))
        return ("Noted. The user sees it on the project's git map, and KOLONİ compares it "
                "with git at the end of the turn.")

    def _offered(self: "AgentRunner", ctx: Ctx, tools, always: bool = False,  # noqa: C901
                 show: bool = False) -> list[dict]:
        """The schemas of `tools` for this agent, as things stand right now."""
        if not ctx.answering and ctx.agent_id in self._following:
            # K-oda-lead: following the room it opened, it is offered only that (`_follow_call`).
            # shortcut: its tools - and the parts of its instructions they gate - change as it
            # starts and stops following: two prompt-cache rewrites of the opener a room; keep its
            # own tools offered and refused if that cost is seen to matter.
            return [ROOM_SCHEMAS["post_to_room"], ROOM_SCHEMAS["invite_to_room"],
                    *FOLLOW_SCHEMAS.values()]
        if self._hands_code(ctx):  # (kept in ctx.tools: a sub-agent's are capped by them)
            tools = [tool for tool in tools if tool not in HANDED]
        door, running = None, False
        with self._factory() as session:
            # Slice 61: what the user switched off on the Tools page, read at every step.
            off = tools_off(session)
            tools = [tool for tool in tools if tool not in off]
            conversation = session.get_one(Conversation, ctx.cid)
            roles = []
            if "spawn_agent" in tools:
                # Only those it may open now: on, in the chat's teams (its recipe's step), or
                # named; and the teams' leads beside each other.
                door = self._door(session, ctx)
                # B-67: a recipe it runs is at work (or starts with its next agent).
                running = any(
                    state["status"] == recipe_run.RUNNING if (
                        state := self._live_state(row, ctx.run_id)) else
                    self._recipe_of(session, row, team) is not None
                    for row, team in self._runs(session, ctx))
                named = self._names_past(session, ctx)
                roles = [role for role in agent_roles(session) if not closed(role, door, named)
                         ] + [lead for _r, _t, lead in self._rows(session, ctx.cid)
                              if lead and not ctx.depth]
            # Lead decides (slice 84b): the Lead at its own work picks the chat's teams.
            may = [] if self._no_pick(ctx, conversation) else pickable(session)
            pick = [pick_schema(
                [(team, team_roles(session, team)) for team in may],
                session.scalars(select(Recipe.name).order_by(Recipe.created_at)).all(),
            )] if may else []
            # Slice 106: the Lead at the user's own turn may put a "While you're away" card.
            away_tool = [away_schema(
                session.scalars(select(Team.name).order_by(Team.created_at)).all(),
                session.scalars(select(Recipe.name).order_by(Recipe.created_at)).all(),
            )] if self._no_away(session, ctx) is None else []
            # Read at every step, like the roles: what the user unticks is gone at once.
            team = guide(list_providers(session), models_dev.load(
                self.settings.runtime_root)) if "spawn_agent" in tools else []
            files = self._files_of(session, ctx)
            between = [] if ctx.run_id in self._sides else team_requests.schemas(
                self, session, ctx)
        facts = self._who(ctx.run_id) if {"message_agent", "discuss"} & set(tools) else {}
        reachable = [
            who_line(other.name, other.role, *facts[other.agent_id], CAN[kind])
            for other, kind in self._reachable(ctx)
        ] if "message_agent" in tools else []
        others = [
            who_line(other.name, other.role, *known)
            for agent_id, known in facts.items()
            if agent_id != ctx.agent_id and (other := self._ctxs.get(agent_id))
            and known[2] in ("running", "queued", "waiting", "blocked", "completed", "failed")
        ] if "discuss" in tools else []
        earlier = [
            earlier_line(
                before.name, before.role, before.provider,
                # (One Copilot's auto picked goes on on auto: `_ran_on_before`.)
                "auto" if before.model_from == "auto" else None if before.model_from == "settings"
                else before.model, before.status,
                before.task, before.turn,
            )
            for before in self._earlier(ctx)
        ] if "message_agent" in tools else []
        # shortcut: a CLI working with its own tools is given its skills whole in its
        # instructions (`_skills_told`), not use_skill; measure the CLIs' own skill folders
        # with the real CLIs (slice 45 design, 3 and 7).
        known = [] if getattr(ctx.model, "native", False) else self._skills(ctx)
        schemas = tool_schemas_for(tools, roles, reachable, always, team, others, earlier, show)
        # (with the To-do list's tools: the jobs go onto it)
        at = next((i + 1 for i, s in enumerate(schemas) if s["function"]["name"] == "assess_task"),
                  len(schemas))
        schemas[at:at] = away_tool
        if door is not None and door.step and door.step[1]:
            # Where the chat's recipes are, read at every step as the roles are (slice 84b-2).
            # (R57: a Lead refused the Coder at the spec step asked for it first again.)
            refused = sorted(role for role in self._refused_roles.get(ctx.run_id, ())
                             if role.casefold() not in door.step[0])
            for spawn in (s["function"] for s in schemas if s["function"]["name"] == "spawn_agent"):
                spawn["description"] += f"\nNow: {door.step[1]}." + (
                    f"\nRefused in this turn, and no role of this step either: "
                    f"{', '.join(refused)}. Do not ask for {'it' if len(refused) == 1 else 'them'}"
                    " again here: open the step's own roles." if refused else "") + (
                    f"\n{RECIPE_RULES}." if running else "")
        if self._reports_git(ctx):
            schemas = [*schemas, REPORT_GIT_SCHEMA]
        if files:
            # The files the user attached (slice 85b): read, and handed on by their names.
            for one in (s["function"] for s in schemas
                        if s["function"]["name"] in ("spawn_agent", "message_agent")):
                one["parameters"]["properties"]["attachments"] = ATTACHMENTS_PROPERTY if (
                    "read_attachment" not in off) else ATTACHMENTS_UNREAD
            if "read_attachment" not in off:
                schemas = [*schemas, READ_ATTACHMENT_SCHEMA]
        if ctx.part or ctx.depth == 0 and self._map_told(ctx):
            # K-buyuk-proje: only with parts to name (the Lead's brief lists them): a project of
            # one part is offered spawn_agent as it was.
            for spawn in (s["function"] for s in schemas if s["function"]["name"] == "spawn_agent"):
                spawn["parameters"]["properties"]["folder"] = FOLDER_PROPERTY
        if self._no_branch_here(ctx) is None:
            # K-dal-takim: only where it can be had - offered as it was elsewhere.
            for spawn in (s["function"] for s in schemas if s["function"]["name"] == "spawn_agent"):
                spawn["parameters"]["properties"]["on_branch"] = ON_BRANCH_PROPERTY
        if getattr(ctx.model, "collaborates", True) and not ctx.answering and (
                "recall_output" not in off):
            # At its own work, as show is; always, not only once something was cut: the tools
            # are the cache's first part.
            schemas = [*schemas, RECALL_OUTPUT_SCHEMA]
        return schemas + between + [
            mcp_client.schema(server.name, tool) for server, tool in self._mcp(ctx).values()
        ] + skill_schemas(known, "run_command" in tools) + pick

    def _earlier(self: "AgentRunner", ctx: Ctx) -> list[topics.Earlier]:
        """The agents of earlier turns of the topic that this agent can go on with: for
        the lead, at its own work, the ones `topics.continuable` finds; for anyone else
        none. Read off the record each time.
        Going on with an agent is opening one: a lead whose role may not open agents
        (no spawn_agent) is offered none and reaches none."""
        if ctx.depth != 0 or ctx.answering or "spawn_agent" not in ctx.tools:
            return []
        with self._factory() as session:
            return topics.continuable(session, ctx.run_id)

    def _who(self: "AgentRunner",
             run_id: str) -> dict[str, tuple[str | None, str | None, str, str | None]]:
        """Where each agent of a turn runs, its state and its task, oldest first."""
        with self._factory() as session:
            rows = session.execute(
                select(Agent.id, Agent.provider_name, Agent.model_id, Agent.status, Agent.task)
                .where(Agent.run_id == run_id)
                .order_by(Agent.created_at, literal_column("agents.rowid"))
            ).all()
        # One that is answering somebody is, for everyone else, still what it was.
        return {
            agent_id: (provider, model, self._answering.get(agent_id, status), task)
            for agent_id, provider, model, status, task in rows
        }

    def _from(self: "AgentRunner", ctx: Ctx, message_id: str, sender: str | None, name: str,
              relation: str,
              content: str) -> str:
        """A message from another agent as its receiver reads it. A note - nobody waits
        for an answer to it - also says how to answer, when its sender can be reached."""
        how = ""
        if (
            message_id in self._notes and "message_agent" in ctx.tools
            and any(other.agent_id == sender for other, _kind in self._reachable(ctx))
        ):
            how = f'; reply with message_agent(to="{name}")'
        # (What comes from elsewhere is KOLONİ's own words, and what the agent it works for
        # says is its word: neither is looked at, 93-A4.)
        # Nor what a member keeps of a discussion: it holds the user's words too.
        said = injection.noted(content, "agent") if sender and relation not in (
            "elsewhere", "above") and not self._is_above(sender, ctx) and not (
            content.startswith(MEMORY_HEAD)) else content
        return f"Message from {name} ({FROM[relation]}{how}):\n\n{said}"

    def _is_above(self: "AgentRunner", agent_id: str, other: Ctx) -> bool:
        """Whether the agent is somewhere in the chain that opened `other`."""
        walk = other.parent_id
        while walk is not None:
            if walk == agent_id:
                return True
            parent = self._ctxs.get(walk)
            walk = parent.parent_id if parent else None
        return False

    def _reachable(self: "AgentRunner", ctx: Ctx) -> list[tuple[Ctx, str]]:
        """The agents this one can message now, each with the kind of turn it would take:
        "continue" (a finished agent below it works on) or "answer" (read-only)."""
        if ctx.answering:
            return []
        with self._factory() as session:
            rows = session.execute(
                select(Agent.id, Agent.status)
                .where(Agent.run_id == ctx.run_id)
                .order_by(Agent.created_at, literal_column("agents.rowid"))
            ).all()
        found: list[tuple[Ctx, str]] = []
        for agent_id, status in rows:
            other = self._ctxs.get(agent_id)
            if other is None or agent_id == ctx.agent_id:
                continue
            # One that is answering somebody is, for everyone else, still what it was.
            status = self._answering.get(agent_id, status)
            # K-lead-bekliyor: one that waits for the user's word alone is shown "waiting", but
            # for a message it is at work as before - a note for its next step, or steered
            # through a CLI's door; "answer" would leave a CLI Lead out of reach while it asks.
            if status == "waiting" and self._asks.get(agent_id) and not self._out.get(agent_id):
                status = "running"
            if status in ("completed", "failed"):
                kind = "continue" if self._is_above(ctx.agent_id, other) else "answer"
            elif status == "waiting":
                kind = "answer"
            elif status in ("running", "queued", "blocked"):
                if agent_id in self._halted:  # (R143: its team was stopped - no next step)
                    continue
                # One that waits for a file is at work: it takes its next step when the
                # file is its own.
                kind = "note"
            else:
                continue
            # A CLI working with its own tools cannot be held to reading, and there is
            # no telling when, if ever, a note would reach it - but for the agent it works for,
            # into its turn, where its CLI has a door (89d B: "steer", `_steer_message`).
            if kind != "continue" and getattr(other.model, "native", False):
                if not (kind == "note" and agent_id in self._doors
                        and self._is_above(ctx.agent_id, other)):
                    continue
                kind = "steer"
            found.append((other, kind))
        return found

    async def _message(self: "AgentRunner", ctx: Ctx, call_id: str, args: dict) -> tuple[str, str]:
        """Give another agent a turn on a message, and return its reply. A name that no
        agent of this turn has may be that of an agent of an earlier turn of the topic:
        the lead goes on with it (`_go_on`), which is opening an agent."""
        to, body = args.get("to"), args.get("message")
        if not isinstance(to, str) or not to.strip():
            raise ToolError("missing required argument: to")
        if not isinstance(body, str) or not body.strip():
            raise ToolError("missing required argument: message")
        to, body = " ".join(to.split()), _lines_written_out(body.strip())
        # K-isimler: an agent told of the Orchestrator may write to it by that title.
        # shortcut: a team's coordinator is not mapped back to its lead's name; add it if seen.
        if to.casefold() == ORCHESTRATOR.casefold():
            to = LEAD
        if len(body) > MAX_MESSAGE_CHARS:
            raise ToolError(f"a message has at most {MAX_MESSAGE_CHARS} characters")
        if to.casefold() == ctx.name.casefold():
            raise ToolError("you cannot message yourself")
        handed_files = self._named_files(ctx, args.get("attachments"))  # (slice 85b)
        reachable = self._reachable(ctx)
        match = next((m for m in reachable if m[0].name.casefold() == to.casefold()), None)
        if match is None:
            return await self._message_unknown(ctx, call_id, to, body, reachable)
        target, kind = match
        in_room = self._member_of(ctx)
        if in_room is not None and in_room[0].outcome is None and (
            target.agent_id == in_room[0].lead.agent_id
        ):
            # It would have the lead take a step while its room runs - which one following its
            # room reads there (K-oda-lead).
            raise ToolError(rooms.TO_THE_OPENER.format(opener=target.name)
                            if in_room[0].reads else rooms.NOT_THE_LEAD)
        self._within_limit(ctx)
        if kind == "steer":  # (its files only once its CLI took the message)
            return await self._steer_message(ctx, target, body, handed_files)
        # shortcut: not with an earlier turn's agent gone on with (`_go_on`); hand them there
        # too if a Lead is seen to do it.
        self._hand_files(ctx, handed_files, target.agent_id)
        if kind == "note":
            # It is at work: the message is left for its next step, and nobody waits. No
            # promise that it is read: one that takes no further step is never handed it.
            self._send(ctx, target, body, delivered=False)
            self._channel(ctx, ctx.agent_id, target.agent_id, "note", body)
            return "succeeded", (
                f"noted: {target.name} is at work and is handed this at its next step, if "
                "it takes one. It does not reply unless it messages you; go on with your "
                "own work."
            )
        return await self._message_turn(ctx, call_id, target, body)

    async def _message_unknown(self: "AgentRunner", ctx: Ctx, call_id: str, to: str, body: str,
                               reachable) -> tuple[str, str]:
        """`_message` to a name it cannot reach now: an earlier turn's agent goes on (its
        reply), else why not, raised."""
        known = next(
            (c for c in self._ctxs.values()
             if c.run_id == ctx.run_id and c.name.casefold() == to.casefold()), None)
        # Found by its name, among the agents `_earlier` finds and nowhere else:
        # nothing an agent writes here names an agent of another topic.
        before = [] if known is not None else self._earlier(ctx)
        earlier = next((e for e in before if e.name.casefold() == to.casefold()), None)
        if earlier is not None:  # (one gone on with is below it: its reply is looked at)
            return self._reply_read(ctx, call_id, *await self._go_on(
                ctx, call_id, earlier, body))
        listed = ", ".join(
            [other.name for other, _kind in reachable] + [e.name for e in before])
        can = f"You can reach: {listed}." if listed else "Right now nobody can be reached."
        if known is None:
            with self._factory() as session:
                if self._a_lead(session, ctx.cid, to):  # (B-379)
                    raise ToolError(f"{to} is not at work yet: {LEADS_LATER}")
            raise ToolError(f"there is no agent named {to} in this turn. {can}")
        why = self._message_why_not(known)
        raise ToolError(f"{known.name} cannot be messaged by you now: {why}. {can}")

    def _message_why_not(self: "AgentRunner", known: Ctx) -> str:
        """`_message`: why an agent of this turn cannot be messaged now."""
        with self._factory() as session:
            state = session.get_one(Agent, known.agent_id).status
        if state in ("proposed", "rejected"):
            why = "it never ran"
        elif known.agent_id in self._halted:
            why = "its team was stopped, and it takes no next step"
        elif not getattr(known.model, "collaborates", True):
            # A CLI with none of KOLONİ's tools: nothing reaches it while it works.
            why = (
                "it works on its own and cannot be handed a note, so only the agent it "
                "works for can carry on with it, once it has finished"
            )
        elif getattr(known.model, "native", False):
            # (agy reading only: B-310 gave it KOLONİ's tools, and it is held to reading.)
            held = "" if getattr(known.model, "reads", False) else (
                " that cannot be held to reading")
            why = (f"it works with tools of its own{held}, so only the agent it works for "
                   "can message it")
        else:
            why = "it is not at work, waiting or finished"
        return why

    async def _message_turn(self: "AgentRunner", ctx: Ctx, call_id: str, target: Ctx,
                            body: str) -> tuple[str, str]:
        """`_message`: the receiver's turn on it - taken once it is the sender's to give."""
        async with self._handing_over(ctx), self._turn_of(target.agent_id):
            # Things may have moved while this waited its turn with the receiver.
            self._within_limit(ctx)
            now_kind = next(
                (k for other, k in self._reachable(ctx) if other.agent_id == target.agent_id),
                None,
            )
            if now_kind == "steer":  # (its files are handed already)
                return await self._steer_message(ctx, target, body, [])
            if now_kind == "note":
                self._send(ctx, target, body, delivered=False)
                self._channel(ctx, ctx.agent_id, target.agent_id, "note", body)
                status, result = "succeeded", (
                    f"noted: {target.name} is at work again and is handed this at its "
                    "next step, if it takes one. It does not reply unless it messages you."
                )
            elif now_kind is None:
                raise ToolError(f"{target.name} can no longer be messaged by you")
            else:
                status, result = await self._reply_turn(ctx, target, now_kind, body)
                if status == "succeeded":
                    await self._add_to_guide(ctx, target, call_id, result)
                if not self._is_above(target.agent_id, ctx):
                    return self._reply_read(ctx, call_id, status, result)
        return status, result

    async def _steer_message(self: "AgentRunner", ctx: Ctx, target: Ctx, body: str,
                             files: list) -> tuple[str, str]:
        """89d B: a message of the agent a CLI works for into the CLI's turn while it works
        (`steer`, Claude Code's or Codex's door: `_reachable`) - as that agent's, `quoted()`,
        never as the user's; on record in its conversation, with its `files`, once its CLI took
        it. Its sender is told if its turn ends before it read it (`_observe`)."""
        said = AGENT_STEERED.format(message=self._from(
            target, "", ctx.agent_id, ctx.name, "above", quoted(body)))
        if why := await self.steer(target, said, kept=True):
            raise ToolError(f"{target.name} cannot be messaged by you now: "
                            f"{self._not_taken(target, why, door=True)}")
        self._steered_by[target.agent_id] = (ctx.agent_id, said, body)
        self._hand_files(ctx, files, target.agent_id)
        self._send(ctx, target, body, delivered=True)
        self._channel(ctx, ctx.agent_id, target.agent_id, "note", body)
        return "succeeded", SENT_WHILE_IT_WORKS.format(name=target.name)

    @staticmethod
    def _not_taken(ctx: Ctx, why: str, door: bool) -> str:
        """Why `steer` did not reach it, as a message's sender is told: where it had a `door`
        that did not take it, a turn that is ending (Claude Code's, Codex's) - not a CLI that
        hears nothing."""
        name = ctx.name or ctx.role
        ending = door and why == NOT_HEARD.format(name=name)
        return TURN_ENDING.format(name=name) if ending else why.removeprefix(CANT_UNDO)

    def _reply_read(self: "AgentRunner", ctx: Ctx, call_id: str, status: str,
                    result: str) -> tuple[str, str]:
        """Another agent's reply as the agent that messaged it reads it: after the note where
        it reads like orders (93-A4) - not called for a reply of the agent it works for."""
        if self._orders(ctx, "agent", "another agent's reply", result, call_id):
            result = f"{injection.NOTE}\n{result}"
        return status, result

    def _within_limit(self: "AgentRunner", ctx: Ctx) -> None:
        with self._factory() as session:
            sent = session.scalar(
                select(func.count()).select_from(ChannelMessage).where(
                    ChannelMessage.run_id == ctx.run_id,
                    ChannelMessage.kind.in_(("message", "note")),
                )
            )
        if (sent or 0) >= MAX_MESSAGES_PER_TURN:
            raise ToolError(
                f"limit of {MAX_MESSAGES_PER_TURN} messages between agents per turn "
                "reached. Go on with what you know."
            )

    def _send(self: "AgentRunner", ctx: Ctx, target: Ctx, body: str, delivered: bool,
              koloni: bool = False) -> str:
        """Put a message from one agent into another's conversation; returns its id.
        (The receiver's turn is where it goes: the two are of one turn, but for what
        KOLONİ says of a file held by an agent of another conversation.) `koloni`: KOLONİ's
        own word (from nobody), read as it is."""
        with self._factory() as session:
            inbound = Message(
                conversation_id=target.cid, run_id=target.run_id, agent_id=target.agent_id,
                from_agent_id=None if koloni else ctx.agent_id, role="agent", content=body,
                status="complete",
                delivered_at=now() if delivered else None,
            )
            session.add(inbound)
            session.commit()
            inbound_id, payload = inbound.id, message_out(inbound)
        if not delivered:
            self._notes[inbound_id] = target.run_id
        self.bus.emit(target.cid, target.run_id, "message.created", payload)
        return inbound_id

    def _deliver(self: "AgentRunner", ctx: Ctx) -> list[str]:
        """Hand an agent the notes left for it, what is new to it on the turn's
        notebook and - a member of a room - in its room; returns them as it will read
        them."""
        posts = self._hand_posts(ctx)
        with self._factory() as session:
            # Not in a turn taken to answer or to speak: the notebook waits for its own work.
            handed = [] if ctx.answering else self._hand_notes(session, ctx)
            waiting = session.scalars(
                select(Message)
                .where(Message.agent_id == ctx.agent_id, Message.role == "agent")
                .where(Message.delivered_at.is_(None), Message.run_id == ctx.run_id)
                .order_by(Message.created_at, literal_column("messages.rowid"))
            ).all()
            if not waiting and not handed:
                return posts
            names = dict(session.execute(
                select(Agent.id, Agent.name).where(Agent.run_id == ctx.run_id)).all())
            for message in waiting:
                message.delivered_at = now()
            # One commit: the notes in its conversation and the mark of how far it has
            # read are both on record, or neither is.
            session.commit()
            payloads = [message_out(message) for message in waiting]
            notes = [
                (m.id, m.from_agent_id, names.get(m.from_agent_id or "", "another agent"),
                 m.content)
                for m in waiting
            ]
            # One from an agent that is not of this turn: of another conversation.
            far = {
                m.from_agent_id: session.scalar(
                    select(Agent.name).where(Agent.id == m.from_agent_id))
                for m in waiting if m.from_agent_id and m.from_agent_id not in names
            }
            new = [message_out(message) for message in handed]
            of = {post.id: post for post in session.scalars(select(BoardPost).where(
                BoardPost.id.in_([m.board_post_id for m in handed])))}
            from_notebook = [
                board.handed(
                    board.labelled(names.get(m.from_agent_id, "another agent"), of[m.board_post_id])
                    if m.from_agent_id else None,
                    self._note_from(ctx, m.from_agent_id, of[m.board_post_id]), m.content,
                    of[m.board_post_id].koloni,
                )
                for m in handed
            ]
            # Other agents' words (not KOLONİ's, from elsewhere or on the notebook): their
            # note to the agent is where it reads them (`_from`, `board.handed`).
            heard = [(f"a message from {name}", content) for _id, sender, name, content in notes
                     if sender and sender not in far and not self._is_above(sender, ctx)] + [
                (f"a note from {names.get(m.from_agent_id, 'another agent')}", m.content)
                for m in handed if m.from_agent_id and not of[m.board_post_id].koloni
                and m.from_agent_id != ctx.parent_id]
        for payload in payloads:
            self.bus.emit(ctx.cid, ctx.run_id, "message.completed", payload)
        for payload in new:
            self.bus.emit(ctx.cid, ctx.run_id, "message.created", payload)
        for where, content in heard:
            self._orders(ctx, "agent", where, content)
        def relation(sender: str) -> str:
            # As its conversation says it later (`_history`): one of its sub-agents is "below".
            if sender in far:
                return "elsewhere"
            below = self._ctxs.get(sender)
            return "below" if below is not None and self._is_above(ctx.agent_id, below) else "other"

        return [
            # (From nobody: KOLONİ's own word, `_send(koloni=True)`, read as it is.)
            content if sender is None else self._from(
                ctx, message_id, sender, far.get(sender) or name, relation(sender), content)
            for message_id, sender, name, content in notes
        ] + from_notebook + posts

    @staticmethod
    def _note_from(ctx: Ctx, writer: str | None, post: BoardPost) -> str:
        """Who a note on the notebook is from, to the agent handed it. The agent that
        opened it is the one it works for - and its note is still no task."""
        return board.FROM_ABOVE.format(whom="your team" if post.team_id and not post.everyone
                                       else "every agent of this turn") if (
            writer and writer == ctx.parent_id) else FROM["other"]

    def _hand_notes(self: "AgentRunner", session, ctx: Ctx) -> list[Message]:
        """Write the notebook's notes this agent has not seen into its conversation, and
        move its mark past them - in the caller's transaction, which commits both. Its
        own notes are passed over, and another team's (its mark moves past them too). The
        mark only moves from where it was read: were two deliveries to the same agent ever
        under way, the second hands over nothing."""
        seen = session.scalar(select(Agent.board_seen).where(Agent.id == ctx.agent_id)) or 0
        posts = session.scalars(
            select(BoardPost)
            .where(BoardPost.run_id == ctx.run_id, BoardPost.seq > seen)
            .order_by(BoardPost.seq)
        ).all()
        if not posts:
            return []
        reads = self._reader(session, ctx)
        moved = session.execute(
            update(Agent)
            .where(Agent.id == ctx.agent_id, Agent.board_seen == seen)
            .values(board_seen=posts[-1].seq)
        )
        if moved.rowcount != 1:
            session.rollback()
            return []
        rows = [
            Message(
                conversation_id=ctx.cid, run_id=ctx.run_id, agent_id=ctx.agent_id,
                from_agent_id=post.agent_id, role="agent", content=post.content,
                status="complete", delivered_at=now(), board_post_id=post.id,
            )
            for post in posts if post.agent_id != ctx.agent_id and reads(post)
        ]
        session.add_all(rows)
        return rows

    def _team_of(self: "AgentRunner", session, cid: str, run_id: str,
                 agent_id: str) -> tuple[str, str] | None:
        """K-not-oda: the team an agent of a turn works in, (id, name), by the rule the canvas
        frames its agents by: where a row of the chat's teams ran in the turn, the row whose
        agents it is among; else (B-101's frames by roles) the team whose lead opened it or an
        agent above it, the first of the chat's teams that has its role or is led by it, or else
        the team of the agent that opened it (K-takimlar-arasi: a Coder Backend's lead opened,
        and its helper, are Backend's, though the Web app comes first and has a Coder too).
        None: the Lead, an agent of no team, a chat with no teams.
        shortcut: where a row ran, an agent in none (a member of a room the user opened, one kept
        beside a recipe) is of no team, and every team reads its notes; give it its opener's
        team if that is met."""
        rows = self._rows(session, cid)
        if not rows:
            return None
        ran = [(row.state or {}, team) for row, team, _lead in rows
               if (row.state or {}).get("run_id") == run_id]
        if ran:
            return next(((team.id, team.name) for state, team in ran
                         if agent_id in state.get("agents", ())), None)
        roles = self._chat_roles(session, rows)
        led = {lead.name: team for _row, team, lead in rows if lead}
        walk = session.get(Agent, agent_id)
        while walk is not None and walk.depth > 0:  # (what a lead opened, and all under it)
            opener = session.get(Agent, walk.parent_agent_id or "")
            if opener is not None and opener.role_name in led:
                return led[opener.role_name].id, led[opener.role_name].name
            walk = opener
        while agent_id:
            agent = session.get(Agent, agent_id)
            if agent is None or agent.depth == 0:
                return None
            found = next(
                (team for _row, team, _lead in rows if agent.role_name in roles[team.id]), None)
            if found is not None:
                return found.id, found.name
            agent_id = agent.parent_agent_id or ""
        return None

    @staticmethod
    def _chat_roles(session, rows) -> dict[str, set[str]]:
        """Each of the chat's teams' roles by the team's id: those that are on, and its lead."""
        return {team.id: {*team_roles(session, team), *session.scalars(
            select(Role.name).where(Role.id == team.lead_role_id))} for _row, team, _lead in rows}

    def _between(self: "AgentRunner", session, ctx: Ctx, roles: list[str],
                 agents: list[str]) -> list[str]:
        """K-not-oda: the teams a room's or a discussion's members come from - of these roles,
        and agents of the turn - where no one of the chat's teams holds them all: a room
        between teams. [] within one team, or in a chat with no teams. A role is of each team
        that has it or is led by it; an agent of its team (`_team_of`); one of no team holds
        nobody back."""
        rows = self._rows(session, ctx.cid)
        if not rows:
            return []
        of = self._chat_roles(session, rows)
        held = [{team for team, names in of.items() if role in names} for role in roles] + [
            {found[0]} for agent in agents
            if (found := self._team_of(session, ctx.cid, ctx.run_id, agent))]
        held = [one for one in held if one]
        if len(held) < 2 or set.intersection(*held):
            return []
        order = [team.id for _row, team, _lead in rows]
        named = {min(one, key=order.index) for one in held}  # (the first of the chat's it is in)
        return [team.name for _row, team, _lead in rows if team.id in named]

    def _leads_teams(self: "AgentRunner", session, ctx: Ctx) -> bool:
        """Whether this agent may bring teams together (a room, a note for every team): the
        Lead, or the lead of one of the chat's teams that runs it beside another (`_rows`)."""
        return ctx.depth == 0 or any(
            lead is not None and lead.name == ctx.role for _row, _team, lead in self._rows(
                session, ctx.cid))

    def _reader(self: "AgentRunner", session, ctx: Ctx) -> Callable[[BoardPost], bool]:
        """Which notes an agent reads: the Lead every team's; any other its own team's, the
        whole turn's (a note of no team) and one for every team."""
        if ctx.depth == 0:
            return lambda _post: True
        team = self._team_of(session, ctx.cid, ctx.run_id, ctx.agent_id)
        mine = team[0] if team else None
        return lambda post: post.team_id is None or post.everyone or post.team_id == mine

    # --- the shared notebook ---------------------------------------------------

    def _write_note(self: "AgentRunner", run_id: str, cid: str, agent_id: str | None, content: str,
                    team: tuple[str, str] | None = None, everyone: bool = False,
                    koloni: bool = False) -> dict:
        """Put a note on a turn's notebook (the user's, with no agent; KOLONİ's own with
        `koloni`) - on its team's (id, name), or for every team; ToolError when the notebook
        is full.

        Nothing here waits (no await), and it is only ever called on the event loop: a
        note's place in the order is taken and written in one go, so no note can land
        behind the mark of an agent that has already read past it. `_deliver` relies on
        the same."""
        with self._factory() as session:
            last, written = session.execute(
                select(func.max(BoardPost.seq), func.sum(func.length(BoardPost.content)))
                .where(BoardPost.run_id == run_id)
            ).one()
            last, written = last or 0, written or 0
            if last >= board.MAX_NOTES_PER_TURN:
                raise ToolError(board.full())
            if written + len(content) > board.room(self.settings.context_char_budget):
                raise ToolError(board.no_room())
            post = BoardPost(
                run_id=run_id, conversation_id=cid, agent_id=agent_id, content=content,
                seq=last + 1, team_id=team[0] if team else None, team=team[1] if team else None,
                everyone=everyone, koloni=koloni,
            )
            session.add(post)
            session.commit()
            payload = board_post_out(post)
        self.bus.emit(cid, run_id, "board.posted", payload)
        return payload

    def _backlog(self: "AgentRunner", ctx: Ctx, name: str, args: dict) -> str:
        """read_backlog, add_task, change_task or assess_task on the backlog of the
        conversation's project (`app.backlog`, whose functions bear the tools' names)."""
        with self._factory() as session:
            try:
                project_id = backlog.project_of(session, ctx.cid)
                said = getattr(backlog, name)(session, project_id, args)
            except backlog.Refused as exc:
                raise ToolError(str(exc)) from None
            session.commit()
        if name != "read_backlog":
            announce(self._factory, self.bus, project_id, "backlog.changed")
        return said

    def _post_note(self: "AgentRunner", ctx: Ctx, args: dict) -> str:
        """An agent writes on the notebook - its team's, where it works in one; nobody is
        waited for. A team's lead may write for every team (`everyone`)."""
        note, everyone = board.plan_note(args)
        with self._factory() as session:
            team = self._team_of(session, ctx.cid, ctx.run_id, ctx.agent_id)
            if everyone and team is not None and not self._leads_teams(session, ctx):
                raise ToolError(board.NOT_A_LEAD)
        payload = self._write_note(ctx.run_id, ctx.cid, ctx.agent_id, note, team,
                                   everyone and team is not None)
        with self._factory() as session:
            post = session.get_one(BoardPost, payload["id"])
            # (Those that read it: not another team's.)
            at_work = sum(
                1 for agent_id, known in self._who(ctx.run_id).items()
                if agent_id != ctx.agent_id
                and known[2] in ("running", "queued", "waiting", "blocked")
                and (agent_id not in self._ctxs
                     or self._reader(session, self._ctxs[agent_id])(post))
            )
        # No promise that it is read: an agent that takes no further step, or a CLI at
        # work with its own tools that asks KOLONİ for nothing, is never handed it.
        if not at_work:
            return (
                "noted: nobody else is at work right now; an agent that starts or goes on "
                "later in this turn sees it if it takes a step."
            )
        who = (
            "1 other agent at work sees this at its next step, if it takes one"
            if at_work == 1
            else f"{at_work} other agents at work see this at their next step, if they take one"
        )
        return f"noted: {who}. Nobody replies to a note; go on with your own work."

    async def _record_made(
        self: "AgentRunner", ctx: Ctx, root: Path, paths: Collection[str], copy: copies.Copy | None
    ) -> None:
        """R161: the files a command of this agent's made that no change record holds - a
        docx, a pdf, a picture: written only by a command - are its outputs beside the chat,
        as if it had shown them (`_show`): of a made kind (`views.made_here`), and only what
        `show` would put there. In a copy, only what the copy itself changed: what it was made
        with, or another agent's work brought into it (`Copy.refresh`), is not this command's.
        shortcut: at most `views.MOST_MADE` an agent, the rest left out (a report a command
        writes again and again); and each path once a conversation - the agent that made it
        first keeps it (not another whose look finds it taken in, or put back), made again it
        keeps its first place in the list. Not from `_look_at_project` (a CLI in a copy
        writing the project by its path): look there too if such outputs are missed."""
        if _changes_nothing(ctx):  # (what changed beside it, at work at once: not its)
            return
        owner = None if copy is None else next(
            (one for one, held in self._copies.items() if held is copy), None)
        ws = copy.workspace() if copy is not None else Workspace(str(root))
        with self._factory() as session:
            had = set(session.scalars(select(ShownFile.path).where(
                ShownFile.conversation_id == ctx.cid)))
            left = views.MOST_MADE - session.scalar(select(func.count()).where(
                ShownFile.conversation_id == ctx.cid, ShownFile.agent_id == ctx.agent_id))
        wanted = sorted(rel for rel in paths if rel not in had and views.made_here(rel))
        if left <= 0 or not wanted:
            return

        def vetted() -> list[str]:  # (each reads the disk: off the loop)
            out: list[str] = []
            for rel in wanted:
                if copy is not None and copy.state(rel) is None:
                    continue
                try:
                    rel = views.check_shown(ws, rel)
                except WorkspaceError:
                    continue  # (gone, a hard link, a secret, by a link out of it)
                if rel not in had and rel not in out:
                    out.append(rel)
                    if len(out) >= left:
                        break
            return out

        found = await asyncio.to_thread(vetted)
        with self._factory() as session:
            rows = [ShownFile(conversation_id=ctx.cid, agent_id=ctx.agent_id, path=rel,
                              copy_owner=owner) for rel in found]
            session.add_all(rows)
            session.commit()
            payloads = [{"id": row.id, "path": row.path, "agent_id": ctx.agent_id, "note": None}
                        for row in rows]
        for payload in payloads:
            self.bus.emit(ctx.cid, ctx.run_id, "view.shown", payload)

    def _show(self: "AgentRunner", ctx: Ctx, ws: Workspace, args: dict) -> str:
        """Put a file of the project - or of the agent's working copy - before the user, in
        the view beside the chat (`app.views`). It only reads: nobody is asked."""
        path, note = args.get("path"), args.get("note")
        if not isinstance(path, str):
            raise ToolError("missing required argument: path")
        if note is not None and not isinstance(note, str):
            raise ToolError("argument note must be a string")
        try:
            rel = views.check_shown(ws, path)
        except WorkspaceError as exc:
            raise ToolError(str(exc)) from None
        note = " ".join((note or "").split())[: views.MAX_NOTE_CHARS] or None
        # Shown from a working copy: served from there while it is (`copy_workspace`).
        owner = self._copy_owner(ctx) if self._copy_of(ctx) is not None else None
        with self._factory() as session:
            row = ShownFile(conversation_id=ctx.cid, agent_id=ctx.agent_id, path=rel, note=note,
                            copy_owner=owner)
            session.add(row)
            session.commit()
            payload = {"id": row.id, "path": rel, "agent_id": ctx.agent_id, "note": note}
        self.bus.emit(ctx.cid, ctx.run_id, "view.shown", payload)
        return f"shown: {rel} is in the view beside the chat"
