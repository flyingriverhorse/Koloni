"""Slice 95: before a database is moved to a newer schema it is copied aside, so a migration that
goes wrong does not take every conversation, memory and setting with it. Only when a migration
will run; the last few copies are kept."""

import sqlite3

from alembic import command

from app.db.session import BACKUPS_KEPT, upgrade_db
from tests.test_migration_0002 import _config


def revision(db):
    with sqlite3.connect(db) as conn:
        return conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]


def test_a_database_behind_is_copied_aside_before_it_is_moved_on(tmp_path):
    db = tmp_path / "koloni.db"
    command.upgrade(_config(db), "0066")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO projects (id, name, root_path, created_at) "
                     "VALUES ('p', 'mine', 'C:/work/mine', '2026-10-24 01:00:00')")
    upgrade_db(db)
    (copy,) = (tmp_path / "backups").glob("koloni-0066-*.db")
    assert revision(copy) == "0066"  # as it was before the move
    with sqlite3.connect(copy) as conn:
        assert conn.execute("SELECT name FROM projects").fetchall() == [("mine",)]
    assert revision(db) != "0066"


def test_no_copy_when_nothing_moves_or_there_is_nothing_yet(tmp_path):
    db = tmp_path / "koloni.db"
    upgrade_db(db)  # a new database: nothing to keep
    upgrade_db(db)  # already at the newest schema: nothing moves
    assert not (tmp_path / "backups").exists()


def test_only_the_last_copies_are_kept(tmp_path):
    db = tmp_path / "koloni.db"
    command.upgrade(_config(db), "0066")
    backups = tmp_path / "backups"
    backups.mkdir()
    for n in range(BACKUPS_KEPT + 2):
        (backups / f"koloni-0060-2026010{n}T000000.db").write_bytes(b"old")
    (backups / "notes.txt").write_text("not ours")
    upgrade_db(db)
    kept = sorted(p.name for p in backups.glob("koloni-*.db"))
    assert len(kept) == BACKUPS_KEPT
    assert any(name.startswith("koloni-0066-") for name in kept)  # the new one stays
    assert (backups / "notes.txt").exists()
