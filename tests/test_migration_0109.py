"""Migration 0109 (B-190): the built-in Spec writer and Summarizer, where still as KOLONİ gave
them, write the document they are asked for; one the user changed is left alone; going back
puts back exactly what was there."""

import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest
from alembic import command

from tests.test_migration_0002 import _config

AT = "2026-10-28 10:00:00"


def _role(conn, rid, name, tools, instructions, builtin=1):
    conn.execute("INSERT INTO roles (id, name, description, instructions, tools, builtin, "
                 "created_by_agent, kind, mcp, skills, created_at, updated_at) VALUES "
                 "(?, ?, '', ?, ?, ?, 0, 'write', '[]', '[]', ?, ?)",
                 (rid, name, instructions, json.dumps(tools), builtin, AT, AT))


def _held(conn):
    return {name: (json.loads(tools), said) for name, tools, said in conn.execute(
        "SELECT name, tools, instructions FROM roles WHERE name IN ('Spec writer', 'Summarizer')")}


def _frozen():
    """The migration itself, as a module: its frozen texts."""
    path = Path(__file__).parents[1] / "alembic" / "versions" / "0109_spec_summary_write.py"
    spec = importlib.util.spec_from_file_location("m0109", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


M = _frozen()


def _before(tmp_path, change=lambda name, tools, said, builtin: (tools, said, builtin)):
    """A database just before 0109 with both roles as KOLONI gave them - or as `change` makes
    them - and what they held."""
    cfg = _config(db := tmp_path / "r.db")
    command.upgrade(cfg, M.down_revision)
    with sqlite3.connect(db) as conn:
        conn.execute("DELETE FROM roles WHERE name IN ('Spec writer', 'Summarizer')")
        for name, tools, said, _tools, _said in M.ROLES:
            _role(conn, name[:4], name, *change(name, tools, said, 1))
        return cfg, db, _held(conn)


def test_stock_ones_write_the_document_asked_for_and_going_back_is_exact(tmp_path):
    cfg, db, before = _before(tmp_path)
    command.upgrade(cfg, "0109")
    with sqlite3.connect(db) as conn:
        after = _held(conn)
    # As the migration says, word for word (a later one, 0120, moves the Spec writer on).
    assert after == {name: (new_tools, new_said) for name, _t, _s, new_tools, new_said in M.ROLES}
    assert all({"write_file", "edit_file"} <= set(tools) for tools, _said in after.values())
    command.downgrade(cfg, M.down_revision)
    with sqlite3.connect(db) as conn:
        assert _held(conn) == before
    command.upgrade(cfg, "0109")
    with sqlite3.connect(db) as conn:
        assert _held(conn) == after


@pytest.mark.parametrize("change", [
    lambda name, tools, said, builtin: (tools, said + " Mine.", builtin),  # its words changed
    lambda name, tools, said, builtin: (tools[:-1], said, builtin),  # a tool taken off
    lambda name, tools, said, builtin: (tools, said, 0),  # the user's own by that name
])
def test_one_the_user_changed_or_made_is_left_alone(tmp_path, change):
    cfg, db, before = _before(tmp_path, change)
    command.upgrade(cfg, "0109")
    with sqlite3.connect(db) as conn:
        assert _held(conn) == before
