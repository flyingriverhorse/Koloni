"""Migration 0131 (K-kanit): the checking roles are told to say "verified" only of what they ran,
only where their instructions are still as KOLONİ gave them, and it is taken away going back."""

import importlib.util
import sqlite3
from pathlib import Path

from alembic import command

from app.roles import BUILTIN_ROLES
from tests.test_migration_0002 import _config
from tests.test_migration_0106 import _role


def _frozen():
    path = Path(__file__).parents[1] / "alembic" / "versions" / "0131_reviewer_ran.py"
    spec = importlib.util.spec_from_file_location("m0131", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


M = _frozen()
EDITED = "Review it my way."


def _said(db):
    with sqlite3.connect(db) as conn:
        return dict(conn.execute("SELECT name, instructions FROM roles"))


def test_stock_checking_roles_are_told_an_edited_one_is_not_and_back(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0130")
    with sqlite3.connect(db) as conn:
        for name, was in M.ROLES.items():
            _role(conn, name, EDITED if name == "Reviewer" else was, 1, "check")
    before = _said(db)
    command.upgrade(cfg, "0131")
    after = _said(db)
    for name in ("Tester", "Security reviewer", "Model evaluator"):
        # (a new install's words, from app.roles, are the same)
        assert after[name] == f"{M.ROLES[name]} {M.RAN}" == BUILTIN_ROLES[name].instructions
    assert after["Reviewer"] == EDITED
    assert f"{M.ROLES['Reviewer']} {M.RAN}" == BUILTIN_ROLES["Reviewer"].instructions
    command.downgrade(cfg, "0130")
    assert _said(db) == before
