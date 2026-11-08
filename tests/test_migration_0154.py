"""Migration 0154 (B-414): projects and conversations, old and new, give an agent's room at least
60000 tokens; going back drops it."""

import sqlite3

from alembic import command

from tests.test_migration_0002 import _config

AT = "2026-11-08 10:00:00"
ADD = "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, 'c', ?, ?)"


def test_every_conversation_and_project_gives_a_room_at_least_60000_tokens_and_back(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0153")
    with sqlite3.connect(db) as conn:
        conn.execute(ADD, ("old", AT, AT))

    command.upgrade(cfg, "0154")
    with sqlite3.connect(db) as conn:
        conn.execute(ADD, ("new", AT, AT))
        assert conn.execute("SELECT id, room_min_tokens FROM conversations ORDER BY id").fetchall() == [
            ("new", 60_000), ("old", 60_000)]
        assert ("room_min_tokens",) in [(row[1],) for row in conn.execute("PRAGMA table_info(projects)")]

    command.downgrade(cfg, "0153")
    with sqlite3.connect(db) as conn:
        for table in ("conversations", "projects"):
            assert "room_min_tokens" not in [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
