"""Kanıtlı bitiş S7 (plan decisions 14b, 19): where the end check decides a test run failed, KOLONİ
first tells what is not this turn's - a test that fails in the full run and passes alone once is
flaky (noted in the project's memory, not sent back); one that fails on the code as it was before
the turn too was failing before (said, not sent back) - and after a whole suite passes it holds the
project's last green state (a drop in tests, a rise in skipped ones, not said why: sent back), and
in a bug fix runs the new test on the old code, where it must fail. "Before" is a throwaway copy of
the work with each changed file written back as it was, dropped through the copies' own removal
path. `BeforeMixin`; S11 reads `flaky` / `failing_before` for its diagnosis."""

import asyncio
import logging
import math
import posixpath
import re
import sys
import time
import uuid
from collections.abc import Callable
from contextlib import asynccontextmanager, suppress
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import literal_column, or_, select

from app import ci_commands, copies, ledger, memory, proof, proof_before, test_found
from app.agent.ctx import Ctx
from app.agent.stronger_mixin import steers_tests
from app.commands import only_reads
from app.db.models import (
    Command,
    Conversation,
    FileChange,
    Memory,
    Message,
    Run,
    ToolCall,
    now,
)
from app.proof import TestRun

if TYPE_CHECKING:
    from app.agent import AgentRunner
    from app.agent.proof_mixin import Proof

log = logging.getLogger(__name__)

FLAKY = "Flaky: {id} failed in the full run and passed alone (noted in this project's memory)"
FLAKY_NOTE = "Failed in a full run and passed alone ({date}); seen {n} times"
BEFORE = "{n} were failing before this turn, {m} new"
# CL-336 M: a lint, format or type check failing only on files the turn did not change, each of
# its findings there on the old code too.
LINT_BEFORE = "Were failing before this turn: {files} ({command})"
AT_LAST = "{n} were failing at the last run ({when}), {m} now"
CAUGHT = "The new test fails on the old code ✓"
NOT_CAUGHT = "The new test passes on the old code too: it may not catch the bug"
NO_BEFORE = "Not checked against the old code: {why}"
CHANGED_BY_COMMAND = "a command changed the project this turn, and what it changed is not on record"
ASKS_AGAIN = "not re-run alone or on the old code: it would ask again"
REGRESSION = "Regression: {id} passed at the last green run and fails now{by}"
UNUSUAL = "Not re-run alone or on the old code: an unusual test name ({ids})"
EXCUSED = "{said} - the answer says why: “{why}”"
# R (CL-345): fewer tests, or more skipped, that no change of the turn's could make - a test file
# deleted by hand outside KOLONİ, a pull, a branch switched: said, not sent back.
NOT_OURS = "{said} - not this turn's change"
NOT_YOURS = " These were failing before this turn and are not yours to fix: {ids}."
GREEN_LEAD = (
    "Not the end yet: {said}, against this project's last green run - and your answer "
    "does not say why. Put back what was taken away, or say in your answer, in a "
    "sentence that names the tests, why they were removed or skipped; KOLONİ runs them "
    "again."
)
_SEEN = re.compile(r"seen (\d+) times")


def _touched(test_id: str, cwd: str, touched: set[str]) -> bool:
    """R: whether a test's file (a pytest node id's part before `::`; a vitest or jest id is its
    file) is one of `touched` - from the run's folder or the project's root, or ending so (a
    rootdir elsewhere), whatever its case where the disk ignores case (Windows, macOS): any
    doubt, touched."""
    fold: Callable[[str], str] = str.casefold if sys.platform in ("win32", "darwin") else str
    file = fold(test_id.split("::", 1)[0].replace("\\", "/").removeprefix("./"))
    joined = posixpath.normpath(posixpath.join(fold(cwd), file)) if cwd not in ("", ".") else file
    return any(
        one in (file, joined) or one.endswith("/" + file) or file.endswith("/" + one)
        for one in map(fold, touched)
    )


def _named(command: str):
    """KOLONİ's runs that may be known by `command`: its line, or one with coverage's report flags
    (S9) - `proof._known_as` tells."""
    return or_(Command.command == command, Command.command.contains("coverage-"))


