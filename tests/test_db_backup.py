"""Slice 95: before a database is moved to a newer schema it is copied aside, so a migration that
goes wrong does not take every conversation, memory and setting with it. Only when a migration
will run; the last few copies are kept. And a routine copy at the start, one a day, the last few
kept, whatever the schema: a long-lived install has one between releases too."""

import sqlite3
from datetime import UTC, datetime, timedelta

from alembic import command

from app.db.session import BACKUPS_KEPT, DAILY_KEPT, back_up_daily, upgrade_db
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


# --- the routine copy: one a day at the start, whatever the schema ---------------------------

AT = datetime(2026, 11, 14, 9, 0, tzinfo=UTC)


def _daily(tmp_path) -> list[str]:
    return sorted(p.name for p in (tmp_path / "backups").glob("daily-*"))


def test_a_start_with_no_copy_of_the_day_makes_one_and_the_same_day_no_other(tmp_path):
    db = tmp_path / "koloni.db"
    upgrade_db(db)
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO projects (id, name, root_path, created_at) "
                     "VALUES ('p', 'mine', 'C:/work/mine', '2026-10-24 01:00:00')")
    back_up_daily(db, AT)
    assert _daily(tmp_path) == ["daily-koloni-20261114T090000.db"]
    with sqlite3.connect(tmp_path / "backups" / "daily-koloni-20261114T090000.db") as conn:
        assert conn.execute("SELECT name FROM projects").fetchall() == [("mine",)]
    # Started again the same UTC date, to its last second: none.
    back_up_daily(db, AT + timedelta(hours=3))
    back_up_daily(db, AT.replace(hour=23, minute=59, second=59))
    assert _daily(tmp_path) == ["daily-koloni-20261114T090000.db"]
    # The next date, though less than a day on (09:00, then 08:58): one.
    back_up_daily(db, AT + timedelta(hours=23, minutes=58))
    assert _daily(tmp_path) == ["daily-koloni-20261114T090000.db",
                                "daily-koloni-20261115T085800.db"]


def test_a_copy_named_later_than_now_is_no_copy_of_today_and_the_first_to_go(tmp_path):
    """A clock that was a year ahead for one start: it held back every copy after it."""
    db = tmp_path / "koloni.db"
    upgrade_db(db)
    backups = tmp_path / "backups"
    backups.mkdir()
    (backups / "daily-koloni-20271114T090000.db").write_bytes(b"ahead")
    for day in range(DAILY_KEPT - 1):
        back_up_daily(db, AT + timedelta(days=day))
    # Kept while the copies are few: it may be the newest there is.
    assert _daily(tmp_path) == ["daily-koloni-20261114T090000.db",
                                "daily-koloni-20261115T090000.db",
                                "daily-koloni-20271114T090000.db"]
    back_up_daily(db, AT + timedelta(days=DAILY_KEPT))
    assert _daily(tmp_path) == ["daily-koloni-20261114T090000.db",
                                "daily-koloni-20261115T090000.db",
                                f"daily-koloni-202611{14 + DAILY_KEPT}T090000.db"]


def test_only_the_last_routine_copies_are_kept_and_no_other_file_goes(tmp_path):
    db = tmp_path / "koloni.db"
    command.upgrade(_config(db), "0066")
    backups = tmp_path / "backups"
    backups.mkdir()
    for day in range(1, DAILY_KEPT + 2):
        (backups / f"daily-koloni-2026110{day}T000000.db").write_bytes(b"old")
    # A copy made before a migration, the update script's, a file of the user's, one of another
    # shape, and what a copy that was cut short left.
    others = ["koloni-0060-20250101T000000.db", "koloni-20250101T000000.db", "notes.txt",
              "daily-koloni-mine.db"]
    for name in others:
        (backups / name).write_bytes(b"not ours")
    (backups / "daily-koloni-20261101T000000.db.part").write_bytes(b"half")
    back_up_daily(db, AT)
    assert sorted(p.name for p in backups.iterdir()) == sorted([
        *others, *(f"daily-koloni-2026110{day}T000000.db" for day in (DAILY_KEPT, DAILY_KEPT + 1)),
        "daily-koloni-20261114T090000.db"])
    # And the copy before a migration neither counts a routine one among its own nor deletes it.
    upgrade_db(db)
    assert len(_daily(tmp_path)) == DAILY_KEPT + 1  # (the one of another shape too)
    assert len(list(backups.glob("koloni-0066-*.db"))) == 1


def test_a_copy_that_fails_is_logged_and_the_start_goes_on(tmp_path, monkeypatch, caplog):
    from app.db import session

    db = tmp_path / "koloni.db"
    upgrade_db(db)

    def full(_conn, to):
        to.write_bytes(b"half")
        raise sqlite3.OperationalError("database or disk is full")

    monkeypatch.setattr(session, "_copy", full)
    back_up_daily(db, AT)
    assert "database not copied" in caplog.text and "disk is full" in caplog.text
    assert not list((tmp_path / "backups").iterdir())  # no copy, and none half made
    # What cannot be deleted either stops no start; the next one makes the copy and clears it.
    held = tmp_path / "backups" / "daily-koloni-20261114T090000.db.part"
    monkeypatch.setattr(type(held), "unlink", lambda *_, **__: (_ for _ in ()).throw(
        PermissionError("held")))
    back_up_daily(db, AT)
    assert held.exists()
    monkeypatch.undo()
    back_up_daily(db, AT + timedelta(minutes=5))
    assert [p.name for p in (tmp_path / "backups").iterdir()] == [
        "daily-koloni-20261114T090500.db"]


def test_the_start_that_serves_makes_the_copy_and_an_app_a_test_makes_does_not(
        tmp_path, monkeypatch, settings):
    import logging.config
    from types import SimpleNamespace

    from app import main

    main.create_app(settings)
    assert not (settings.db_path.parent / "backups").exists()
    copied = []
    monkeypatch.setenv("KOLONI_RUNTIME_ROOT", str(tmp_path / "served"))
    monkeypatch.setattr(main, "not_dumpable", lambda: None)
    monkeypatch.setattr(logging.config, "dictConfig", lambda _config: None)
    monkeypatch.setattr(main, "create_app", lambda _settings: SimpleNamespace(
        state=SimpleNamespace(page_key="k")))
    monkeypatch.setattr(main, "show_link", lambda *_: None)
    monkeypatch.setattr(main, "back_up_daily", copied.append)
    monkeypatch.setattr(main, "serve", lambda *_, **__: copied.append("served"))
    main.run()
    assert copied == [tmp_path / "served" / "data" / "koloni.db", "served"]
