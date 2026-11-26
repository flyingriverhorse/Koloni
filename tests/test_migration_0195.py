"""Migration 0195 (tarifler T3): the ready Feature, Model change and Pipeline change as KOLONİ drew
them lose their Tester and general Reviewer steps - Feature keeps its UI review, Model change its
metrics, Pipeline change its data quality, each looping back to its build - and the two that
followed the project check their tests and a review; one changed since is left alone; going back
draws them as before."""

import json
import sqlite3

from alembic import command

from app.recipes import problems
from app.schemas import RecipeGraph
from tests.test_migration_0002 import _config

NAMES = ("Feature", "Model change", "Pipeline change")


def _graphs(db) -> dict:
    with sqlite3.connect(db) as conn:
        return {
            name: json.loads(graph)
            for name, graph in conn.execute(
                "SELECT name, graph FROM recipes WHERE ready = 1 AND name IN (?, ?, ?)", NAMES
            )
        }


def _way(graph) -> list:
    return [(s["id"], s["who"], s["done_when"], s["group"]) for s in graph["steps"]]


def test_the_three_lose_their_tester_and_reviewer_and_come_back(tmp_path):
    db = tmp_path / "t.db"
    cfg = _config(db)
    command.upgrade(cfg, "0194")
    was = _graphs(db)
    command.upgrade(cfg, "0195")
    now = _graphs(db)
    review = "no_findings"
    assert _way(now["Feature"]) == [
        ("spec", {"role": "Spec writer"}, "done", None),
        ("build", {"role": "Coder"}, "done", None),
        ("ui", {"role": "UI designer"}, review, None),
    ]
    assert _way(now["Model change"]) == [
        ("plan", {"role": "Data scientist"}, "done", None),
        ("experts", {"experts": "learned"}, review, None),
        ("build", {"role": "ML engineer"}, "done", None),
        ("metrics", {"role": "Model evaluator"}, review, None),
    ]
    assert _way(now["Pipeline change"]) == [
        ("build", {"role": "Data engineer"}, "done", None),
        ("quality", {"role": "Data analyst"}, review, None),
    ]
    # (The build loop last: where Ask for changes and KOLONİ's fix round go back to.)
    assert {
        name: [(o["from"], o["to"], o["rounds"]) for o in g["loops"]] for name, g in now.items()
    } == {
        "Feature": [("ui", "build", 2)],
        "Model change": [("experts", "plan", 1), ("metrics", "build", 2)],
        "Pipeline change": [("quality", "build", 2)],
    }
    assert [(a["from"], a["to"]) for a in now["Pipeline change"]["arrows"]] == [
        ("start", "build"),
        ("build", "quality"),
        ("quality", "end"),
    ]
    assert all(g["groups"] == [] for g in now.values())
    # Feature's Checks step as it was; the two that followed the project: tests and a review.
    assert now["Feature"]["checks"] == was["Feature"]["checks"]
    assert "checks" not in was["Model change"] and "checks" not in was["Pipeline change"]
    assert (
        now["Model change"]["checks"]
        == now["Pipeline change"]["checks"]
        == was["Feature"]["checks"]
    )
    for name in NAMES:
        RecipeGraph.model_validate(now[name])  # (read as the app reads a recipe)
        assert {k: now[name][k] for k in ("version", "ends")} == {
            k: was[name][k] for k in ("version", "ends")
        }
    command.downgrade(cfg, "0194")
    assert _graphs(db) == was


def test_a_changed_one_is_left_alone(tmp_path):
    db = tmp_path / "t.db"
    cfg = _config(db)
    command.upgrade(cfg, "0194")
    was = _graphs(db)
    changed = {**was["Feature"], "loops": [{"from": "reviews", "to": "build", "rounds": 1}]}
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE recipes SET graph = ? WHERE name = 'Feature'", (json.dumps(changed),))
    command.upgrade(cfg, "0195")
    now = _graphs(db)
    assert now["Feature"] == changed
    assert now["Model change"] != was["Model change"]  # (the others still go)
    command.downgrade(cfg, "0194")
    assert _graphs(db) == {**was, "Feature": changed}


def test_the_thin_ones_run(make_client):
    # (Saved as KOLONİ's page saves a recipe: nothing in it keeps it from running.)
    client, _model = make_client([])
    ready = {r["name"]: r["graph"] for r in client.get("/api/recipes").json()["recipes"]}
    with client.app.state.session_factory() as session:
        for name in NAMES:
            graph = RecipeGraph.model_validate(ready[name])
            assert problems(session, graph, client.app.state.providers) == [], name
