"""k-canli-016 (the user's decision): Fix rounds "Until it passes", the default - failing work
goes back while each round makes progress; it stops where a round changes nothing, at the
ceiling, or at the turn's token limit, and says why. A number of rounds, 1 to 10, still holds."""

import pytest

from app import proof
from tests.fakes import Script, ScriptedExecutor
from tests.test_agent_writes import write
from tests.test_chat_flow import text
from tests.test_proof_end_scenarios import OWN, PASS, begin, texts

pytestmark = pytest.mark.no_po

CHECK = "python check.py"


def said(snap):
    """The Checked rows but the review's notes ("No review: a small change …")."""
    return [one for one in texts(snap) if not one.startswith("No review")]


def fails(many):
    """A test run with `many` failing - read by its count (no ids of a runner KOLONİ knows)."""
    return Script([f"F...\n{many} failed, 3 passed\n"], exit_code=1)


def lead(rounds):
    """The Lead's work and an answer, then a fix and an answer `rounds` times."""
    steps = [write("a.py", "x = 0\n"), text("done")]
    for n in range(1, rounds + 1):
        steps += [write("a.py", f"x = {n}\n", f"w{n}"), text(f"fixed {n}")]
    return steps


@pytest.mark.parametrize("given", [None, "until"])
def test_until_it_passes_is_the_default_and_null_or_until_sets_it(client, project_dir, given):
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    assert client.get(f"/api/projects/{pid}").json()["fix_rounds"] is None  # (a new project)
    assert client.patch(f"/api/projects/{pid}", json={"fix_rounds": 3},
                        headers=OWN).json()["fix_rounds"] == 3
    assert client.patch(f"/api/projects/{pid}", json={"fix_rounds": given},
                        headers=OWN).json()["fix_rounds"] is None
    # (left out: kept)
    assert client.patch(f"/api/projects/{pid}", json={"check_command": CHECK},
                        headers=OWN).json()["fix_rounds"] is None


@pytest.mark.parametrize(("rounds", "status"), [(1, 200), (10, 200), (0, 422), (11, 422),
                                                ("twice", 422)])
def test_a_projects_fix_rounds_are_until_or_one_to_ten(client, project_dir, rounds, status):
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    assert client.patch(f"/api/projects/{pid}", json={"fix_rounds": rounds},
                        headers=OWN).status_code == status


def test_while_each_round_makes_progress_it_goes_on_past_two(make_client, wait_run,
                                                              project_dir):
    executor = ScriptedExecutor([fails(3), fails(2), fails(1), PASS])
    client, _model = make_client(lead(3), executor=executor)
    cid, run_id = begin(client, project_dir, check_command=CHECK, fix_rounds="until")
    rows = said(wait_run(client, cid, run_id))
    assert len(executor.started) == 4
    assert rows == ["Tests passed: python check.py - 4 passed in 0.1s",
                    "Sent back to fix: round 3 (until it passes, 3 failing → 0)"], rows


def test_a_round_that_changed_nothing_stops_the_rounds_and_says_so(make_client, wait_run,
                                                                   project_dir):
    executor = ScriptedExecutor([fails(2), fails(2)])
    client, _model = make_client(lead(1), executor=executor)
    cid, run_id = begin(client, project_dir, check_command=CHECK, fix_rounds="until",
                        stronger_model=False)
    rows = said(wait_run(client, cid, run_id))
    assert len(executor.started) == 2
    assert rows[1:] == ["Sent back to fix: round 1 (until it passes, 2 failing → 2)",
                        proof.STOPPED_AFTER.format(n=1, why=proof.NO_PROGRESS)], rows


def test_the_ceiling_stops_a_model_that_keeps_making_progress(make_client, wait_run,
                                                              project_dir, monkeypatch):
    # (a model that "makes progress" forever: bounded by the ceiling - 20, 3 here)
    monkeypatch.setattr(proof, "UNTIL_CEILING", 3)
    executor = ScriptedExecutor([fails(9), fails(8), fails(7), fails(6)])
    client, _model = make_client(lead(3), executor=executor)
    cid, run_id = begin(client, project_dir, check_command=CHECK, fix_rounds="until",
                        stronger_model=False)
    rows = said(wait_run(client, cid, run_id))
    assert len(executor.started) == 4
    assert rows[1:] == ["Sent back to fix: round 3 (until it passes, 9 failing → 6)",
                        proof.STOPPED_AFTER.format(n=3, why=proof.AT_CEILING.format(most=3))]


