"""Migration 0156 (K-yargıç): every project, old and new, asks about a harmful-looking command at
Full auto as before, and a command can keep what the check of the user's words said of it;
going back drops both."""

import sqlite3

from alembic import command

from tests.test_migration_0002 import _config

AT = "2026-11-21 10:00:00"


def test_every_project_asks_as_before_and_a_command_keeps_what_the_check_said_and_back(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0155")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO projects (id, name, root_path, created_at) "
                     "VALUES ('p', 'p', 'C:/p', ?)", (AT,))

    command.upgrade(cfg, "0156")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT full_auto_check FROM projects").fetchall() == [("ask",)]
        assert "judged" in [row[1] for row in conn.execute("PRAGMA table_info(commands)")]

    command.downgrade(cfg, "0155")
    with sqlite3.connect(db) as conn:
        assert "full_auto_check" not in [
            row[1] for row in conn.execute("PRAGMA table_info(projects)")]
        assert "judged" not in [row[1] for row in conn.execute("PRAGMA table_info(commands)")]
