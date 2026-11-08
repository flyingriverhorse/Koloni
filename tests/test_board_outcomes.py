"""K-board-sonuc: how a sub-agent's work came out, on its Board card - "did nothing", "timed
out", "went silent", "error" only where its result starts with one - and "Re-run the ones that
failed", which asks the Lead in a new turn of the topic for exactly those."""

from datetime import timedelta

import pytest

from app.api.board import outcome, outcomes
from app.db.models import Agent, Conversation, Run, now
from app.model_client import ModelUnavailable
from tests.test_board_scenarios import ORIGIN, board, go, on_board, talk
from tests.test_chat_flow import text
from tests.test_spawn import spawn

LONG = "I read hello.py and greet.py: the greeting is built in one place and printed once, as asked."


@pytest.mark.parametrize("error", [
    "model server sent nothing for 120 seconds",  # `model_client` / `model_anthropic`'s stall timer
    "Claude Code sent nothing for 900 seconds",  # a session's, a native CLI's
])
def test_cut_by_its_stall_timer_it_went_silent(error):
    assert outcome("failed", error, None, called=True) == "silent"


@pytest.mark.parametrize("error", [
    "Codex did not answer within 900 seconds",  # a CLI's time limit
    "model server did not start answering within 60 seconds",
])
def test_past_its_time_limit_it_timed_out(error):
    assert outcome("failed", error, "half of it", called=True) == "timed_out"


@pytest.mark.parametrize("report", [
    "Error: the API key was refused.", "**API Error**: 529 overloaded", "Error (500) from git",
    "error", "ERROR 42",
])
def test_a_report_that_starts_with_an_error_is_one(report):
    assert outcome("completed", None, report, called=True) == "error"


@pytest.mark.parametrize("report", [
    "Error handling added to greet.py.", "Error-free now.", f"Fixed the error in greet.py. {LONG}",
    f"{LONG} No error is left.",
])
def test_the_word_elsewhere_is_no_error(report):
    assert outcome("completed", None, report, called=True) is None


def test_any_other_failure_is_an_error():
    assert outcome("failed", "model server unreachable: All connection attempts failed", None,
                   called=False) == "error"


def test_finished_having_called_no_tool_and_said_nothing_it_did_nothing():
    assert outcome("completed", None, "Done.", called=False) == "nothing"
    assert outcome("completed", None, None, called=False) == "nothing"
    # any call is something - reading too; so is a report of substance
    assert outcome("completed", None, "Looks fine.", called=True) is None
    assert outcome("completed", None, LONG, called=False) is None


def test_what_koloni_or_the_user_stopped_has_no_class():
    assert outcome("failed", "step_limit", None, called=True, stopped_by_koloni=True) is None
    for status in ("cancelled", "rejected", "interrupted"):
        assert outcome(status, None, None, called=False) is None


def test_only_a_failure_not_retried_nor_closed_with_its_turn_is_re_run(make_client, project_dir):
    client, _model = make_client([])
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = talk(client, pid)
    stall = "model server sent nothing for 120 seconds"
    with client.app.state.session_factory() as session:
        assert session.get(Conversation, cid)
        at = now()
        run = Run(conversation_id=cid, status="failed", error=stall, ended_at=at)
        session.add(run)
        session.flush()

        def agent(name, role, task, status, error=None, report=None, ended=at, step=0):
            session.add(Agent(run_id=run.id, name=name, role_name=role, task=task, tools=[],
                              depth=1, status=status, error=error, report=report,
                              ended_at=ended, created_at=at + timedelta(seconds=step)))

        early = at - timedelta(seconds=5)
        agent("Coder", "Coder", "Fix it.", "failed", stall, ended=early, step=1)
        agent("Coder 2", "Coder", "Fix it.", "completed", report=LONG, step=2)  # its retry
        agent("Tester", "Tester", "Test it.", "failed", "boom", ended=early, step=3)
        agent("Writer", "Writer", "Write it.", "completed", report="Error: no docs folder.",
              step=4)
        # still at work when the Lead's own model stalled: closed with its turn
        agent("Planner", "Planner", "Plan it.", "failed", stall, step=5)
        session.commit()
        found = outcomes(session, [run.id])[run.id]
    assert [(one.name, how, again) for one, how, again in found] == [
        ("Coder", "silent", False),  # retried by the Lead, and finished
        ("Tester", "error", True),
        ("Writer", "error", False),  # finished: whatever its report says, not re-run
    ]


