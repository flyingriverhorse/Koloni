"""A job while the user is away (slice 106, `app.away`) and a turn nobody watches: what waits
for the morning and what is asked, its deadline, the trigger it proposes, and how such a turn
ends - `AwayMixin`.
"""

import asyncio
import contextlib
from typing import TYPE_CHECKING

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app import away, project_map
from app.agent.ctx import TERMINAL, Ctx, announce
from app.agent.words import AGENT_TERMINAL
from app.commands import (
    harms,
    installs,
    reaches_shared_git,
    runs_another,
    runs_inline,
    scratch_delete_only,
    switches_branch,
    with_cwd,
)
from app.db.models import Agent, AwayRun, Conversation, Merge, Run, now
from app.roles import LEAD
from app.tools import ToolError

if TYPE_CHECKING:
    from app.agent import AgentRunner


def branch_held(session: Session, project_id: str, but_run: str | None = None,
                copies: bool = False) -> tuple[str, str] | None:
    """K-dallar: whose work a switch of the project's branch would go under, and why in the
    git map's words, with what to do - an agent at work in a turn of the project that is not
    over (but `but_run`, the asking agent's own: there only one at work in a copy, `copies`),
    a Take in that waits, or a kept copy. None for none."""
    runs = select(Run.id).join(Conversation, Conversation.id == Run.conversation_id).where(
        Conversation.project_id == project_id)
    busy = runs.where(Run.status.not_in(TERMINAL), Run.id != (but_run or ""))
    whose_work = Agent.run_id.in_(busy)
    if copies:
        whose_work = or_(whose_work, and_(Agent.run_id == (but_run or ""),
                                          Agent.copy["state"].as_string() == "own"))
    found = session.execute(
        select(Agent.name, Agent.role_name).where(whose_work, Agent.status.not_in(AGENT_TERMINAL))
        .order_by(Agent.depth.desc()).limit(1)).first()
    if found or session.scalar(busy.limit(1)):
        whose = (found.name or found.role_name) if found else "a turn"
        return whose, (f"{whose} is at work — wait for the turn to end" if found
                       else "a turn of the project is running — wait for it to end")
    merge = session.execute(
        select(Merge.status, Agent.name, Agent.role_name).join(Agent, Agent.id == Merge.agent_id)
        .where(Merge.run_id.in_(runs), or_(Merge.status == "pending", and_(
            Merge.status == "interrupted", Merge.kept_in.is_not(None))))
        .order_by(Merge.created_at.desc()).limit(1)).first()
    if merge:
        whose = merge.name or merge.role_name
        held = "finished work waits" if merge.status == "pending" else "work is kept in its copy"
        return whose, f"{whose}'s {held} — Take in or Discard it first"
    return None


