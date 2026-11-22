"""Migration 0161 (kanıtlı bitiş S4): the five core roles - Coder, Tester, Reviewer, Debugger,
Security reviewer - are on and keep the tools their job needs (Karar 5: one taken away comes
back, the user's other tools stay); the ready Bugfix as 0074 drew it sends a failing test back to
Fix it and starts with a failing test, one changed since is left alone. Going back draws Bugfix
as before and leaves the roles as they are."""

import json
import sqlite3

from alembic import command

from app.recipes import _loops
from app.schemas import RecipeGraph
from tests.test_migration_0002 import _config

READ = ["list_dir", "read_file", "search", "view_image"]


def _graph(conn, name="Bugfix"):
    (graph,) = conn.execute("SELECT graph FROM recipes WHERE name = ?", (name,)).fetchone()
    return json.loads(graph)


def _role(conn, name, tools, builtin=1, enabled=0):
    conn.execute(
        "INSERT INTO roles (id, name, description, instructions, tools, builtin, "
        "created_by_agent, kind, enabled, mcp, skills, created_at, updated_at) "
        "VALUES (?, ?, '', '', ?, ?, 0, 'check', ?, '[]', '[]', '2026-11-22', '2026-11-22')",
        (name, name, json.dumps(tools), builtin, enabled))


def _roles(db):
    with sqlite3.connect(db) as conn:
        return {name: (json.loads(tools), enabled) for name, tools, enabled in conn.execute(
            "SELECT name, tools, enabled FROM roles WHERE kind = 'check'")}


def test_bugfix_as_drawn_gets_its_test_loop_and_failing_test_step(tmp_path):
    db = tmp_path / "b.db"
    cfg = _config(db)
    command.upgrade(cfg, "0159")
    with sqlite3.connect(db) as conn:
        was = _graph(conn)
    command.upgrade(cfg, "0161")
    with sqlite3.connect(db) as conn:
        now = _graph(conn)
    assert now["loops"] == [{"from": "review", "to": "fix", "rounds": 2},
                            {"from": "test", "to": "fix", "rounds": 2}]
    assert [(s["id"], s["name"]) for s in now["steps"]] == [
        ("reproduce", "Reproduce it with a failing test"), ("fix", "Fix it"), ("test", "Test it"),
        ("review", "Review it")]
    # (Nothing else moved: the same arrows, ends and Who.)
    assert {**now, "steps": was["steps"], "loops": was["loops"]} == was
    assert [s["who"] for s in now["steps"]] == [s["who"] for s in was["steps"]]
    # A migration skips the save's check: its two loops are ones a saved recipe may have.
    graph = RecipeGraph.model_validate(now)
    said: list = []
    _loops(graph, {s.id: s for s in graph.steps}, {}, {s.id: s.name for s in graph.steps},
           {a.from_: [a.to] for a in graph.arrows}, lambda at, msg: said.append((at, msg)))
    assert said == []


def test_a_changed_bugfix_is_left_alone(tmp_path):
    db = tmp_path / "b.db"
    cfg = _config(db)
    command.upgrade(cfg, "0159")
    with sqlite3.connect(db) as conn:
        changed = {**_graph(conn), "loops": [{"from": "review", "to": "fix", "rounds": 1}]}
        conn.execute("UPDATE recipes SET graph = ? WHERE name = 'Bugfix'", (json.dumps(changed),))
    command.upgrade(cfg, "0161")
    with sqlite3.connect(db) as conn:
        assert _graph(conn) == changed


def test_core_roles_are_on_and_keep_their_tools(tmp_path):
    db = tmp_path / "r.db"
    cfg = _config(db)
    command.upgrade(cfg, "0159")
    with sqlite3.connect(db) as conn:
        # The user took the Tester's run_command away and gave it web_search; switched it off.
        _role(conn, "Tester", ["list_dir", "read_file", "web_search"])
        _role(conn, "Reviewer", [*READ, "ask_user"], enabled=1)
        _role(conn, "Coder", ["read_file"])
        _role(conn, "Debugger", [*READ, "write_file", "edit_file", "run_command"])
        # A user's own role by a core role's name, and a built-in role that is no core one.
        _role(conn, "Security reviewer", ["read_file"], builtin=0)
        _role(conn, "Data analyst", ["read_file"])
    command.upgrade(cfg, "0161")
    assert _roles(db) == {
        "Tester": (["list_dir", "read_file", "web_search", "search", "view_image", "run_command"], 1),
        "Reviewer": ([*READ, "ask_user"], 1),
        "Coder": (["read_file", "list_dir", "search", "view_image", "write_file", "edit_file",
                   "run_command"], 1),
        "Debugger": ([*READ, "write_file", "edit_file", "run_command"], 1),
        "Security reviewer": (["read_file"], 0),
        "Data analyst": (["read_file"], 0),
    }
    # Going back leaves the roles as they are: a switch or a tool is the user's to change again.
    before = _roles(db)
    command.downgrade(cfg, "0159")
    assert _roles(db) == before


def test_downgrade_puts_bugfix_back(tmp_path):
    db = tmp_path / "b.db"
    cfg = _config(db)
    command.upgrade(cfg, "0159")
    with sqlite3.connect(db) as conn:
        was = _graph(conn)
    command.upgrade(cfg, "0161")
    with sqlite3.connect(db) as conn:
        now = _graph(conn)
    command.downgrade(cfg, "0159")
    with sqlite3.connect(db) as conn:
        assert _graph(conn) == was
    command.upgrade(cfg, "head")
    with sqlite3.connect(db) as conn:
        assert _graph(conn) == now