def test_the_turns_token_limit_stops_the_rounds(make_client, wait_run, project_dir):
    # (a write is 2 tokens, an answer 8: 10 at the first end, 20 at the second - past 15)
    executor = ScriptedExecutor([fails(3), fails(2), PASS])
    client, _model = make_client(lead(2), executor=executor)
    cid, run_id = begin(client, project_dir, check_command=CHECK, fix_rounds="until",
                        stronger_model=False, turn_token_limit=15)
    rows = said(wait_run(client, cid, run_id))
    assert len(executor.started) == 2
    assert rows[1:] == ["Sent back to fix: round 1 (until it passes, 3 failing → 2)",
                        proof.STOPPED_AFTER.format(n=1, why=proof.TOKEN_LIMIT)], rows


def test_a_number_of_rounds_still_holds(make_client, wait_run, project_dir):
    executor = ScriptedExecutor([fails(3), fails(2), fails(1)])
    client, _model = make_client(lead(2), executor=executor)
    cid, run_id = begin(client, project_dir, check_command=CHECK, fix_rounds=2,
                        stronger_model=False)
    rows = said(wait_run(client, cid, run_id))
    assert rows[1:] == ["Sent back to fix: 2 of 2 rounds",
                        proof.STILL_FAILING.format(most=2)], rows


def test_a_hold_put_another_way_on_the_same_file_is_no_progress(make_client, wait_run,
                                                                project_dir):
    # (Findings are a model's words: by who found them and the file each names, counted - a
    # Reviewer that rewords the same finding each round makes no progress.)
    from app.agent import review_mixin
    from tests.test_proof_review_scenarios import BIG, hold
    executor = ScriptedExecutor([PASS, PASS])
    client, _model = make_client({
        "Lead": [write("a.py", BIG), text("done"), write("a.py", BIG + "y = 1\n", "w2"),
                 text("fixed")],
        "Reviewer": [hold("a.py:3 divides by zero")],
        "Reviewer 2": [hold("a.py:3 still divides by zero, see the loop")]}, executor=executor)
    cid, run_id = begin(client, project_dir, check_command=CHECK, fix_rounds="until",
                        stronger_model=False)
    rows = said(wait_run(client, cid, run_id))
    assert len(executor.started) == 2, rows
    assert review_mixin.HELD_STOPPED.format(n=1, why=proof.NO_PROGRESS) in rows, rows
    assert "Sent back to fix: round 1 (until it passes, 1 failing → 1)" in rows, rows
    assert not any(one.startswith("Stopped after") for one in rows), rows  # (the hold says it)


def test_each_kind_is_held_to_its_own_last_round():
    # (Tests, then a review, then the tests again with the same failures: no progress for the
    # tests - the review's round between is no progress of theirs.)
    from types import SimpleNamespace

    from app.agent import AgentRunner
    from app.agent.proof_mixin import Proof
    stub = SimpleNamespace(_over_limits=lambda _ctx: None)
    stub._no_round = lambda ctx, held, kind, failing: AgentRunner._no_round(
        stub, ctx, held, kind, failing)
    held = Proof(most=proof.UNTIL_CEILING, until_passes=True)

    def back(kind, *failing):
        return AgentRunner._round_left(stub, None, held, kind, frozenset(failing), kind)
    assert back("tests", "t1", "t2") and back("review", "Reviewer | a.py #0")
    assert back("tests", "t1")  # (one fixed: progress)
    assert not back("tests", "t1") and held.halted == proof.NO_PROGRESS and held.rounds == 3
    assert not back("review", "Reviewer | b.py #0")  # (stopped: it stays stopped)


@pytest.mark.parametrize("given", [None, "until", 7])
def test_only_the_apps_own_page_changes_fix_rounds(client, project_dir, given):
    # (review of k-canli-016: an explicit null slipped past the own-page check - an agent's
    # command against the app's address turned a project's 1 round into Until it passes)
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    assert client.patch(f"/api/projects/{pid}", json={"fix_rounds": 1},
                        headers=OWN).status_code == 200
    assert client.patch(f"/api/projects/{pid}", json={"fix_rounds": given}).status_code == 403
    assert client.get(f"/api/projects/{pid}").json()["fix_rounds"] == 1


def test_failures_that_take_turns_are_no_progress():
    # (review of k-canli-016: A, B, A counted as progress every round - up to the ceiling)
    from types import SimpleNamespace

    from app.agent import AgentRunner
    from app.agent.proof_mixin import Proof
    stub = SimpleNamespace(_over_limits=lambda _ctx: None)
    stub._no_round = lambda ctx, held, kind, failing: AgentRunner._no_round(
        stub, ctx, held, kind, failing)
    held = Proof(most=proof.UNTIL_CEILING, until_passes=True)

    def back(*failing):
        return AgentRunner._round_left(stub, None, held, "tests", frozenset(failing), "tests")
    assert back("t_a") and back("t_b")
    assert not back("t_a") and held.halted == proof.NO_PROGRESS and held.rounds == 2
