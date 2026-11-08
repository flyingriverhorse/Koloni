"""Migration 0084 (batch-16): the ready Feature recipe loses its "Approve it" step - the Lead
approves itself - and gets it back going back; a ready recipe drawn otherwise is left alone."""

import json
import sqlite3

from alembic import command

from tests.test_migration_0002 import _config


def feature(db):
    with sqlite3.connect(db) as conn:
        (graph,) = conn.execute("SELECT graph FROM recipes WHERE name = 'Feature'").fetchone()
    return json.loads(graph)


def test_the_ready_feature_recipe_has_no_approve_step_and_gets_it_back_going_back(tmp_path):
    db = tmp_path / "fresh.db"
    cfg = _config(db)
    command.upgrade(cfg, "0083")
    before = feature(db)
    assert "approve" in [step["id"] for step in before["steps"]]

    command.upgrade(cfg, "head")

    after = feature(db)
    assert "approve" not in [step["id"] for step in after["steps"]]
    assert {"from": "reviews", "to": "end"} in after["arrows"]
    assert not [arrow for arrow in after["arrows"] if "approve" in arrow.values()]

    command.downgrade(cfg, "0083")

    back = feature(db)
    assert sorted(map(json.dumps, back["steps"])) == sorted(map(json.dumps, before["steps"]))
    assert sorted(map(json.dumps, back["arrows"])) == sorted(map(json.dumps, before["arrows"]))
