"""Migration 0141 (K-evrim): the ready "Evolve" recipe - three Coders as candidates, a target of
80, round again at most three times - only where no recipe has its name; going back takes it away
where nothing names it."""

import json
import sqlite3

from alembic import command

from app.schemas import RecipeGraph
from tests.test_migration_0002 import _config

AT = "2026-11-04 10:00:00"


def _evolve(db):
    with sqlite3.connect(db) as conn:
        return conn.execute("SELECT id, ready, graph FROM recipes WHERE lower(name) = 'evolve'").fetchall()


def test_a_fresh_database_has_it_and_it_reads_as_a_recipe(tmp_path):
    db = tmp_path / "fresh.db"
    command.upgrade(_config(db), "0141")
    ((_id, ready, graph),) = _evolve(db)
    drawn = RecipeGraph.model_validate(json.loads(graph))
    assert ready == 1 and drawn.steps[0].who.model_dump() == {
        "candidates": "Coder", "most": 3, "target": 80}
    assert [(one.from_, one.to, one.rounds) for one in drawn.loops] == [("try", "try", 3)]
    command.downgrade(_config(db), "0140")
    assert _evolve(db) == []


def test_a_users_own_evolve_is_kept_and_not_taken_away(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0140")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO recipes (id, name, ready, graph, created_at, updated_at) "
                     "VALUES ('mine', 'evolve', 0, '{}', ?, ?)", (AT, AT))
    command.upgrade(cfg, "0141")
    assert _evolve(db) == [("mine", 0, "{}")]
    command.downgrade(cfg, "0140")
    assert _evolve(db) == [("mine", 0, "{}")]