class BeforeMixin:
    async def _proof_before(
        self: "AgentRunner", ctx: Ctx, held: "Proof", failed: list[tuple[TestRun, str]]
    ) -> list[tuple[TestRun, str]]:
        """The failures that are this turn's: of each failed run, the tests that pass alone are
        flaky and those that fail on the old code too were failing before - neither is sent
        back; a regression (passed at the last green run) is named. A run whose failing tests
        are all one or the other drops out."""
        kept = []
        for run, output in failed:
            if ci_commands.checks_files(run.command):  # (CL-336 M: its findings name files)
                if not await self._lint_before(ctx, held, run, output):
                    kept.append((run, output))
                continue
            named = proof_before.failed_ids(run.command, output)
            self._regressions(ctx, held, run, named)
            # (Review: an id is what the run PRINTED - only a plain one goes on a line run unasked.)
            ids = [one for one in named if proof_before.plain_id(one)]
            odd = self._unusual(held, run.command, named)
            if not ids or not self._may_rerun(ctx, held, run):
                if ids:
                    self._said_once(
                        held, proof.row("before", "note", NO_BEFORE.format(why=ASKS_AGAIN))
                    )
                kept.append((run, output))
                continue
            still = await self.flaky(ctx, held, run, ids)
            new = await self.failing_before(ctx, held, run, still) if still else []
            if new or odd:
                kept.append((run, output))
        return kept

    async def _lint_before(
        self: "AgentRunner", ctx: Ctx, held: "Proof", run: TestRun, output: str
    ) -> bool:
        """CL-336 M: whether a failed lint, format or type check was failing before - said, not
        sent back: no file the turn changed is in its output, and each finding is there on the
        old code too, as often (a type error in a file the turn did not touch may be the turn's;
        a config error of the turn's names no file). Not where none is named, nor without the
        old code: the turn's."""
        root = self._ws(ctx).root
        now_found = proof_before.lint_findings(
            output, root, run.cwd, [one.path for one in held.changes]
        )
        if now_found is None:
            return False
        why = (
            CHANGED_BY_COMMAND
            if self._changed_by_command(ctx)
            else None
            if (self._may_rerun(ctx, held, run))
            else ASKS_AGAIN
        )
        if why:
            self._said_once(held, proof.row("before", "note", NO_BEFORE.format(why=why)))
            return False
        async with self._throwaway_copy(ctx) as place:
            made = None if place is None else await self._run_aside(ctx, held, run, place)
            then = (
                proof_before.lint_findings(made[1], place.root, run.cwd)
                if (made and place)
                else None
            )
        if then is None or not now_found[1] <= then[1]:
            return False
        files = sorted(now_found[0])
        more = (
            f" +{len(files) - proof.MOST_TOUCHED} more" if len(files) > proof.MOST_TOUCHED else ""
        )
        self._said_once(
            held,
            proof.row(
                "before",
                "note",
                LINT_BEFORE.format(
                    files=", ".join(files[: proof.MOST_TOUCHED]) + more,
                    command=f"from CI: {run.command}" if run.ci else run.command,
                ),
                run.command,
            ),
        )
        return True

    async def flaky(
        self: "AgentRunner", ctx: Ctx, held: "Proof", run: TestRun, ids: list[str]
    ) -> list[str]:
        """S11's hook too: `ids` of `run` run alone once - those that pass are flaky (said, noted
        in the project's memory); the ones still failing. All of them where it cannot tell."""
        line = proof_before.alone(run.command, ids)
        made = await self._run_aside(ctx, held, TestRun(line, run.cwd, run.yours)) if line else None
        if made is None:
            return ids
        row, output = made
        counted = test_found.counts(output, line or "")
        if not (counted and counted.ran):
            return ids  # (it ran none - collected only, say - or did not end: no word on any)
        failing = (
            set() if row["state"] == "passed" else set(proof_before.failed_ids(line or "", output))
        )
        if row["state"] != "passed" and not failing:
            return ids
        for one in (one for one in ids if one not in failing):
            self._said_once(held, proof.row("before", "note", FLAKY.format(id=one), run.command))
            self._note_flaky(ctx, one)
        return [one for one in ids if one in failing]

    async def failing_before(
        self: "AgentRunner", ctx: Ctx, held: "Proof", run: TestRun, ids: list[str]
    ) -> list[str]:
        """S11's hook too: `ids` of `run` on the code as it was before the turn (a throwaway
        copy) - those failing there too were failing before (said, not sent back); the new ones.
        All of them where the old code cannot be rebuilt."""
        if self._changed_by_command(ctx):
            self._said_once(
                held, proof.row("before", "note", NO_BEFORE.format(why=CHANGED_BY_COMMAND))
            )
            return ids
        line = proof_before.alone(run.command, ids) or run.command
        async with self._throwaway_copy(ctx) as place:
            made = (
                None
                if place is None
                else await self._run_aside(ctx, held, TestRun(line, run.cwd, run.yours), place)
            )
        if made is None:
            return ids
        row, output = made
        there = set(proof_before.failed_ids(line, output)) if row["state"] == "failed" else set()
        before = [one for one in ids if one in there]
        new = [one for one in ids if one not in there]
        if before:
            self._said_once(
                held,
                proof.row("before", "note", BEFORE.format(n=len(before), m=len(new)), run.command),
            )
            held.before_ids += before
        return new

    async def _after_pass(
        self: "AgentRunner", ctx: Ctx, held: "Proof", runs: list[TestRun]
    ) -> str | None:
        """The tests passed: what the last failing run of the same command said is said; the
        project's last green state is held (decision 14b) - and kept anew; in a bug fix the new
        test runs on the old code."""
        said = []
        for row in [
            one
            for one in held.rows
            if one["kind"] == "tests"
            and one["state"] == "passed"
            and one["command"]
            and one["counts"]
            and not one["text"].startswith("Related")
        ]:
            run = next((one for one in runs if one.command == row["command"]), None)
            if run is not None:
                self._at_last_run(ctx, held, run)
                said += self._green(ctx, held, run, dict(row["counts"] or {}))
        await self._bugfix_check(ctx, held, runs)
        if not said or not self._round_left(
            ctx, held, "green", frozenset(said), "tests removed or skipped"
        ):
            return None
        return GREEN_LEAD.format(said="; ".join(said))

    def _green(
        self: "AgentRunner", ctx: Ctx, held: "Proof", run: TestRun, counts: dict
    ) -> list[str]:
        """Decision 14b: a whole suite that passed against the project's last green run of it -
        fewer tests, more skipped, and the Orchestrator's answer says no why: failed rows, what
        goes back. Else this run is the green state from now on."""
        key = f"{run.cwd} {run.command}"
        ran, skipped = counts["passed"] + counts["failed"], counts["skipped"]
        with self._factory() as session:
            project = self._project(session, ctx.cid)
            if project is None:
                return []
            was = (project.tests_green or {}).get(key)
            said = proof_before.green_said(was, ran, skipped)
            fewer, skips = (
                self._could_drop(session, ctx, held, run, was, ran)
                if said and was
                else (True, True)
            )
            ours = [one for one in said if (skips if one.startswith("Skipped") else fewer)]
            for one in (one for one in said if one not in ours):  # (R: the green state moves)
                self._said_once(
                    held, proof.row("tests", "note", NOT_OURS.format(said=one), run.command)
                )
            said = ours
            answer = self._last_answer(session, ctx)
            why = {one: proof_before.excuse(answer, one) for one in said}
            for one in (one for one in said if why[one]):  # (excused, still shown: a note)
                self._said_once(
                    held,
                    proof.row("tests", "note", EXCUSED.format(said=one, why=why[one]), run.command),
                )
            if left := [one for one in said if not why[one]]:
                # (its code "removed": Fix it says fewer tests ran, not that they failed)
                held.rows += [
                    proof.row("tests", "failed", one, run.command, reason="removed") for one in left
                ]
                return left
            project.tests_green = {
                **(project.tests_green or {}),
                key: {
                    "ran": ran,
                    "skipped": skipped,
                    "at": now().isoformat(),
                    "ids": self._passed_now(session, ctx, run),
                },
            }
            session.commit()
        return []

    def _could_drop(
        self: "AgentRunner", session, ctx: Ctx, held: "Proof", run: TestRun, was: dict, ran: int
    ) -> tuple[bool, bool]:
        """R (CL-345; its fourth round, the main session's rule: conservative): whether a drop
        against the last green run `was` - fewer tests run, more skipped - may be the turn's. Fewer
        is outside it only where the turn touched no test file at all - none changed, made, deleted
        or renamed, nothing in a tests folder (`steers_tests`) - and each test the green run listed
        as passed and this run does not (`missing`) lives in a file it did not touch, and none of: a
        command of the turn's that may write ran, wherever it ran (`_wrote_by_command`); what says
        which tests run changed (`steers_tests`, a file the test command names); a change on
        KOLONİ's record since that green run took lines out of a test file (`_tests_cut_since`:
        another turn's, whose suite ended after its answer). A runner that lists no ids (either
        run), or ids that do not add up to the tests each run counted (`ran`: file ids - vitest's,
        jest's - never do; a list cut at MOST_IDS): the turn's, as before R. More skipped: the
        turn's - no runner here lists what it skipped by id.
        shortcut: any test file the turn touched makes the drop its own - a test added to a file,
        with tests deleted by hand elsewhere, is sent back. 0.1.8: the ids collected at the turn's
        start (`pytest --collect-only -q`, `vitest list`) tell green -> start (outside) from start
        -> end (the turn's), whatever it touched.
        shortcut: a test generated from data the turn changed elsewhere - a parametrize list built
        from the app's data, a flag a skipif reads - lives in a file it did not touch, and its
        drop reads as outside; read the tests' imports if that is seen."""
        turns = (True, True)
        if held.unrecorded or held.gone_tests or self._wrote_by_command(session, ctx):
            return turns
        mine = [one for one in held.changes if one.in_project]
        named = {
            word.rsplit("/", 1)[-1]
            for word in run.command.replace("\\", "/").split()
            if "." in word
        }
        if any(
            steers_tests(one.path)
            or one.path.rsplit("/", 1)[-1] in named
            or proof.is_test(one.path)
            for one in mine
        ):
            return turns
        since = was.get("at")
        if since is None or self._tests_cut_since(session, ctx, since):
            return turns
        green, now = was.get("ids"), self._passed_now(session, ctx, run)
        if not green or now is None or len(set(green)) != was.get("ran") or len(set(now)) != ran:
            return turns
        missing = set(green) - set(now)
        touched = {one.path for one in mine}
        fewer = not missing or any(_touched(one, run.cwd, touched) for one in missing)
        return fewer, True

    def _wrote_by_command(self: "AgentRunner", session, ctx: Ctx) -> bool:
        """R: whether a command of the turn's agents that may write files ran (`proof.may_write`)
        - in the project or in any copy of the turn, KOLONİ's own runs aside; Fix it's held turn's
        too. One that may have started counts: only a card turned down did not."""
        mine = select(ToolCall.id).where(ToolCall.provider_call_id.startswith(proof.PROOF_CALL))
        runs = [ctx.run_id, *filter(None, [self._resumed_from.get(ctx.run_id)])]
        return any(
            proof.may_write(line)
            for line in session.scalars(
                select(Command.command).where(
                    Command.run_id.in_(runs),
                    Command.tool_call_id.is_not(None),
                    Command.tool_call_id.not_in(mine),
                    Command.status.not_in(("proposed", "rejected", "parked")),
                )
            )
        )

    def _tests_cut_since(self: "AgentRunner", session, ctx: Ctx, since: str) -> bool:
        """R: whether a change on KOLONİ's record in this project's turns since `since` (the green
        run's time) but this turn's own took lines out of a test file, or deleted one."""
        project = self._project(session, ctx.cid)
        try:
            at = datetime.fromisoformat(since)
        except (TypeError, ValueError):
            return True  # (not known: the turn's)
        if project is None:
            return True
        found = session.execute(
            select(FileChange.id, FileChange.path, FileChange.kind)
            .join(Run, Run.id == FileChange.run_id)
            .join(Conversation, Conversation.id == Run.conversation_id)
            .where(
                Conversation.project_id == project.id,
                FileChange.run_id != ctx.run_id,
                FileChange.created_at >= at,
                FileChange.status.in_((*ledger.KEPT, proof.MERGED)),
            )
        ).all()
        tests = [(id_, kind) for id_, path, kind in found if proof.is_test(path)]
        if any(kind == "delete" for _id, kind in tests):
            return True
        # (the texts of test files' changes alone are read)
        return any(
            before is not None and not proof_before.kept_lines(before, after)
            for before, after in session.execute(
                select(FileChange.before_content, FileChange.after_content).where(
                    FileChange.id.in_([id_ for id_, _kind in tests])
                )
            )
        )

    @staticmethod
    def _passed_now(session, ctx: Ctx, run: TestRun) -> list[str] | None:
        """The tests the turn's last passing run of `run` by KOLONİ lists as passed; None: its
        output lists none. (Its run by the command it is known by - S9's line has coverage's
        report flags: `proof._known_as`.)"""
        wanted = proof._folded(run.command)
        output = next(
            (
                one.output
                for one in session.scalars(
                    select(Command)
                    .join(ToolCall, ToolCall.id == Command.tool_call_id)
                    .where(
                        Command.run_id == ctx.run_id,
                        _named(run.command),
                        ToolCall.provider_call_id.startswith(proof.PROOF_CALL),
                        Command.exit_code == 0,
                    )
                    .order_by(Command.started_at.desc(), literal_column("commands.rowid").desc())
                )
                if proof._known_as(session, one) == wanted
            ),
            None,
        )
        return proof_before.passed_ids(run.command, output or "")

    def _regressions(
        self: "AgentRunner", ctx: Ctx, held: "Proof", run: TestRun, ids: list[str]
    ) -> None:
        """Decision 14b: a failing test of a run whose suite was green before - not one this
        turn wrote - passed then: a regression, named."""
        with self._factory() as session:
            project = self._project(session, ctx.cid)
            green = (project.tests_green or {}) if project is not None else {}
            mine = set(self._new_tests(session, ctx))
        was = green.get(f"{run.cwd} {run.command}")
        if was is None:
            return
        held.rows += [
            proof.row(
                "tests",
                "failed",
                REGRESSION.format(id=one, by=" (by file)" if by_file else ""),
                run.command,
            )
            for one, by_file in proof_before.regressions(ids, was, mine)
        ]

    def _at_last_run(self: "AgentRunner", ctx: Ctx, held: "Proof", run: TestRun) -> None:
        """A command whose last run by KOLONİ in this project (an earlier turn's) failed and
        passes now: how many were failing then, said."""
        with self._factory() as session:
            project = self._project(session, ctx.cid)
            wanted = proof._folded(run.command)
            last = (
                next(
                    (
                        one
                        for one in session.scalars(
                            select(Command)
                            .join(ToolCall, ToolCall.id == Command.tool_call_id)
                            .join(Run, Run.id == Command.run_id)
                            .where(
                                ToolCall.provider_call_id.startswith(proof.PROOF_CALL),
                                _named(run.command),
                                Command.run_id != ctx.run_id,
                                Command.status == "exited",
                                Run.conversation_id.in_(self._chats_of(session, project)),
                            )
                            .order_by(
                                Command.started_at.desc(), literal_column("commands.rowid").desc()
                            )
                        )
                        if proof._known_as(session, one) == wanted
                    ),
                    None,
                )
                if project is not None
                else None
            )
        if last is not None and last.exit_code not in (0, None):
            n = len(proof_before.failed_ids(last.command, last.output)) or 1
            when = last.started_at.strftime("%d %b %H:%M") if last.started_at else "earlier"
            self._said_once(
                held, proof.row("before", "note", AT_LAST.format(n=n, when=when, m=0), run.command)
            )

    async def _bugfix_check(
        self: "AgentRunner", ctx: Ctx, held: "Proof", runs: list[TestRun]
    ) -> None:
        """A bug-fix turn with a new test and a change of the code: the new test alone on the old
        code (a throwaway copy that keeps it) must fail there."""
        with self._factory() as session:
            asked = (
                session.scalar(
                    select(Message.content)
                    .where(Message.run_id == ctx.run_id, Message.role == "user")
                    .limit(1)
                )
                or ""
            )
            written = self._new_tests(session, ctx)
        code = [
            one
            for one in held.changes
            if one.in_project and one.kind == "code" and one.path not in written
        ]
        if (
            not proof_before.BUGFIX.search(asked)
            or not written
            or not code
            or self._unusual(held, runs[0].command if runs else "", written)
        ):
            return
        run = next((one for one in runs if proof_before.alone(one.command, written)), None)
        if run is None:
            return
        line = proof_before.alone(run.command, written) or run.command
        async with self._throwaway_copy(ctx, keep=written) as place:
            made = (
                None
                if place is None
                else await self._run_aside(ctx, held, TestRun(line, run.cwd, run.yours), place)
            )
        if made is not None and made[0]["state"] in ("passed", "failed"):
            caught = made[0]["state"] == "failed"
            held.rows.append(
                proof.row(
                    "tests",
                    "passed" if caught else "failed",
                    CAUGHT if caught else NOT_CAUGHT,
                    line,
                )
            )

    def _unusual(self: "AgentRunner", held: "Proof", command: str, ids: list[str]) -> list[str]:
        """Of test ids a run printed (or test files written), those that are no plain name
        (`proof_before.plain_id`): never put on a line KOLONİ runs unasked - said once."""
        odd = [one for one in ids if not proof_before.plain_id(one)]
        if odd:
            self._said_once(
                held,
                proof.row(
                    "before",
                    "note",
                    UNUSUAL.format(ids=", ".join(one[:80] for one in odd[:3])),
                    command,
                ),
            )
        return odd

    @staticmethod
    def _said_once(held: "Proof", row: proof.Row) -> None:
        """A row of what is not this turn's: kept through the passes, said once."""
        if all(one["text"] != row["text"] for one in held.rows):
            held.rows.append(row)

    def _may_rerun(self: "AgentRunner", ctx: Ctx, held: "Proof", run: TestRun) -> bool:
        """Whether `run` may be run again - alone, on the old code - with no card: it goes
        unasked (your own command, Full auto, a trigger's leave). A guess whose card was said yes
        to is not: no second card is raised for it."""
        how = self._may_run_tests(ctx, run)
        return how == "run" or how == "ask" and (run.yours or self._full_auto(ctx))

    async def _run_aside(
        self: "AgentRunner", ctx: Ctx, held: "Proof", run: TestRun, place=None
    ) -> tuple[proof.Row, str] | None:
        """One more of KOLONİ's runs - alone, or on the old code (`place`) - within what is left
        of the turn's wait, on the leave its whole run had (`_may_rerun`: no card); None where
        none is left."""
        seconds = None if held.until is None else math.ceil(held.until - time.monotonic())
        how = self._may_run_tests(ctx, run)
        if seconds is not None and seconds < 1 or how not in ("run", "ask"):
            return None
        held.yes.setdefault(run.cwd, set()).add(run.command.strip())
        held.place = place
        try:
            return await self._run_tests(ctx, run, how, held, seconds)
        finally:
            held.place = None

    @asynccontextmanager
    async def _throwaway_copy(self: "AgentRunner", ctx: Ctx, keep: list[str] | tuple = ()):
        """The work as it was before the turn: a copy of where the Lead works, made as a
        sub-agent's is, each file the turn changed written back to its first `before` (none:
        removed) - but `keep`. Yields its workspace (None: none could be made); dropped after,
        whatever happens, through the copies' own removal path (its links let go of first)."""
        name = f"before-{uuid.uuid4().hex[:12]}"
        root = self.settings.runtime_root
        made = None
        try:
            # (k-bakis-yeri: Fix it on held work - the old code is the project's, none of the held
            # work in it: its own failure is never "failing before this turn")
            held = self._kept_work(ctx) is not None
            made = await asyncio.to_thread(
                copies.make, Path(ctx.folder) if held else self._ws(ctx).root, root, name
            )
            with self._factory() as session:
                kept = {} if held else proof._kept(session, ctx.run_id)
            for path in keep if held else ():  # (a test the bug-fix check runs: the work's)
                if (place := made.here(path)) is not None:
                    data = self._ws(ctx).resolve(path).read_bytes()
                    place.parent.mkdir(parents=True, exist_ok=True)
                    place.write_bytes(data)
            for path, rows in kept.items():
                if path in keep or (place := made.here(path)) is None:
                    continue
                before = rows[0].before_content
                if before is None:
                    place.unlink(missing_ok=True)
                else:  # (its bytes as on record: no newline of the platform's put in)
                    # shortcut: only text is on record - a binary file changed off it stays as
                    # it is now (by a command: `failing_before` says no old code, the bug-fix
                    # check does not ask; by a CLI's own file tool: not seen). Keep the look's
                    # `made` per turn if one is met.
                    place.parent.mkdir(parents=True, exist_ok=True)
                    place.write_bytes(before.encode("utf-8"))
        except Exception as exc:  # (no old code to run on: said as no "before")
            log.warning("run %s: no copy of the old code: %r", ctx.run_id, exc)
            if made is not None:
                await self._drop_throwaway(name)
            yield None
            return
        try:
            yield made.workspace()
        finally:
            await self._drop_throwaway(name)

    async def _drop_throwaway(self: "AgentRunner", name: str) -> None:
        root = self.settings.runtime_root
        copies.forget(root, name)
        with suppress(OSError):
            await asyncio.to_thread(copies.remove, root, name)

    def _changed_by_command(self: "AgentRunner", ctx: Ctx) -> bool:
        """Whether a command of this turn (not a test run, not a mere read, not KOLONİ's) may
        have changed the project: what it changed is not on record - no "before"."""
        with self._factory() as session:
            mine = select(ToolCall.id).where(ToolCall.provider_call_id.startswith(proof.PROOF_CALL))
            lines = session.scalars(
                select(Command.command).where(
                    Command.run_id == ctx.run_id,
                    Command.status == "exited",
                    Command.tool_call_id.not_in(mine),
                )
            ).all()
        return any(ledger.read_test(line) is None and not only_reads(line) for line in lines)

    def _new_tests(self: "AgentRunner", session, ctx: Ctx) -> list[str]:
        made = [
            path
            for path, rows in proof._kept(session, ctx.run_id).items()
            if rows[0].before_content is None and rows[-1].kind != "delete"
        ]
        return proof_before.new_tests(made)

    @staticmethod
    def _chats_of(session, project):
        from app.db.models import Conversation

        return select(Conversation.id).where(Conversation.project_id == project.id)

    def _last_answer(self: "AgentRunner", session, ctx: Ctx) -> str:
        return (
            session.scalar(
                select(Message.content)
                .where(
                    Message.agent_id == ctx.agent_id,
                    Message.run_id == ctx.run_id,
                    Message.role == "assistant",
                )
                .order_by(Message.created_at.desc(), literal_column("messages.rowid").desc())
                .limit(1)
            )
            or ""
        )

    def _note_flaky(self: "AgentRunner", ctx: Ctx, test: str) -> None:
        """A flaky test in the project's memory, KOLONİ's note: how often it was seen so."""
        subject = f"flaky test: {test}"[:80]
        try:
            with self._factory() as session:
                project = self._project(session, ctx.cid)
                if project is None:
                    return
                about, key = memory.check_about(subject)
                older = session.scalar(
                    select(Memory.text).where(
                        Memory.project_id == project.id,
                        Memory.about_key == key,
                        Memory.status == "active",
                    )
                )
                seen = int(found.group(1)) + 1 if older and (found := _SEEN.search(older)) else 1
                memory.keep_note(
                    session,
                    project.id,
                    memory.Asked(
                        FLAKY_NOTE.format(date=now().strftime("%d %b %Y"), n=seen),
                        about,
                        key,
                        None,
                        None,
                        None,
                        False,
                    ),
                    agent_id=None,
                    run_id=ctx.run_id,
                    conversation_id=ctx.cid,
                    source=None,
                    checked_how=None,
                    noted_by={"provider_name": "KOLONİ", "model_id": None},
                )
                session.commit()
        except Exception as exc:  # (a note of KOLONİ's fails nothing)
            log.warning("run %s: the flaky test not noted: %r", ctx.run_id, exc)
