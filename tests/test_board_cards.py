"""Slice 60b's review round: what a card of the Board says of a conversation's last turn."""

from tests.conftest import Gate
from tests.test_board_scenarios import ORIGIN, board, go, on_board, project, talk
from tests.test_chat_flow import text
from tests.test_claim_scenarios import write
from tests.test_parallel import until
from tests.test_spawn import call, spawn, step


def test_a_turn_of_two_agents_counts_both_and_all_their_tokens(make_client, wait_run, project_dir):
    client, _model = make_client({
        "Lead": [spawn("Reviewer", "Review hello.py"), text("The reviewer is happy.", i=100, o=11)],
        "Reviewer": [text("No problems found.", i=40, o=7)],
    })
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = talk(client, pid)
    snap = wait_run(client, cid, go(client, cid))
    turn = on_board(board(client, pid), cid)["turn"]
    assert turn["agents"] == 2
    # as the chat's turn summary adds it up: the Lead's last prompt and all it wrote, and the Reviewer's
    assert turn["tokens"] == 100 + (2 + 11) + 40 + 7
    lead = next(a for a in snap["agents"] if a["depth"] == 0)
    assert (turn["provider_name"], turn["model_id"]) == (lead["provider_name"], lead["model_id"]) == ("Local", "fake-model")
    assert turn["plan_waits"] is False


def test_a_message_taken_back_before_its_turn_started_is_not_the_last_turn(make_client, wait_run, project_dir):
    first = Gate()
    client, _model, pid = project(make_client, project_dir, [first.step(text("A done"))])
    cid = talk(client, pid)
    ran = go(client, cid)
    first.wait_partial()
    queued = go(client, cid)
    assert client.post(f"/api/runs/{queued}/cancel").status_code == 202
    assert on_board(board(client, pid), cid)["turn"]["id"] == ran
    first.release()
    wait_run(client, cid, ran)
    assert on_board(board(client, pid), cid)["turn"]["id"] == ran


def test_a_plan_that_waits_for_a_yes_is_said_so_until_it_is_answered(make_client, wait_run, project_dir):
    client, _model, pid = project(make_client, project_dir, [text("PLAN: 1. Read hello.py.")])
    client.headers["Origin"] = ORIGIN
    cid = talk(client, pid, plan_first=True)
    run_id = go(client, cid)
    wait_run(client, cid, run_id)
    assert on_board(board(client, pid), cid)["turn"]["plan_waits"] is True
    assert client.post(f"/api/runs/{run_id}/plan/reject", json={}).status_code == 200
    assert on_board(board(client, pid), cid)["turn"]["plan_waits"] is False


def test_a_card_says_a_change_to_approve_apart_from_a_question(make_client, wait_run, project_dir):
    """K-board-ayrim: what an agent asks is counted by kind, from what it put before the user."""
    client, _model, pid = project(make_client, project_dir, [
        step(call("ask_user", {"question": "Which one?"}, "q1")),
        step(write("a.txt", "A")),
        text("done"),
    ])
    cid = talk(client, pid, permission_mode="ask", lead_hands_code=False)
    run_id = go(client, cid)
    snap = until(client, cid, lambda s: [q["status"] for q in s["questions"]] == ["pending"])
    (lead,) = on_board(board(client, pid), cid)["agents"]
    assert (lead["status"], lead["questions"], lead["changes_to_approve"]) == ("waiting_approval", 1, 0)
    answered = client.post(f"/api/questions/{snap['questions'][0]['id']}/answer", json={"answer": "yes"})
    assert answered.status_code == 200
    snap = until(client, cid, lambda s: [c["status"] for c in s["file_changes"]] == ["proposed"])
    (lead,) = on_board(board(client, pid), cid)["agents"]
    assert (lead["status"], lead["questions"], lead["changes_to_approve"]) == ("waiting_approval", 0, 1)
    assert client.post(f"/api/file-changes/{snap['file_changes'][0]['id']}/approve").status_code == 200
    wait_run(client, cid, run_id)
    assert on_board(board(client, pid), cid)["agents"] == []
