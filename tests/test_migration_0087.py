"""Migration 0087 (slice 106): the nights while the user is away, and each task's part in one -
a task kept from before has none; going back, both are gone."""

import sqlite3

from alembic import command

from tests.test_migration_0002 import _config

AT = "2026-10-26 10:00:00"


def test_old_tasks_come_through_with_no_night_and_back(tmp_path):
    db = tmp_path / "fresh.db"
    cfg = _config(db)
    command.upgrade(cfg, "0086")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO projects (id, name, root_path, created_at) "
                     "VALUES ('p', 'p', 'C:/p', ?)", (AT,))
        conn.execute("INSERT INTO backlog_tasks (id, project_id, title, priority, status, position, "
                     "created_by, created_at) VALUES ('t', 'p', 'old', 'normal', 'todo', 0, "
                     "'user', ?)", (AT,))

    command.upgrade(cfg, "head")

    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT away_run_id, away_state, away_why FROM backlog_tasks"
                            ).fetchall() == [(None, None, None)]
        assert conn.execute("SELECT count(*) FROM away_runs").fetchone() == (0,)

    command.downgrade(cfg, "0086")

    with sqlite3.connect(db) as conn:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(backlog_tasks)")]
        assert "away_run_id" not in columns and "away_state" not in columns
        assert conn.execute("SELECT title FROM backlog_tasks").fetchall() == [("old",)]
        assert conn.execute("SELECT name FROM sqlite_master WHERE name = 'away_runs'"
                            ).fetchone() is None
