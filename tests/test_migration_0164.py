"""Migration 0164 (a chat's Check after a change, S10): every chat starts on the project's
(null); going back drops it."""

import sqlite3

from alembic import command

from tests.test_migration_0002 import _config

AT = "2026-11-22 18:00:00"


def test_every_chat_starts_on_the_projects_and_back(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0163")
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO conversations (id, title, created_at, updated_at) VALUES ('c', 'c', ?, ?)",
            (AT, AT),
        )
    command.upgrade(cfg, "0164")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT after_change FROM conversations").fetchall() == [(None,)]
        conn.execute("UPDATE conversations SET after_change = 'off'")
    command.downgrade(cfg, "0163")
    with sqlite3.connect(db) as conn:
        names = [row[1] for row in conn.execute("PRAGMA table_info(conversations)")]
        assert "after_change" not in names
