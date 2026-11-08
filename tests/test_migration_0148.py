"""Migration 0148 (R188): a chat in no project loses the old default room and discussion token
limits it still had; one somebody set, and a project's chat, keep theirs; going back gives a
plain chat with none the old defaults again."""

import sqlite3

from alembic import command

from tests.test_migration_0002 import _config

AT = "2026-11-05 10:00:00"
SHOW = "SELECT id, room_tokens, discussion_budget FROM conversations ORDER BY id"


def test_a_plain_chats_old_default_token_limits_go_and_a_set_one_stays(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0147")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO projects (id, root_path, name, created_at) "
                     "VALUES ('p', 'C:/x', 'x', ?)", (AT,))
        for cid, project, room, talk in (("old", None, 400_000, 200_000),
                                         ("set", None, 90_000, 50_000),
                                         ("kept", "p", 400_000, 200_000)):
            conn.execute(
                "INSERT INTO conversations (id, title, project_id, room_tokens, discussion_budget,"
                " created_at, updated_at) VALUES (?, 'c', ?, ?, ?, ?, ?)",
                (cid, project, room, talk, AT, AT))

    command.upgrade(cfg, "0148")
    with sqlite3.connect(db) as conn:
        assert conn.execute(SHOW).fetchall() == [
            ("kept", 400_000, 200_000), ("old", None, None), ("set", 90_000, 50_000)]

    command.downgrade(cfg, "0147")
    with sqlite3.connect(db) as conn:
        assert conn.execute(SHOW).fetchall() == [
            ("kept", 400_000, 200_000), ("old", 400_000, 200_000), ("set", 90_000, 50_000)]
