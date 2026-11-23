"""Migration 0168 (a project's CI commands, S8): none offered or approved at first; going back
drops it."""

import sqlite3

from alembic import command

from tests.test_migration_0002 import _config

AT = "2026-11-23 12:00:00"


def test_every_project_starts_with_no_ci_commands_and_back(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0165")
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO projects (id, name, root_path, created_at) VALUES ('p', 'p', 'C:/p', ?)",
            (AT,),
        )
    command.upgrade(cfg, "0168")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT ci_commands FROM projects").fetchall() == [(None,)]
    command.downgrade(cfg, "0165")
    with sqlite3.connect(db) as conn:
        assert "ci_commands" not in [row[1] for row in conn.execute("PRAGMA table_info(projects)")]
