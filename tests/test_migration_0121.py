"""K-spawn-roller (R121): which built-in roles may open a helper, and migration 0121 giving
spawn_agent to the six that gain it - only where their tools are still as KOLONİ gave them."""

import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest
from alembic import command

from app.roles import BUILTIN_ROLES
from tests.test_migration_0002 import _config
from tests.test_migration_0109 import _role

GIVEN = {"Lead", "Planner", "Coder", "Data engineer", "ML engineer"}
GAIN = {"Architect", "Debugger", "Product owner", "Spec writer", "DevOps", "MLOps engineer"}


def test_who_may_open_a_helper():
    assert {name for name, spec in BUILTIN_ROLES.items()
            if "spawn_agent" in spec.tools} == GIVEN | GAIN
    for name in GAIN:  # (each is told what a helper is for)
        assert "spawn_agent" in BUILTIN_ROLES[name].instructions, name


def _frozen():
    path = Path(__file__).parents[1] / "alembic" / "versions" / "0121_spawn_roles.py"
    spec = importlib.util.spec_from_file_location("m0121", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


M = _frozen()
NAMES = ", ".join(f"'{name}'" for name, _ in M.ROLES)


def _held(conn):
    return {name: json.loads(tools) for name, tools in conn.execute(
        f"SELECT name, tools FROM roles WHERE name IN ({NAMES})")}


def _before(tmp_path, change=lambda tools, builtin: (tools, builtin)):
    """A database just before 0121 with the six roles as KOLONI gave them - or as `change`
    makes them - and what they held."""
    cfg = _config(db := tmp_path / "r.db")
    command.upgrade(cfg, M.down_revision)
    with sqlite3.connect(db) as conn:
        conn.execute(f"DELETE FROM roles WHERE name IN ({NAMES})")
        for at, (name, tools) in enumerate(M.ROLES):
            tools, builtin = change(tools, 1)
            _role(conn, str(at), name, tools, "as given", builtin)
        return cfg, db, _held(conn)


def test_stock_ones_gain_spawn_agent_and_going_back_is_exact(tmp_path):
    cfg, db, before = _before(tmp_path)
    assert set(dict(M.ROLES)) == GAIN
    command.upgrade(cfg, "0121")
    with sqlite3.connect(db) as conn:
        after = _held(conn)
    # As the migration itself gives them (its frozen lists): app.roles has moved on since (51).
    assert after == {name: M._with_spawn(was) for name, was in M.ROLES}
    command.downgrade(cfg, M.down_revision)
    with sqlite3.connect(db) as conn:
        assert _held(conn) == before


@pytest.mark.parametrize("change", [
    lambda tools, builtin: (tools[:-1], builtin),  # a tool taken off by hand
    lambda tools, builtin: ([*tools, "show"], builtin),  # one added by hand
    lambda tools, builtin: (tools, 0),  # the user's own by that name
])
def test_one_the_user_changed_or_made_is_left_alone(tmp_path, change):
    cfg, db, before = _before(tmp_path, change)
    command.upgrade(cfg, "0121")
    with sqlite3.connect(db) as conn:
        assert _held(conn) == before
