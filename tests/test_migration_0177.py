"""Migration 0177 (0.1.8, To-do in a chat): goals and stories, a task's story and kind, a turn's
task and a topic's story. A task kept from before is a task of no story; going back, the tables
and the columns go and the task stays."""

import sqlite3

from alembic import command

from tests.test_migration_0002 import _config

AT = "2026-11-24 10:00:00"


def tables(conn) -> set[str]:
    return {name for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def columns(conn, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def test_goals_stories_and_the_links_come_and_go(tmp_path):
    db = tmp_path / "fresh.db"
    cfg = _config(db)
    command.upgrade(cfg, "0176")
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO projects (id, name, root_path, created_at) VALUES ('p', 'p', 'C:/p', ?)",
            (AT,),
        )
        conn.execute(
            "INSERT INTO backlog_tasks (id, project_id, title, priority, status, position, "
            "created_by, created_at) VALUES ('t', 'p', 'old', 'normal', 'todo', 0, 'user', ?)",
            (AT,),
        )

    command.upgrade(cfg, "0177")

    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT kind, story_id FROM backlog_tasks").fetchall() == [
            ("task", None)
        ]
        assert {"goals", "stories"} <= tables(conn)
        assert {"task_id"} <= columns(conn, "runs") and {"story_id"} <= columns(conn, "topics")
        # (a story made outside the app's code has its notes empty, not null)
        conn.execute(
            "INSERT INTO stories (id, project_id, title, position, created_by, created_at) "
            "VALUES ('s', 'p', 'Login', 0, 'user', ?)",
            (AT,),
        )
        assert conn.execute("SELECT notes FROM stories").fetchall() == [("[]",)]

    command.downgrade(cfg, "0176")

    with sqlite3.connect(db) as conn:
        assert not {"goals", "stories"} & tables(conn)
        assert not {"kind", "story_id"} & columns(conn, "backlog_tasks")
        assert "task_id" not in columns(conn, "runs")
        assert "story_id" not in columns(conn, "topics")
        assert conn.execute("SELECT title FROM backlog_tasks").fetchall() == [("old",)]
