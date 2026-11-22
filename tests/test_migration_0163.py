"""Migration 0163 (tests found): what KOLONİ found and saved as a project's test command, by
folder, and its one look for one, start empty; going back drops both."""

import sqlite3

from alembic import command

from tests.test_migration_0002 import _config

AT = "2026-11-22 16:00:00"


def test_every_project_starts_with_nothing_found_and_back(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0162")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO projects (id, name, root_path, created_at) "
                     "VALUES ('p', 'p', 'C:/p', ?)", (AT,))
    command.upgrade(cfg, "0163")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT tests_found, tests_look FROM projects").fetchall() == [
            ("{}", None)]
    command.downgrade(cfg, "0162")
    with sqlite3.connect(db) as conn:
        names = [row[1] for row in conn.execute("PRAGMA table_info(projects)")]
        assert "tests_found" not in names and "tests_look" not in names
