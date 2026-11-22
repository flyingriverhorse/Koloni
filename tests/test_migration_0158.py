"""Migration 0158 (☾ Away): a To-do task keeps the chat it was proposed in, an away run what was
spent before its Go away; a new project lets the Orchestrator decide a waiting card after 5
minutes, one from before keeps what it had, and a chat's own (a plain chat's) stays "waits". Going back drops both and the old defaults return."""

import sqlite3

from alembic import command

from tests.test_migration_0002 import _config

AT = "2026-11-21 10:00:00"
PROJECT = "INSERT INTO projects (id, name, root_path, created_at) VALUES (?, ?, ?, ?)"
CHAT = "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, 'c', ?, ?)"
AWAY = "SELECT when_away, away_minutes FROM {} ORDER BY id"


def test_old_rows_keep_their_away_setting_new_ones_decide_after_5_minutes_and_back(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0156")
    with sqlite3.connect(db) as conn:
        conn.execute(PROJECT, ("a", "old", "C:/a", AT))
        conn.execute(CHAT, ("a", AT, AT))

    command.upgrade(cfg, "0158")
    with sqlite3.connect(db) as conn:
        conn.execute(PROJECT, ("b", "new", "C:/b", AT))
        conn.execute(CHAT, ("b", AT, AT))
        assert conn.execute(AWAY.format("projects")).fetchall() == [("waits", 10), ("lead", 5)]
        # (a chat with no folder has no way to change it: everything waits there, as before)
        assert conn.execute(AWAY.format("conversations")).fetchall() == [("waits", 10)] * 2
        assert "proposed_in" in [row[1] for row in conn.execute("PRAGMA table_info(backlog_tasks)")]
        assert "spent_before" in [row[1] for row in conn.execute("PRAGMA table_info(away_runs)")]

    command.downgrade(cfg, "0156")
    with sqlite3.connect(db) as conn:
        conn.execute(PROJECT, ("c", "back", "C:/c", AT))
        assert conn.execute(AWAY.format("projects")).fetchall()[-1] == ("waits", 10)
        assert "proposed_in" not in [
            row[1] for row in conn.execute("PRAGMA table_info(backlog_tasks)")]
        assert "spent_before" not in [
            row[1] for row in conn.execute("PRAGMA table_info(away_runs)")]
