"""Migration 0165 (Fix rounds, S3): every project starts on 2; going back drops it."""

import sqlite3

from alembic import command

from tests.test_migration_0002 import _config

AT = "2026-11-22 20:00:00"


def test_every_project_starts_on_two_fix_rounds_and_back(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0164")
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO projects (id, name, root_path, created_at) VALUES ('p', 'p', 'C:/p', ?)",
            (AT,),
        )
    command.upgrade(cfg, "0165")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT fix_rounds FROM projects").fetchall() == [(2,)]
    command.downgrade(cfg, "0164")
    with sqlite3.connect(db) as conn:
        assert "fix_rounds" not in [row[1] for row in conn.execute("PRAGMA table_info(projects)")]
