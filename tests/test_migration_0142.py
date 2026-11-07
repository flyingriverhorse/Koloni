"""Migration 0142 (K-bilgi 6): the Project notes offers' table - there going up, gone going back."""

import sqlite3

from alembic import command

from tests.test_migration_0002 import _config


def _tables(db) -> set[str]:
    with sqlite3.connect(db) as conn:
        return {name for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def test_the_offers_table_comes_and_goes(tmp_path):
    db = tmp_path / "x.db"
    command.upgrade(_config(db), "0142")
    assert "notes_offers" in _tables(db)
    command.downgrade(_config(db), "0141")
    assert "notes_offers" not in _tables(db)
