"""Migration 0088 (K-canvas-dili, B-107): each turn keeps its chat teams' rows - the turn a row last
ran in keeps it as it is, in the chat's order, with what the canvas reads of its state; a turn no
row remembers has none; going back, the column is gone and the turns stay."""

import json
import sqlite3

from alembic import command

from tests.test_migration_0002 import _config

AT = "2026-10-26 10:00:00"


def test_a_turn_a_row_remembers_keeps_it_and_back(tmp_path):
    db = tmp_path / "fresh.db"
    cfg = _config(db)
    command.upgrade(cfg, "0087")
    state = {"run_id": "new", "team": "Web app", "recipe": "Feature", "status": "in", "why": None,
             "steps": [], "agents": ["a"], "ended_ready": True, "graph": {"steps": []}, "slots": {}}
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO conversations (id, title, created_at, updated_at) "
                     "VALUES ('c', 'c', ?, ?)", (AT, AT))
        for run in ("old", "new"):
            conn.execute("INSERT INTO runs (id, conversation_id, status, created_at) "
                         "VALUES (?, 'c', 'completed', ?)", (run, AT))
        for row, team, position, kept in (("t2", "docs", 1, {**state, "team": "Docs"}),
                                          ("t1", "web", 0, state), ("t3", "api", 2, None)):
            conn.execute("INSERT INTO conversation_teams (id, conversation_id, team_id, recipe_id, "
                         "picked_by, why, position, state) VALUES (?, 'c', ?, NULL, 'user', NULL, ?, ?)",
                         (row, team, position, kept and json.dumps(kept)))

    command.upgrade(cfg, "head")

    with sqlite3.connect(db) as conn:
        teams = dict(conn.execute("SELECT id, teams FROM runs").fetchall())
        assert teams["old"] is None
        shown = {key: value for key, value in state.items() if key not in ("graph", "slots")}
        assert json.loads(teams["new"]) == [
            {"team_id": "web", "recipe_id": None, "picked_by": "user", "why": None, "state": shown},
            {"team_id": "docs", "recipe_id": None, "picked_by": "user", "why": None,
             "state": {**shown, "team": "Docs"}}]

    command.downgrade(cfg, "0087")

    with sqlite3.connect(db) as conn:
        assert "teams" not in [row[1] for row in conn.execute("PRAGMA table_info(runs)")]
        assert sorted(conn.execute("SELECT id FROM runs").fetchall()) == [("new",), ("old",)]
