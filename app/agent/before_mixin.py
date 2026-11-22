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
import re
import time
import uuid
from contextlib import asynccontextmanager, suppress
from typing import TYPE_CHECKING

from sqlalchemy import literal_column, select

from app import copies, ledger, memory, proof, proof_before, test_found
from app.agent.ctx import Ctx
from app.commands import only_reads
from app.db.models import Command, Memory, Message, Run, ToolCall, now
from app.proof import TestRun

if TYPE_CHECKING:
    from app.agent import AgentRunner
    from app.agent.proof_mixin import Proof

log = logging.getLogger(__name__)

FLAKY = "Flaky: {id} failed in the full run and passed alone (noted in this project's memory)"
FLAKY_NOTE = "Failed in a full run and passed alone ({date}); seen {n} times"
BEFORE = "{n} were failing before this turn, {m} new"
AT_LAST = "{n} were failing at the last run ({when}), {m} now"
CAUGHT = "The new test fails on the old code ✓"
NOT_CAUGHT = "The new test passes on the old code too: it may not catch the bug"
NO_BEFORE = "Not checked against the old code: {why}"
CHANGED_BY_COMMAND = "a command changed the project this turn, and what it changed is not on record"
ASKS_AGAIN = "not re-run alone or on the old code: it would ask again"
REGRESSION = "Regression: {id} passed at the last green run and fails now"
NOT_YOURS = " These were failing before this turn and are not yours to fix: {ids}."
GREEN_LEAD = ("Not the end yet: {said}, against this project's last green run - and your answer "
              "does not say why. Put back what was taken away, or say in your answer why the "
              "tests were removed or skipped; KOLONİ runs them again.")
_SEEN = re.compile(r"seen (\d+) times")


