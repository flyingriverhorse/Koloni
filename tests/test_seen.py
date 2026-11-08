"""Slice 38f-2, beside its acceptance set (`test_archive_scenarios`): the migration, a room
opened in an archived conversation, the Board's word on each conversation's last turn (what
the rail's badge, the toasts and the Conversations list read), and one turn's own usage."""

import sqlite3

from alembic import command

from tests.test_board_scenarios import ORIGIN, board, on_board
from tests.test_chat_flow import text
from tests.test_claim_scenarios import write
from tests.test_copy_scenarios import one
from tests.test_migration_0002 import _config
from tests.test_parallel import until
from tests.test_rooms import room_in
from tests.test_spawn import step
from tests.test_trigger_scenarios import setup
from tests.test_usage_scenarios import began, turn, usage


# (As the acceptance set's own, which skips as a whole until the code is there.)
def listed(client, pid, cid):
    return next(c for c in client.get(f"/api/projects/{pid}/conversations").json() if c["id"] == cid)


def archive(client, cid, archived=True):
    answer = client.patch(f"/api/conversations/{cid}", json={"archived": archived})
    assert answer.status_code == 200, answer.text
    return answer.json()


def test_migration_0047_adds_archived_at_and_takes_it_away(tmp_path):
    cfg = _config(tmp_path / "old.db")
    command.upgrade(cfg, "0047")

    def columns():
        with sqlite3.connect(tmp_path / "old.db") as conn:
            return {row[1] for row in conn.execute("PRAGMA table_info(conversations)")}

    assert "archived_at" in columns()
    command.downgrade(cfg, "0046")
    assert "archived_at" not in columns()


def test_archiving_is_not_activity(make_client, project_dir):
    client, _model, pid, cid = setup(make_client, project_dir, {"Lead": []})
    before = listed(client, pid, cid)["updated_at"]
    assert archive(client, cid)["updated_at"] == before
    assert archive(client, cid, archived=False)["updated_at"] == before


def test_a_room_the_user_opens_brings_its_conversation_back(make_client, wait_run, project_dir):
    client, _model, cid, run_id, _room = room_in(
        make_client, project_dir, {"Coder": [text("ok")], "Reviewer": [text("ok")]},
        before=lambda client: archive(client, cid_of(client)),
    )
    wait_run(client, cid, run_id, timeout=20.0)
    assert client.get(f"/api/conversations/{cid}").json()["conversation"]["archived_at"] is None


def cid_of(client):
    pid = client.get("/api/projects").json()[0]["id"]
    return client.get(f"/api/projects/{pid}/conversations").json()[0]["id"]


def test_the_board_says_each_conversations_last_turn(make_client, wait_run, project_dir):
    client, _model, pid, cid = began(make_client, project_dir, [text("a"), text("b")])
    assert on_board(board(client, pid), cid)["turn"] is None          # none yet
    turn(client, wait_run, cid)
    last = turn(client, wait_run, cid)
    told = on_board(board(client, pid), cid)["turn"]
    assert (told["id"], told["status"]) == (last["id"], "completed")
    assert told["ended_at"] is not None


def test_one_turns_usage_and_cost(make_client, wait_run, project_dir):
    client, _model, pid, cid = began(make_client, project_dir, [text("a", 1_000_000, 0),
                                                                 text("b", 3_000_000, 0)])
    turn(client, wait_run, cid)
    second = turn(client, wait_run, cid)
    assert client.put("/api/prices", json={
        "model_id": "fake-model", "input": 2, "output": 2, "currency": "USD"}).status_code == 200
    (row,) = usage(client, run_id=second["id"])["by_model"]
    assert (row["runs"], row["input_tokens"]) == (1, 3_000_000)
    assert row["cost"] == {"amount": 6.0, "currency": "USD"}
    assert usage(client, run_id="nope")["by_model"] == []


def test_changes_that_wait_are_one_thing_on_the_board_with_nobody_asking_besides(
    make_client, wait_run, project_dir
):
    # (What the badge counts: an agent that asks, plus each set of changes - never one twice.)
    client, _model, cid, run_id = one(
        make_client, project_dir, [step(write("a.txt", "A")), text("A done")],
        permission_mode="ask")
    snap = until(client, cid, lambda s: [m["status"] for m in s["merges"]] == ["pending"])
    told = on_board(board(client, snap["conversation"]["project_id"]), cid)
    assert told["merges_pending"] == 1
    assert [a["name"] for a in told["agents"] if a["status"] == "waiting_approval"] == []
    client.headers["Origin"] = ORIGIN
    assert client.post(f"/api/merges/{snap['merges'][0]['id']}/reject").status_code == 200
    wait_run(client, cid, run_id)


def test_only_a_message_from_the_apps_own_page_brings_a_conversation_back(
    make_client, wait_run, project_dir
):
    client, _model, pid, cid = setup(make_client, project_dir, {"Lead": [text("one"), text("two")]})
    archive(client, cid)
    del client.headers["Origin"]  # (a command an agent runs against the app's address)
    sent = client.post(f"/api/conversations/{cid}/messages", json={"content": "hi"})
    assert sent.status_code == 201, sent.text
    wait_run(client, cid, sent.json()["run"]["id"])
    assert listed(client, pid, cid)["archived_at"] is not None
    client.headers["Origin"] = ORIGIN
    sent = client.post(f"/api/conversations/{cid}/messages", json={"content": "hi"})
    wait_run(client, cid, sent.json()["run"]["id"])
    assert listed(client, pid, cid)["archived_at"] is None
