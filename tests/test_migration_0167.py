"""Migration 0167 (Check by kind of work, S5a): every project starts with all kinds on ({});
going back drops it."""

import json
import sqlite3

from alembic import command

from tests.test_migration_0002 import _config

AT = "2026-11-22 22:00:00"


def test_check_kinds_default_empty_and_back(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0165")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO projects (id, name, root_path, created_at) "
                     "VALUES ('p', 'p', 'C:/p', ?)", (AT,))
    command.upgrade(cfg, "0167")
    with sqlite3.connect(db) as conn:
        (kinds,) = conn.execute("SELECT check_kinds FROM projects").fetchone()
        assert json.loads(kinds) == {}
    command.downgrade(cfg, "0165")
    with sqlite3.connect(db) as conn:
        assert "check_kinds" not in [row[1] for row in conn.execute("PRAGMA table_info(projects)")]
