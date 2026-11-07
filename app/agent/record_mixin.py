"""Record keeping: an agent's messages and tool calls on record, calls left open when a turn is
cut short, a run's status and how it finishes, the roles it did not open, git after a turn,
and the next turn that waits - `RecordMixin`.
"""

import asyncio
import contextlib
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import and_, func, literal_column, or_, select, true

from app import away, backlog, board, earlier, git, recipe_run
from app.agent.ctx import TERMINAL, Ctx, _NobodyToAsk, announce
from app.agent.merge import _forget_secrets, landed
from app.agent.words import NOBODY, UNFINISHED
from app.db.models import (
    Agent,
    BacklogTask,
    BoardPost,
    Conversation,
    Discussion,
    FileChange,
    Merge,
    Message,
    Question,
    Role,
    Run,
    ToolCall,
    WebRequest,
    now,
)
from app.roles import LEAD, shown_name
from app.serialize import (
    board_post_out,
    conversation_out,
    discussion_out,
    file_change_out,
    message_out,
    question_out,
    run_out,
    tool_call_out,
    web_request_out,
)
from app.team import quoted
from app.workspace import in_scratch

if TYPE_CHECKING:
    from app.agent import AgentRunner

log = logging.getLogger("app.agent")


class RecordMixin:
    # --- record keeping ------------------------------------------------------

    def _save_message(self: "AgentRunner", message_id: str, content: str, status: str,
                      blocks: dict | None = None) -> dict:
        with self._factory() as session:
            message = session.get(Message, message_id)
            message.content = content
            message.status = status
            message.blocks = blocks or message.blocks
            session.commit()
            return message_out(message)

    def _set_call(self: "AgentRunner", cid: str, call_id: str, **fields) -> None:
        with self._factory() as session:
            call = session.get(ToolCall, call_id)
            for key, value in fields.items():
                setattr(call, key, value)
            session.commit()
            run_id, payload = call.run_id, tool_call_out(call)
        self.bus.emit(cid, run_id, "tool_call.updated", payload)

    def _interrupt_open_calls(  # noqa: C901
        self: "AgentRunner", run_id: str, cid: str, agent_id: str | None = None,
        after_call: int = 0, only: set | None = None,
    ) -> None:
        """Settle what was cut short: the whole run's, or only one agent's (and of that
        agent's calls, only those made after call number `after_call`). With `only` -
        the calls of an answer turn - nothing but those calls: the agent's own work,
        which may be waiting on the user, is not the answer's to settle."""
        one_agent = (
            (
                ToolCall.agent_id == agent_id,
                FileChange.agent_id == agent_id,
                Question.agent_id == agent_id,
            )
            if agent_id
            else (true(), true(), true())
        )
        with self._factory() as session:
            open_calls = session.scalars(
                select(ToolCall)
                .where(ToolCall.run_id == run_id, ToolCall.status.in_(("pending", "running")))
                .where(one_agent[0], ToolCall.seq > after_call)
                .where(ToolCall.id.in_(only) if only is not None else true())
                .order_by(ToolCall.seq)
            ).all()
            for call in open_calls:
                call.status, call.result, call.ended_at = "interrupted", UNFINISHED, now()
                _forget_secrets(session, call)
            session.commit()
            payloads = [tool_call_out(call) for call in open_calls]
        for payload in payloads:
            self.bus.emit(cid, run_id, "tool_call.updated", payload)
        if only is not None:
            return
        self.commands.close_open(run_id, cid, agent_id)
        # A change still waiting for a decision dies with its run. One the user had said
        # yes to, whose agent never got its place, is not "rejected" - that is the user's
        # own no: it was never made ("discarded"), and when the yes was said stays.
        with self._factory() as session:
            waiting = session.scalars(
                select(FileChange)
                .where(FileChange.run_id == run_id,
                       FileChange.status.in_(("proposed", "approved")))
                .where(one_agent[1])
            ).all()
            for change in waiting:
                change.status, change.decided_at = (
                    ("discarded", change.decided_at) if change.status == "approved"
                    else ("rejected", now()))
            session.commit()
            payloads = [file_change_out(change) for change in waiting]
        for payload in payloads:
            self.bus.emit(cid, run_id, "file_change.updated", payload)
        # And a search or a request nobody decided on. One the user had said yes to
        # whose call was cut short here - its agent never got its place, or its answer
        # never came - is not left "approved", which is what one that went out is:
        # "interrupted", as its call is.
        cut_short = [call.id for call in open_calls]
        with self._factory() as session:
            undecided = session.scalars(
                select(WebRequest)
                .where(WebRequest.run_id == run_id, or_(
                    WebRequest.status == "proposed",
                    and_(WebRequest.status == "approved",
                         WebRequest.tool_call_id.in_(cut_short))))
                .where(WebRequest.agent_id == agent_id if agent_id else true())
            ).all()
            for asked in undecided:
                if asked.status == "approved":
                    asked.status = "interrupted"
                else:
                    asked.status, asked.decided_at = "rejected", now()
            session.commit()
            payloads = [web_request_out(asked) for asked in undecided]
        for payload in payloads:
            self.bus.emit(cid, run_id, "web_request.updated", payload)
        # So does a question nobody answered.
        with self._factory() as session:
            unanswered = session.scalars(
                select(Question)
                .where(Question.run_id == run_id, Question.status == "pending")
                .where(one_agent[2])
            ).all()
            for question in unanswered:
                question.status = "cancelled"
            session.commit()
            payloads = [question_out(question) for question in unanswered]
        for payload in payloads:
            self.bus.emit(cid, run_id, "question.updated", payload)
        # And a discussion that was going on: the whole run's, or the one this agent opened.
        with self._factory() as session:
            talks = session.scalars(
                select(Discussion)
                .where(Discussion.run_id == run_id, Discussion.status == "running")
                .where(Discussion.agent_id == agent_id if agent_id else true())
            ).all()
            for talk in talks:
                talk.status, talk.ended_at = "cancelled", now()
            session.commit()
            payloads = [discussion_out(session, talk) for talk in talks]
        for payload in payloads:
            self.bus.emit(cid, run_id, "discussion.updated", payload)

    def _update_run(self: "AgentRunner", run_id: str, cid: str, **fields) -> None:
        # Several agents may be waiting on the user at once: the turn waits for approval
        # until the last of them has its decision.
        if fields == {"status": "waiting_approval"}:
            if run_id in self._unwatched:
                # Should never be reached: everything that waits asks `_nobody_to_ask`
                # first. If something ever does not, it is refused here, not waited for.
                raise _NobodyToAsk(NOBODY.format(
                    trigger=quoted(self._unwatched[run_id].trigger_name), what="do this"))
            self._asking[run_id] = self._asking.get(run_id, 0) + 1
            if run_id in self._away_jobs:  # (after what it waits for is on record)
                asyncio.get_running_loop().call_soon(self._job_waits, run_id, True)
        elif fields == {"status": "running"}:
            left = self._asking[run_id] = max(0, self._asking.get(run_id, 0) - 1)
            task = self._tasks.get(run_id)
            # Not while another still asks; and a turn being stopped is not "running".
            if left or (task is not None and task.cancelling()):
                return
            if run_id in self._away_jobs:
                self._job_waits(run_id, False)
        with self._factory() as session:
            run = session.get(Run, run_id)
            for key, value in fields.items():
                setattr(run, key, value)
            session.commit()
            payload = run_out(run)
        self.bus.emit(cid, run_id, "run.updated", payload)
        if "status" in fields:  # (K-symphony: a task's card says when its turn waits for you)
            with contextlib.suppress(Exception), self._factory() as session:
                project_id = session.scalar(select(BacklogTask.project_id).where(
                    BacklogTask.conversation_id == cid, BacklogTask.status == "doing").limit(1))
                announce(self._factory, self.bus, project_id, "backlog.changed")

    def _roles_not_opened(self: "AgentRunner", run_id: str, cid: str, ctx: Ctx) -> None:
        """K-lead-andigi-rol (R114), B-331: a Lead's answer that claims a role's work
        ("Reviewer confirmed the change", "I asked Tester to run it") while no agent of that
        role was opened this turn gets one line of KOLONİ's own under it - a "koloni" message,
        which no agent is given - so the user is not told of a check that was not made. Role
        names as whole words, whatever their case; not Lead. A bare mention, a list of roles,
        a could / would / can / will, or a line ending with "?" is no claim.
        shortcut: English only - the name then a past-tense verb in the same sentence, or
        "I asked / had / opened / let / got" before it; a claim worded otherwise is missed
        (better than noise) - add its words where a line is seen to mislead."""
        did = (r"\b(?:confirmed|checked|reviewed|tested|verified|found|reported|approved|agreed"
               r"|said|wrote|fixed|ran|looked|finished|done|(?:has|have|had) \w+e[dn])\b")
        i_had = r"\bI (?:asked|had|opened|let|got|told|sent|made)\b"
        modal = r"\b(?:could|would|can|will|may|might|should)\b"
        with self._factory() as session:
            message = self.last_answer(session, run_id, ctx.agent_id)
            if message is None:
                return
            opened = {name.casefold() for name in session.scalars(
                select(Agent.role_name).where(Agent.run_id == run_id, Agent.id != ctx.agent_id))}
            claims = [one for line in message.content.splitlines()
                      if not line.rstrip().endswith("?")
                      for one in re.split(r"[.!;]", line) if not re.search(modal, one, re.I)]
            named = [name for name in session.scalars(select(Role.name).order_by(Role.name))
                     if name.casefold() not in opened and name.casefold() != LEAD.casefold()
                     and (word := rf"\b{re.escape(name)}\b")
                     and any(re.search(rf"{word}.*?{did}|{i_had}.*?{word}", one, re.I)
                             for one in claims)]
            if not named:
                return
        self._koloni_line(cid, run_id, (
            f"{', '.join(named)} {'was' if len(named) == 1 else 'were'} not opened this turn."))

    def _closed_not_opened(self: "AgentRunner", run_id: str, cid: str | None) -> None:
        """B-385: at the turn's end, however it ended, the user is told of each role refused on
        a model closed to agents that was never opened after all (`_closed_said`)."""
        said = self._closed_said.pop(run_id, None)
        if not said or cid is None:
            return
        with self._factory() as session:
            opened = {name.casefold() for name in session.scalars(select(Agent.role_name).where(
                Agent.run_id == run_id, Agent.status != "rejected"))}
        for role, text in said.items():
            if shown_name(role).casefold() not in opened:
                self._koloni_line(cid, run_id, text)

    def _koloni_line(self: "AgentRunner", cid: str, run_id: str, text: str) -> None:
        """A line of KOLONİ's own in the chat - a "koloni" message, which no agent is given - once
        a turn for the same words (B-385: an agent refused on a model closed to agents)."""
        with self._factory() as session:
            if session.scalar(select(Message.id).where(
                    Message.run_id == run_id, Message.role == "koloni",
                    Message.content == text).limit(1)):
                return
            note = Message(conversation_id=cid, run_id=run_id, role="koloni", content=text)
            session.add(note)
            session.commit()
            payload = message_out(note)
        self.bus.emit(cid, run_id, "message.completed", payload)

    def _say_landed(self: "AgentRunner", cid: str, run_id: str, due: bool) -> None:
        """B-205: where the turn's work is, under the Lead's answer - a "landed" message of
        KOLONİ's own, from the records (`merge.landed`), which no agent is given. Nothing said
        where not `due`, nor for a turn that changed no file.
        shortcut: said as it stands at the turn's end; a kept copy taken in or discarded later
        does not change it (its card says so) - rewrite it at `decide_kept` if that misleads."""
        if not due:
            return
        try:
            with self._factory() as session:
                said = landed(session, run_id)
                if said is None:
                    return
                note = Message(conversation_id=cid, run_id=run_id, role="landed", content=said)
                session.add(note)
                session.commit()
                payload = message_out(note)
        except Exception as exc:  # (it fails nothing of the turn)
            log.warning("run %s: where its work is not said: %r", run_id, exc)
            return
        self.bus.emit(cid, run_id, "message.completed", payload)

    async def _git_after(self: "AgentRunner", run_id: str, cid: str, root: Path | None) -> None:
        """What the turn did to the project's git, against how it began (slice 70), said in
        the chat as a line of KOLONİ's own - a "git" message, which no agent is given -
        where there is something to say (`git.turn_note`).
        shortcut: another chat's turn in the project, or the user's own hand, at the same
        time is taken for this turn's doing; tell them apart if users are misled by it."""
        before = self._git_at.get(run_id)
        if before is None or root is None:
            return
        clis = self._git_clis.get(run_id, {})
        cli = next(iter(clis.values())) if len(clis) == 1 else None
        reports = list(self._git_said.get(run_id, []))

        def note() -> str | None:
            after = git.where(root)
            return None if after is None else git.turn_note(root, before, after, cli, reports)

        said = await asyncio.to_thread(note)
        if said is None:
            return
        with self._factory() as session:
            message = Message(conversation_id=cid, run_id=run_id, role="git", content=said)
            session.add(message)
            session.commit()
            payload = message_out(message)
        self.bus.emit(cid, run_id, "message.completed", payload)

    def _finish(self: "AgentRunner", run_id: str, cid: str, status: str,
                error: str | None) -> list[str]:
        """The turn on record as over, and what follows at once. The backlog tasks it
        moved, or whose turn stopped the backlog working itself (`backlog.turn_ended`)."""
        with self._factory() as session:
            run = session.get(Run, run_id)
            run.status, run.error, run.ended_at = status, error, now()
            conversation = session.get(Conversation, cid)
            conversation.updated_at = now()
            # A backlog task worked on here waits for review - with the turn, not after it
            # (and goes back to todo where a turn ends otherwise: `_force_fail`,
            # `recover_interrupted`, a Stop with nothing to stop).
            moved = backlog.turn_ended(session, run, status)
            job = away.turn_ended(session, run, status)
            later = away.after_the_night(session, run) if job else None
            session.commit()
            payload, conversation_payload = run_out(run), conversation_out(conversation)
            if later is not None:
                self.bus.emit(later.conversation_id, None, "message.completed", message_out(later))
            project_id = conversation.project_id
            side = run.compare_id is not None
        # What was said in it is found from here on (`app.earlier`). If that cannot be
        # written the turn ends all the same: it is indexed when the app next starts.
        with contextlib.suppress(Exception), self._factory() as session:
            earlier.index_run(session, run_id)
            session.commit()
        self._close_agents(run_id, cid, status, error)
        try:
            self._continuation_note(run_id, cid)
        except Exception as exc:  # (it fails nothing of the turn)
            log.warning("run %s: no continuation note: %r", run_id, exc)
        self._unattended_over(run_id, status, error)
        self.bus.emit(cid, None, "conversation.updated", conversation_payload)
        self.bus.emit(cid, run_id, "run.finished", payload)
        self.start_next(cid)
        # Where the backlog works itself, the next task starts now - after any turn: one
        # whose task was moved on by hand held it back (`backlog.busy`). It never raises.
        # Not after a side of a comparison: only the conversation's own turns move it.
        if project_id is None:  # (a plain chat has none - and None would name every plain chat)
            return moved
        changed = job
        if not self._closing and not side:
            with contextlib.suppress(Exception), self._factory() as session:
                changed = backlog.chain(session, project_id, self.bus, self.start) or changed
            with contextlib.suppress(Exception), self._factory() as session:
                changed = away.go_on(session, project_id, self) or changed
        if moved or changed:  # (once, after the chain: a halt it set is seen too)
            announce(self._factory, self.bus, project_id, "backlog.changed")
        return moved

    @staticmethod
    def _still_waiting(session, cid: str, run_id: str | None, but: str | None = None
                       ) -> list[str]:
        """G7: what waits for the user, as it stands now: the questions of turn `run_id` nobody
        answered, and - of any turn of the chat but `but` - a plan still to decide on and a
        kept copy still to take in or discard. What somebody wrote is quoted (`board.said`)."""
        names = dict(session.execute(select(Agent.id, Agent.name).join(
            Run, Run.id == Agent.run_id).where(Run.conversation_id == cid)).all())
        other = Run.id != but if but else true()
        waits = [f"{names.get(asked.agent_id, 'an agent')} asked, not answered: "
                 f"{board.said(asked.question)}" for asked in session.scalars(
                     select(Question).where(
                         Question.run_id == run_id,
                         Question.status.in_(("pending", "cancelled", "interrupted"))
                     ).order_by(Question.created_at))]
        waits += [f"the plan, to approve or turn down: {board.said(str(plan.get('text') or ''))}"
                  for plan in session.scalars(select(Run.plan).where(
                      Run.conversation_id == cid, Run.plan.is_not(None), other
                  ).order_by(Run.created_at)) if plan.get("status") == "proposed"]
        waits += [f"{names.get(kept.agent_id, 'an agent')}'s work, kept for Take in or Discard "
                  f"({len(kept.files)} {'file' if len(kept.files) == 1 else 'files'})"
                  for kept in session.scalars(select(Merge).join(Run, Run.id == Merge.run_id).where(
                      Run.conversation_id == cid, Merge.status == "interrupted",
                      Merge.kept_in.is_not(None), other).order_by(Merge.created_at))]
        return waits

    def _continuation_note(self: "AgentRunner", run_id: str, cid: str) -> None:
        """G7: as a turn ends, KOLONİ notes where the work stands, from its records and with no
        model (`board.continuation`), on the turn's notebook - past its limits: it is KOLONİ's,
        not an agent's. Only a turn of the user's own message says what they asked.
        shortcut: a turn a restart cut off (`recover_interrupted`) gets none, and the next Lead
        is told nothing of it; write one there if that is missed."""
        with self._factory() as session:
            run = session.get_one(Run, run_id)
            agents = session.scalars(select(Agent).where(Agent.run_id == run_id).order_by(
                Agent.created_at, literal_column("agents.rowid"))).all()
            waits = self._still_waiting(session, cid, run_id)
            asked = session.scalar(select(Message.content).where(
                Message.run_id == run_id, Message.role == "user").order_by(
                Message.created_at, literal_column("messages.rowid")).limit(1)) if (
                run.by_user and run.status != "completed") else None
            done = [agent.name for agent in agents if agent.depth and agent.status == "completed"]
            left = [f"{agent.name} ({agent.status})" for agent in agents
                    if agent.depth and agent.status in ("failed", "cancelled", "interrupted")]
            for row, team, _lead in self._rows(session, cid):
                state = row.state or {}
                if state.get("run_id") != run_id or state.get("status") == recipe_run.WAITING:
                    continue
                what = f"{team.name} ({state.get('recipe') or 'no recipe'}"
                if state["status"] in (recipe_run.DONE, recipe_run.IN):
                    done.append(what + ")")
                elif state["status"] != recipe_run.READY:  # (its copy waits: above)
                    why = f": {state['why']}" if state.get("why") else ""
                    left.append(f"{what}, {state['status']}{why})")
            files = list(dict.fromkeys(path for path in session.scalars(
                select(FileChange.path).where(
                    FileChange.run_id == run_id, FileChange.status == "applied")
                .order_by(FileChange.created_at)) if not in_scratch(path)))
            note = board.continuation(
                board.ENDED.get(run.status, run.status), waits, asked, done,
                files[:board.FILES_NAMED] + ([f"{len(files) - board.FILES_NAMED} more"]
                                             if len(files) > board.FILES_NAMED else []), left)
            if note is None:
                return
            last = session.scalar(select(func.max(BoardPost.seq)).where(BoardPost.run_id == run_id))
            post = BoardPost(run_id=run_id, conversation_id=cid, agent_id=None, content=note,
                             seq=(last or 0) + 1, koloni=True)
            session.add(post)
            session.commit()
            payload = board_post_out(post)
        self.bus.emit(cid, run_id, "board.posted", payload)

    def start_next(self: "AgentRunner", cid: str) -> None:
        """Start the oldest queued run of a conversation, if nothing else is running."""
        if self._closing:
            return
        with self._factory() as session:
            runs = session.scalars(
                select(Run)
                .where(Run.conversation_id == cid, Run.status.not_in(TERMINAL))
                .order_by(Run.created_at, literal_column("runs.rowid"))
            ).all()
            if not runs or runs[0].status != "queued":
                return
            run = runs[0]
            run.status, run.started_at = "running", now()
            session.commit()
            run_id, payload = run.id, run_out(run)
        self.bus.emit(cid, run_id, "run.updated", payload)
        self.start(run_id)
