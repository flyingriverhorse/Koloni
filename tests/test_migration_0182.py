"""Migration 0182 (0.1.8, To-do in a chat): Run the backlog, Runs by itself and Run settings go -
the project's six columns of them, and what a task's flow held for them ("queued", "branch");
going back, the columns come back with their defaults."""

import json
import sqlite3

from alembic import command

from tests.test_migration_0002 import _config
from tests.test_migration_0177 import AT, columns

GONE = {
    "backlog_auto",
    "backlog_halt",
    "backlog_mode",
    "backlog_provider_id",
    "backlog_model_id",
    "backlog_lead_work",
}


def test_run_settings_go_and_old_queue_marks_are_cleared(tmp_path):
    db = tmp_path / "fresh.db"
    cfg = _config(db)
    command.upgrade(cfg, "0181")
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO projects (id, name, root_path, created_at, backlog_auto, backlog_mode) "
            "VALUES ('p', 'p', 'C:/p', ?, 1, 'full_auto')",
            (AT,),
        )
        for task_id, flow in (
            ("a", {"queued": True, "branch": True, "after": ["x"]}),
            ("b", {"queued": True}),
            ("c", {"stuck": "why"}),
            ("d", {"fix": "it failed", "fixed": True, "place": 2}),  # (0.1.7 left it doing)
        ):
            conn.execute(
                "INSERT INTO backlog_tasks (id, project_id, title, priority, status, position, "
                "created_by, created_at, flow) VALUES (?, 'p', ?, 'normal', ?, 0, 'user', ?, ?)",
                (task_id, task_id, "doing" if task_id == "d" else "todo", AT, json.dumps(flow)),
            )

    command.upgrade(cfg, "0182")

    with sqlite3.connect(db) as conn:
        assert not GONE & columns(conn, "projects")
        flows = dict(conn.execute("SELECT id, flow FROM backlog_tasks").fetchall())
        assert json.loads(flows["a"]) == {"after": ["x"]}
        assert flows["b"] is None and json.loads(flows["c"]) == {"stuck": "why"}
        # (a task 0.1.7 left doing: no fix round due, in no queue, todo again)
        assert json.loads(flows["d"]) == {"fixed": True}
        assert conn.execute("SELECT status FROM backlog_tasks WHERE id = 'd'").fetchone() == (
            "todo",
        )

    command.downgrade(cfg, "0181")

    with sqlite3.connect(db) as conn:
        assert columns(conn, "projects") >= GONE
        assert conn.execute("SELECT backlog_auto, backlog_mode FROM projects").fetchone() == (
            0,
            "ask",
        )
