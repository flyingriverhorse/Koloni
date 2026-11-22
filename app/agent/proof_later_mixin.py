"""Kanıtlı bitiş S6 (plan decision 10): a watched turn's end check does not hold the chat on the
whole suite. The tests related to the changed files run first (`proof_related`) - the answer waits
for those, and a failure goes back as S1's does; then the whole suite starts, and where it is not
over soon it goes on after the answer, as a pull request's CI does: its Checked row says "Full
tests running" and is written again when it ends (`_checked_update`). A failure then offers Fix
it - nothing starts by itself. A turn nobody waits on (an Away job, a To-do task's, a trigger's) and
work in a copy (a branch turn's: taken in or set aside under the run) wait for it as before.

Every one of KOLONİ's test runs at a turn's end is a task of its own (`Check`): the user may stop
it ("Stop this check", `stop_check`), a newer run in the project takes the place of one going on
after its turn, and Stop everything, putting the chat away and KOLONİ closing end it. Settings ›
The app says how many go at once and how many test processes each may start (`proof.load_of`)."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from app import proof, proof_related
from app.agent.ctx import Ctx
from app.db.models import Message
from app.proof import Row, TestRun
from app.serialize import message_out

if TYPE_CHECKING:
    from app.agent import AgentRunner
    from app.agent.proof_mixin import Proof

log = logging.getLogger(__name__)

# How long the answer waits for a whole suite where no related tests ran first: one over by then
# is said and sent back as S1's; one still running goes on after the answer. (After related
# tests, none: they were the answer's check.)
DETACH_SECONDS = 60
YOU_STOPPED = "you stopped the check"
BY_YOU = "{what} stopped by you at {clock} - not checked"
# What KOLONİ's own test runs are given besides the environment an agent's command gets.
# shortcut: only pytest-xdist's `-n auto` reads it; vitest's / jest's workers are not set - set
# theirs once measured.
WORKERS_ENV = "PYTEST_XDIST_AUTO_NUM_WORKERS"


def _future() -> asyncio.Future:
    return asyncio.get_running_loop().create_future()


@dataclass
class Check:
    """One of KOLONİ's test runs at a turn's end, while it runs: whose, what it is called in its
    row, when it was started (monotonic), how long its turn's pass waits for it (`until`, None:
    to its own limit), once it is past its card (`started`), once it has the machine (`going`,
    with when), whether it went on after the answer, and why it was stopped."""
    run_id: str
    cid: str
    project_id: str
    what: str
    until: float | None
    since: float = field(default_factory=time.monotonic)
    started: asyncio.Future = field(default_factory=lambda: _future())
    going: asyncio.Future = field(default_factory=lambda: _future())
    later: bool = False
    why: str | None = None


class ProofLaterMixin:
    def _may_go_on(self: "AgentRunner", ctx: Ctx) -> bool:
        """Whether this turn's whole suite may go on after its answer: somebody waits for the
        answer, and the work is in the project itself - not a copy taken in or set aside under
        the run."""
        return self._answer_waits(ctx) and self._works_in(ctx) is None

    async def _all_tests(self: "AgentRunner", ctx: Ctx, held: "Proof",
                         runs: list[TestRun]) -> list[tuple[TestRun, str]]:
        """Each test command's row in `held`; the failed ones, with their output. Where the
        suite may go on after the answer: the related tests first, then the whole suite - which
        stops holding the answer at once after them, else after DETACH_SECONDS."""
        later = self._may_go_on(ctx)
        project_id = self._project_id(ctx)
        if later:  # (what went on of an earlier state of the project is void now: as CI's)
            self._end_checks(lambda one: one.later and one.project_id == project_id,
                             proof.SUPERSEDED)
        failed, quick = await self._related_first(ctx, held, runs) if later else ([], False)
        if failed:
            held.rows.append(proof.row("tests", "note", proof.FULL_HELD))
            return failed
        until = time.monotonic() + (0 if quick else DETACH_SECONDS) if later else None
        for run in runs:
            made, output = self._unrun(run) if held.stopped else await self._tests_of(
                ctx, run, held, until)
            held.rows.append(made)
            if made["state"] == "failed":
                failed.append((run, output))
        return failed

    async def _related_first(self: "AgentRunner", ctx: Ctx, held: "Proof",
                             runs: list[TestRun]) -> tuple[list[tuple[TestRun, str]], bool]:
        """The tests related to the turn's changes, for each command that can name them - not
        for a whole run that stands on record, nor a guess that still needs its card (one card a
        guess). The failed ones; and whether any passed."""
        failed, passed = [], False
        paths = [one.path for one in held.changes if one.in_project]
        root = self._ws(ctx).root
        for run in runs:
            if held.stopped or not (run.yours or self._full_auto(ctx)) or (
                    self._fresh_of(ctx, run) is not None):
                continue
            narrowed = await asyncio.to_thread(proof_related.related, run, paths, root)
            if narrowed is None:
                continue
            made, output = await self._tests_of(ctx, narrowed, held)
            made["text"] = proof.related_said(made["text"])
            held.rows.append(made)
            passed = passed or made["state"] == "passed"
            if made["state"] == "failed":
                failed.append((narrowed, output))
        return failed, passed

    @staticmethod
    def _unrun(run: TestRun) -> tuple[Row, str]:
        return proof.row("tests", "not_run", proof.NOT_RUN.format(why=YOU_STOPPED), run.command,
                         not run.yours), ""

    async def _go_on_tests(self: "AgentRunner", ctx: Ctx, run: TestRun, held: "Proof",
                           until: float) -> tuple[Row, str]:
        """A whole suite that may go on after the answer: never cut at the answer's wait, nor
        left unrun for being slow - one that was slow before goes on at once."""
        with self._factory() as session:
            project = self._project(session, ctx.cid)
            slow = project is not None and proof.too_slow(session, project.id, run, DETACH_SECONDS)
        how = self._may_run_tests(ctx, run)
        if how not in ("run", "ask"):
            return proof.row("tests", "not_run", proof.NOT_RUN.format(why=how), run.command,
                             not run.yours), ""
        return await self._run_tests(ctx, run, how, held, None,
                                     0.0 if slow else max(0.0, until - time.monotonic()))

    def _project_id(self: "AgentRunner", ctx: Ctx) -> str:
        with self._factory() as session:
            project = self._project(session, ctx.cid)
            return project.id if project is not None else ""

    def _slot(self: "AgentRunner", runs: int) -> asyncio.Semaphore:
        """The app-wide slot KOLONİ's test runs take, for `runs` at once: a new one where the
        setting changed - a run holding the old one gives that one back."""
        if runs != self._test_runs:
            self._test_slot, self._test_runs = asyncio.Semaphore(runs), runs
        return self._test_slot

    async def _as_check(self: "AgentRunner", ctx: Ctx, held: "Proof", run: TestRun,
                        later: float | None,
                        start: Callable[[Check], Awaitable[tuple[Row, str]]]) -> tuple[Row, str]:
        """Run `start` as a check of its own: waited for to its end where `later` is None; else
        past its card, then `later` seconds - still running then, it goes on after the answer.
        Stopped by the user meanwhile: its row says so, and the turn goes on."""
        check = Check(ctx.run_id, ctx.cid, self._project_id(ctx),
                      "Tests" if later is None else "Full tests",
                      held.until if later is None else None)
        task = asyncio.ensure_future(start(check))
        self._checks[task] = check
        task.add_done_callback(lambda done: self._checks.pop(done, None))
        if not await self._waited(task, check.started, later):
            return self._go_on_later(task, check, run), ""
        if task.cancelled():
            return self._stopped_row(check, run.command, not run.yours), ""
        return task.result()

    @staticmethod
    async def _waited(task: asyncio.Future, started: asyncio.Future, later: float | None) -> bool:
        """Whether `task` ended while its turn waited. Never left before its card is answered:
        a card of a turn that is over would set it waiting again. Stop meanwhile stops it too."""
        try:
            if later is None:
                await asyncio.wait({task})
            else:
                await asyncio.wait({task, started}, return_when=asyncio.FIRST_COMPLETED)
                await asyncio.wait({task}, timeout=later)
        except asyncio.CancelledError:
            task.cancel()
            await asyncio.wait({task})
            raise
        return task.done()

    @staticmethod
    def _stopped_row(check: Check, command: str | None, guessed: bool) -> Row:
        return proof.row("tests", "not_run", (check.why or proof.STOPPED).format(
            what=check.what, clock=proof.clock(int(time.monotonic() - check.since))),
            command, guessed)

    def _go_on_later(self: "AgentRunner", task: asyncio.Future, check: Check,
                     run: TestRun) -> Row:
        """The row of a whole suite that goes on after the answer: waiting for the machine, then
        running (its clock from when it started), then as it ended - each written where it is
        (`_checked_update`). Kept in `_telling`: KOLONİ closing ends it.
        shortcut: one that writes a standing file (an instruction file, `.koloni/`) asks about it
        on a card as it ends (`_own_command_looked`) and holds its slot until that is answered,
        its turn over; let such a card not wait after the turn if it is ever met."""
        check.later = True
        self._telling.add(task)
        task.add_done_callback(self._telling.discard)
        made = proof.row("tests", "running", proof.FULL_QUEUED.format(command=run.command),
                         run.command, not run.yours)

        def going(at: asyncio.Future) -> None:
            self._checked_update(check, made, {
                **made, "text": proof.FULL_RUNNING.format(command=run.command),
                "started_at": at.result().isoformat()})
        if check.going.done():
            going(check.going)
        else:
            check.going.add_done_callback(going)
        task.add_done_callback(lambda done: self._ended_later(check, made, done))
        return made

    def _ended_later(self: "AgentRunner", check: Check, made: Row, done: asyncio.Future) -> None:
        """A suite gone on after its answer is over: its row as it ended. Ended by KOLONİ
        closing: nothing here - the next start says so (`proof.settle_running`)."""
        if done.cancelled() and self._closing:
            return
        try:
            self._checked_update(check, made, self._later_row(check, made, done))
        except Exception as exc:  # (a row of KOLONİ's fails nothing)
            log.warning("run %s: the tests gone on after it not said: %r", check.run_id, exc)

    def _later_row(self: "AgentRunner", check: Check, made: Row, done: asyncio.Future) -> Row:
        if done.cancelled():
            return self._stopped_row(check, made["command"], made["guessed"])
        if (exc := done.exception()) is not None:
            return proof.row("tests", "not_run", proof.NOT_STARTED.format(
                first=str(exc) or type(exc).__name__), made["command"], made["guessed"])
        row, _output = done.result()
        if not made["started_at"]:
            return row
        with self._factory() as session:
            changed = proof.changed_since(session, check.project_id,
                                          datetime.fromisoformat(made["started_at"]))
        # (Review Focus 2: a pass on what is no longer the work is no pass.)
        return {**row, "text": row["text"] + proof.CHANGED_WHILE,
                "state": "note" if row["state"] == "passed" else row["state"]} if changed else row

    def _checked_update(self: "AgentRunner", check: Check, row: Row, new: Row) -> None:
        """`row` of the turn's Checked section is now `new`: in the turn's rows still to be
        written, and in its "checked" message where that is written - sent again under the same
        id, which the page puts in place of the first."""
        was = dict(row)
        row.update(new)  # (every key of a row: none of the old is left)
        try:
            with self._factory() as session:
                note = session.scalar(select(Message).where(
                    Message.run_id == check.run_id, Message.role == "checked"))
                rows = list((note.blocks or {}).get("rows", [])) if note is not None else []
                if note is None or was not in rows:
                    return
                rows[rows.index(was)] = dict(new)
                note.blocks, note.content = {"rows": rows}, proof.checked_text(rows)
                session.commit()
                payload = message_out(note)
        except Exception as exc:  # (a row of KOLONİ's fails nothing)
            log.warning("run %s: its Checked row not written again: %r", check.run_id, exc)
            return
        self.bus.emit(check.cid, check.run_id, "message.completed", payload)

    def _end_checks(self: "AgentRunner", which: Callable[[Check], bool], why: str) -> bool:
        found = [task for task, one in self._checks.items() if which(one) and not task.done()]
        for task in found:
            self._checks[task].why = why
            task.cancel()
        return bool(found)

    def stop_check(self: "AgentRunner", run_id: str) -> bool:
        """"Stop this check" (plan decision 17): the turn's test runs that run now - its related
        tests while the answer waits, or its whole suite gone on after it - are stopped; what
        finished stays, and the rest of the turn's runs are not started. False: none runs."""
        stopped = self._end_checks(lambda one: one.run_id == run_id, BY_YOU)
        if stopped and (held := self._proofs.get(run_id)) is not None:
            held.stopped = True
        return stopped

    def stop_later(self: "AgentRunner", cid: str | None = None) -> None:
        """The test runs gone on after their turns - of chat `cid`, or every one: Stop
        everything, a chat put away."""
        self._end_checks(lambda one: one.later and cid in (None, one.cid), proof.STOPPED)
