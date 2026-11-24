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
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import select

from app import proof, proof_related
from app.agent.ctx import Ctx
from app.agent.merge import Written, _digest
from app.db.models import Command, Message, now
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
BY_YOU_EARLY = "{what} stopped by you before they started - not checked"
BUSY_HERE = (
    "its tests run on after a turn, or wait for the machine: stop them first (Stop this "
    "check, under the turn's answer)"
)
# What KOLONİ's own test runs are given besides the environment an agent's command gets.
# shortcut: only pytest-xdist's `-n auto` reads it; vitest's / jest's workers are not set - set
# theirs once measured.
WORKERS_ENV = "PYTEST_XDIST_AUTO_NUM_WORKERS"


def _future() -> asyncio.Future:
    return asyncio.get_running_loop().create_future()


class Slots:
    """KOLONİ's own test runs at once: at most `limit` (Settings), the ones going counted
    across a change of it - a lower limit holds new runs until enough of those going end."""

    def __init__(self, limit: int = 1) -> None:
        self.limit, self.taken, self._freed = limit, 0, asyncio.Event()

    async def acquire(self) -> bool:
        while self.taken >= self.limit:
            self._freed.clear()
            await self._freed.wait()
        self.taken += 1
        return True

    def release(self) -> None:
        self.taken -= 1
        self._freed.set()

    def locked(self) -> bool:
        return self.taken >= self.limit


@dataclass
class Check:
    """One of KOLONİ's test runs at a turn's end, while it runs: whose, what it is called in its
    row, the command and folder it runs, how long its turn's pass waits for it (`until`, None:
    to its own limit), once it is past its card (`started`), once it has the machine (`going`,
    with when), its call, whether it went on after the answer, why it was stopped, and once its
    run ended and waits on the user's answer on a file it wrote (`on_card`)."""

    run_id: str
    cid: str
    project_id: str
    what: str
    command: str
    cwd: str
    until: float | None
    started: asyncio.Future = field(default_factory=lambda: _future())
    going: asyncio.Future = field(default_factory=lambda: _future())
    call_id: str | None = None
    later: bool = False
    why: str | None = None
    on_card: asyncio.Future = field(default_factory=lambda: _future())
    # CL-336 L: rows of its own said under its row once it ends (a file it changed).
    after: list = field(default_factory=list)


