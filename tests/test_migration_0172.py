"""Migration 0172 (tarif maliyeti T1): the ready Bugfix as 0161 and 0170 drew it is Reproduce it ->
Fix it -> Checks, no loop, its Checks step as it was; one changed since is left alone; going back
draws it as before."""

import json
import sqlite3

from alembic import command

from app.recipes import problems
from app.schemas import RecipeGraph
from tests.test_migration_0002 import _config


def _graph(db):
    with sqlite3.connect(db) as conn:
        (graph,) = conn.execute(
            "SELECT graph FROM recipes WHERE name = 'Bugfix' AND ready = 1"
        ).fetchone()
    return json.loads(graph)


def test_bugfix_is_reproduce_then_fix_then_checks_and_back(tmp_path):
    db = tmp_path / "b.db"
    cfg = _config(db)
    command.upgrade(cfg, "0171")
    was = _graph(db)
    command.upgrade(cfg, "0172")
    now = _graph(db)
    assert [(s["id"], s["name"], s["who"]) for s in now["steps"]] == [
        ("reproduce", "Reproduce it with a failing test", {"role": "Debugger"}),
        ("fix", "Fix it", {"role": "Coder"}),
    ]
    assert [(a["from"], a["to"]) for a in now["arrows"]] == [
        ("start", "reproduce"),
        ("reproduce", "fix"),
        ("fix", "end"),
    ]
    assert now["loops"] == [] and now["checks"] == was["checks"]
    assert {k: now[k] for k in ("version", "groups", "ends")} == {
        k: was[k] for k in ("version", "groups", "ends")
    }
    RecipeGraph.model_validate(now)  # (read as the app reads a recipe)
    command.downgrade(cfg, "0171")
    assert _graph(db) == was


def test_a_changed_bugfix_is_left_alone(tmp_path):
    db = tmp_path / "b.db"
    cfg = _config(db)
    command.upgrade(cfg, "0171")
    changed = {**_graph(db), "loops": [{"from": "review", "to": "fix", "rounds": 1}]}
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE recipes SET graph = ? WHERE name = 'Bugfix'", (json.dumps(changed),))
    command.upgrade(cfg, "0172")
    assert _graph(db) == changed
    command.downgrade(cfg, "0171")
    assert _graph(db) == changed


def test_the_thin_bugfix_runs(make_client):
    # (Saved as KOLONİ's page saves a recipe: nothing in it keeps it from running.)
    client, _model = make_client([])
    with client.app.state.session_factory() as session:
        (bugfix,) = [
            r for r in client.get("/api/recipes").json()["recipes"] if r["name"] == "Bugfix"
        ]
        graph = RecipeGraph.model_validate(bugfix["graph"])
        assert problems(session, graph, client.app.state.providers) == []
