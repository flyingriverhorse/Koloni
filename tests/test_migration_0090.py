"""Migration 0090 (K-uzman): a role's knowledge - none for a role from before - and the ready
Integration recipe, not over a recipe of the user's own by that name; going back takes both away."""

import json
import sqlite3

from alembic import command

from tests.test_migration_0002 import _config

AT = "2026-10-27 10:00:00"


def test_roles_from_before_are_no_experts_and_integration_comes_ready(tmp_path):
    db = tmp_path / "fresh.db"
    cfg = _config(db)
    command.upgrade(cfg, "0089")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO roles (id, name, description, instructions, tools, builtin, "
                     "created_by_agent, kind, enabled, mcp, skills, created_at, updated_at) VALUES "
                     "('r', 'Mine', '', '', '[]', 0, 0, 'build', 1, '[]', '[]', ?, ?)", (AT, AT))

    command.upgrade(cfg, "head")

    with sqlite3.connect(db) as conn:
        # (Since 0136 a role's knowledge is a row it uses: `knows`.)
        assert conn.execute("SELECT knows FROM roles WHERE id = 'r'").fetchone() == ("[]",)
        (ready, graph) = conn.execute(
            "SELECT id, graph FROM recipes WHERE name = 'Integration' AND ready = 1").fetchone()
        # Named by a team as its default, and by a chat's row.
        conn.execute("INSERT INTO teams (id, name, created_at, lead_on, lead_may_pick, "
                     "default_recipe_id) VALUES ('t', 'Pay', ?, 1, 1, ?)", (AT, ready))
        conn.execute("INSERT INTO conversations (id, title, created_at, updated_at) "
                     "VALUES ('c', 'c', ?, ?)", (AT, AT))
        conn.execute("INSERT INTO conversation_teams (id, conversation_id, team_id, recipe_id, "
                     "picked_by, position) VALUES ('ct', 'c', 't', ?, 'user', 0)", (ready,))
    drawn = json.loads(graph)
    assert [s["who"] for s in drawn["steps"]] == [
        {"experts": "stale"}, {"role": "Planner"}, {"experts": "all"}, {"role": "Coder"},
        {"role": "Tester"}]

    command.downgrade(cfg, "0089")

    with sqlite3.connect(db) as conn:
        assert "knowledge" not in {row[1] for row in conn.execute("PRAGMA table_info(roles)")}
        assert conn.execute("SELECT name FROM recipes WHERE name = 'Integration'").fetchall() == []
        assert conn.execute("SELECT default_recipe_id FROM teams WHERE id = 't'").fetchall() == [(None,)]
        assert conn.execute("SELECT recipe_id FROM conversation_teams").fetchall() == [(None,)]


def test_a_recipe_of_the_users_own_keeps_the_name(tmp_path):
    db = tmp_path / "fresh.db"
    cfg = _config(db)
    command.upgrade(cfg, "0089")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO recipes (id, name, ready, graph, created_at, updated_at) "
                     "VALUES ('mine', 'integration', 0, '{}', ?, ?)", (AT, AT))

    command.upgrade(cfg, "head")

    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT id, ready FROM recipes WHERE lower(name) = 'integration'"
                            ).fetchall() == [("mine", 0)]
