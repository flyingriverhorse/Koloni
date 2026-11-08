"""Migration 0089 (K-not-oda): a note carries its team and whether it is for every team, and
KOLONİ's own note is told apart from the user's; a note from before is the whole turn's, as it
was; going back, the columns go and the notes stay."""

import sqlite3

from alembic import command
from alembic.script import ScriptDirectory

from tests.test_migration_0002 import _config

AT = "2026-10-27 10:00:00"
NEW = ["team_id", "team", "everyone", "koloni"]


def columns(conn):
    return [row[1] for row in conn.execute("PRAGMA table_info(board_posts)")]


def test_a_note_from_before_is_the_whole_turns_and_back(tmp_path):
    db = tmp_path / "fresh.db"
    cfg = _config(db)
    command.upgrade(cfg, "0088")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO conversations (id, title, created_at, updated_at) "
                     "VALUES ('c', 'c', ?, ?)", (AT, AT))
        conn.execute("INSERT INTO runs (id, conversation_id, status, created_at) "
                     "VALUES ('r', 'c', 'completed', ?)", (AT,))
        conn.execute("INSERT INTO board_posts (id, run_id, conversation_id, agent_id, content, seq, "
                     "created_at) VALUES ('p', 'r', 'c', NULL, 'mind the tests', 1, ?)", (AT,))

    command.upgrade(cfg, "head")

    with sqlite3.connect(db) as conn:
        assert columns(conn)[-4:] == NEW
        assert conn.execute("SELECT content, team_id, team, everyone, koloni FROM board_posts").fetchall() == [
            ("mind the tests", None, None, 0, 0)]

    command.downgrade(cfg, "0088")

    with sqlite3.connect(db) as conn:
        assert not set(NEW) & set(columns(conn))
        assert conn.execute("SELECT content FROM board_posts").fetchall() == [("mind the tests",)]


def test_one_head(tmp_path):
    assert ScriptDirectory.from_config(_config(tmp_path / "x.db")).get_heads() == ["0154"]
