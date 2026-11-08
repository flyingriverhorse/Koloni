"""Migration 0098 (B-172, the user's): the ready "Quality check" recipe - the Tester runs the tests,
then the Reviewer and the Security reviewer together - is the stock Quality team's default in
place of Review only, only where that is still its default; going back puts Review only back and
takes the recipe away where nothing names it."""

import json
import sqlite3

from alembic import command

from tests.test_migration_0002 import _config
from tests.test_migration_0093 import AT, _defaults


def test_a_fresh_database_gives_quality_its_own_recipe(tmp_path):
    cfg = _config(tmp_path / "fresh.db")
    command.upgrade(cfg, "0098")  # (0102 gives it its Debugger)

    with sqlite3.connect(tmp_path / "fresh.db") as conn:
        found = _defaults(conn)
        (graph,) = conn.execute("SELECT graph FROM recipes WHERE name = 'Quality check' AND ready").fetchone()
    assert (found["Quality"], found["Web app"], found["Backend / API"]) == ("Quality check", "Feature", "Bugfix")
    roles = [step["who"]["role"] for step in json.loads(graph)["steps"]]
    assert roles == ["Tester", "Reviewer", "Security reviewer"]  # no UI designer


def test_a_users_choice_and_a_renamed_quality_are_left_alone_and_going_back_puts_review_only_back(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0093")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO recipes (id, name, ready, graph, created_at, updated_at) "
                     "VALUES ('mine', 'Mine', 0, '{}', ?, ?)", (AT, AT))
        # The stock Quality renamed; a team of the user's own named Quality, with Review only.
        conn.execute("UPDATE teams SET name = 'Checks' WHERE name = 'Quality'")
        conn.execute("INSERT INTO teams (id, name, created_at, lead_on, lead_may_pick, default_recipe_id) "
                     "SELECT 'u', 'Quality', ?, 1, 1, id FROM recipes WHERE name = 'Review only'", (AT,))

    command.upgrade(cfg, "head")
    with sqlite3.connect(db) as conn:
        found = _defaults(conn)
    assert (found["Checks"], found["Quality"]) == ("Review only", "Review only")

    # The stock one, its default the user's own: kept.
    with sqlite3.connect(db) as conn:
        conn.execute("DELETE FROM teams WHERE id = 'u'")
        conn.execute("UPDATE teams SET name = 'Quality', default_recipe_id = 'mine' WHERE name = 'Checks'")
    command.downgrade(cfg, "0093")
    command.upgrade(cfg, "head")
    with sqlite3.connect(db) as conn:
        assert _defaults(conn)["Quality"] == "Mine"


def test_going_back_puts_review_only_back_and_takes_quality_check_away(tmp_path):
    db = tmp_path / "fresh.db"
    cfg = _config(db)
    command.upgrade(cfg, "head")

    command.downgrade(cfg, "0093")

    with sqlite3.connect(db) as conn:
        assert _defaults(conn)["Quality"] == "Review only"
        assert conn.execute("SELECT COUNT(*) FROM recipes WHERE name = 'Quality check'").fetchone() == (0,)
