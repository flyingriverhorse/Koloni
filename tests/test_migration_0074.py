"""Migration 0074 (slice 84a) on a database made before it: the recipes, the three ready ones
among them - at head with the later ones beside them, Integration (0090), Quality check
(0098) and the eight of 0103 - and a team's default recipe; going back takes them away and
leaves the teams."""

import json
import sqlite3

from alembic import command

from tests.test_migration_0002 import _config

AT = "2026-10-25 10:00:00"


def test_recipes_come_ready_and_go_going_back(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0073")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO teams (id, name, created_at, lead_on, lead_may_pick) "
                     "VALUES ('g', 'Art', ?, 1, 1)", (AT,))

    command.upgrade(cfg, "head")

    with sqlite3.connect(db) as conn:
        ready = conn.execute("SELECT name, ready, graph FROM recipes ORDER BY rowid").fetchall()
        (default,) = conn.execute("SELECT default_recipe_id FROM teams WHERE id = 'g'").fetchone()
    assert [(name, flag) for name, flag, _graph in ready] == [
        ("Feature", 1), ("Bugfix", 1), ("Review only", 1), ("Integration", 1), ("Quality check", 1),
        *[(name, 1) for name in ("Model change", "Pipeline change", "Infra change", "Docs", "Research",
                                 "Spec", "Analysis", "Upkeep", "Evolve")]]
    assert all(json.loads(graph)["version"] == 1 for _n, _f, graph in ready)
    assert default is None

    command.downgrade(cfg, "0073")

    with sqlite3.connect(db) as conn:
        assert "recipes" not in {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert "default_recipe_id" not in {row[1] for row in conn.execute(
            "PRAGMA table_info(teams)")}
        assert conn.execute("SELECT name FROM teams WHERE id = 'g'").fetchone() == ("Art",)
