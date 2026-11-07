"""Migration 0065 (slice 81b) on a database made before it: a built-in role still at the tier
it came with loses it (the Lead picks one for each job now), a tier the user gave is kept;
every role gets a kind of work, and the ready teams are made with the roles there are."""

import sqlite3

from alembic import command

from tests.test_migration_0002 import _config

AT = "2026-10-20 10:00:00"


def test_built_in_tiers_go_unless_the_user_gave_one_and_the_ready_teams_come(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0064")
    with sqlite3.connect(db) as conn:
        for rid, name, builtin, tier in (
            ("p", "Planner", 1, "strongest"),   # as it came: strongest
            ("c", "Coder", 1, "fast"),          # the user's own choice (it came strongest)
            ("t", "Tester", 1, None),           # the user took its tier away
            ("m", "Shipper", 0, "strongest"),   # a role of the user's own
        ):
            conn.execute(
                "INSERT INTO roles (id, name, description, instructions, tools, builtin, "
                "created_by_agent, tier, mcp, skills, created_at, updated_at) "
                "VALUES (?, ?, '', '', '[]', ?, 0, ?, '[]', '[]', ?, ?)",
                (rid, name, builtin, tier, AT, AT))

    command.upgrade(cfg, "head")

    with sqlite3.connect(db) as conn:
        roles = {rid: (tier, kind, enabled) for rid, tier, kind, enabled in conn.execute(
            "SELECT id, tier, kind, enabled FROM roles WHERE kind != 'lead' AND knows = '[]'")}
        # (Not 63a's leads, nor 0103's experts.)
        teams = dict(conn.execute("SELECT name, id FROM teams"))
        coder_in = {name for (name,) in conn.execute(
            "SELECT teams.name FROM role_teams JOIN teams ON teams.id = role_teams.team_id "
            "WHERE role_teams.role_id = 'c'")}
        mine_in = conn.execute("SELECT COUNT(*) FROM role_teams WHERE role_id = 'm'").fetchone()
    assert roles == {
        "p": (None, "plan", 1), "c": ("fast", "build", 1), "t": (None, "check", 1),
        "m": ("strongest", "build", 1),
    }
    assert len(teams) == 11 and coder_in == {"Web app", "Backend / API"}  # (0103: ML, DataOps)
    assert mine_in == (0,)  # only built-in roles join a ready team
