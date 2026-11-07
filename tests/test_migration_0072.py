"""Migration 0072: a conversation's lane and a change's outside_lane go, the rest of both
rows stays; going back puts the two columns back empty."""

import sqlite3

from alembic import command

from tests.test_migration_0002 import _config

AT = "2026-10-25 10:00:00"


def _columns(conn, table):
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def test_the_lane_goes_and_comes_back_empty(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0071")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO conversations (id, title, lane, created_at, updated_at) "
                     "VALUES ('c', 'Talk', 'docs/', ?, ?)", (AT, AT))
        conn.execute(
            "INSERT INTO file_changes (id, run_id, agent_id, path, kind, after_content, "
            "after_sha, status, created_at, outside_lane) "
            "VALUES ('f', 'r', 'a', 'src/x.py', 'create', 'x', 's', 'applied', ?, 1)", (AT,))

    command.upgrade(cfg, "head")

    with sqlite3.connect(db) as conn:
        assert "lane" not in _columns(conn, "conversations")
        assert "outside_lane" not in _columns(conn, "file_changes")
        assert conn.execute("SELECT title FROM conversations").fetchall() == [("Talk",)]
        assert conn.execute("SELECT path FROM file_changes").fetchall() == [("src/x.py",)]

    command.downgrade(cfg, "0071")

    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT title, lane FROM conversations").fetchall() == [
            ("Talk", None)]
        assert conn.execute("SELECT path, outside_lane FROM file_changes").fetchall() == [
            ("src/x.py", 0)]
