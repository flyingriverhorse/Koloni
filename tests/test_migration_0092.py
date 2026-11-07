"""Migration 0092: a room from before is not paused (29c), and a conversation from before asks
before a page's scripts run (K-39-betik); going back takes both columns away."""

import sqlite3

from alembic import command

from tests.test_migration_0002 import _config

AT = "2026-10-27 10:00:00"


def test_rooms_and_conversations_from_before_are_not_paused_and_ask(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0091")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO conversations (id, title, created_at, updated_at) "
                     "VALUES ('c', 'c', ?, ?)", (AT, AT))
        conn.execute("INSERT INTO runs (id, conversation_id, status, created_at) "
                     "VALUES ('r', 'c', 'completed', ?)", (AT,))
        conn.execute("INSERT INTO rooms (id, run_id, goal, status, seconds, created_at) "
                     "VALUES ('o', 'r', 'g', 'ended', 0, ?)", (AT,))

    command.upgrade(cfg, "0092")

    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT paused FROM rooms").fetchall() == [(0,)]
        assert conn.execute("SELECT page_scripts FROM conversations").fetchall() == [(0,)]

    command.downgrade(cfg, "0091")

    with sqlite3.connect(db) as conn:
        assert "paused" not in {row[1] for row in conn.execute("PRAGMA table_info(rooms)")}
        assert "page_scripts" not in {
            row[1] for row in conn.execute("PRAGMA table_info(conversations)")}
    command.upgrade(cfg, "0092")
