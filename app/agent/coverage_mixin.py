"""Kanıtlı bitiş S9: where the project already measures coverage, the end check's whole-suite run
(in the turn, or gone on after the answer - never the related step) gets report flags only, its
report written under the project's scratch; what share of the turn's changed lines the tests ran
is said under the answer, and the new lines none ran go to the Reviewer as data. The run keeps
its own leave and its own name (rows, reuse and the green state know it by its command without
the flags); flags its runner does not know are dropped and the run runs once more without them.
`CoverageMixin`."""

import hashlib
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from app import coverage, proof
from app.agent.ctx import Ctx
from app.agent.proof_mixin import SLOT_BUSY
from app.proof import Row, TestRun
from app.workspace import SCRATCH

if TYPE_CHECKING:
    from app.agent import AgentRunner
    from app.agent.proof_mixin import Proof

MEASURED = "Coverage: {p}% of the changed lines are run by tests ({tool})"
NOT_MEASURED = "Coverage: not measured ({why})"
FLAGS_FAILED = "the flags failed"
NO_REPORT = "no report"
UNRUN = "New lines no test runs: {path} {ranges}"


class CoverageMixin:
    async def _covered_tests(self: "AgentRunner", ctx: Ctx, run: TestRun, held: "Proof",
                             until: float | None) -> tuple[Row, str]:
        """`_tests_of` for a whole suite - with report flags where the project has the tool, and
        the run is not one already on record that stands for it."""
        place = Path(self._ws(ctx).root)
        tool = coverage.tool_of(place / run.cwd, run.command)
        key = (run.command, run.cwd)
        if tool is None:
            return await self._tests_of(ctx, run, held, until)
        if self._fresh_of(ctx, run) is not None:
            # (a run on record stands: what this turn measured on the same work stands with it)
            seen, rows, unrun = held.measured.get(key, (None, [], {}))
            if rows and seen == held.seen:
                held.covered[key] = rows
                held.uncovered.update(unrun)
            return await self._tests_of(ctx, run, held, until)
        # (the same folder each pass of the turn: a run again is the same line on the canvas)
        out = place / SCRATCH / f"coverage-{hashlib.sha256(
            f'{ctx.run_id}|{run.cwd}|{run.command}'.encode()).hexdigest()[:12]}"
        shutil.rmtree(out, ignore_errors=True)  # (an earlier pass's, if left)
        # (relative at the root - a path naming the project is asked about in a copy; whole in a
        # part: `../.koloni` climbs out of the scratch, asked about at every level)
        line = coverage.with_coverage(run.command, tool, (
            out.relative_to(place) if run.cwd == "." else out).as_posix())
        held.lines[(run.command, run.cwd)] = line
        if run.yours or run.command.strip() in held.yes.get(run.cwd, set()):
            held.yes.setdefault(run.cwd, set()).add(line.strip())  # (its own leave: no card more)
        try:
            made, output = await self._tests_of(ctx, run, held, until)
        finally:
            held.lines.pop((run.command, run.cwd), None)
        if self._flags_to_blame(made, output):
            shutil.rmtree(out, ignore_errors=True)
            made, output = await self._tests_of(ctx, run, held, until, fresh=False)
            if made["state"] != "not_run":
                held.covered[key] = [proof.row("coverage", "note", NOT_MEASURED.format(
                    why=FLAGS_FAILED), run.command)]
        elif made["state"] == "running":
            held.covering[key] = (tool, out)  # (gone on after the answer: read as it ends)
        elif made["state"] == "not_run":
            shutil.rmtree(out, ignore_errors=True)  # (declined, stopped: nothing to say)
        else:
            held.covered[key] = self._coverage_read(ctx, held, run, tool, out)
        return made, output

    @staticmethod
    def _flags_to_blame(made: Row, output: str) -> bool:
        """Whether the run with report flags may have failed, or not run, for them: its runner
        did not know them or a threshold of the project's failed (`coverage.FLAGS_FAILED`), or
        it did not run for a reason other than your no, your Stop or a busy slot (a gate the
        plain line passes, filters a runner read the flags as)."""
        if made["state"] == "failed":
            return bool(coverage.FLAGS_FAILED.search(output))
        return made["state"] == "not_run" and not any(why in made["text"] for why in (
            "declined on its card", SLOT_BUSY, "not finished", "stopped"))

    def _coverage_rows(self: "AgentRunner", held: "Proof", run: TestRun) -> list[Row]:
        return held.covered.pop((run.command, run.cwd), [])

    def _coverage_later(self: "AgentRunner", ctx: Ctx, held: "Proof", run: TestRun) -> list[Row]:
        """A whole suite gone on after the answer has ended: its report, read now."""
        found = held.covering.pop((run.command, run.cwd), None)
        return self._coverage_read(ctx, held, run, *found) if found else []

    def _coverage_read(self: "AgentRunner", ctx: Ctx, held: "Proof", run: TestRun, tool: str,
                       out: Path) -> list[Row]:
        """The report's word on the turn's added lines: the share run, its row; the new lines
        none ran, kept for the Reviewer (`held.uncovered`). The report is read only under the
        scratch, size-capped (`coverage.report`), and deleted after.
        shortcut: read and matched on the event loop (a report up to 20 MB, the turn's diffs) -
        hand it to a thread if a big project's answer is felt to stall."""
        place = Path(self._ws(ctx).root)
        data = coverage.report(place, out, tool)
        shutil.rmtree(out, ignore_errors=True)
        if data is None:
            return [proof.row("coverage", "note", NOT_MEASURED.format(why=NO_REPORT), run.command)]
        with self._factory() as session:
            added = proof.added_lines(session, ctx.run_id, ctx.agent_id, self._sharing(ctx))
        said = coverage.changed_lines_covered(place, data, tool, added, run.cwd)
        held.uncovered.update(said.uncovered)
        rows = [] if said.percent is None else [proof.row("coverage", "note", MEASURED.format(
            p=said.percent, tool=tool), run.command)]
        held.measured[(run.command, run.cwd)] = (held.seen, rows, said.uncovered)
        return rows

    @staticmethod
    def _unrun_lines(held: "Proof") -> str:
        """For the Reviewer's brief, as data: each new line no test ran, by file."""
        return "\n".join(UNRUN.format(path=path, ranges=coverage.ranges(lines))
                         for path, lines in sorted(held.uncovered.items()))
