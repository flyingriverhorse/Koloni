"""Migration 0085 (slice 85c): a file sent before it has no record of whose model saw it -
an empty one, not a missing one - and loses the column going back."""

import sqlite3

from alembic import command

from tests.test_migration_0002 import _config


def test_an_earlier_file_reads_back_with_no_one_shown_it_and_the_column_goes_back(tmp_path):
    db = tmp_path / "fresh.db"
    cfg = _config(db)
    command.upgrade(cfg, "0084")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO conversations (id, title, created_at, updated_at) "
                     "VALUES ('c', 'chat', '2026-10-25', '2026-10-25')")
        conn.execute("INSERT INTO attachments (id, conversation_id, name, kind, mime, size, "
                     "summary, created_at) VALUES ('a', 'c', 'shot.png', 'image', 'image/png', "
                     "32, 'PNG image', '2026-10-25')")

    command.upgrade(cfg, "head")

    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT shown_to FROM attachments").fetchone() == ("{}",)
    command.downgrade(cfg, "0084")
    with sqlite3.connect(db) as conn:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(attachments)")]
    assert "shown_to" not in columns and "given_to" in columns
