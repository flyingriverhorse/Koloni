"""Migration 0080 (K-lider-araclari): every team's lead whose tools are still the ones 0073
gave it - a ready team's, renamed or not, or one of the user's - gets open_room and discuss; one
the user changed is left as it is; going back takes the two away again."""

import json
import sqlite3

from alembic import command

from tests.test_migration_0002 import _config

SEEDED = ["list_dir", "read_file", "search", "spawn_agent", "ask_user", "message_agent",
          "post_note", "read_notes", "remember", "recall"]
WITH_ROOMS = [*SEEDED[:6], "open_room", "discuss", *SEEDED[6:]]
EDITED = ["list_dir", "read_file", "spawn_agent"]
AT = "2026-10-25"


def leads(db):
    with sqlite3.connect(db) as conn:
        return {team: json.loads(tools) for team, tools in conn.execute(
            "SELECT teams.name, roles.tools FROM teams JOIN roles ON roles.id = teams.lead_role_id")}


def team(conn, name, tools):
    """A team of the user's with its lead, as 63a makes one."""
    conn.execute("INSERT INTO roles (id, name, description, instructions, tools, builtin, "
                 "created_by_agent, kind, mcp, skills, created_at, updated_at) VALUES (?, ?, '', "
                 "'', ?, 0, 0, 'lead', '[]', '[]', ?, ?)",
                 (f"{name}-l", f"{name} lead", json.dumps(tools), AT, AT))
    conn.execute("INSERT INTO teams (id, name, created_at, lead_role_id, lead_on, lead_may_pick) "
                 "VALUES (?, ?, ?, ?, 1, 1)", (name, name, AT, f"{name}-l"))


def test_every_untouched_lead_gets_the_room_tools_and_loses_them_going_back(tmp_path):
    db = tmp_path / "fresh.db"
    cfg = _config(db)
    command.upgrade(cfg, "0079")
    assert leads(db)["Web app"] == SEEDED and leads(db)["Docs"] == SEEDED
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE roles SET tools = ? WHERE id = (SELECT lead_role_id FROM teams "
                     "WHERE name = 'Docs')", (json.dumps(EDITED),))
        conn.execute("UPDATE teams SET name = 'Infra' WHERE name = 'Ops'")
        team(conn, "Art", SEEDED)
        team(conn, "Paint", EDITED)
    before = leads(db)

    # (to before 28e's 0125, which gives view_image to whoever reads files)
    command.upgrade(cfg, "0123")

    after = leads(db)
    assert (after["Docs"], after["Paint"]) == (EDITED, EDITED)
    assert after["Infra"] == after["Art"] == after["Web app"] == WITH_ROOMS
    assert all(tools == WITH_ROOMS for name, tools in after.items() if name not in ("Docs", "Paint"))

    command.downgrade(cfg, "0079")

    assert leads(db) == before
