"""Migration 0187 (0.1.9): what Full auto's judge does with a command it finds risky - "refuse"
(the agent goes on) in every project, those kept from before too; going back, the choice goes."""

import sqlite3

from alembic import command

from tests.test_migration_0002 import _config
from tests.test_migration_0177 import AT, columns


def test_every_project_refuses_and_the_choice_goes_back(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0186")
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO projects (id, name, root_path, created_at) VALUES ('p', 'p', 'C:/p', ?)",
            (AT,),
        )

    command.upgrade(cfg, "0187")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT judge_risky FROM projects").fetchall() == [("refuse",)]
        conn.execute(
            "INSERT INTO projects (id, name, root_path, created_at) VALUES ('n', 'n', 'C:/n', ?)",
            (AT,),
        )
        assert conn.execute("SELECT judge_risky FROM projects WHERE id = 'n'").fetchone() == (
            "refuse",
        )

    command.downgrade(cfg, "0186")
    with sqlite3.connect(db) as conn:
        assert "judge_risky" not in columns(conn, "projects")
        assert conn.execute("SELECT id FROM projects ORDER BY id").fetchall() == [("n",), ("p",)]
