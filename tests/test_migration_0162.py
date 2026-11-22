"""Migration 0162 (after a change): "Finish only when the tests pass" (89m) folds into After a change -
a project that had turned it off gets Nothing, every other one Check it; going back drops the new
setting and keeps the old one as it was."""

import sqlite3

from alembic import command

from tests.test_migration_0002 import _config

AT = "2026-11-22 10:00:00"


def _three_projects(db):
    with sqlite3.connect(db) as conn:
        for pid, finish in (("unset", None), ("on", 1), ("off", 0)):
            conn.execute("INSERT INTO projects (id, name, root_path, created_at, finish_tests) "
                         "VALUES (?, ?, ?, ?, ?)", (pid, pid, f"C:/{pid}", AT, finish))


def test_finish_tests_off_becomes_nothing_and_the_rest_check_it(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0161")
    _three_projects(db)

    command.upgrade(cfg, "0162")
    with sqlite3.connect(db) as conn:
        got = dict(conn.execute("SELECT id, after_change FROM projects").fetchall())
        assert got == {"unset": "check", "on": "check", "off": "nothing"}
        conn.execute("INSERT INTO projects (id, name, root_path, created_at) "
                     "VALUES ('new', 'new', 'C:/new', ?)", (AT,))
        assert conn.execute("SELECT after_change FROM projects WHERE id = 'new'").fetchone() \
            == ("check",)


def test_downgrade_drops_after_change_and_keeps_finish_tests(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0161")
    _three_projects(db)
    command.upgrade(cfg, "0162")

    command.downgrade(cfg, "0161")
    with sqlite3.connect(db) as conn:
        assert "after_change" not in [
            row[1] for row in conn.execute("PRAGMA table_info(projects)")]
        assert dict(conn.execute("SELECT id, finish_tests FROM projects").fetchall()) == {
            "unset": None, "on": 1, "off": 0}
