"""K-drawio: migration 0128 gives the four roles that write documents, designs and code
diagram_image - only where their tools are still as KOLONİ gave them, in any order (B-335) and
with or without what later migrations gave (28e's view_image, slice 51's browser)."""

import importlib.util
import json
import sqlite3
from pathlib import Path

from alembic import command

from app.roles import BROWSER, BUILTIN_ROLES, DIAGRAM
from tests.test_migration_0002 import _config
from tests.test_migration_0109 import _role

GAIN = {"Lead", "Coder", "Docs writer", "UI designer"}


def test_who_draws_diagrams():
    # (K-belge-ciktilari's Designer is made with it, by no migration.)
    assert {name for name, spec in BUILTIN_ROLES.items()
            if set(DIAGRAM) <= set(spec.tools)} == GAIN | {"Designer"}


def _frozen():
    path = Path(__file__).parents[1] / "alembic" / "versions" / "0128_diagram_image.py"
    spec = importlib.util.spec_from_file_location("m0128", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


M = _frozen()
NAMES = ", ".join(f"'{name}'" for name, _ in M.ROLES)


def _held(conn):
    return {name: json.loads(tools) for name, tools in conn.execute(
        f"SELECT name, tools FROM roles WHERE name IN ({NAMES})")}


def _before(tmp_path, change=lambda name, tools: tools):
    cfg = _config(db := tmp_path / "r.db")
    command.upgrade(cfg, M.down_revision)
    with sqlite3.connect(db) as conn:
        conn.execute(f"DELETE FROM roles WHERE name IN ({NAMES})")
        for at, (name, tools) in enumerate(M.ROLES):
            _role(conn, str(at), name, change(name, tools), "as given", 1)
        return cfg, db, _held(conn)


def _bare(tools):
    """Without view_image, which app.roles gives every reader (28e)."""
    return [tool for tool in tools if tool != "view_image"]


def _upgrade_and_back(cfg, db, before):
    command.upgrade(cfg, "0128")
    with sqlite3.connect(db) as conn:
        after = _held(conn)
    command.downgrade(cfg, M.down_revision)
    with sqlite3.connect(db) as conn:
        assert _held(conn) == before
    return after


def test_stock_ones_gain_it_where_app_roles_has_it_and_going_back_is_exact(tmp_path):
    assert set(dict(M.ROLES)) == GAIN
    after = _upgrade_and_back(*_before(tmp_path))
    for name in GAIN:
        assert after[name] == _bare(BUILTIN_ROLES[name].tools), name


def test_a_list_with_view_image_gains_it_too_after_it(tmp_path):
    after = _upgrade_and_back(*_before(
        tmp_path, lambda name, tools: [*tools[:3], "view_image", *tools[3:]]))
    assert after["Docs writer"][:7] == ["list_dir", "read_file", "search", "view_image",
                                        "write_file", "edit_file", "diagram_image"]
    for name in GAIN:
        assert after[name] == list(BUILTIN_ROLES[name].tools), name


def test_an_upgraded_lead_in_another_order_or_with_the_browser_appended_gains_it(tmp_path):
    """B-335: a Lead upgraded over the years has propose_trigger last, or the browser tools
    appended - KOLONİ's own list all the same."""
    def upgraded(name, tools):
        if name == "Lead":
            return [*[t for t in tools if t not in ("propose_trigger", *BROWSER)],
                    "propose_trigger", *BROWSER]
        if name == "Coder":
            return [*[t for t in tools if t not in BROWSER], *BROWSER]
        return tools
    cfg, db, before = _before(tmp_path, upgraded)
    after = _upgrade_and_back(cfg, db, before)
    for name in GAIN:
        assert "diagram_image" in after[name], name
        assert sorted(after[name]) == sorted([*before[name], "diagram_image"]), name


def test_a_list_the_user_changed_is_left_alone_both_ways(tmp_path):
    cfg, db, before = _before(tmp_path, lambda name, tools: tools[:-1])
    assert _upgrade_and_back(cfg, db, before) == before
