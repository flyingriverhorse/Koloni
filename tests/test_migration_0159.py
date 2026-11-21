"""Migration 0159 (disposable deletes): every project, old and new, asks about a delete as before
until the user allows disposable ones, and a command can keep what of it was disposable; going
back drops both."""

import sqlite3

from alembic import command

from tests.test_migration_0002 import _config

AT = "2026-11-21 10:00:00"


def test_every_project_asks_as_before_and_a_command_keeps_what_was_disposable_and_back(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0158")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO projects (id, name, root_path, created_at) "
                     "VALUES ('p', 'p', 'C:/p', ?)", (AT,))

    command.upgrade(cfg, "0159")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT disposable_deletes FROM projects").fetchall() == [(0,)]
        assert "disposable" in [row[1] for row in conn.execute("PRAGMA table_info(commands)")]

    command.downgrade(cfg, "0158")
    with sqlite3.connect(db) as conn:
        assert "disposable_deletes" not in [
            row[1] for row in conn.execute("PRAGMA table_info(projects)")]
        assert "disposable" not in [
            row[1] for row in conn.execute("PRAGMA table_info(commands)")]
