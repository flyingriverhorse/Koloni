"""Migration 0106 (K-rol-cogul): the split rule is added to the Lead's and the teams' leads'
instructions only where they are still as KOLONİ gave them, and taken away again going back."""

import importlib.util
import sqlite3
from pathlib import Path

from alembic import command

from tests.test_migration_0002 import _config


def _frozen():
    """The migration itself, as a module: its frozen texts - not today's `app.roles`, whose
    words move on (K-isimler: "report to the Orchestrator")."""
    path = Path(__file__).parents[1] / "alembic" / "versions" / "0106_lead_splits_work.py"
    spec = importlib.util.spec_from_file_location("m0106", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


M = _frozen()
STOCK_LEAD, STOCK_TEAM_LEAD = M.LEAD, M.TEAM_LEAD
EDITED = "Run the stages; ask me before anything big."


def _role(conn, name, does, builtin, kind):
    conn.execute(
        "INSERT INTO roles (id, name, description, instructions, tools, builtin, "
        "created_by_agent, kind, enabled, mcp, skills, created_at, updated_at) "
        "VALUES (?, ?, '', ?, '[]', ?, 0, ?, 1, '[]', '[]', '2026-10-28', '2026-10-28')",
        (name, name, does, builtin, kind))


def _said(db):
    with sqlite3.connect(db) as conn:
        return dict(conn.execute("SELECT name, instructions FROM roles WHERE name = 'Lead' "
                                 "OR kind = 'lead'"))


def test_unchanged_leads_are_told_to_split_an_edited_one_is_not_and_back(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0105")
    with sqlite3.connect(db) as conn:
        _role(conn, "Lead", STOCK_LEAD, 1, "plan")
        _role(conn, "Mine lead", EDITED, 0, "lead")
    before = _said(db)
    ready = [name for name, does in before.items() if does == STOCK_TEAM_LEAD]
    assert ready  # (the ready teams' leads, as 0073/0103 made them)
    command.upgrade(cfg, "0106")
    after = _said(db)
    assert after["Lead"] == f"{M.LEAD} {M.LEAD_SPLITS}"
    assert all(after[name] == f"{M.TEAM_LEAD} {M.TEAM_SPLITS}" for name in ready)
    assert after["Mine lead"] == EDITED
    command.downgrade(cfg, "0105")
    assert _said(db) == before
