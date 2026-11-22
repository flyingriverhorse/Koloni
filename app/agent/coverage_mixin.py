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
        if tool is None or self._fresh_of(ctx, run) is not None:
            return await self._tests_of(ctx, run, held, until)
        # (the same folder each pass of the turn: a run again is the same line on the canvas)
        out = place / SCRATCH / f"coverage-{hashlib.sha256(
            f'{ctx.run_id}|{run.cwd}|{run.command}'.encode()).hexdigest()[:12]}"
        shutil.rmtree(out, ignore_errors=True)  # (an earlier pass's, if left)
        line = coverage.with_coverage(run.command, tool, str(out))
        held.lines[(run.command, run.cwd)] = line
        if run.yours or run.command.strip() in held.yes.get(run.cwd, set()):
            held.yes.setdefault(run.cwd, set()).add(line.strip())  # (its own leave: no card more)
        try:
            made, output = await self._tests_of(ctx, run, held, until)
        finally:
            held.lines.pop((run.command, run.cwd), None)
        key = (run.command, run.cwd)
        if made["state"] == "failed" and coverage.FLAGS_FAILED.search(output):
            shutil.rmtree(out, ignore_errors=True)
            made, output = await self._tests_of(ctx, run, held, until, fresh=False)
            held.covered[key] = [proof.row("coverage", "note", NOT_MEASURED.format(
                why=FLAGS_FAILED), run.command)]
        elif made["state"] == "running":
            held.covering[key] = (tool, out)  # (gone on after the answer: read as it ends)
        elif made["state"] == "not_run":
            shutil.rmtree(out, ignore_errors=True)  # (declined, refused, stopped: nothing to say)
        else:
            held.covered[key] = self._coverage_read(ctx, held, run, tool, out)
        return made, output

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
        scratch, size-capped (`coverage.report`), and deleted after."""
        place = Path(self._ws(ctx).root)
        data = coverage.report(place, out, tool)
        shutil.rmtree(out, ignore_errors=True)
        if data is None:
            return [proof.row("coverage", "note", NOT_MEASURED.format(why=NO_REPORT), run.command)]
        with self._factory() as session:
            added = proof.added_lines(session, ctx.run_id, ctx.agent_id, self._sharing(ctx))
        said = coverage.changed_lines_covered(place, data, tool, added)
        held.uncovered.update(said.uncovered)
        return [] if said.percent is None else [proof.row("coverage", "note", MEASURED.format(
            p=said.percent, tool=tool), run.command)]

    @staticmethod
    def _unrun_lines(held: "Proof") -> str:
        """For the Reviewer's brief, as data: each new line no test ran, by file."""
        return "\n".join(UNRUN.format(path=path, ranges=coverage.ranges(lines))
                         for path, lines in sorted(held.uncovered.items()))
