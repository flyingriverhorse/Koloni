"""Migration 0086 (batch-18, K-devret): slice 48's on / off becomes who changes the files - on is
"delegates", off "itself" - and a folder's new chats start with "delegates"; going back, only
"delegates" is on."""

import sqlite3

from alembic import command

from tests.test_migration_0002 import _config

AT = "2026-10-26 10:00:00"


def test_on_delegates_off_writes_itself_and_back(tmp_path):
    db = tmp_path / "fresh.db"
    cfg = _config(db)
    command.upgrade(cfg, "0085")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO projects (id, name, root_path, created_at) "
                     "VALUES ('p', 'p', 'C:/p', ?)", (AT,))
        for cid, on in (("on", 1), ("off", 0)):
            conn.execute("INSERT INTO conversations (id, title, lead_hands_code, created_at, "
                         "updated_at) VALUES (?, 't', ?, ?, ?)", (cid, on, AT, AT))

    command.upgrade(cfg, "head")

    with sqlite3.connect(db) as conn:
        assert dict(conn.execute("SELECT id, lead_work FROM conversations")) == {
            "on": "delegates", "off": "itself"}
        assert conn.execute("SELECT lead_work FROM projects").fetchone() == ("delegates",)
        conn.execute("UPDATE conversations SET lead_work = 'decides' WHERE id = 'on'")

    command.downgrade(cfg, "0085")

    with sqlite3.connect(db) as conn:
        # (deciding, the Lead had its write tools: back, it writes itself)
        assert dict(conn.execute("SELECT id, lead_hands_code FROM conversations")) == {
            "on": 0, "off": 0}
