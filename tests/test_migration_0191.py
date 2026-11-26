"""Migration 0191 (0.1.10): the notification address and its form go; a day's summary that only
the address would have carried loses its time, one the desktop shows keeps it; going back, the
columns come back empty."""

import sqlite3

from alembic import command

from tests.test_migration_0002 import _config
from tests.test_migration_0177 import AT, columns

ADDRESS = "https://hooks.example.com/secret"


def test_the_address_goes_and_a_summary_with_nowhere_to_go_loses_its_time(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0190")
    with sqlite3.connect(db) as conn:
        for pid, desktop in (("hook", 0), ("both", 1)):
            conn.execute(
                "INSERT INTO projects (id, name, root_path, created_at, notify_url, "
                "notify_format, notify_desktop, day_note_at) VALUES (?, ?, ?, ?, ?, 'discord', ?, "
                "'18:00')",
                (pid, pid, f"C:/{pid}", AT, ADDRESS, desktop),
            )

    command.upgrade(cfg, "0191")
    with sqlite3.connect(db) as conn:
        assert not {"notify_url", "notify_format"} & columns(conn, "projects")
        assert conn.execute("SELECT id, day_note_at FROM projects ORDER BY id").fetchall() == [
            ("both", "18:00"),
            ("hook", None),
        ]

    command.downgrade(cfg, "0190")
    with sqlite3.connect(db) as conn:
        assert conn.execute(
            "SELECT id, notify_url, notify_format FROM projects ORDER BY id"
        ).fetchall() == [("both", None, "slack"), ("hook", None, "slack")]
