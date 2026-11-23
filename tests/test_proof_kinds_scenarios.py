"""Kanıtlı bitiş S5a at a turn's end: under Test and review, what the turn wrote of documents,
diagrams, data and slides is checked with no model (`KindsMixin._proof_kinds`), after the tests and
before the review; a sure problem is a fix round, one count with failing tests (Fix rounds); a kind
switched off, or Tests only, checks nothing of it."""

import pytest

from app.proof_kinds import KINDS_TO_FIX
from tests.fakes import ScriptedExecutor
from tests.test_agent_writes import write
from tests.test_chat_flow import text
from tests.test_proof_end_scenarios import PASS, begin, checked, failing, texts

pytestmark = pytest.mark.no_po  # (the PO's own request would take a scripted step)

NUDGE = KINDS_TO_FIX.split(":")[0]  # "Not the end yet"
GOOD = "# Readme\n\nSee [the guide](docs/guide.md).\n"
BROKEN = "# Readme\n\nSee [the guide](docs/gone.md).\n"


def told(model) -> int:
    """How often the Orchestrator was told of problems in what it wrote, in its last request."""
    return sum(
        str(m.get("content")).startswith("Not the end yet: KOLONİ's checks of what")
        for m in model.calls[-1]
        if m["role"] == "user"
    )


@pytest.fixture
def guide(project_dir):
    (project_dir / "docs").mkdir()
    (project_dir / "docs" / "guide.md").write_text("# Guide\n", encoding="utf-8")
    return project_dir


def test_a_docs_turn_checks_links_and_runs_no_tests(make_client, wait_run, guide):
    executor = ScriptedExecutor([])
    client, model = make_client([write("README.md", GOOD), text("done")], executor=executor)
    cid, run_id = begin(client, guide)
    snap = wait_run(client, cid, run_id)
    assert executor.started == [] and told(model) == 0
    assert texts(snap) == [
        "No tests: only documents, slides, diagrams or data changed",
        "README.md: 1 links, all found",
        "Spelling: not checked",
    ]


def test_a_broken_link_is_one_fix_round_then_said(make_client, wait_run, guide):
    client, model = make_client(
        [write("README.md", BROKEN), text("done"), write("README.md", GOOD, "w2"), text("fixed")],
        executor=ScriptedExecutor([]),
    )
    cid, run_id = begin(client, guide)
    snap = wait_run(client, cid, run_id)
    nudged = [
        str(m["content"])
        for m in model.calls[-1]
        if m["role"] == "user" and str(m["content"]).startswith(NUDGE)
    ]
    assert len(nudged) == 1 and "README.md: link to docs/gone.md not found" in nudged[0]
    assert "README.md: 1 links, all found" in texts(snap)
    assert texts(snap)[-1] == "Sent back to fix: 1 of 2 rounds (1 problem in what it wrote)"


def test_a_text_answer_to_the_nudge_keeps_the_failed_line(make_client, wait_run, guide):
    client, _model = make_client(
        [
            write("README.md", BROKEN),
            text("done"),
            text("The guide moves next week; leave the link."),
        ],
        executor=ScriptedExecutor([]),
    )
    cid, run_id = begin(client, guide)
    rows = [(row["state"], row["text"]) for row in checked(wait_run(client, cid, run_id))]
    assert ("failed", "README.md: link to docs/gone.md not found") in rows, rows


def test_fix_rounds_one_sends_a_kind_back_once(make_client, wait_run, guide):
    client, model = make_client(
        [
            write("README.md", BROKEN),
            text("done"),
            write("README.md", BROKEN + "\nMore.\n", "w2"),
            text("again"),
        ],
        executor=ScriptedExecutor([]),
    )
    cid, run_id = begin(client, guide, fix_rounds=1)
    snap = wait_run(client, cid, run_id)
    assert told(model) == 1  # (the second answer, still broken, is not sent back: the cap)
    assert "README.md: link to docs/gone.md not found" in texts(snap)
    assert texts(snap)[-1] == "Sent back to fix: 1 of 1 rounds (1 problem in what it wrote)"


def test_a_tests_round_and_a_kinds_round_share_the_count(make_client, wait_run, guide):
    executor = ScriptedExecutor([failing(), PASS, PASS])
    client, _model = make_client(
        [
            write("a.py", "x = 1\n"),
            write("README.md", BROKEN, "w2"),
            text("done"),
            write("a.py", "x = 2\n", "w3"),
            text("tests fixed"),
            write("README.md", BROKEN + "\nStill.\n", "w4"),
            text("tried"),
        ],
        executor=executor,
    )
    cid, run_id = begin(client, guide, check_command="python check.py")
    snap = wait_run(client, cid, run_id)
    assert texts(snap)[-1] == (
        "Sent back to fix: 2 of 2 rounds (tests fail; 1 problem in what it wrote)"
    ), texts(snap)


def test_a_switched_off_kind_is_said_not_checked(make_client, wait_run, guide):
    client, model = make_client(
        [write("README.md", BROKEN), text("done")], executor=ScriptedExecutor([])
    )
    cid, run_id = begin(client, guide, check_kinds={"docs": False})
    snap = wait_run(client, cid, run_id)
    assert told(model) == 0
    assert "Not checked: documents switched off for this project" in texts(snap)


def test_mixed_code_and_docs_turn_has_both_lines(make_client, wait_run, guide):
    client, _model = make_client(
        [write("a.py", "x = 1\n"), write("README.md", GOOD, "w2"), text("done")],
        executor=ScriptedExecutor([PASS]),
    )
    cid, run_id = begin(client, guide, check_command="python check.py")
    said = texts(wait_run(client, cid, run_id))
    assert said[0] == "Tests passed: python check.py - 4 passed in 0.1s"
    assert "README.md: 1 links, all found" in said


def test_tests_only_checks_no_kind(make_client, wait_run, guide):
    client, model = make_client(
        [write("README.md", BROKEN), text("done")], executor=ScriptedExecutor([])
    )
    cid, run_id = begin(client, guide, after_change="tests")
    snap = wait_run(client, cid, run_id)
    assert told(model) == 0 and texts(snap) == [
        "No tests: only documents, slides, diagrams or data changed"
    ]


def test_a_kind_the_turn_ended_before_is_said_not_checked(make_client, wait_run, guide):
    # (The tests' nudge ends the pass before the kinds; a text answer then ends the turn.)
    client, _model = make_client(
        [
            write("a.py", "x = 1\n"),
            write("README.md", BROKEN, "w2"),
            text("done"),
            text("I cannot fix the test."),
        ],
        executor=ScriptedExecutor([failing()]),
    )
    cid, run_id = begin(client, guide, check_command="python check.py")
    said = texts(wait_run(client, cid, run_id))
    assert "Not checked: documents - the turn ended before KOLONİ's check" in said, said


def test_a_link_broken_before_the_turn_is_said_and_not_sent_back(make_client, wait_run, guide):
    # (A README the turn only added to: its old broken link is not the turn's to fix.)
    (guide / "README.md").write_text("# Readme\n\n[old](docs/gone.md)\n", encoding="utf-8")
    client, model = make_client(
        [
            write(
                "README.md", "# Readme\n\n[old](docs/gone.md)\n\nSee [the guide](docs/guide.md).\n"
            ),
            text("done"),
        ],
        executor=ScriptedExecutor([]),
    )
    cid, run_id = begin(client, guide)
    rows = [(row["state"], row["text"]) for row in checked(wait_run(client, cid, run_id))]
    assert told(model) == 0
    assert ("note", "README.md: link to docs/gone.md not found - so before this turn") in rows, rows
