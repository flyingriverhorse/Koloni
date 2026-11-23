"""Migration 0171 (Fix rounds: Until it passes, k-canli-016): a project still at the old default
2 moves to it (null); any other number is kept; going back makes it 2 again."""

import sqlite3

from alembic import command

from tests.test_migration_0002 import _config

AT = "2026-11-23 20:00:00"


def test_the_old_default_moves_to_until_it_passes_and_a_number_set_is_kept(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0169")
    with sqlite3.connect(db) as conn:
        for pid, rounds in (("a", 2), ("b", 3), ("c", 1)):
            conn.execute("INSERT INTO projects (id, name, root_path, created_at, fix_rounds) "
                         "VALUES (?, ?, ?, ?, ?)", (pid, pid, f"C:/{pid}", AT, rounds))
    command.upgrade(cfg, "0171")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT id, fix_rounds FROM projects ORDER BY id").fetchall() == [
            ("a", None), ("b", 3), ("c", 1)]
        conn.execute("INSERT INTO projects (id, name, root_path, created_at) "
                     "VALUES ('d', 'd', 'C:/d', ?)", (AT,))
        assert conn.execute("SELECT fix_rounds FROM projects WHERE id = 'd'").fetchone() == (
            None,)  # (a new project: until it passes)
    command.downgrade(cfg, "0169")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT id, fix_rounds FROM projects ORDER BY id").fetchall() == [
            ("a", 2), ("b", 3), ("c", 1), ("d", 2)]
