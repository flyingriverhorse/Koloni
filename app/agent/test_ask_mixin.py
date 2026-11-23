"""Kanıtlı bitiş S2 (plan decision 4): a turn that changed source and no test is asked, once, for
a test - for a bug fix, one that fails without the fix first - or one line of why none can be
written; and its Checked section names the tests it added, a test it removed, or that line.
`TestAskMixin._proof_test_ask` is the gate's last step: after the tests (S1, S6) and the review
(S3), so that no check of KOLONİ's own ever waits behind this nudge - an answer to a nudge with
no tool call ends the turn."""

from typing import TYPE_CHECKING

from sqlalchemy import literal_column, select

from app import proof
from app.agent.ctx import Ctx
from app.agent.words import TEST_ASKED
from app.db.models import Message
from app.proof import Change, Row

if TYPE_CHECKING:
    from app.agent import AgentRunner
    from app.agent.proof_mixin import Proof

NAMED = 3  # files named in a line, then "+N more"
MOST_SAID = 120  # characters of the Orchestrator's line quoted


def named(paths: list[str]) -> str:
    more = f" +{len(paths) - NAMED} more" if len(paths) > NAMED else ""
    return ", ".join(paths[:NAMED]) + more


class TestAskMixin:
    async def _proof_test_ask(self: "AgentRunner", ctx: Ctx, held: "Proof") -> str | None:
        """Where the turn changed source in the project and no test (`proof.untested`), the
        Orchestrator is asked once a turn (`asked_test`) - model-side, so the last step; it
        spends no fix round. Its rows are made with the Checked section (`_test_rows`)."""
        if (
            held.asked_test
            or "tests" not in held.checks.on
            or not (missing := proof.untested(held.changes))
        ):
            return None
        held.asked_test = True
        return TEST_ASKED.format(files=named(missing))

    def _test_rows(
        self: "AgentRunner",
        session,
        run_id: str,
        lead_id: str | None,
        found: list[Change],
        held: "Proof",
    ) -> list[Row]:
        """S2's rows, from the turn's changes as they stand at its end: the tests it added or
        changed; each test it removed that was there before (failed - the Reviewer judges it
        too); where it was asked and wrote none, the first line of the Orchestrator's last
        answer - its reason (an answer with no tool call ended the turn: no pass after it)."""
        removed = proof.removed_tests(found)
        # (CL-329 G: and each a command deleted - on no record, read off git)
        removed += [path for path in held.gone_tests if path not in removed]
        rows = [
            proof.row("test", "failed", proof.TEST_REMOVED.format(path=path)) for path in removed
        ]
        # (k-onceki-1, J: a test a stronger model changed without leave is said as no pass)
        if new := [one for one in proof.new_tests(found) if one.path not in held.loosened]:
            return [
                proof.row(
                    "test", "note", proof.NEW_TESTS.format(files=named([one.path for one in new]))
                ),
                *rows,
            ]
        if held.asked_test:
            rows.append(
                proof.row(
                    "test",
                    "note",
                    proof.NO_NEW_TEST.format(line=self._last_line(session, run_id, lead_id)),
                )
            )
        return rows

    @staticmethod
    def _last_line(session, run_id: str, lead_id: str | None) -> str:
        """The first line of the Orchestrator's last words in the turn, cut."""
        said = (
            session.scalar(
                select(Message.content)
                .where(
                    Message.run_id == run_id,
                    Message.agent_id == lead_id,
                    Message.role == "assistant",
                    Message.content != "",
                )
                .order_by(Message.created_at.desc(), literal_column("messages.rowid").desc())
                .limit(1)
            )
            or ""
        )
        line = next((one.strip() for one in said.splitlines() if one.strip()), "")
        return line if len(line) <= MOST_SAID else line[: MOST_SAID - 1] + "…"