class BeforeMixin:
    async def _proof_before(self: "AgentRunner", ctx: Ctx, held: "Proof",
                            failed: list[tuple[TestRun, str]]) -> list[tuple[TestRun, str]]:
        """The failures that are this turn's: of each failed run, the tests that pass alone are
        flaky and those that fail on the old code too were failing before - neither is sent
        back; a regression (passed at the last green run) is named. A run whose failing tests
        are all one or the other drops out."""
        kept = []
        for run, output in failed:
            ids = proof_before.failed_ids(run.command, output)
            self._regressions(ctx, held, run, ids)
            if not ids or not self._may_rerun(ctx, held, run):
                if ids:
                    self._said_once(held, proof.row("before", "note", NO_BEFORE.format(
                        why=ASKS_AGAIN)))
                kept.append((run, output))
                continue
            still = await self.flaky(ctx, held, run, ids)
            new = await self.failing_before(ctx, held, run, still) if still else []
            if new:
                kept.append((run, output))
        return kept

    async def flaky(self: "AgentRunner", ctx: Ctx, held: "Proof", run: TestRun,
                    ids: list[str]) -> list[str]:
        """S11's hook too: `ids` of `run` run alone once - those that pass are flaky (said, noted
        in the project's memory); the ones still failing. All of them where it cannot tell."""
        line = proof_before.alone(run.command, ids)
        made = await self._run_aside(ctx, held, TestRun(line, run.cwd, run.yours)) if line else None
        if made is None:
            return ids
        row, output = made
        counted = test_found.counts(output, line or "")
        if row["state"] != "passed" and not (counted and counted.ran):
            return ids  # (it ran none, or did not end: no word on any of them)
        failing = set() if row["state"] == "passed" else set(
            proof_before.failed_ids(line or "", output))
        if row["state"] != "passed" and not failing:
            return ids
        for one in (one for one in ids if one not in failing):
            self._said_once(held, proof.row("before", "note", FLAKY.format(id=one), run.command))
            self._note_flaky(ctx, one)
        return [one for one in ids if one in failing]

    async def failing_before(self: "AgentRunner", ctx: Ctx, held: "Proof", run: TestRun,
                             ids: list[str]) -> list[str]:
        """S11's hook too: `ids` of `run` on the code as it was before the turn (a throwaway
        copy) - those failing there too were failing before (said, not sent back); the new ones.
        All of them where the old code cannot be rebuilt."""
        if self._changed_by_command(ctx):
            self._said_once(held, proof.row("before", "note", NO_BEFORE.format(
                why=CHANGED_BY_COMMAND)))
            return ids
        line = proof_before.alone(run.command, ids) or run.command
        async with self._throwaway_copy(ctx) as place:
            made = None if place is None else await self._run_aside(
                ctx, held, TestRun(line, run.cwd, run.yours), place)
        if made is None:
            return ids
        row, output = made
        there = set(proof_before.failed_ids(line, output)) if row["state"] == "failed" else set()
        before = [one for one in ids if one in there]
        new = [one for one in ids if one not in there]
        if before:
            self._said_once(held, proof.row("before", "note", BEFORE.format(
                n=len(before), m=len(new)), run.command))
            held.before_ids += before
        return new

    async def _after_pass(self: "AgentRunner", ctx: Ctx, held: "Proof",
                          runs: list[TestRun]) -> str | None:
        """The tests passed: what the last failing run of the same command said is said; the
        project's last green state is held (decision 14b) - and kept anew; in a bug fix the new
        test runs on the old code."""
        said = []
        for row in [one for one in held.rows if one["kind"] == "tests" and one["state"] == "passed"
                    and one["command"] and one["counts"] and not one["text"].startswith("Related")]:
            run = next((one for one in runs if one.command == row["command"]), None)
            if run is not None:
                self._at_last_run(ctx, held, run)
                said += self._green(ctx, held, run, dict(row["counts"] or {}))
        await self._bugfix_check(ctx, held, runs)
        if not said or held.rounds >= held.most or held.recipe_spent:
            return None
        held.rounds += 1
        held.sent.append("tests removed or skipped")
        return GREEN_LEAD.format(said="; ".join(said))

    def _green(self: "AgentRunner", ctx: Ctx, held: "Proof", run: TestRun,
               counts: dict) -> list[str]:
        """Decision 14b: a whole suite that passed against the project's last green run of it -
        fewer tests, more skipped, and the Orchestrator's answer says no why: failed rows, what
        goes back. Else this run is the green state from now on."""
        key = f"{run.cwd} {run.command}"
        ran, skipped = counts["passed"] + counts["failed"], counts["skipped"]
        with self._factory() as session:
            project = self._project(session, ctx.cid)
            if project is None:
                return []
            said = proof_before.green_said((project.tests_green or {}).get(key), ran, skipped)
            if said and not proof_before.SAID_WHY.search(self._last_answer(session, ctx)):
                held.rows += [proof.row("tests", "failed", one, run.command) for one in said]
                return said
            project.tests_green = {**(project.tests_green or {}), key: {
                "ran": ran, "skipped": skipped, "at": now().isoformat()}}
            session.commit()
        return []

    def _regressions(self: "AgentRunner", ctx: Ctx, held: "Proof", run: TestRun,
                     ids: list[str]) -> None:
        """Decision 14b: a failing test of a run whose suite was green before - not one this
        turn wrote - passed then: a regression, named."""
        with self._factory() as session:
            project = self._project(session, ctx.cid)
            green = (project.tests_green or {}) if project is not None else {}
            mine = set(self._new_tests(session, ctx))
        if f"{run.cwd} {run.command}" not in green:
            return
        held.rows += [proof.row("tests", "failed", REGRESSION.format(id=one), run.command)
                      for one in ids if one.split("::")[0] not in mine]

    def _at_last_run(self: "AgentRunner", ctx: Ctx, held: "Proof", run: TestRun) -> None:
        """A command whose last run by KOLONİ in this project (an earlier turn's) failed and
        passes now: how many were failing then, said."""
        with self._factory() as session:
            project = self._project(session, ctx.cid)
            last = session.scalar(
                select(Command).join(ToolCall, ToolCall.id == Command.tool_call_id)
                .join(Run, Run.id == Command.run_id).where(
                    ToolCall.provider_call_id.startswith(proof.PROOF_CALL),
                    Command.command == run.command, Command.run_id != ctx.run_id,
                    Command.status == "exited", Run.conversation_id.in_(
                        self._chats_of(session, project)))
                .order_by(Command.started_at.desc(), literal_column("commands.rowid").desc())
                .limit(1)) if project is not None else None
        if last is not None and last.exit_code not in (0, None):
            n = len(proof_before.failed_ids(last.command, last.output)) or 1
            when = last.started_at.strftime("%d %b %H:%M") if last.started_at else "earlier"
            self._said_once(held, proof.row("before", "note", AT_LAST.format(
                n=n, when=when, m=0), run.command))

    async def _bugfix_check(self: "AgentRunner", ctx: Ctx, held: "Proof",
                            runs: list[TestRun]) -> None:
        """A bug-fix turn with a new test and a change of the code: the new test alone on the old
        code (a throwaway copy that keeps it) must fail there."""
        with self._factory() as session:
            asked = session.scalar(select(Message.content).where(
                Message.run_id == ctx.run_id, Message.role == "user").limit(1)) or ""
            written = self._new_tests(session, ctx)
        code = [one for one in held.changes if one.in_project and one.kind == "code"
                and one.path not in written]
        run = next((one for one in runs if proof_before.alone(one.command, written)), None)
        if not proof_before.BUGFIX.search(asked) or not written or not code or run is None:
            return
        line = proof_before.alone(run.command, written) or run.command
        async with self._throwaway_copy(ctx, keep=written) as place:
            made = None if place is None else await self._run_aside(
                ctx, held, TestRun(line, run.cwd, run.yours), place)
        if made is not None and made[0]["state"] in ("passed", "failed"):
            caught = made[0]["state"] == "failed"
            held.rows.append(proof.row("tests", "passed" if caught else "failed",
                                       CAUGHT if caught else NOT_CAUGHT, line))

    @staticmethod
    def _said_once(held: "Proof", row: proof.Row) -> None:
        """A row of what is not this turn's: kept through the passes, said once."""
        if all(one["text"] != row["text"] for one in held.rows):
            held.rows.append(row)

    def _may_rerun(self: "AgentRunner", ctx: Ctx, held: "Proof", run: TestRun) -> bool:
        """Whether `run` may be run again - alone, on the old code - with no card: it went
        unasked (your own command, Full auto, a trigger's leave) or its card was said yes to this
        turn. Else it is not: no second card is raised for it."""
        how = self._may_run_tests(ctx, run)
        return how == "run" or how == "ask" and (run.yours or self._full_auto(ctx) or (
            run.command.strip() in held.yes.get(run.cwd, set())))

    async def _run_aside(self: "AgentRunner", ctx: Ctx, held: "Proof", run: TestRun,
                         place=None) -> tuple[proof.Row, str] | None:
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
            made = await asyncio.to_thread(copies.make, self._ws(ctx).root, root, name)
            with self._factory() as session:
                kept = proof._kept(session, ctx.run_id)
            for path, rows in kept.items():
                if path in keep or (place := made.here(path)) is None:
                    continue
                before = rows[0].before_content
                if before is None:
                    place.unlink(missing_ok=True)
                else:
                    place.parent.mkdir(parents=True, exist_ok=True)
                    place.write_text(before, encoding="utf-8")
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
            lines = session.scalars(select(Command.command).where(
                Command.run_id == ctx.run_id, Command.status == "exited",
                Command.tool_call_id.not_in(mine))).all()
        return any(ledger.read_test(line) is None and not only_reads(line) for line in lines)

    def _new_tests(self: "AgentRunner", session, ctx: Ctx) -> list[str]:
        made = [path for path, rows in proof._kept(session, ctx.run_id).items()
                if rows[0].before_content is None and rows[-1].kind != "delete"]
        return proof_before.new_tests(made)

    @staticmethod
    def _chats_of(session, project):
        from app.db.models import Conversation
        return select(Conversation.id).where(Conversation.project_id == project.id)

    def _last_answer(self: "AgentRunner", session, ctx: Ctx) -> str:
        return session.scalar(select(Message.content).where(
            Message.agent_id == ctx.agent_id, Message.run_id == ctx.run_id,
            Message.role == "assistant").order_by(
            Message.created_at.desc(), literal_column("messages.rowid").desc()).limit(1)) or ""

    def _note_flaky(self: "AgentRunner", ctx: Ctx, test: str) -> None:
        """A flaky test in the project's memory, KOLONİ's note: how often it was seen so."""
        subject = f"flaky test: {test}"[:80]
        try:
            with self._factory() as session:
                project = self._project(session, ctx.cid)
                if project is None:
                    return
                about, key = memory.check_about(subject)
                older = session.scalar(select(Memory.text).where(
                    Memory.project_id == project.id, Memory.about_key == key,
                    Memory.status == "active"))
                seen = int(found.group(1)) + 1 if older and (found := _SEEN.search(older)) else 1
                memory.keep_note(
                    session, project.id, memory.Asked(FLAKY_NOTE.format(
                        date=now().strftime("%d %b %Y"), n=seen), about, key, None, None, None,
                        False), agent_id=None, run_id=ctx.run_id, conversation_id=ctx.cid,
                    source=None, checked_how=None,
                    noted_by={"provider_name": "KOLONİ", "model_id": None})
                session.commit()
        except Exception as exc:  # (a note of KOLONİ's fails nothing)
            log.warning("run %s: the flaky test not noted: %r", ctx.run_id, exc)

