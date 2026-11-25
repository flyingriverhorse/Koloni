"""Migration 0185 (0.1.9 §8, one judge): Check what I said first is the judge's box now - on in a
project whose old choice was "judge", off in any other; the old choice is kept as it was. Going
back, the box goes."""

import sqlite3

from alembic import command

from tests.test_migration_0002 import _config
from tests.test_migration_0177 import AT, columns


def test_the_box_is_on_only_where_the_old_choice_was_judge_and_goes_back(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0183")
    with sqlite3.connect(db) as conn:
        for pid, check in (("a", "ask"), ("j", "judge")):
            conn.execute(
                "INSERT INTO projects (id, name, root_path, created_at, full_auto_check) "
                "VALUES (?, ?, ?, ?, ?)",
                (pid, pid, f"C:/{pid}", AT, check),
            )

    command.upgrade(cfg, "0185")
    with sqlite3.connect(db) as conn:
        assert conn.execute(
            "SELECT id, full_auto_check, full_auto_judge, judge_words FROM projects ORDER BY id"
        ).fetchall() == [("a", "ask", 1, 0), ("j", "judge", 1, 1)]

    command.downgrade(cfg, "0183")
    with sqlite3.connect(db) as conn:
        assert "judge_words" not in columns(conn, "projects")
        assert conn.execute("SELECT full_auto_check FROM projects ORDER BY id").fetchall() == [
            ("ask",),
            ("judge",),
        ]
