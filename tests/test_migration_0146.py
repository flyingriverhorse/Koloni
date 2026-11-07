"""Migration 0146 (the user, R185): a new conversation's rooms have no token limit; one from before
keeps the 400000 it has, and going back gives new ones that again."""

import sqlite3

from alembic import command

from tests.test_migration_0002 import _config

AT = "2026-11-04 10:00:00"
ADD = "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, 'c', ?, ?)"


def test_a_new_conversation_has_no_room_token_limit_and_one_from_before_keeps_its_own(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0145")
    with sqlite3.connect(db) as conn:
        conn.execute(ADD, ("old", AT, AT))

    command.upgrade(cfg, "0146")
    with sqlite3.connect(db) as conn:
        conn.execute(ADD, ("new", AT, AT))
        assert conn.execute(
            "SELECT id, room_posts, room_tokens, room_minutes FROM conversations ORDER BY id"
        ).fetchall() == [("new", 40, None, 30), ("old", 40, 400_000, 30)]

    command.downgrade(cfg, "0145")
    with sqlite3.connect(db) as conn:
        conn.execute(ADD, ("back", AT, AT))
        assert conn.execute(
            "SELECT id, room_tokens FROM conversations ORDER BY id"
        ).fetchall() == [("back", 400_000), ("new", None), ("old", 400_000)]
