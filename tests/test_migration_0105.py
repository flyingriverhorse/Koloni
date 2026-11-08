"""Migration 0105 (K-oda-izle): a room from before is one the Lead does not follow; going back
takes the column away."""

import sqlite3

from alembic import command

from tests.test_migration_0002 import _config

AT = "2026-10-28 10:00:00"


def test_a_room_from_before_is_not_followed_by_the_lead(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0104")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO conversations (id, title, created_at, updated_at) "
                     "VALUES ('c', 'c', ?, ?)", (AT, AT))
        conn.execute("INSERT INTO runs (id, conversation_id, status, created_at) "
                     "VALUES ('r', 'c', 'completed', ?)", (AT,))
        conn.execute("INSERT INTO rooms (id, run_id, goal, status, seconds, created_at) "
                     "VALUES ('o', 'r', 'g', 'ended', 0, ?)", (AT,))

    command.upgrade(cfg, "0105")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT lead_follows FROM rooms").fetchall() == [("off",)]

    command.downgrade(cfg, "0104")
    with sqlite3.connect(db) as conn:
        assert "lead_follows" not in {row[1] for row in conn.execute("PRAGMA table_info(rooms)")}
