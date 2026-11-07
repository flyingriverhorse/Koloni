"""Migration 0138 (K-bilgi): a role's knowledge becomes a knowledge of every project (roles have no
project) that the role uses in full; its folder stays. Going back gives the role its knowledge as
it was."""

import json
import sqlite3

from alembic import command

from tests.test_migration_0002 import _config

AT = "2026-11-03 10:00:00"
KNOWN = {"topic": "Pay", "sources": ["docs/api.md", "https://docs.test/pay"], "max_pages": 30,
         "max_usd": 1.5, "learn_with": {"provider_id": "p", "model_id": "haiku"},
         "removed": ["https://docs.test/pay/old"], "weekly": True, "search_answering": True}


def test_an_experts_knowledge_moves_to_the_knowledge_page_and_back(tmp_path):
    db = tmp_path / "x.db"
    cfg = _config(db)
    command.upgrade(cfg, "0137")
    with sqlite3.connect(db) as conn:
        # ("o": saved before removed, weekly and search_answering were kept.)
        old = {"topic": "Old", "sources": ["old.md"], "max_pages": 20, "max_usd": 0.5,
               "learn_with": None}
        for rid, known in (("e", json.dumps(KNOWN)), ("r", None), ("o", json.dumps(old))):
            conn.execute("INSERT INTO roles (id, name, description, instructions, tools, builtin, "
                         "created_by_agent, kind, enabled, mcp, skills, knowledge, created_at, "
                         "updated_at) VALUES (?, ?, '', '', '[]', 0, 0, 'plan', 1, '[]', '[]', ?, ?, "
                         "?)", (rid, f"Mine {rid}", known, AT, AT))
        ready = dict(conn.execute("SELECT name, knowledge FROM roles WHERE knowledge IS NOT NULL"))

    command.upgrade(cfg, "0138")
    with sqlite3.connect(db) as conn:
        knows = {rid: json.loads(knows) for rid, knows in conn.execute(
            "SELECT id, knows FROM roles WHERE id IN ('e', 'r')")}
        assert knows["r"] == [] and [one["mode"] for one in knows["e"]] == ["full"]
        row = conn.execute("SELECT project_id, topic, sources, max_pages, max_usd, learn_with, "
                           "removed, weekly, search_web FROM knowledge WHERE id = ?",
                           (knows["e"][0]["knowledge_id"],)).fetchone()
        assert row == (None, "Pay", json.dumps(KNOWN["sources"]), 30, 1.5,
                       json.dumps(KNOWN["learn_with"]), json.dumps(KNOWN["removed"]), 1, 1)
        # 0103's ready experts (no project yet): theirs too, in every project.
        assert conn.execute("SELECT COUNT(*) FROM knowledge WHERE project_id IS NULL").fetchone() == (
            len(ready),)
        assert "knowledge" not in {one[1] for one in conn.execute("PRAGMA table_info(roles)")}
        assert conn.execute("SELECT removed, weekly, search_web FROM knowledge WHERE topic = 'Old'"
                            ).fetchone() == ("[]", 0, 0)

    command.downgrade(cfg, "0137")
    with sqlite3.connect(db) as conn:
        back = dict(conn.execute("SELECT name, knowledge FROM roles WHERE knowledge IS NOT NULL"))
        assert {name: json.loads(known) for name, known in back.items() if name != "Mine o"} == {
            name: json.loads(known) for name, known in ready.items() if name != "Mine o"}
        assert json.loads(back["Mine e"]) == KNOWN
        assert json.loads(back["Mine o"]) == {**old, "removed": [], "weekly": False,
                                              "search_answering": False}
        assert conn.execute("SELECT name FROM sqlite_master WHERE name = 'knowledge'").fetchall() == []
