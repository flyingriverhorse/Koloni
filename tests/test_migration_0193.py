"""Migration 0193: rooms are gone - `open_room` from every role, the budgets a room spent from
every folder and chat, a recipe's Room step as an "All at once" group of its roles, and one line
in each chat that had a room. The rooms' own tables and what was said in them stay. Going back,
the line goes, the budgets come back at their defaults and the built-in Lead has the tool again."""

import json
import sqlite3

from alembic import command

from tests.test_migration_0002 import _config
from tests.test_migration_0109 import _role
from tests.test_migration_0177 import AT, columns

BUDGETS = {"room_posts", "room_tokens", "room_minutes", "room_min_tokens"}
MEETING = {
    "version": 1,
    "steps": [
        {"id": "plan", "name": "Plan", "who": {"role": "Planner"}},
        {"id": "meet", "name": "Build it", "who": {"room": ["Coder", "Tester"]}, "ask_me": True},
    ],
    "ends": [{"id": "end", "then": "in"}],
    "arrows": [
        {"from": "start", "to": "plan"},
        {"from": "plan", "to": "meet"},
        {"from": "meet", "to": "end"},
    ],
}


def tools_of(conn) -> dict:
    return {rid: json.loads(tools) for rid, tools in conn.execute("SELECT id, tools FROM roles")}


def test_rooms_go_and_what_was_said_in_them_stays(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0190")
    with sqlite3.connect(db) as conn:
        conn.execute("DELETE FROM role_teams")
        conn.execute("DELETE FROM roles")
        _role(conn, "lead", "Lead", ["read_file", "message_agent", "open_room", "discuss"], "")
        _role(conn, "mine", "Mine", ["read_file", "open_room"], "", builtin=0)
        conn.execute(
            "INSERT INTO recipes (id, name, ready, graph, created_at, updated_at) "
            "VALUES ('rc', 'Meet', 0, ?, ?, ?)",
            (json.dumps(MEETING), AT, AT),
        )
        conn.execute(
            "INSERT INTO projects (id, name, root_path, created_at, room_posts) "
            "VALUES ('p', 'p', 'C:/p', ?, 12)",
            (AT,),
        )
        conn.execute(
            "INSERT INTO conversations (id, project_id, title, created_at, updated_at) "
            "VALUES ('c', 'p', 'c', ?, ?)",
            (AT, AT),
        )
        conn.execute(
            "INSERT INTO runs (id, conversation_id, status, created_at) "
            "VALUES ('r', 'c', 'completed', ?)",
            (AT,),
        )
        conn.execute(
            "INSERT INTO rooms (id, run_id, goal, status, paused, lead_follows, seconds, "
            "created_at) VALUES ('room', 'r', 'Build it together', 'ended', 0, 'off', 0, ?)",
            (AT,),
        )
        conn.execute(
            "INSERT INTO room_posts (id, room_id, number, type, text, open, created_at) "
            "VALUES ('post', 'room', 1, 'result', 'Done: the page is built.', 0, ?)",
            (AT,),
        )

    command.upgrade(cfg, "0193")
    with sqlite3.connect(db) as conn:
        assert tools_of(conn) == {
            "lead": ["read_file", "message_agent", "discuss"],
            "mine": ["read_file"],
        }
        for table in ("projects", "conversations"):
            assert not BUDGETS & columns(conn, table)
        graph = json.loads(conn.execute("SELECT graph FROM recipes WHERE id = 'rc'").fetchone()[0])
        assert graph["groups"] == [{"id": "meet", "name": "Build it"}]
        assert [(s["id"], s["who"], s.get("group"), s.get("ask_me")) for s in graph["steps"]] == [
            ("plan", {"role": "Planner"}, None, None),
            ("meet-1", {"role": "Coder"}, "meet", True),
            ("meet-2", {"role": "Tester"}, "meet", True),
        ]
        assert graph["arrows"] == MEETING["arrows"]  # (they meet the group, by the step's id)
        (line,) = conn.execute(
            "SELECT run_id, conversation_id, status, created_at, content FROM messages "
            "WHERE role = 'koloni'"
        ).fetchall()
        assert line[:4] == ("r", "c", "complete", AT)
        assert "removed in 0.1.10" in line[4]
        # (kept as it was: the room and what was said in it are the user's)
        assert conn.execute("SELECT goal, status FROM rooms").fetchall() == [
            ("Build it together", "ended")
        ]
        assert conn.execute("SELECT text FROM room_posts").fetchall() == [
            ("Done: the page is built.",)
        ]

    command.downgrade(cfg, "0190")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT id FROM messages").fetchall() == []
        assert tools_of(conn) == {
            "lead": ["read_file", "message_agent", "open_room", "discuss"],
            "mine": ["read_file"],
        }
        for table in ("projects", "conversations"):
            assert columns(conn, table) >= BUDGETS
        assert conn.execute(
            "SELECT room_posts, room_tokens, room_minutes, room_min_tokens FROM projects"
        ).fetchall() == [(40, None, 30, 60000)]
        assert conn.execute("SELECT COUNT(*) FROM rooms").fetchone() == (1,)
