"""Migration 0169 (Then a stronger model, S11): every project starts on; going back drops it."""

import sqlite3

from alembic import command

from tests.test_migration_0002 import _config

AT = "2026-11-23 10:00:00"


def test_every_project_starts_with_a_stronger_model_on_and_back(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0170")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO projects (id, name, root_path, created_at) "
                     "VALUES ('p', 'p', 'C:/p', ?)", (AT,))
    command.upgrade(cfg, "0169")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT stronger_model FROM projects").fetchall() == [(1,)]
    command.downgrade(cfg, "0170")
    with sqlite3.connect(db) as conn:
        assert "stronger_model" not in [
            row[1] for row in conn.execute("PRAGMA table_info(projects)")]
