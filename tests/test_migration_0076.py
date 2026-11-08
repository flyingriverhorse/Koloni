"""Migration 0076 (slice 84b-2): a chat team's row gets the state of its recipe's run, empty for
the rows there are; going back drops it and keeps the rows."""

import sqlite3

from alembic import command

from tests.test_migration_0002 import _config

AT = "2026-10-25 10:00:00"


def test_a_rows_state_comes_empty_and_goes_back_with_the_row_kept(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0075")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO teams (id, name, created_at, lead_on, lead_may_pick) "
                     "VALUES ('g', 'Art', ?, 1, 1)", (AT,))
        conn.execute("INSERT INTO conversations (id, title, teams_mode, created_at, updated_at) "
                     "VALUES ('c', 't', 'manual', ?, ?)", (AT, AT))
        conn.execute("INSERT INTO conversation_teams (id, conversation_id, team_id, picked_by, "
                     "position) VALUES ('r', 'c', 'g', 'user', 0)")

    command.upgrade(cfg, "head")

    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT id, state FROM conversation_teams").fetchall() == [("r", None)]
        conn.execute("UPDATE conversation_teams SET state = '{\"status\": \"running\"}'")

    command.downgrade(cfg, "0075")

    with sqlite3.connect(db) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(conversation_teams)")}
        assert conn.execute("SELECT id, team_id FROM conversation_teams").fetchall() == [("r", "g")]
    assert "state" not in columns
