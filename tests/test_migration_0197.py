"""Migration 0197 (0.1.11, note_decision): the Orchestrator's noted decisions have a table of their
own; going back drops it, the rest of the database as it was."""

import sqlite3

from alembic import command

from tests.test_migration_0002 import _config


def tables(db):
    with sqlite3.connect(db) as conn:
        return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_the_noted_decisions_table_comes_and_goes(tmp_path):
    db = tmp_path / "fresh.db"
    cfg = _config(db)
    command.upgrade(cfg, "0197")
    assert "noted_decisions" in tables(db)
    with sqlite3.connect(db) as conn:
        named = [row[1] for row in conn.execute("PRAGMA table_info(noted_decisions)")]
    assert named == [
        "id",
        "run_id",
        "agent_id",
        "tool_call_id",
        "what",
        "why",
        "seen_at",
        "created_at",
    ]
    command.downgrade(cfg, "0196")
    assert "noted_decisions" not in tables(db) and "runs" in tables(db)