class AwayMixin:
    # --- a job while the user is away (slice 106, `app.away`) ------------------------------

    def _job_waits(self: "AgentRunner", run_id: str, waiting: bool) -> None:
        """A job's turn waits for the user's word - the next job may start - or goes on."""
        if waiting and self._asking.get(run_id, 0) <= self._lead_asked.get(run_id, 0):
            return  # (all it waits for the Lead answers first; where it does not, called again)
        with contextlib.suppress(Exception), self._factory() as session:
            project_id = away.waits(session, run_id, waiting)
            if project_id is None:
                return
            if waiting and not self._closing:
                away.go_on(session, project_id, self)
            announce(self._factory, self.bus, project_id, "backlog.changed")

    def cut(self: "AgentRunner", run_id: str, why: str) -> None:
        """Stop a job's turn as Stop does, its copy kept (`execute`), with why on record: its
        night stopped (`away.stop`)."""
        task = self._tasks.get(run_id)
        if task is not None and run_id not in self._away_cut:
            self._away_cut[run_id] = why
            task.cancel()

    def _hold_to_away(self: "AgentRunner", ctx: Ctx) -> None:
        """Before a model step, or a CLI, of a job while the user is away: past the night's
        time, or over its money, the night stops here - this job's turn with it."""
        if ctx.run_id not in self._away_jobs:
            return
        with self._factory() as session:
            night = away.night_of(session, ctx.cid)
            why = away.over(session, night) if night is not None else None
            if night is not None and why:
                away.stop(session, night, why, self)
            elif night is not None and (why := away.job_over(session, ctx.cid)):
                self.cut(ctx.run_id, why)  # (this job only: the next one goes on)
        if why:
            raise asyncio.CancelledError

    def _branch_asks(self: "AgentRunner", ctx: Ctx, command: str, in_copy: bool) -> str:
        """K-dallar: why an agent's own branch switch (`switches_branch`) is asked at every
        level - another turn of the project is at work, or a copy of it is held (an agent of
        this turn at work in one, a Take in or a kept copy waits): it moves the project under
        that work. Alone it runs as before, and the turn's end says it (`git.turn_note`). ""
        otherwise, and in a working copy: git is not there - but in a branch's worktree
        (K-dal-takim), where git is the user's own repository: what reaches its shared state
        is asked at every level (`reaches_shared_git`)."""
        owner = self._works_in(ctx) or ""
        copy = self._copies.get(owner)
        # (Or about to be made: the first command makes it - `_working_copy`.)
        if copy is not None and copy.branch or owner not in self._copies and (
                owner in self._on_branch):
            return reaches_shared_git(command, copy.branch if copy is not None else None)
        if in_copy or ctx.root is None or not switches_branch(command):
            return ""
        with self._factory() as session:
            project_id = session.scalar(
                select(Conversation.project_id).where(Conversation.id == ctx.cid))
            held = project_id and branch_held(session, project_id, ctx.run_id, copies=True)
        return f"switches the branch under {held[0]}'s work" if held else ""

    def _night_asks(self: "AgentRunner", ctx: Ctx, plain: str, cwd: object = None,
                    scratch_of: str | None = None) -> str:
        """Why a command waits for the user at every level. In a turn they watch: it deletes
        or overwrites, or sends something off this machine (`harms`) - at Full auto too, by
        the user's rule that nothing else asks there (K-fullauto-sorma). In a job while they
        are away those and, as nothing of a turn nobody watches goes unasked that cannot be
        taken back, one that runs what is not seen through a shell or a wrapper
        (`runs_another`), or - in a copy with the project's dependency folders linked in -
        installs into the project's own (`installs`); "" for one that does none of these, or
        in a turn nobody watches (its trigger's leave decides). In a side of a comparison harm
        (a side is thrown away, a push is not) and such an install alone: it stays in the
        project whichever side is chosen (K-54). In a backlog task's turn (K-r135) a night's,
        in the project itself - and so also one that runs code written on its line
        (`runs_inline`), but for the user's own test command (`project_map.own_test`).
        `plain` runs in `cwd` (run_command's), as `with_cwd` judges it. `scratch_of`: the
        folder the command runs in, where a delete only in its scratch is no harm to ask about
        in a watched turn (B-336, `scratch_delete_only`); None, not a copy's nor a CLI's own."""
        command = with_cwd(plain, cwd)
        if ctx.run_id in self._sides:
            # shortcut: not an install in a shell or a wrapper (`cmd /c npm i`), which
            # `runs_another` would catch only by asking about every one; look inside if seen.
            copy = self._copies.get(self._sides[ctx.run_id])
            return harms(command) or (
                installs(command) if copy is not None and copy.links else "")
        if ctx.run_id in self._backlog_turns:  # (a night's rules, in the project: no copy)
            if why := harms(command) or runs_another(command):
                return why
            if not (inline := runs_inline(command)):
                return ""
            with self._factory() as session:
                project = self._project(session, ctx.cid)
                tests = project.test_commands if project is not None else None
            return "" if project_map.own_test(tests, plain, cwd if isinstance(cwd, str) else None
                                              ) else inline
        if ctx.run_id not in self._away_jobs:
            # (K-fullauto-sorma: at Full auto an instruction file alone is no harm.)
            if not self._watched(ctx.run_id) or scratch_delete_only(command, scratch_of):
                return ""
            return harms(command, not self._full_auto(ctx))
        copy = self._copies.get(self._away_jobs[ctx.run_id])
        # shortcut: a job's agent runs its tests with its own line, judged as any command (R147:
        # a pipe into a filter no longer asks); have KOLONİ run the project's check_command for
        # it, unasked, if a test line is still seen to make a night's job wait.
        return harms(command) or runs_another(command) or (
            installs(command) if copy is not None and copy.links else "")

    def _arm_deadline(self: "AgentRunner", run_id: str, cid: str) -> None:
        """A job's turn is cut at its hour or at its night's time, whichever comes first -
        by the loop's clock, so also while no step of it is taken (a long command, a CLI)."""
        with self._factory() as session:
            night = away.night_of(session, cid)
            seconds = away.JOB_MINUTES * 60.0
            if night is not None and night.until is not None:
                seconds = min(seconds, (night.until - now()).total_seconds())
        later = self.call_later or asyncio.get_running_loop().call_later
        self._away_timers[run_id] = later(max(0.0, seconds), self._deadline, run_id, cid)

    def _deadline(self: "AgentRunner", run_id: str, cid: str) -> None:
        """A job's time is up: its night stops where its own time is (`away.over`), else the job
        is cut, its copy kept - not one that waits for the user's word."""
        with contextlib.suppress(Exception), self._factory() as session:
            night, task = away.night_of(session, cid), away.job_of(session, cid)
            if night is None or task is None or task.away_state == "waits":
                return
            if why := away.over(session, night):
                away.stop(session, night, why, self)
            else:
                self.cut(run_id, away.JOB_TOO_LONG)

    def _keeps_out(self: "AgentRunner", ctx: Ctx, path: str | None = None,
                   command: str | None = None,
                   what: str = "", cwd: str | None = None) -> str | None:
        """Why a write of `path` (relative, or a full one in the project or the job's copy) or
        `command` (its words also from `cwd`, the folder it runs in) is refused in a job while
        the user is away: it touches a place the user kept out - also after the night, in a
        job that waited for the user. Each try is on record for the morning. None elsewhere."""
        if ctx.run_id not in self._away_jobs:
            return None
        copy = self._copies.get(self._away_jobs[ctx.run_id])
        roots = (ctx.folder, *([str(copy.workspace().root)] if copy is not None else []))
        with self._factory() as session:
            task = away.job_of(session, ctx.cid)
            night = session.get(AwayRun, task.away_run_id) if task and task.away_run_id else None
            kept = away.kept_out(night, path, command, root=roots, cwd=cwd)
            if night is None or kept is None:
                return None
            away.tried(session, night, task.id if task else None, f"{ctx.name or ctx.role}: {what}")
        return away.KEPT_OUT.format(path=kept)

    def _no_away(self: "AgentRunner", session, ctx: Ctx) -> str | None:
        """Why this agent may not put a "While you're away" card before the user; None: it
        may. Only the Lead whose role keeps the To-do list, at the user's own turn of a chat
        with a folder: never a trigger's turn, a plan, a side of a comparison or a job of the
        night itself."""
        if (ctx.role != LEAD or ctx.depth or ctx.answering or ctx.discussion or ctx.root is None
                or "add_task" not in ctx.tools
                or not self._watched(ctx.run_id) or ctx.run_id in self._sides
                or ctx.run_id in self._away_jobs):
            return "plan_away is the Orchestrator's, at a turn of the user's own"
        run = session.get_one(Run, ctx.run_id)
        return "plan_away is not for a plan turn" if run.plan_turn or run.unattended else None

    def _plan_away(self: "AgentRunner", ctx: Ctx, args: dict) -> str:
        with self._factory() as session:
            if why := self._no_away(session, ctx):
                raise ToolError(why)
            try:
                said = away.plan(session, session.get_one(Conversation, ctx.cid), ctx.run_id,
                                 args)
            except away.Refused as exc:
                raise ToolError(str(exc)) from None
            session.commit()
            project_id = session.get_one(Conversation, ctx.cid).project_id
        announce(self._factory, self.bus, project_id, "backlog.changed")
        return said

    def _propose_trigger(self: "AgentRunner", ctx: Ctx, args: dict) -> str:
        """A trigger on a card in the chat (slice 69): nothing is made, nobody waits. Never in
        a turn nobody is watching - a trigger's turn would go on proposing triggers."""
        # (Here, not at the top: app.triggers reads this module.)
        from app import triggers as trigger_rules
        if not self._watched(ctx.run_id):
            raise ToolError("propose_trigger is for a turn the user started")
        with self._factory() as session:
            conversation = session.get_one(Conversation, ctx.cid)
            try:
                said = trigger_rules.propose(
                    session, conversation, ctx.run_id, args,
                    self.trigger_day() if self.trigger_day else trigger_rules.local_day(now()))
            except trigger_rules.Invalid as exc:
                raise ToolError(str(exc)) from None
            session.commit()
            project_id = conversation.project_id
        announce(self._factory, self.bus, project_id, "triggers.changed")
        return said

    def _unattended_over(self: "AgentRunner", run_id: str, status: str, error: str | None) -> None:
        if run_id in self._unwatched and self.unattended_ended is not None:
            # Its trigger keeps how it went. A failure to write that down must not keep
            # the turn itself from ending; it is settled when the app next starts.
            with contextlib.suppress(Exception):
                self.unattended_ended(run_id, status, error)
