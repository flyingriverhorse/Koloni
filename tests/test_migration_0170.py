"""Migration 0170 (S5c): the ready Bugfix, Feature, Docs and Evolve say their Checks step's choice;
the other ready recipes follow the project; going back takes it out again."""

import json
import sqlite3

from alembic import command

from app.schemas import RecipeGraph
from tests.test_migration_0002 import _config


def _checks(db) -> dict[str, dict | None]:
    with sqlite3.connect(db) as conn:
        return {
            name: json.loads(graph).get("checks")
            for name, graph in conn.execute("SELECT name, graph FROM recipes WHERE ready = 1")
        }


def test_ready_recipes_get_the_checks_that_fit_and_lose_them_going_back(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0167")
    assert not any(_checks(db).values())
    command.upgrade(cfg, "0170")
    got = _checks(db)
    on = {
        name: sorted(part for part, value in checks.items() if value is True)
        for name, checks in got.items()
        if checks
    }
    assert on == {
        "Bugfix": ["review", "tests"],
        "Feature": ["review", "tests"],
        "Docs": ["docs", "review"],
        "Evolve": ["tests"],
    }
    assert got["Research"] is None  # (the rest follow the project)
    with sqlite3.connect(db) as conn:  # (each reads as the app reads a recipe)
        for (graph,) in conn.execute("SELECT graph FROM recipes WHERE ready = 1"):
            RecipeGraph.model_validate_json(graph)
    command.downgrade(cfg, "0167")
    assert not any(_checks(db).values())
