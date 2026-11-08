"""Migration 0133 (K-tarayici-disari A3): a chat's site goes to its project - one site allowed
in two of its chats is one rule, marked Ask first if either was; a chat of no project keeps its
own, and a request rule stays the chat's. Going back, a project's site is on one of its chats."""

import sqlite3

from alembic import command

from tests.test_migration_0002 import _config

AT = "2026-11-03 10:00:00"


def test_a_chats_site_goes_to_its_project_and_back(tmp_path):
    db = tmp_path / "fresh.db"
    cfg = _config(db)
    command.upgrade(cfg, "0132")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO projects (id, name, root_path, created_at) "
                     "VALUES ('p', 'p', 'C:/p', ?)", (AT,))
        for cid, pid in (("c1", "p"), ("c2", "p"), ("c3", None)):
            conn.execute("INSERT INTO conversations (id, project_id, title, created_at, "
                         "updated_at) VALUES (?, ?, 't', ?, ?)", (cid, pid, AT, AT))
        for rid, cid, kind, host, ask in (
                ("w1", "c1", "page", "docs.test", 0), ("w2", "c2", "page", "docs.test", 1),
                ("w3", "c1", "host", "api.test", 0), ("w4", "c3", "page", "own.test", 0)):
            conn.execute("INSERT INTO allowed_web (id, conversation_id, kind, host, ask_first, "
                         "created_at) VALUES (?, ?, ?, ?, ?, ?)", (rid, cid, kind, host, ask, AT))

    command.upgrade(cfg, "0133")

    rows = "SELECT id, conversation_id, project_id, kind, host, ask_first FROM allowed_web ORDER BY id"
    with sqlite3.connect(db) as conn:
        assert conn.execute(rows).fetchall() == [
            ("w1", None, "p", "page", "docs.test", 1), ("w3", "c1", None, "host", "api.test", 0),
            ("w4", "c3", None, "page", "own.test", 0)]

    command.downgrade(cfg, "0132")

    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT id, conversation_id, kind, host, ask_first FROM allowed_web "
                            "ORDER BY id").fetchall() == [
            ("w1", "c1", "page", "docs.test", 1), ("w3", "c1", "host", "api.test", 0),
            ("w4", "c3", "page", "own.test", 0)]


def test_going_back_a_site_joins_the_chats_own_rule_for_it(tmp_path):
    db = tmp_path / "fresh.db"
    cfg = _config(db)
    command.upgrade(cfg, "0133")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO projects (id, name, root_path, created_at) "
                     "VALUES ('p', 'p', 'C:/p', ?)", (AT,))
        conn.execute("INSERT INTO conversations (id, project_id, title, created_at, updated_at) "
                     "VALUES ('c1', 'p', 't', ?, ?)", (AT, AT))
        # (A chat moved in before its sites went with it: its own unmarked rule beside the
        # project's marked one, and the project's site no chat holds.)
        for rid, cid, pid, host, ask in (("w1", None, "p", "docs.test", 1),
                                         ("w2", "c1", None, "docs.test", 0),
                                         ("w3", None, "p", "shop.test", 0)):
            conn.execute("INSERT INTO allowed_web (id, conversation_id, project_id, kind, host, "
                         "ask_first, created_at) VALUES (?, ?, ?, 'page', ?, ?, ?)",
                         (rid, cid, pid, host, ask, AT))

    command.downgrade(cfg, "0132")

    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT id, conversation_id, host, ask_first FROM allowed_web "
                            "ORDER BY id").fetchall() == [
            ("w2", "c1", "docs.test", 1), ("w3", "c1", "shop.test", 0)]
