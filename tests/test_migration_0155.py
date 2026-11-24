"""Migration 0155 (K-yavas): a question may hang off no call - a card of the turn's own; one from
before keeps its call; going back, the turn's own cards go and the rest stay."""

import sqlite3

from alembic import command

from tests.test_migration_0002 import _config

AT = "2026-11-20 10:00:00"
ASK = (
    "INSERT INTO questions (id, run_id, agent_id, tool_call_id, question, options, leave, "
    "status, created_at) VALUES (?, 'r', 'a', ?, 'go on?', '[]', 1, 'pending', ?)"
)


def test_a_question_may_hang_off_no_call_and_back(tmp_path):
    db = tmp_path / "fresh.db"
    cfg = _config(db)
    command.upgrade(cfg, "0154")
    with sqlite3.connect(db) as conn:
        conn.execute(ASK, ("old", "t", AT))

    command.upgrade(cfg, "head")

    with sqlite3.connect(db) as conn:
        conn.execute(ASK, ("turns", None, AT))
        assert conn.execute("SELECT id, tool_call_id FROM questions ORDER BY id").fetchall() == [
            ("old", "t"),
            ("turns", None),
        ]

    command.downgrade(cfg, "0154")

    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT id, tool_call_id FROM questions").fetchall() == [("old", "t")]
