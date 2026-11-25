"""A job while the user is away (slice 106, `app.away`) and a turn nobody watches: what waits
for the morning and what is asked, its deadline, the trigger it proposes, and how such a turn
ends - `AwayMixin`.
"""

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app import away, copies, parked
from app.agent.ctx import TERMINAL, Ctx, announce
from app.agent.words import AGENT_TERMINAL
from app.api.usage import over_budget
from app.commands import (
    harms,
    installs,
    reaches_shared_git,
    runs_another,
    scratch_delete_only,
    switches_branch,
    with_cwd,
)
from app.db.away_models import Parked
from app.db.models import (
    Agent,
    AwayRun,
    BacklogTask,
    Command,
    Conversation,
    Merge,
    Message,
    Project,
    Run,
    ToolCall,
    now,
)
from app.model_cli import CliStepClient
from app.model_native import ClaudeNativeClient
from app.roles import LEAD
from app.serialize import message_out, run_out
from app.tools import ToolError
from app.workspace import Workspace

if TYPE_CHECKING:
    from app.agent import AgentRunner

# Go away, to the away chat's Lead at work (`away_now`).
AWAY_TOLD = (
    "KOLONİ: the user has gone away (Away): finish this turn deciding what you can "
    "yourself; a question of yours to them waits for their return, so ask none you can "
    "do without. Their To-do list is worked through after this turn."
)


def branch_held(
    session: Session, project_id: str, but_run: str | None = None, copies: bool = False
) -> tuple[str, str] | None:
    """K-dallar: whose work a switch of the project's branch would go under, and why in the
    git map's words, with what to do - an agent at work in a turn of the project that is not
    over (but `but_run`, the asking agent's own: there only one at work in a copy, `copies`),
    a Take in that waits, or a kept copy. None for none."""
    runs = (
        select(Run.id)
        .join(Conversation, Conversation.id == Run.conversation_id)
        .where(Conversation.project_id == project_id)
    )
    busy = runs.where(Run.status.not_in(TERMINAL), Run.id != (but_run or ""))
    whose_work = Agent.run_id.in_(busy)
    if copies:
        whose_work = or_(
            whose_work,
            and_(Agent.run_id == (but_run or ""), Agent.copy["state"].as_string() == "own"),
        )
    found = session.execute(
        select(Agent.name, Agent.role_name)
        .where(whose_work, Agent.status.not_in(AGENT_TERMINAL))
        .order_by(Agent.depth.desc())
        .limit(1)
    ).first()
    if found or session.scalar(busy.limit(1)):
        whose = (found.name or found.role_name) if found else "a turn"
        return whose, (
            f"{whose} is at work — wait for the turn to end"
            if found
            else "a turn of the project is running — wait for it to end"
        )
    merge = session.execute(
        select(Merge.status, Agent.name, Agent.role_name)
        .join(Agent, Agent.id == Merge.agent_id)
        .where(
            Merge.run_id.in_(runs),
            or_(
                Merge.status == "pending",
                and_(Merge.status == "interrupted", Merge.kept_in.is_not(None)),
            ),
        )
        .order_by(Merge.created_at.desc())
        .limit(1)
    ).first()
    if merge:
        whose = merge.name or merge.role_name
        held = "finished work waits" if merge.status == "pending" else "work is kept in its copy"
        return whose, f"{whose}'s {held} — Take in or Discard it first"
    return None


