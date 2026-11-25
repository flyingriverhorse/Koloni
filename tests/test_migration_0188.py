"""Migration 0188 (0.1.9 §8): Check what I said first's box is ticked in a project made after it - a
judge model's measurement passed -, and a project already there keeps its box. Going back, a new
project's box is unticked again."""

import sqlite3

from alembic import command

from tests.test_migration_0002 import _config
from tests.test_migration_0177 import AT

INSERT = "INSERT INTO projects (id, name, root_path, created_at) VALUES (?, ?, ?, ?)"


def test_a_new_projects_box_is_ticked_and_one_there_keeps_its_own(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0187")
    with sqlite3.connect(db) as conn:
        conn.execute(INSERT, ("before", "before", "C:/before", AT))

    command.upgrade(cfg, "0188")
    with sqlite3.connect(db) as conn:
        conn.execute(INSERT, ("after", "after", "C:/after", AT))
        boxes = conn.execute("SELECT id, judge_words FROM projects ORDER BY id").fetchall()
    assert boxes == [("after", 1), ("before", 0)]

    command.downgrade(cfg, "0187")
    with sqlite3.connect(db) as conn:
        conn.execute(INSERT, ("back", "back", "C:/back", AT))
        back = conn.execute("SELECT judge_words FROM projects WHERE id = 'back'").fetchone()
    assert back == (0,)
