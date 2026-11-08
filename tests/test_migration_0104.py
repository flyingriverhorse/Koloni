"""Migration 0104 (K-tarifsiz): a chat's team row from before follows its recipe or its team's
default, as it did - not No recipe; going back takes the column away."""

import sqlite3

from alembic import command

from tests.test_migration_0002 import _config

AT = "2026-10-28 10:00:00"


def test_a_chat_team_from_before_is_not_no_recipe(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0101")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO conversations (id, title, created_at, updated_at) "
                     "VALUES ('c', 'c', ?, ?)", (AT, AT))
        conn.execute("INSERT INTO conversation_teams (id, conversation_id, team_id, picked_by, "
                     "position) VALUES ('t', 'c', (SELECT id FROM teams LIMIT 1), 'user', 0)")

    command.upgrade(cfg, "0104")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT no_recipe FROM conversation_teams").fetchall() == [(0,)]

    command.downgrade(cfg, "0101")
    with sqlite3.connect(db) as conn:
        assert "no_recipe" not in {
            row[1] for row in conn.execute("PRAGMA table_info(conversation_teams)")}
