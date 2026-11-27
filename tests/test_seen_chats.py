"""herdr's "done, not seen" (28 Nov 2026): a chat whose last turn ended - done, failed or stopped -
after its page last had it on screen is said so on the Board (Chats, Now). Opening it - its page
saying it looks at it - makes it seen; a turn that ends while it is looked at stays seen."""

import sqlite3

from alembic import command

from tests.test_chat_flow import text
from tests.test_looking import OWN, opened
from tests.test_migration_0002 import _config
from tests.test_migration_0177 import AT, columns


def chat(client, project_dir):
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    return pid, cid


def turn(client, cid, wait_run):
    run = client.post(f"/api/conversations/{cid}/messages", json={"content": "go"}, headers=OWN)
    return wait_run(client, cid, run.json()["run"]["id"])


def unseen(client, pid, cid):
    board = client.get(f"/api/projects/{pid}/board").json()
    return next(c for c in board["conversations"] if c["conversation_id"] == cid)["unseen"]


def test_a_turn_that_ended_out_of_sight_is_not_seen_until_its_chat_is_looked_at(
    make_client, wait_run, project_dir
):
    client, _model = make_client([text("one"), text("two"), text("three")])
    pid, cid = chat(client, project_dir)
    assert not unseen(client, pid, cid)  # (no turn yet)
    turn(client, cid, wait_run)  # (nobody has it open)
    assert unseen(client, pid, cid)
    looked = {"client": "tab-1", "looking": True}
    assert (
        client.post(f"/api/conversations/{cid}/looking", json=looked, headers=OWN).status_code
        == 204
    )
    assert not unseen(client, pid, cid)
    hidden = opened(client.app.state.bus, cid, "tab-1", looking=False)  # (open, its tab hidden)
    turn(client, cid, wait_run)
    assert unseen(client, pid, cid)
    hidden.looking = True  # (on screen as its next turn ends: seen as it ends)
    turn(client, cid, wait_run)
    assert not unseen(client, pid, cid)
    away = {"client": "tab-1", "looking": False}  # (saying it is not looked at sees nothing)
    client.post(f"/api/conversations/{cid}/looking", json=away, headers=OWN)
    assert not unseen(client, pid, cid)


def test_every_chat_there_is_counts_as_seen_as_the_column_comes(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0197")
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO conversations (id, title, created_at, updated_at) VALUES ('c', 't', ?, ?)",
            (AT, AT),
        )
    command.upgrade(cfg, "0198")
    with sqlite3.connect(db) as conn:
        (seen,) = conn.execute("SELECT seen_at FROM conversations").fetchone()
        assert seen is not None and seen > AT
    command.downgrade(cfg, "0197")
    with sqlite3.connect(db) as conn:
        assert "seen_at" not in columns(conn, "conversations")
