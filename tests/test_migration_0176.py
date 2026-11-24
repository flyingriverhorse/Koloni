"""Migration 0176 (a project's longest command): every project, old and new, keeps the 10 minutes
it had until the user raises them; going back drops the setting."""

import sqlite3

from alembic import command

from tests.test_migration_0002 import _config

AT = "2026-11-24 10:00:00"


def test_every_project_keeps_ten_minutes_and_back(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0175")
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO projects (id, name, root_path, created_at) VALUES ('p', 'p', 'C:/p', ?)",
            (AT,),
        )

    command.upgrade(cfg, "0176")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT longest_command FROM projects").fetchall() == [(10,)]

    command.downgrade(cfg, "0175")
    with sqlite3.connect(db) as conn:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(projects)")]
        assert "longest_command" not in columns
