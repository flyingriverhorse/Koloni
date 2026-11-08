"""Migration 0091 (K-vekil-karar): a chat from before waits for the user while they are away,
after 10 minutes were it turned on; a question from before was nobody's but the user's to
answer. Going back takes the columns away."""

import sqlite3

from alembic import command

from tests.test_migration_0002 import _config

AT = "2026-10-27 10:00:00"


def test_chats_and_questions_from_before_wait_for_the_user(tmp_path):
    db = tmp_path / "fresh.db"
    cfg = _config(db)
    command.upgrade(cfg, "0090")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO conversations (id, title, created_at, updated_at) "
                     "VALUES ('c', 'c', ?, ?)", (AT, AT))

    command.upgrade(cfg, "head")

    with sqlite3.connect(db) as conn:
        assert conn.execute(
            "SELECT when_away, away_minutes FROM conversations").fetchall() == [("waits", 10)]
        columns = {row[1] for row in conn.execute("PRAGMA table_info(questions)")}
        assert {"lead_why", "seen_at"} <= columns

    command.downgrade(cfg, "0090")

    with sqlite3.connect(db) as conn:
        assert not {"when_away", "away_minutes"} & {
            row[1] for row in conn.execute("PRAGMA table_info(conversations)")}
        assert not {"lead_why", "seen_at"} & {
            row[1] for row in conn.execute("PRAGMA table_info(questions)")}
