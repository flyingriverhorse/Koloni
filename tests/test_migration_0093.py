"""Migration 0093 (K-takim-tarif): three ready teams get a default recipe - Web app Feature,
Backend / API Bugfix, Quality Review only - only where the team is still the ready one and has
none; going back takes away only those."""

import sqlite3

from alembic import command

from tests.test_migration_0002 import _config

AT = "2099-01-01 10:00:00"  # later than the ready teams, made as the migrations ran


def _defaults(conn):
    return dict(conn.execute(
        "SELECT teams.name, recipes.name FROM teams LEFT JOIN recipes "
        "ON recipes.id = teams.default_recipe_id"))


def test_a_fresh_database_has_the_three_defaults(tmp_path):
    cfg = _config(tmp_path / "fresh.db")
    command.upgrade(cfg, "0093")  # (0098 gives Quality its own: test_migration_0098)

    with sqlite3.connect(tmp_path / "fresh.db") as conn:
        assert _defaults(conn) == {
            "Web app": "Feature", "Backend / API": "Bugfix", "Quality": "Review only",
            "Data": None, "Docs": None, "Ops": None, "Research": None, "Product": None,
            "Maintenance": None}


def test_an_old_database_a_choice_a_renamed_team_and_a_users_team_are_left_alone(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0092")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO recipes (id, name, ready, graph, created_at, updated_at) "
                     "VALUES ('mine', 'Mine', 0, '{}', ?, ?)", (AT, AT))
        conn.execute("UPDATE teams SET default_recipe_id = 'mine' WHERE name = 'Backend / API'")
        # The user's own by a ready team's name, the ready one renamed away first.
        conn.execute("UPDATE teams SET name = 'Old web' WHERE name = 'Web app'")
        conn.execute("INSERT INTO teams (id, name, created_at, lead_on, lead_may_pick) "
                     "VALUES ('u', 'Web app', ?, 1, 1)", (AT,))

    command.upgrade(cfg, "0093")

    with sqlite3.connect(db) as conn:
        found = _defaults(conn)
    assert found["Backend / API"] == "Mine"
    assert found["Quality"] == "Review only"  # still the ready one, with none
    assert found["Web app"] is None and found["Old web"] is None

    command.downgrade(cfg, "0092")

    with sqlite3.connect(db) as conn:
        assert _defaults(conn)["Backend / API"] == "Mine"


def test_going_back_takes_the_defaults_away(tmp_path):
    db = tmp_path / "fresh.db"
    cfg = _config(db)
    command.upgrade(cfg, "head")

    command.downgrade(cfg, "0092")

    with sqlite3.connect(db) as conn:
        assert set(_defaults(conn).values()) == {None}
