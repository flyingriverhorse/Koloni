"""Migration 0183 (0.1.9, Full auto's judge): a project's switch of it, on in the projects there are
too; the user's Judge model, none chosen; and the lines not asked about again. Going back, all three
go."""

import sqlite3

from alembic import command

from tests.test_migration_0002 import _config
from tests.test_migration_0177 import AT, columns, tables


def test_the_judge_is_on_in_a_project_there_was_and_its_record_comes_and_goes(tmp_path):
    db = tmp_path / "fresh.db"
    cfg = _config(db)
    command.upgrade(cfg, "0182")
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO projects (id, name, root_path, created_at) VALUES ('p', 'p', 'C:/p', ?)",
            (AT,),
        )
        conn.execute("INSERT INTO user_preferences (id, text) VALUES (1, 'be brief')")

    command.upgrade(cfg, "0183")

    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT full_auto_judge FROM projects").fetchone() == (1,)
        assert conn.execute(
            "SELECT text, judge_provider_id, judge_model_id FROM user_preferences"
        ).fetchone() == ("be brief", None, None)
        conn.execute(
            "INSERT INTO judge_allowed (id, project_id, command, cwd, program_sha, created_at) "
            "VALUES ('a', 'p', 'python gen.py', '.', '', ?)",
            (AT,),
        )
        try:
            conn.execute(
                "INSERT INTO judge_allowed (id, project_id, command, cwd, program_sha, created_at)"
                " VALUES ('b', 'p', 'python gen.py', '.', '', ?)",
                (AT,),
            )
            raise AssertionError("the same line twice")
        except sqlite3.IntegrityError:
            pass

    command.downgrade(cfg, "0182")

    with sqlite3.connect(db) as conn:
        assert "full_auto_judge" not in columns(conn, "projects")
        assert not {"judge_provider_id", "judge_model_id"} & columns(conn, "user_preferences")
        assert "judge_allowed" not in tables(conn)
