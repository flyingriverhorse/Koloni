"""Migration 0153 (B-202): a team's lead's instructions say its roles do every file job - only
where they are still as KOLONİ gave them; an edited one and the Orchestrator's are left alone,
and going back gives the ready teams' words again."""

import importlib.util
import sqlite3
from pathlib import Path

from alembic import command

from app.roles import LEAD_INSTRUCTIONS
from tests.test_migration_0002 import _config
from tests.test_migration_0106 import _role, _said


def _frozen():
    """The migration itself, as a module: its frozen texts."""
    path = Path(__file__).parents[1] / "alembic" / "versions" / "0153_team_leads_hand_files.py"
    spec = importlib.util.spec_from_file_location("m0153", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


M = _frozen()
EDITED = "Run the stages; a small job stays with you."


def test_koloni_s_lead_words_are_rewritten_an_edited_one_and_the_orchestrators_are_not_and_back(
        tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0152")
    with sqlite3.connect(db) as conn:
        _role(conn, "Lead", f"Do small jobs yourself. {M.WAS_SPLITS}", 1, "plan")  # (its own words)
        _role(conn, "Made lead", M.WAS[1], 0, "lead")  # (a team made since K-isimler)
        _role(conn, "Mine lead", EDITED, 0, "lead")
    before = _said(db)
    ready = [name for name, does in before.items() if does == M.WAS[0]]
    assert ready  # (the ready teams' leads, as 0106 left them)
    orchestrator = before["Lead"]
    command.upgrade(cfg, "0153")
    after = _said(db)
    assert all(after[name] == M.NOW for name in [*ready, "Made lead"])
    assert after["Mine lead"] == EDITED and after["Lead"] == orchestrator
    command.downgrade(cfg, "0152")
    assert _said(db) == {**before, "Made lead": M.WAS[0]}


def test_a_new_teams_lead_is_given_the_migrations_words():
    assert LEAD_INSTRUCTIONS == M.NOW
