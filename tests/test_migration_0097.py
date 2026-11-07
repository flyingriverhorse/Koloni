"""Migration 0097 (K-tetik-bitis, K-tetik-degismedi, 69): a trigger made before it runs as it
always did - even when nothing changed - and has no end; the built-in Lead and Planner get
propose_trigger; going back takes all of it away, and going up again gives it again."""

import importlib.util
import json
import sqlite3
from pathlib import Path

from alembic import command

from tests.test_migration_0002 import _config

AT = "2026-10-25"
# The revision 0097 follows, as the migration says it (it is re-pointed as branches land).
_spec = importlib.util.spec_from_file_location(
    "m0097", Path(__file__).parent.parent / "alembic" / "versions" / "0097_trigger_ends.py")
_m0097 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_m0097)
BEFORE = _m0097.down_revision
TOOLS = ["list_dir", "read_file", "post_note"]


def role(conn, name, builtin=1):
    conn.execute("INSERT INTO roles (id, name, description, instructions, tools, builtin, "
                 "created_by_agent, kind, mcp, skills, created_at, updated_at) VALUES (?, ?, '', "
                 "'', ?, ?, 0, 'plan', '[]', '[]', ?, ?)",
                 (name, name, json.dumps(TOOLS), builtin, AT, AT))


def tools(db):
    with sqlite3.connect(db) as conn:
        return {name: json.loads(listed) for name, listed in conn.execute(
            "SELECT name, tools FROM roles WHERE name IN ('Lead', 'Planner', 'Mine')")}


def test_triggers_made_before_run_as_they_did_and_the_lead_and_planner_may_propose(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, BEFORE)
    with sqlite3.connect(db) as conn:
        conn.execute("DELETE FROM roles WHERE name IN ('Lead', 'Planner')")
        role(conn, "Lead")
        role(conn, "Planner")
        role(conn, "Mine", builtin=0)
        conn.execute(
            "INSERT INTO triggers (id, project_id, conversation_id, name, kind, config, message, "
            "permissions, budget, catch_up, enabled, failures, created_at, updated_at) VALUES "
            "('t', 'p', 'c', 'old', 'schedule', '{\"every_minutes\": 60}', 'look', "
            "'{\"write\": false, \"commands\": [], \"agents\": 0}', "
            "'{\"steps\": 15, \"minutes\": 10, \"per_day\": 24}', 1, 1, 0, ?, ?)", (AT, AT))

    # (to before 28e's 0125, which gives view_image to whoever reads files)
    command.upgrade(cfg, "0123")

    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT run_unchanged, ends, ran, last_key FROM triggers").fetchall() == [
            (1, None, 0, None)]
        assert conn.execute("SELECT count(*) FROM trigger_proposals").fetchone() == (0,)
    assert tools(db) == {"Lead": [*TOOLS, "propose_trigger"], "Planner": [*TOOLS, "propose_trigger"],
                         "Mine": TOOLS}

    command.downgrade(cfg, BEFORE)

    assert tools(db) == {"Lead": TOOLS, "Planner": TOOLS, "Mine": TOOLS}
    with sqlite3.connect(db) as conn:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(triggers)")]
        assert not {"ends", "ran", "last_key", "run_unchanged"} & set(columns)
        assert conn.execute("SELECT name FROM sqlite_master WHERE name = 'trigger_proposals'"
                            ).fetchall() == []

    command.upgrade(cfg, "0123")

    assert tools(db)["Lead"] == [*TOOLS, "propose_trigger"]
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT run_unchanged FROM triggers").fetchall() == [(1,)]
