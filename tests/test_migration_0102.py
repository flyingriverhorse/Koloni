"""Migration 0102 (the conditional recipe step, the user's): the ready "Quality check" recipe, as
0098 drew it, gets its Debugger - only if the Tester found a problem, then the tests again, at
most 2 rounds - and going back draws it as 0098 did. A copy of the user's, or one changed since,
is left alone."""

import json
import sqlite3

from alembic import command

from tests.test_migration_0002 import _config
from tests.test_migration_0093 import AT


def _graph(conn, name="Quality check"):
    (graph,) = conn.execute("SELECT graph FROM recipes WHERE name = ?", (name,)).fetchone()
    return json.loads(graph)


def _roles(graph):
    return [(step["who"]["role"], step.get("when")) for step in graph["steps"]]


def test_up_down_and_up_again_and_a_users_copy_drawn_the_same_is_left_alone(tmp_path):
    db = tmp_path / "q.db"
    cfg = _config(db)
    command.upgrade(cfg, "0098")
    with sqlite3.connect(db) as conn:
        was = _graph(conn)
        conn.execute("INSERT INTO recipes (id, name, ready, graph, created_at, updated_at) "
                     "SELECT 'mine', 'My quality check', 0, graph, ?, ? FROM recipes "
                     "WHERE name = 'Quality check'", (AT, AT))

    command.upgrade(cfg, "0102")
    with sqlite3.connect(db) as conn:
        now = _graph(conn)
        assert _roles(now) == [("Tester", None), ("Debugger", "problem"), ("Reviewer", None),
                               ("Security reviewer", None)]
        assert now["loops"] == [{"from": "fix", "to": "test", "rounds": 2}]
        assert _graph(conn, "My quality check") == was

    command.downgrade(cfg, "0099")
    with sqlite3.connect(db) as conn:
        assert (_graph(conn), _graph(conn, "My quality check")) == (was, was)

    command.upgrade(cfg, "head")
    with sqlite3.connect(db) as conn:
        assert (_graph(conn), _graph(conn, "My quality check")) == (now, was)


def test_the_users_own_quality_check_from_before_0098_is_left_alone(tmp_path):
    db = tmp_path / "q.db"
    cfg = _config(db)
    command.upgrade(cfg, "0093")
    mine = {"version": 1, "steps": [], "note": "the user's own"}
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO recipes (id, name, ready, graph, created_at, updated_at) "
                     "VALUES ('mine', 'Quality check', 0, ?, ?, ?)", (json.dumps(mine), AT, AT))
    command.upgrade(cfg, "0102")
    with sqlite3.connect(db) as conn:
        assert _graph(conn) == mine


def test_a_ready_quality_check_changed_since_0098_is_left_alone(tmp_path):
    db = tmp_path / "q.db"
    cfg = _config(db)
    command.upgrade(cfg, "0098")
    with sqlite3.connect(db) as conn:
        changed = {**_graph(conn), "loops": [{"from": "reviews", "to": "test", "rounds": 1}]}
        conn.execute("UPDATE recipes SET graph = ? WHERE name = 'Quality check'", (json.dumps(changed),))
    command.upgrade(cfg, "0102")
    with sqlite3.connect(db) as conn:
        assert _graph(conn) == changed