class ProofLaterMixin:
    def _may_go_on(self: "AgentRunner", ctx: Ctx) -> bool:
        """Whether this turn's whole suite may go on after its answer: somebody waits for the
        answer, and the work is in the project itself - not a copy taken in or set aside under
        the run."""
        return self._answer_waits(ctx) and self._works_in(ctx) is None

    async def _all_tests(
        self: "AgentRunner", ctx: Ctx, held: "Proof", runs: list[TestRun]
    ) -> list[tuple[TestRun, str]]:
        """Each test command's row in `held`; the failed ones, with their output. Where the
        suite may go on after the answer: the related tests first, then the whole suite - which
        stops holding the answer at once after them, else after DETACH_SECONDS."""
        later = self._may_go_on(ctx) and not held.judging  # (J: a hand-off waits for its verdict)
        project_id, mine = self._project_id(ctx), {(run.command, run.cwd) for run in runs}
        if later:  # (the same suite gone on over an earlier state of the project: void, as CI's)
            self._end_checks(
                lambda one: (
                    one.later and one.project_id == project_id and (one.command, one.cwd) in mine
                ),
                proof.SUPERSEDED,
            )
        failed, quick = await self._related_first(ctx, held, runs) if later else ([], False)
        if failed:
            held.rows.append(proof.row("tests", "note", proof.FULL_HELD))
            return failed
        until = time.monotonic() + (0 if quick else DETACH_SECONDS) if later else None
        for run in runs:
            made, output = (
                self._unrun(run)
                if held.stopped
                else await self._covered_tests(ctx, run, held, until)
            )  # (S9: coverage on the whole suite only)
            held.rows.append(made)
            held.rows += self._coverage_rows(held, run)
            # (S1b: a guess that really ran tests is saved; one gone on after the answer, as it
            # ends - `_ended_later`.)
            held.rows.extend(self._save_found(ctx, held, run, made, output))
            if made["state"] == "failed":
                failed.append((run, output))
        return failed

    async def _related_first(
        self: "AgentRunner", ctx: Ctx, held: "Proof", runs: list[TestRun]
    ) -> tuple[list[tuple[TestRun, str]], bool]:
        """The tests related to the turn's changes, for each command that can name them - not
        for a whole run that stands on record, nor a guess that still needs its card (one card a
        guess). The failed ones; and whether any passed."""
        failed, passed = [], False
        paths = [one.path for one in held.changes if one.in_project]
        root = self._ws(ctx).root
        for run in runs:
            if (
                held.stopped
                or not (run.yours or self._full_auto(ctx))
                or (self._fresh_of(ctx, run) is not None)
            ):
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
        return proof.row(
            "tests", "not_run", proof.NOT_RUN.format(why=YOU_STOPPED), run.command, run.guessed
        ), ""

    async def _go_on_tests(
        self: "AgentRunner", ctx: Ctx, run: TestRun, held: "Proof", until: float
    ) -> tuple[Row, str]:
        """A whole suite that may go on after the answer: never cut at the answer's wait, nor
        left unrun for being slow - one that was slow before goes on at once."""
        with self._factory() as session:
            project = self._project(session, ctx.cid)
            slow = project is not None and proof.too_slow(session, project.id, run, DETACH_SECONDS)
        how = self._may_run_tests(ctx, run)
        if how not in ("run", "ask"):
            return proof.row(
                "tests", "not_run", proof.NOT_RUN.format(why=how), run.command, run.guessed
            ), ""
        return await self._run_tests(
            ctx, run, how, held, None, 0.0 if slow else max(0.0, until - time.monotonic())
        )

    def _project_id(self: "AgentRunner", ctx: Ctx) -> str:
        with self._factory() as session:
            project = self._project(session, ctx.cid)
            return project.id if project is not None else ""

    def _slot(self: "AgentRunner", runs: int) -> Slots:
        """The app-wide slots KOLONİ's test runs take, `runs` at once as Settings say now."""
        self._test_slot.limit = runs
        return self._test_slot

    def _written_since(
        self: "AgentRunner", ctx: Ctx, at: datetime, since: float
    ) -> dict[str, Written]:
        """What others wrote in the project after a test run of KOLONİ's started there (`at`;
        `since`, monotonic) - recorded changes of any turn (written, taken in, taken back) and
        KOLONİ's own writes (`seen_in_project`) - by path (casefolded): never that run's to take
        back while a path holds what one left (review B1; by the bytes, round 2); written over
        by the tests, put back to what the last of them left (round 3).
        shortcut: a file the user edits by hand meanwhile is on no record: taken back, kept
        aside (`_keep_aside`); look at the files' times if that is ever met."""
        folder = str(Path(ctx.folder).resolve())
        found: dict[str, list[tuple[datetime, bytes | None, bool]]] = {}
        for (where, rel), (when, made, held, known) in self._seen_writes.items():
            if where == folder and when >= since:
                found.setdefault(rel.casefold(), []).append((made, held, known))
        with self._factory() as session:
            project = self._project(session, ctx.cid)
            for rel, left in (
                proof.written_since(session, project.id, at) if project else {}
            ).items():
                found.setdefault(rel.casefold(), []).extend(
                    (made, None if text is None else text.encode("utf-8"), True)
                    for made, text in left
                )
        return {
            rel: Written(
                frozenset(_digest(held) for _made, held, known in writes if known),
                *max(writes, key=lambda one: one[0])[1:],
            )
            for rel, writes in found.items()
        }

    def _on_file_card(self: "AgentRunner", call_id: str) -> None:
        """CL-316: the check whose run (its call) ended and now waits on the user's answer on a
        file it wrote - its row says so, and stops counting (`_go_on_later`)."""
        for check in list(self._checks.values()):
            if check.call_id == call_id and not check.on_card.done():
                check.on_card.set_result(None)

    def checking(self: "AgentRunner", run_id: str) -> bool:
        """Whether a test run of the turn's end check still runs (or waits for the machine)."""
        return any(
            one.run_id == run_id and not task.done() for task, one in list(self._checks.items())
        )

    def checks_in(self: "AgentRunner", project_id: str) -> str | None:
        """Why a project is not deleted now: a test run of KOLONİ's in it runs, or waits for the
        machine - it would start later in a folder no longer KOLONİ's."""
        return (
            BUSY_HERE
            if any(
                one.project_id == project_id and not task.done()
                for task, one in self._checks.items()
            )
            else None
        )

    async def _as_check(
        self: "AgentRunner",
        ctx: Ctx,
        held: "Proof",
        run: TestRun,
        later: float | None,
        start: Callable[[Check], Awaitable[tuple[Row, str]]],
    ) -> tuple[Row, str]:
        """Run `start` as a check of its own: waited for to its end where `later` is None; else
        past its card, then `later` seconds - still running then, it goes on after the answer.
        Stopped by the user meanwhile: its row says so, and the turn goes on."""
        check = Check(
            ctx.run_id,
            ctx.cid,
            self._project_id(ctx),
            "Tests" if later is None else "Full tests",
            run.command,
            run.cwd,
            held.until if later is None else None,
        )
        task = asyncio.ensure_future(start(check))
        self._checks[task] = check
        task.add_done_callback(lambda done: self._checks.pop(done, None))
        if not await self._waited(task, check.started, later):
            return self._go_on_later(task, check, run, ctx, held), ""
        if task.cancelled():
            return self._stopped_row(check, run.command, run.guessed), ""
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
        """Its row once stopped: by the user, at how long it had run from its start (as its
        row's clock counts) - or before it started; else why."""
        went = check.going.result() if check.going.done() else None
        why = check.why or proof.STOPPED
        why = BY_YOU_EARLY if why == BY_YOU and went is None else why
        took = int((now() - went).total_seconds()) if went is not None else 0
        return proof.row(
            "tests",
            "not_run",
            why.format(what=check.what, clock=proof.clock(took)),
            command,
            guessed,
        )

    def _go_on_later(
        self: "AgentRunner",
        task: asyncio.Future,
        check: Check,
        run: TestRun,
        ctx: Ctx,
        held: "Proof",
    ) -> Row:
        """The row of a whole suite that goes on after the answer: waiting for the machine, then
        running (its clock from when it started), then as it ended - each written where it is
        (`_checked_update`). Kept in `_telling`: KOLONİ closing ends it. What it writes of
        standing files is taken back as it ends with no card, its turn untouched (review B2)."""
        check.later = True  # (from here on its look at standing files asks nothing: `over`)
        self._telling.add(task)
        task.add_done_callback(self._telling.discard)
        made = proof.row(
            "tests",
            "running",
            proof.FULL_QUEUED.format(command=run.command),
            run.command,
            run.guessed,
        )

        def going(at: asyncio.Future) -> None:
            if not check.on_card.done():
                self._checked_update(
                    check,
                    made,
                    {
                        **made,
                        "text": proof.FULL_RUNNING.format(command=run.command),
                        "started_at": at.result().isoformat(),
                    },
                )

        def on_card(_at: asyncio.Future) -> None:  # (CL-316: no clock while it waits on you)
            self._checked_update(
                check,
                made,
                {
                    **made,
                    "text": proof.FULL_ON_CARD.format(command=run.command),
                    "started_at": None,
                },
            )

        if check.going.done():
            going(check.going)
        else:
            check.going.add_done_callback(going)
        check.on_card.add_done_callback(on_card)
        task.add_done_callback(lambda done: self._ended_later(check, made, done, ctx, held, run))
        return made

    def _ended_later(
        self: "AgentRunner",
        check: Check,
        made: Row,
        done: asyncio.Future,
        ctx: Ctx,
        held: "Proof",
        run: TestRun,
    ) -> None:
        """A suite gone on after its answer is over: its row as it ended - and a guess that
        really ran tests saved, as in the turn (`_save_found`), its row under it. Ended by KOLONİ
        closing: nothing here - the next start says so (`proof.settle_running`).
        shortcut: a lint line gone on after the answer that fails only where it failed before is
        not told apart (S7 / CL-336 M run in the turn only): its row offers Fix it, nothing starts
        by itself; run `_lint_before` here too if that is seen to mislead."""
        if done.cancelled() and self._closing:
            return
        saved: list[Row] = []
        if not done.cancelled() and done.exception() is None:
            try:
                saved = self._save_found(ctx, held, run, *done.result())
            except Exception as exc:  # (a save that broke saves nothing: the row is said)
                log.warning("run %s: the guess gone on after it not saved: %r", check.run_id, exc)
        try:
            ended = self._later_row(check, made, done)
        except Exception as exc:  # (a row of KOLONİ's fails nothing)
            log.warning("run %s: the tests gone on after it not said: %r", check.run_id, exc)
            return
        try:
            green = self._green_later(ctx, held, run, ended)
        except Exception as exc:  # (a comparison that broke keeps the run's own row said)
            log.warning("run %s: the suite gone on not held to green: %r", check.run_id, exc)
            green = []

        def said(more: list[Row]) -> None:
            more = [*saved, *green, *more, *check.after]
            try:
                held.rows.extend(more)  # (its Checked section not yet written: there)
                self._checked_update(check, made, ended, *more)
            except Exception as exc:  # (a row of KOLONİ's fails nothing)
                log.warning("run %s: the tests gone on after it not said: %r", check.run_id, exc)

        # (S9: its coverage report, read as it ends - off the loop, said with it)
        if not self._coverage_later(ctx, held, run, said):
            said([])

    def _green_later(
        self: "AgentRunner", ctx: Ctx, held: "Proof", run: TestRun, ended: Row
    ) -> list[Row]:
        """R, second round: a whole suite gone on after the answer that passed is held to the
        project's last green run as one in the turn is (`_green`) - what it says goes under it on
        the turn's Checked (a drop of the turn's: failed, offering Fix it, the green state where
        it was); a pass on what changed while it ran (a note) is held to nothing."""
        if ended["state"] != "passed" or not ended.get("counts"):
            return []
        before = len(held.rows)
        self._green(ctx, held, run, dict(ended["counts"] or {}))
        said, held.rows[before:] = held.rows[before:], []
        return said

    def _later_row(self: "AgentRunner", check: Check, made: Row, done: asyncio.Future) -> Row:
        if done.cancelled():
            return self._stopped_row(check, made["command"], made["guessed"])
        if (exc := done.exception()) is not None:
            return proof.row(
                "tests",
                "not_run",
                proof.NOT_STARTED.format(first=str(exc) or type(exc).__name__),
                made["command"],
                made["guessed"],
            )
        row, _output = done.result()
        if not check.going.done():  # (never started: nothing ran beneath a change)
            return row
        with self._factory() as session:
            ran = (
                session.scalar(select(Command).where(Command.tool_call_id == check.call_id))
                if check.call_id
                else None
            )
            # (From its start - its row's clock may be gone: it waited on your answer, CL-316.)
            changed = proof.changed_since(session, check.project_id, check.going.result(), ran)
        # (Review Focus 2: a pass on what is no longer the work is no pass.)
        return (
            {
                **row,
                "text": row["text"] + proof.CHANGED_WHILE,
                "state": "note" if row["state"] == "passed" else row["state"],
            }
            if changed
            else row
        )

    def _checked_update(self: "AgentRunner", check: Check, row: Row, new: Row, *after: Row) -> None:
        """`row` of the turn's Checked section is now `new` (and `after` follows it in the
        written one): in the turn's rows still to be written, and in its "checked" message where
        that is written - sent again under the same id, which the page puts in place of the
        first."""
        was = dict(row)
        row.update(new)  # (every key of a row: none of the old is left)
        try:
            with self._factory() as session:
                note = session.scalar(
                    select(Message).where(Message.run_id == check.run_id, Message.role == "checked")
                )
                rows = list((note.blocks or {}).get("rows", [])) if note is not None else []
                if note is None or was not in rows:
                    return
                at = rows.index(was)
                rows[at : at + 1] = [dict(new), *map(dict, after)]
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
        """ "Stop this check" (plan decision 17): the turn's test runs that run now - its related
        tests while the answer waits, or its whole suite gone on after it - are stopped; what
        finished stays, and the rest of the turn's runs are not started. False: none runs."""
        stopped = self._end_checks(lambda one: one.run_id == run_id, BY_YOU)
        if stopped and (held := self._proofs.get(run_id)) is not None:
            held.stopped = True
        return self._stop_looks(run_id) or stopped  # (S3: KOLONİ's looks that run now too)

    def stop_later(self: "AgentRunner", cid: str | None = None) -> None:
        """The test runs gone on after their turns - of chat `cid`, or every one: Stop
        everything, a chat put away."""
        self._end_checks(lambda one: one.later and cid in (None, one.cid), proof.STOPPED)
