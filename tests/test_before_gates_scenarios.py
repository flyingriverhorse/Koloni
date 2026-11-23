"""k-bakis-yeri N: a test run whose failures were all failing before this turn (S7) is said, not
sent back - so it holds back no look either: a big change still gets KOLONİ's review. (A failure
of the turn's own still keeps the look off: test_proof_review_scenarios
`test_failing_tests_are_fixed_before_any_look`.) A fake model per agent, a scripted executor."""

import pytest

from app import proof
from app.agent import before_mixin
from tests.fakes import ScriptedExecutor
from tests.test_chat_flow import text
from tests.test_proof_before_scenarios import ONE, PYTEST, failing
from tests.test_proof_end_scenarios import begin, texts
from tests.test_proof_review_scenarios import BIG, MERGE, SIGN, calls_of, reviewers
from tests.test_spawn import call, step

pytestmark = pytest.mark.no_po


def test_a_change_whose_failing_tests_were_failing_before_is_still_looked_over(
    make_client, wait_run, project_dir
):
    executor = ScriptedExecutor([failing(ONE), failing(ONE), failing(ONE)])
    client, model = make_client(
        {
            "Lead": [step(call("write_file", {"path": "a.py", "content": BIG}, "w")), text("done")],
            "Reviewer": [MERGE],
        },
        executor=executor,
    )
    cid, run_id = begin(client, project_dir, check_command=PYTEST)
    snap = wait_run(client, cid, run_id)
    rows = texts(snap)
    assert before_mixin.BEFORE.format(n=1, m=0) in rows, rows
    assert f"Review: Reviewer ({SIGN}) - MERGE, no findings" in rows, rows
    assert [a["name"] for a in reviewers(snap)] == ["Reviewer"]
    # (and the Reviewer is told so: a red line failing before is no finding of the change's)
    assert before_mixin.BEFORE.format(n=1, m=0) in calls_of(model, "Reviewer")[0]


def test_still_failing_reads_past_rows_failing_before():
    failed = proof.row("tests", "failed", "Tests failed: x", "x")
    assert proof.still_failing([failed])
    assert not proof.still_failing([{**failed, "before": True}])
    assert not proof.still_failing([proof.row("tests", "passed", "Tests passed: x", "x")])
