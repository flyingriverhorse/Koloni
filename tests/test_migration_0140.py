"""Migration 0140 (K-evrim slice 1): a project's measure command - none for one there before, a
column of its own; and back, the rest of the project as it was."""

import sqlite3

from alembic import command

from tests.test_migration_0002 import _config

AT = "2026-11-03 10:00:00"


def _columns(db):
    with sqlite3.connect(db) as conn:
        return [row[1] for row in conn.execute("PRAGMA table_info(projects)")]


def test_a_project_gets_no_measure_command_and_back(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0139")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO projects (id, name, root_path, created_at, check_command) "
                     "VALUES ('p', 'p', 'C:/p', ?, 'pytest -q')", (AT,))
    command.upgrade(cfg, "0140")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT check_command, measure_command FROM projects").fetchall() == [
            ("pytest -q", None)]
        conn.execute("UPDATE projects SET measure_command = 'python measure.py'")
    command.downgrade(cfg, "0139")
    assert "measure_command" not in _columns(db)
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT check_command FROM projects").fetchall() == [("pytest -q",)]