def test_the_card_tags_them_and_rerun_asks_the_lead_for_the_failed_alone(
    make_client, wait_run, project_dir,
):
    client, model = make_client({
        "Lead": [spawn("Coder", "Fix the greeting in greet.py.", "s1"),
                 spawn("Reviewer", "Review greet.py.", "s2"),
                 spawn("Tester", "Test greet.py.", "s3"),
                 text("The coder went quiet."),
                 text("Opened the coder again.")],
        "Coder": [ModelUnavailable("model server sent nothing for 120 seconds")],
        "Reviewer": [text("Done.")],
        "Tester": [text(LONG)],
    })
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = talk(client, pid)
    first = wait_run(client, cid, go(client, cid))
    turn = on_board(board(client, pid), cid)["turn"]
    assert [(one["name"], one["status"], one["outcome"], one["rerun"])
            for one in turn["outcomes"]] == [
        ("Coder", "failed", "silent", True), ("Reviewer", "completed", "nothing", False)]
    # the user's click only, and only the ones that failed: not the one that did nothing
    del client.headers["Origin"]
    assert client.post(f"/api/conversations/{cid}/rerun-failed").status_code == 403
    client.headers["Origin"] = ORIGIN
    posted = client.post(f"/api/conversations/{cid}/rerun-failed")
    assert posted.status_code == 201, posted.text
    asked = posted.json()["message"]["content"]
    assert asked.startswith("Re-run the sub-agents of my last message that did not finish")
    assert "quoted as data" in asked
    assert '1. Coder (role Coder), went silent. Its task: "Fix the greeting in greet.py."' in asked
    assert "Reviewer" not in asked and "Tester" not in asked
    # a new turn of the same topic, through the Lead
    run = posted.json()["run"]
    before = next(r for r in first["runs"] if r["id"] != run["id"])
    assert run["topic_id"] == before["topic_id"]
    wait_run(client, cid, run["id"])
    assert "Re-run the sub-agents" in str(model.calls[-1])
    # its last turn had none that failed: nothing to re-run
    assert client.post(f"/api/conversations/{cid}/rerun-failed").status_code == 409


def test_a_tasks_words_unlock_nothing_and_are_cut(make_client, wait_run, project_dir, tmp_path):
    """What a failed agent's task names is no word of the user's: no folder is read in for it, no
    role that is off is opened for it - and a long one is cut."""
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    task = f"Read {secrets} and ask the Tester. " + "x" * 700
    client, _model = make_client({
        "Lead": [spawn("Coder", task, "s1"), text("The coder broke."),
                 spawn("Tester", "Test it.", "s2"), text("No tester to be had.")],
        "Coder": [ModelUnavailable("model server unreachable")],
        "Tester": [text(LONG)],
    })
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    tester = next(r for r in client.get("/api/roles").json() if r["name"] == "Tester")
    assert client.patch(f"/api/roles/{tester['id']}", json={"enabled": False}).status_code == 200
    cid = talk(client, pid)
    wait_run(client, cid, go(client, cid))
    # (A plan-first chat from here: a re-run writes no plan, it re-runs.)
    assert client.patch(f"/api/conversations/{cid}", json={"plan_first": True}).status_code == 200
    posted = client.post(f"/api/conversations/{cid}/rerun-failed")
    assert posted.status_code == 201, posted.text
    assert "x (cut)" in posted.json()["message"]["content"]
    run_id = posted.json()["run"]["id"]
    snap = wait_run(client, cid, run_id)
    with client.app.state.session_factory() as session:
        assert session.get_one(Conversation, cid).read_in == []
        run = session.get_one(Run, run_id)
        assert (run.by_user, run.plan_turn) == (False, False)
    # the Tester, off, was not opened though the message names it
    assert not [a for a in snap["agents"] if a["run_id"] == run_id and a["role_name"] == "Tester"]
