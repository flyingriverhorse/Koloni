"""Migration 0189: triggers are gone - their four tables, the switch that paused them all, and
`propose_trigger` from every role; a turn a trigger started stays as it was. Going back, the
tables come back as they were, empty, and the built-in Lead and Planner get the tool again."""

import importlib.util
import json
import sqlite3
from pathlib import Path

from alembic import command

from app.roles import BUILTIN_ROLES
from tests.test_migration_0002 import _config
from tests.test_migration_0177 import AT, tables

_spec = importlib.util.spec_from_file_location(
    "m0189", Path(__file__).parents[1] / "alembic" / "versions" / "0189_no_triggers.py"
)
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)


def before_0189(name: str) -> list[str]:
    """A built-in role's tools as app.roles had them before 0189 took propose_trigger off: what
    the older migrations' tests compare with."""
    tools = list(BUILTIN_ROLES[name].tools)
    if name in M.AFTER:
        tools.insert(tools.index(M.AFTER[name]) + 1, M.TOOL)
    return tools


GONE = ("triggers", "trigger_runs", "trigger_changes", "trigger_proposals")
LEAD = ["read_file", "assess_task", "propose_trigger", "post_note"]
PLANNER = ["read_file", "discuss", "propose_trigger", "remember"]


def role(conn, role_id: str, name: str, tools: list[str], builtin: bool) -> None:
    conn.execute(
        "INSERT INTO roles (id, name, description, instructions, tools, builtin, "
        "created_by_agent, created_at, updated_at) VALUES (?, ?, '', '', ?, ?, 0, ?, ?)",
        (role_id, name, json.dumps(tools), builtin, AT, AT),
    )


def tools_of(conn) -> dict[str, list[str]]:
    return {name: json.loads(held) for name, held in conn.execute("SELECT id, tools FROM roles")}


def shape(conn) -> dict:
    """Each trigger table as SQLite has it: its columns, indexes and foreign keys. The keys in any
    order, without their numbers: 0020's batch copy of `triggers` writes them in an order that
    changes from run to run."""
    return {
        table: (
            conn.execute(f"PRAGMA table_info({table})").fetchall(),
            sorted(
                (name, conn.execute(f"PRAGMA index_info({name})").fetchall())
                for _, name, *_ in conn.execute(f"PRAGMA index_list({table})")
            ),
            sorted(row[2:] for row in conn.execute(f"PRAGMA foreign_key_list({table})")),
        )
        for table in GONE
    }


def test_the_tables_the_switch_and_the_tool_go_and_a_triggers_turn_stays(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0187")
    with sqlite3.connect(db) as conn:
        conn.execute("DELETE FROM roles")
        role(conn, "lead", "Lead", LEAD, True)
        role(conn, "plan", "Planner", PLANNER, True)
        role(conn, "mine", "Mine", ["read_file", "propose_trigger"], False)
        conn.execute(
            "INSERT INTO projects (id, name, root_path, created_at) VALUES ('p', 'p', 'C:/p', ?)",
            (AT,),
        )
        conn.execute(
            "INSERT INTO conversations (id, project_id, title, created_at, updated_at) "
            "VALUES ('c', 'p', 'c', ?, ?)",
            (AT, AT),
        )
        conn.execute(
            "INSERT INTO triggers (id, project_id, conversation_id, name, kind, config, message, "
            "permissions, budget, catch_up, enabled, failures, created_at, updated_at) VALUES "
            "('t', 'p', 'c', 'watch', 'schedule', '{}', 'look', '{}', '{}', 1, 1, 0, ?, ?)",
            (AT, AT),
        )
        conn.execute(
            "INSERT INTO trigger_runs (id, trigger_id, run_id, at, late) VALUES ('tr', 't', 'r', ?, 0)",
            (AT,),
        )
        conn.execute(
            "INSERT INTO runs (id, conversation_id, status, created_at, unattended, trigger_id, "
            "trigger_name) VALUES ('r', 'c', 'completed', ?, 1, 't', 'watch')",
            (AT,),
        )
        conn.executemany(
            "INSERT INTO flags (name, value) VALUES (?, '1')", [("triggers_paused",), ("kept",)]
        )

    command.upgrade(cfg, "0189")
    with sqlite3.connect(db) as conn:
        assert not tables(conn) & set(GONE)
        assert conn.execute("SELECT name FROM flags").fetchall() == [("kept",)]
        assert tools_of(conn) == {
            "lead": ["read_file", "assess_task", "post_note"],
            "plan": ["read_file", "discuss", "remember"],
            "mine": ["read_file"],
        }
        assert conn.execute(
            "SELECT unattended, trigger_id, trigger_name FROM runs WHERE id = 'r'"
        ).fetchall() == [(1, "t", "watch")]

    command.downgrade(cfg, "0187")
    with sqlite3.connect(db) as conn:
        assert set(GONE) <= tables(conn)
        assert all(
            conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone() == (0,) for table in GONE
        )
        # (in its place again; the user's own role does not get it back)
        assert tools_of(conn) == {"lead": LEAD, "plan": PLANNER, "mine": ["read_file"]}


def test_going_back_makes_the_tables_as_they_were(tmp_path):
    db = tmp_path / "fresh.db"
    cfg = _config(db)
    command.upgrade(cfg, "0187")
    with sqlite3.connect(db) as conn:
        before = shape(conn)
    command.upgrade(cfg, "0189")
    command.downgrade(cfg, "0187")
    with sqlite3.connect(db) as conn:
        assert shape(conn) == before