def _tells_own_sub_agents(ctx: Ctx) -> bool:
    """☾ Away: whether KOLONİ tells the Orchestrator's own calls of its tools from those of a
    sub-agent of its CLI's own - always on a model KOLONİ steps (none such), and on Claude Code,
    whose hook names them (`USED_INSIDE`).
    shortcut: the other CLIs' own sub-agents are not measured: their Go away line takes no
    task; measure Copilot's and Codex's hooks and add each here."""
    model = ctx.model
    if not isinstance(model, CliStepClient):
        return True
    return isinstance(model, ClaudeNativeClient) and model.command == "claude"


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

    def away_now(self: "AgentRunner", cid: str) -> None:
        """Go away from chat `cid`: every card of it the Lead may decide (`_decidable`) is decided
        now, whatever its time - not another chat's, whose own minutes hold; its Lead at work is
        told the user went (call 8).
        shortcut: told at its next step (`_nudge`), not into a CLI's turn at once (`steer`);
        steer it if a CLI's Lead is seen to ask after Go away."""
        for chat, now_go in list(self._decidable.values()):
            if chat == cid:
                now_go()
        for lead in [one for one in self._ctxs.values() if one.cid == cid and not one.depth]:
            self._nudge(lead, AWAY_TOLD)

    def _away_full_auto(self: "AgentRunner", ctx: Ctx) -> bool:
        """K-yargıç while away (call 9): a job whose Away runs - or its going-on turn after the
        user's decisions (§10) -, its chat at Full auto - as the chat the user went away from."""
        if ctx.run_id not in self._away_jobs:
            return False
        with self._factory() as session:
            return (
                away.night_of(session, ctx.cid) is not None
                or away.going_on(session, session.get_one(Run, ctx.run_id))
            ) and session.get_one(Conversation, ctx.cid).permission_mode == "full_auto"

    def _parker(
        self: "AgentRunner", ctx: Ctx, make: Callable[[], Awaitable[Workspace]] | None
    ) -> Callable[[str], Awaitable[str]] | None:
        """☾ Away (§10): how a command's card of a job is parked while its night runs - read at each
        card, so I'm back, Stop all or the night's end make the next card the user's again. None
        elsewhere: a turn they watch, a trigger's, a To-do task's, KOLONİ's own commands. Parking
        makes the job's copy first (`make`: the command's own `where`; a CLI's is made), which is
        kept for the morning (`_set_aside`), writes the record (`parked.park`) and says what the
        agent is told."""
        if ctx.run_id not in self._away_jobs:
            return None
        with self._factory() as session:
            if away.night_of(session, ctx.cid) is None:
                return None

        async def park(command_id: str) -> str:
            if make is not None:
                with contextlib.suppress(ToolError):  # (its folder not in the copy: none to keep)
                    await make()
            copy = self._copies.get(self._works_in(ctx) or "")
            with self._factory() as session:
                command = session.get_one(Command, command_id)
                call = session.get(ToolCall, command.tool_call_id or "")
                task = away.job_of(session, ctx.cid)
                if task is not None:
                    parked.park(
                        session,
                        task,
                        "command",
                        command.id,
                        command.command,
                        {
                            "cwd": command.cwd,
                            "copy": str(copy.root) if copy is not None else None,
                            "location": command.location,
                            "image": command.image,
                            "timeout": command.timeout_seconds,
                            "reason": command.asked_reason,
                            "judge": call.why_asked
                            if call is not None and command.asked_reason == "judge"
                            else None,
                            "needs_project": parked.needs_project(command.command),
                        },
                    )
                    session.commit()
                return parked.said(command.command, command.cwd)

        return park

    def _parked_here(self: "AgentRunner", owner: str) -> bool:
        """Whether something of a job parked in this agent's copy still waits for the morning
        (no going-on turn for it yet): the copy is kept for its Run, changed or not. Once gone on,
        an unchanged copy goes as any does - no empty card to take in."""
        copy = self._copies.get(owner)
        if copy is None:
            return False
        with self._factory() as session:
            return (
                session.scalar(
                    select(Parked.id)
                    .where(
                        Parked.data["copy"].as_string() == str(copy.root),
                        Parked.went_on.is_(None),
                    )
                    .limit(1)
                )
                is not None
            )

    def _set_aside(
        self: "AgentRunner",
        owner: str,
        why: str = "one side of a comparison, waiting for your choice",
        found: tuple[copies.Copy, list] | None = None,
    ) -> None:
        """A side of a comparison is over - or a turn whose recipe was not taken in: what it
        changed stays in its copy, kept as a kept copy is (`_keep_copy`), for the user's
        choice to take in or throw away (`decide_kept`). A copy that changed nothing goes
        with its turn - but one a job parked a command in (`_parked_here`). `found`: its
        changes, from a look made off the event loop (`_look_aside`) - for the copy that look
        was at."""
        copy = self._copies.get(owner)
        if copy is None:
            return
        changed = found[1] if found is not None and found[0] is copy else copy.changes()
        if any(not copy.ignored(one[0]) for one in changed) or self._parked_here(owner):
            self._keep_copy(owner, why)  # (B-189: not for a new file git ignores alone)

    def typing(self: "AgentRunner", question_id: str) -> None:
        """The user types an answer to a question that waits: the Lead holds off it
        (`TYPING_HOLD_SECONDS`). Nothing kept for one nobody waits on."""
        if question_id in self._answers:
            self._typing_at[question_id] = asyncio.get_running_loop().time()

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
            # (§10: a going-on turn after the night is held to the job's ceiling alone)
            going = night is not None or away.going_on(session, session.get_one(Run, ctx.run_id))
            if night is not None and why:
                away.stop(session, night, why, self)
            elif going and (why := away.job_over(session, ctx.cid)):
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
        if (
            copy is not None
            and copy.branch
            or owner not in self._copies
            and (owner in self._on_branch)
        ):
            return reaches_shared_git(command, copy.branch if copy is not None else None)
        if in_copy or ctx.root is None or not switches_branch(command):
            return ""
        with self._factory() as session:
            project_id = session.scalar(
                select(Conversation.project_id).where(Conversation.id == ctx.cid)
            )
            held = project_id and branch_held(session, project_id, ctx.run_id, copies=True)
        return f"switches the branch under {held[0]}'s work" if held else ""

    def _night_asks(
        self: "AgentRunner", ctx: Ctx, plain: str, cwd: object = None, scratch_of: str | None = None
    ) -> str:
        """Why a command waits for the user at every level. In a turn they watch: it deletes
        or overwrites, or sends something off this machine (`harms`) - at Full auto too, by
        the user's rule that nothing else asks there (K-fullauto-sorma). In a job while they
        are away those and, as nothing of a turn nobody watches goes unasked that cannot be
        taken back, one that runs what is not seen through a shell or a wrapper
        (`runs_another`), or - in a copy with the project's dependency folders linked in -
        installs into the project's own (`installs`); "" for one that does none of these, or
        in a turn nobody watches (its trigger's leave decides). In a side of a comparison harm
        (a side is thrown away, a push is not) and such an install alone: it stays in the
        project whichever side is chosen (K-54). (A To-do task's turn is its chat's, 0.1.8.)
        `plain` runs in `cwd` (run_command's), as `with_cwd` judges it. `scratch_of`: the
        folder the command runs in, where a delete only in its scratch is no harm to ask about
        in a watched turn (B-336, `scratch_delete_only`); None, not a copy's nor a CLI's own."""
        command = with_cwd(plain, cwd)
        if ctx.run_id in self._sides:
            # shortcut: not an install in a shell or a wrapper (`cmd /c npm i`), which
            # `runs_another` would catch only by asking about every one; look inside if seen.
            copy = self._copies.get(self._sides[ctx.run_id])
            return harms(command) or (installs(command) if copy is not None and copy.links else "")
        if ctx.run_id not in self._away_jobs:
            # (K-fullauto-sorma: at Full auto an instruction file alone is no harm.)
            if not self._watched(ctx.run_id) or scratch_delete_only(command, scratch_of):
                return ""
            return harms(command, not self._full_auto(ctx))
        copy = self._copies.get(self._away_jobs[ctx.run_id])
        # shortcut: a job's agent runs its tests with its own line, judged as any command (R147:
        # a pipe into a filter no longer asks); have KOLONİ run the project's test command for
        # it, unasked, if a test line is still seen to make a night's job wait.
        return (
            harms(command)
            or runs_another(command)
            or (installs(command) if copy is not None and copy.links else "")
        )

    def _arm_deadline(self: "AgentRunner", run_id: str, cid: str) -> None:
        """A job's turn is cut at its hour or at its night's time, whichever comes first -
        by the loop's clock, so also while no step of it is taken (a long command, a CLI)."""
        with self._factory() as session:
            night = away.night_of(session, cid)
            hours = away.unattended(session)[1]
            ends = [hours * 3600.0] if hours else []
            if night is not None and night.until is not None:
                ends.append((night.until - now()).total_seconds())
        later = self.call_later or asyncio.get_running_loop().call_later
        if ends:  # (B-413: no ceiling and no stop time: none)
            self._away_timers[run_id] = later(max(0.0, min(ends)), self._deadline, run_id, cid)
        self._progress(run_id, arm=True)  # (B-413: and where nothing moves, sooner)

    def _deadline(self: "AgentRunner", run_id: str, cid: str) -> None:
        """A job's time is up: its night stops where its own time is (`away.over`), else the job
        is cut, its copy kept - not one that waits for the user's word."""
        with contextlib.suppress(Exception), self._factory() as session:
            night, task = away.night_of(session, cid), away.job_of(session, cid)
            run = session.get(Run, run_id)
            # (§10: a going-on turn after the night has the job's ceiling alone)
            going = night is None and run is not None and away.going_on(session, run)
            if (night is None and not going) or task is None or task.away_state == "waits":
                return
            if night is not None and (why := away.over(session, night)):
                away.stop(session, night, why, self)
            else:
                self.cut(run_id, away.too_long(away.unattended(session)[1] or 0))

    def _keeps_out(
        self: "AgentRunner",
        ctx: Ctx,
        path: str | None = None,
        command: str | None = None,
        what: str = "",
        cwd: str | None = None,
    ) -> str | None:
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
        """Why this agent may not offer the user to go away (☾ Away); None: it may. Only the
        Lead whose role keeps the To-do list, at the user's own turn of a chat with a folder:
        never a trigger's turn, a plan, a side of a comparison or a job while they are away."""
        if (
            ctx.role != LEAD
            or ctx.depth
            or ctx.answering
            or ctx.discussion
            or ctx.root is None
            or "add_task" not in ctx.tools
            or not self._watched(ctx.run_id)
            or ctx.run_id in self._sides
            or ctx.run_id in self._away_jobs
        ):
            return "offer_away is the Orchestrator's, at a turn of the user's own"
        run = session.get_one(Run, ctx.run_id)
        return "offer_away is not for a plan turn" if run.plan_turn or run.unattended else None

    def _offer_away(self: "AgentRunner", ctx: Ctx, args: dict) -> str:
        with self._factory() as session:
            if why := self._no_away(session, ctx):
                raise ToolError(why)
            try:
                said = away.offer(
                    session,
                    session.get_one(Conversation, ctx.cid),
                    ctx.run_id,
                    args,
                    ctx.agent_id if _tells_own_sub_agents(ctx) else None,
                )
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
                    session,
                    conversation,
                    ctx.run_id,
                    args,
                    self.trigger_day() if self.trigger_day else trigger_rules.local_day(now()),
                )
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

    # --- §10: what the user decided runs, and the same agent goes on -------------------------

    def go_on_parked(self: "AgentRunner", task_id: str) -> None:
        """§10: every decision of a job's parked rows is in - what was Run runs in the order parked,
        where it was recorded to, then one going-on turn of the job's chat (`_go_on_parked`). Not
        awaited: the click that gave the last decision is answered at once."""
        if not self._closing:
            asyncio.get_running_loop().create_task(
                self._go_on_parked(task_id), name=f"parked-{task_id}"
            )

    async def _go_on_parked(self: "AgentRunner", task_id: str) -> str | None:
        """`go_on_parked`'s work: the going-on turn's run id, or None where it does not start -
        not every decision in, the user away again, its chat at work (looked at again here), a
        Stop meanwhile, or the month's budget spent. Its run is on record "queued" from the
        start - the job is at work, nothing else of it starts, a message in its chat waits behind
        it - and while what was Run runs, Stop of its chat or of the task cancels it here
        (`cancel`: it stands in `_tasks` under that run)."""
        with self._factory() as session:
            begun = parked.begin(session, task_id)
        if begun is None:
            return None
        run_id, cid, project_id = begun
        self.bus.emit(cid, run_id, "run.started", self._run_payload(run_id))
        announce(self._factory, self.bus, project_id, "backlog.changed")
        me = asyncio.current_task()
        if me is not None:
            self._tasks[run_id] = me
        try:
            merge_id = await self._morning(task_id, run_id, cid)
        except asyncio.CancelledError:
            self._morning_over(run_id, cid, project_id, "cancelled")
            raise
        finally:
            if self._tasks.get(run_id) is me:
                del self._tasks[run_id]
        with self._factory() as session:
            run = session.get_one(Run, run_id)
            chat = session.get_one(Conversation, cid)
            why = over_budget(session, session.get(Project, project_id), chat)
            if run.status != "queued" or why:
                self._morning_over(run_id, cid, project_id, "cancelled", why)
                return None
            rows = list(
                session.scalars(select(Parked).where(Parked.went_on == run_id).order_by(Parked.seq))
            )
            message = Message(
                conversation_id=cid, run_id=run_id, role="user", content=parked.told(rows)
            )
            session.add(message)
            run.status, run.started_at = "running", now()
            session.commit()
            said, payload = message_out(message), run_out(run)
        self.bus.emit(cid, run_id, "message.created", said)
        self.bus.emit(cid, run_id, "run.updated", payload)
        if merge_id is not None:
            self.resume_on(run_id, merge_id)
        self.start(run_id)
        return run_id

    def _run_payload(self: "AgentRunner", run_id: str) -> dict:
        with self._factory() as session:
            return run_out(session.get_one(Run, run_id))

    def _morning_over(
        self: "AgentRunner",
        run_id: str,
        cid: str,
        project_id: str,
        status: str,
        why: str | None = None,
    ) -> None:
        """The going-on turn does not start: its run is over (`status`); its job waits where the
        month's budget stopped it (`why`), else - a Stop, KOLONİ closing - it is stopped, with why
        (Try again works it in its chat; what was Run and did not run then is not run again)."""
        stopped = parked.CLOSED_MEANWHILE if self._closing else parked.STOPPED
        with contextlib.suppress(Exception), self._factory() as session:
            run = session.get_one(Run, run_id)
            if run.status in ("queued", "running"):
                run.status, run.ended_at = "interrupted" if self._closing else status, now()
            task = session.get(BacklogTask, run.task_id or "")
            if task is not None and task.away_state is None:
                task.away_state, task.away_why = (
                    ("waits", f"The project is {why}.") if why else ("stopped", stopped)
                )
            session.commit()
            payload = run_out(run)
            self.bus.emit(cid, run_id, "run.updated", payload)
        announce(self._factory, self.bus, project_id, "backlog.changed")

    async def _morning(self: "AgentRunner", task_id: str, run_id: str, cid: str) -> str | None:
        """What the user said Run, run in the order parked as it was recorded - its line, its
        folder, its copy or (some of that copy taken in) the project, its time limit - with no
        card (`ask=False`: what the user's Run is leave for; an agent's own program is still
        refused, W2, and a place kept out still is). The copies held off Take in and Discard
        meanwhile (`_deciding`). The kept copy the going-on turn goes on in - untouched - or
        None: a fresh one."""
        with self._factory() as session:
            task = session.get_one(BacklogTask, task_id)
            night = session.get(AwayRun, task.away_run_id or "")
            root = session.get_one(Project, task.project_id).root_path
            rows = list(
                session.scalars(
                    select(Parked)
                    .where(Parked.went_on == run_id, Parked.kind == "command")
                    .where(Parked.decision == "run")
                    .order_by(Parked.seq)
                )
            )
            kept = away.kept_copies(session, cid)
            last = kept[-1] if kept and self._undecided(kept[-1]) else None
            places = {row.id: parked.where(session, row) for row in rows}
        held = {merge.id for _place, merge in places.values() if merge is not None}
        held |= {last.id} if last is not None else set()
        held -= self._deciding
        self._deciding |= held
        opened: dict[str, copies.Copy] = {}
        try:
            for row in rows:
                if not self._still_queued(run_id):
                    break
                place, merge = places[row.id]
                said, ran = await self._run_parked(row, place, merge, night, root, cid, opened)
                with self._factory() as session:
                    one = session.get_one(Parked, row.id)
                    one.result, one.data = said, {**one.data, "ran": ran}
                    session.commit()
        finally:
            for copy in opened.values():
                with contextlib.suppress(OSError, ValueError):
                    copies.unlink(self.settings.runtime_root, copy.name)
            self._deciding -= held
        return last.id if last is not None else None

    def _still_queued(self: "AgentRunner", run_id: str) -> bool:
        """The going-on turn is still to start: no Stop of its chat meanwhile."""
        with self._factory() as session:
            return session.get_one(Run, run_id).status == "queued"

    async def _run_parked(
        self: "AgentRunner",
        row: Parked,
        place: str,
        merge: Merge | None,
        night: AwayRun | None,
        root: str,
        cid: str,
        opened: dict[str, copies.Copy],
    ) -> tuple[str, bool]:
        """One Run of the morning: what it said, and whether it ran (False: could not)."""
        cwd = row.data.get("cwd") or "."
        if place == "gone" or merge is None and place == "copy":
            return parked.GONE, False
        if night is not None and (
            kept := away.kept_out(night, command=row.what, root=root, cwd=cwd)
        ):
            return away.KEPT_OUT.format(path=kept), False
        ws = Workspace(Path(root).resolve())
        if place == "copy" and merge is not None and merge.kept_in:
            if merge.kept_in not in opened:
                try:
                    copy = copies.load(
                        Path(root),
                        self.settings.runtime_root,
                        copies.named(self.settings.runtime_root, merge.kept_in),
                    )
                    copies.relink(copy)
                except (OSError, ValueError) as exc:
                    return f"its copy could not be opened ({exc})", False
                opened[merge.kept_in] = copy
            ws = opened[merge.kept_in].workspace()
        with self._factory() as session:
            command = session.get(Command, row.ref_id or "")
            if command is None or command.tool_call_id is None:
                return parked.GONE, False
            run_id, agent_id, call_id = command.run_id, command.agent_id, command.tool_call_id
        seconds = row.data.get("timeout")
        args = {
            "command": row.what,
            "cwd": cwd,
            **({"timeout_seconds": seconds} if isinstance(seconds, int) and seconds > 0 else {}),
        }
        try:
            status, said = await self.commands.run(
                run_id, cid, agent_id, ws, call_id, args, ask=False
            )
        except ToolError as exc:
            return f"error: {exc}", False
        return said, status not in ("denied", "failed")
