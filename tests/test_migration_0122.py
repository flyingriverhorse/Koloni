"""Slice 51: migration 0122 gives the six roles that try a page the browser tools - only
where their tools are still as KOLONİ gave them."""

import importlib.util
import json
import sqlite3
from pathlib import Path

from alembic import command

from app.roles import BROWSER, BUILTIN_ROLES
from tests.test_migration_0002 import _config
from tests.test_migration_0109 import _role

GAIN = {"Lead", "Coder", "Tester", "Researcher", "Debugger", "UI designer"}


def test_who_tries_a_page():
    # (K-belge-ciktilari's Designer and K-site-roller's three are made with them, by no migration.)
    later = {"Designer", "SEO specialist", "Copywriter", "Accessibility reviewer"}
    given = {name: spec for name, spec in BUILTIN_ROLES.items() if name not in later}
    assert {name for name, spec in given.items() if set(BROWSER) <= set(spec.tools)} == GAIN
    assert not any(set(BROWSER) & set(spec.tools) for name, spec in given.items()
                   if name not in GAIN)


def _frozen():
    path = Path(__file__).parents[1] / "alembic" / "versions" / "0122_browser_tools.py"
    spec = importlib.util.spec_from_file_location("m0122", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


M = _frozen()
NAMES = ", ".join(f"'{name}'" for name, _ in M.ROLES)


def _held(conn):
    return {name: json.loads(tools) for name, tools in conn.execute(
        f"SELECT name, tools FROM roles WHERE name IN ({NAMES})")}


def _before(tmp_path, change=lambda tools, builtin: (tools, builtin)):
    cfg = _config(db := tmp_path / "r.db")
    command.upgrade(cfg, M.down_revision)
    with sqlite3.connect(db) as conn:
        conn.execute(f"DELETE FROM roles WHERE name IN ({NAMES})")
        for at, (name, tools) in enumerate(M.ROLES):
            tools, builtin = change(tools, 1)
            _role(conn, str(at), name, tools, "as given", builtin)
        return cfg, db, _held(conn)


def test_stock_ones_gain_the_browser_where_app_roles_has_it_and_going_back_is_exact(tmp_path):
    cfg, db, before = _before(tmp_path)
    assert set(dict(M.ROLES)) == GAIN
    command.upgrade(cfg, "0122")
    with sqlite3.connect(db) as conn:
        after = _held(conn)
    for name in GAIN:
        # (28e's view_image comes with 0125, K-drawio's diagram_image with 0128)
        assert after[name] == [t for t in BUILTIN_ROLES[name].tools
                               if t not in ("view_image", "diagram_image")], name
    command.downgrade(cfg, M.down_revision)
    with sqlite3.connect(db) as conn:
        assert _held(conn) == before


def test_a_list_the_user_changed_is_left_alone_both_ways(tmp_path):
    cfg, db, before = _before(tmp_path, lambda tools, builtin: (tools[:-1], builtin))
    command.upgrade(cfg, "0122")
    with sqlite3.connect(db) as conn:
        assert _held(conn) == before
    command.downgrade(cfg, M.down_revision)
    with sqlite3.connect(db) as conn:
        assert _held(conn) == before


def test_the_same_tools_in_another_order_still_gain_the_browser(tmp_path):
    # B-335: 0097 put propose_trigger last on an upgraded install's Lead.
    cfg, db, _ = _before(tmp_path, lambda tools, builtin: (tools[::-1], builtin))
    command.upgrade(cfg, "0122")
    with sqlite3.connect(db) as conn:
        after = _held(conn)
    for name in GAIN:
        assert set(after[name]) == set(BUILTIN_ROLES[name].tools) - {"view_image", "diagram_image"}, name
