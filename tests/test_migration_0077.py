"""Migration 0077 (K-33a): messages get an index on agent_id, which the track record counts
steps by; going back drops it."""

import sqlite3

from alembic import command

from tests.test_migration_0002 import _config


def indexes(db):
    with sqlite3.connect(db) as conn:
        return {row[1] for row in conn.execute("PRAGMA index_list(messages)")}


def test_messages_agent_id_is_indexed_and_goes_back(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0076")
    assert "ix_messages_agent_id" not in indexes(db)
    command.upgrade(cfg, "head")
    assert "ix_messages_agent_id" in indexes(db)
    command.downgrade(cfg, "0076")
    assert "ix_messages_agent_id" not in indexes(db)
