"""Migration 0075 (slice 84b) on a database made before it: a chat's one team becomes its one
Manual row, with the team's default recipe, and `team_id` goes; a chat with none (or with a team
deleted since) has "No teams". Going back gives `team_id` from the first Manual row."""

import sqlite3

from alembic import command

from tests.test_migration_0002 import _config

AT = "2026-10-25 10:00:00"


def test_a_chats_team_becomes_its_manual_row_and_comes_back_going_back(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0074")
    with sqlite3.connect(db) as conn:
        (feature,) = conn.execute("SELECT id FROM recipes WHERE name = 'Feature'").fetchone()
        conn.execute("INSERT INTO teams (id, name, created_at, lead_on, lead_may_pick, "
                     "default_recipe_id) VALUES ('g', 'Art', ?, 1, 1, ?)", (AT, feature))
        conn.execute("INSERT INTO teams (id, name, created_at, lead_on, lead_may_pick) "
                     "VALUES ('d', 'Docs2', ?, 1, 1)", (AT,))
        for cid, team in (("one", "g"), ("two", "d"), ("none", None), ("gone", "deleted")):
            conn.execute("INSERT INTO conversations (id, title, team_id, created_at, updated_at) "
                         "VALUES (?, 't', ?, ?, ?)", (cid, team, AT, AT))

    command.upgrade(cfg, "head")

    with sqlite3.connect(db) as conn:
        modes = dict(conn.execute("SELECT id, teams_mode FROM conversations"))
        rows = conn.execute("SELECT conversation_id, team_id, recipe_id, picked_by, why, position "
                            "FROM conversation_teams ORDER BY conversation_id").fetchall()
        columns = {row[1] for row in conn.execute("PRAGMA table_info(conversations)")}
        project = {row[1] for row in conn.execute("PRAGMA table_info(projects)")}
    assert modes == {"one": "manual", "two": "manual", "none": "none", "gone": "none"}
    assert rows == [("one", "g", feature, "user", None, 0), ("two", "d", None, "user", None, 0)]
    assert "team_id" not in columns and {"teams_mode", "teams"} <= project

    command.downgrade(cfg, "0074")

    with sqlite3.connect(db) as conn:
        back = dict(conn.execute("SELECT id, team_id FROM conversations"))
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert back == {"one": "g", "two": "d", "none": None, "gone": None}
    assert "conversation_teams" not in tables
