"""Migration 0073 (slice 63a) on a database made before it: every team gets four stages, each
of its roles in the one of its kind of work (the first where its kind is its own), and a lead
card; going back takes the stages and the leads away and leaves the teams and roles."""

import json
import sqlite3

from alembic import command
from sqlalchemy.orm import Session

from app.db.session import make_engine
from app.roles import find_agent_role, list_roles
from tests.test_migration_0002 import _config

AT = "2026-10-25 10:00:00"
LONG = "W" * 60


def test_teams_get_their_stages_and_a_lead_and_lose_them_going_back(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0072")
    with sqlite3.connect(db) as conn:
        for rid, name, kind in (("c", "Coder", "build"), ("t", "Tester", "check"),
                                ("s", "Shipper", "Ship it"), ("o", "Art lead", "build"),
                                # A kind of the user's own words that reads "lead" (before 63a).
                                ("k", "Captain", "lead"), ("w", f"{LONG[:55]} lead", "build")):
            conn.execute(
                "INSERT INTO roles (id, name, description, instructions, tools, builtin, "
                "created_by_agent, kind, mcp, skills, created_at, updated_at) "
                "VALUES (?, ?, '', '', '[]', 1, 0, ?, '[]', '[]', ?, ?)", (rid, name, kind, AT, AT))
        conn.execute("INSERT INTO teams (id, name, created_at) VALUES ('g', 'Art', ?)", (AT,))
        conn.execute("INSERT INTO teams (id, name, created_at) VALUES ('l', ?, ?)", (LONG, AT))
        conn.executemany("INSERT INTO role_teams (role_id, team_id) VALUES (?, 'g')",
                         [("c",), ("t",), ("s",)])

    command.upgrade(cfg, "head")

    with sqlite3.connect(db) as conn:
        stages = conn.execute("SELECT name, position, together FROM team_stages "
                              "WHERE team_id = 'g' ORDER BY position").fetchall()
        placed = dict(conn.execute(
            "SELECT role_teams.role_id, team_stages.name FROM role_teams "
            "JOIN team_stages ON team_stages.id = role_teams.stage_id WHERE role_teams.team_id = 'g'"))
        lead_id, on, may_pick = conn.execute(
            "SELECT lead_role_id, lead_on, lead_may_pick FROM teams WHERE id = 'g'").fetchone()
        name, kind, instructions, tools = conn.execute(
            "SELECT name, kind, instructions, tools FROM roles WHERE id = ?", (lead_id,)).fetchone()
        ready = conn.execute("SELECT COUNT(*) FROM teams WHERE lead_role_id IS NULL").fetchone()
        (long_lead,) = conn.execute(
            "SELECT roles.name FROM roles JOIN teams ON teams.lead_role_id = roles.id "
            "WHERE teams.id = 'l'").fetchone()
    # Its name taken, a long team's lead is numbered and still a role's name (60 at most).
    assert len(long_lead) <= 60 and long_lead.endswith(" lead 2")
    # The user's role of kind "lead" is no team's lead: listed, and opened as any other.
    engine = make_engine(db)
    with Session(engine) as session:
        assert "Captain" in [role.name for role in list_roles(session)]
        assert find_agent_role(session, "Captain") is not None
        assert "Art lead 2" not in [role.name for role in list_roles(session)]
    engine.dispose()
    assert stages == [("Plan", 0, 0), ("Build", 1, 0), ("Check", 2, 0), ("Write & keep up", 3, 0)]
    assert placed == {"c": "Build", "t": "Check", "s": "Plan"}
    assert (on, may_pick, kind) == (1, 1, "lead")
    assert name == "Art lead 2"  # "Art lead" was taken
    assert instructions.startswith("Run your team's stages in order") and "spawn_agent" in json.loads(tools)
    assert ready == (0,)  # every team, the ready ones too, has its lead

    command.downgrade(cfg, "0072")

    with sqlite3.connect(db) as conn:
        # The teams' leads go; the user's own role stays.
        assert conn.execute("SELECT id FROM roles WHERE kind = 'lead'").fetchall() == [("k",)]
        assert conn.execute("SELECT COUNT(*) FROM role_teams WHERE team_id = 'g'").fetchone() == (3,)
        assert {row[1] for row in conn.execute("PRAGMA table_info(teams)")} == {
            "id", "name", "created_at"}
        assert "team_stages" not in {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
