"""Migration 0137 (K-uzman-derin): an expert kept with the old page limit (20) reads up to the new
safety cap (500); one the user set otherwise keeps its own; and back."""

import json
import sqlite3

from alembic import command

from tests.test_migration_0002 import _config
from tests.test_migration_0106 import _role


def _pages(db):
    with sqlite3.connect(db) as conn:
        return {name: json.loads(known)["max_pages"] for name, known in conn.execute(
            "SELECT name, knowledge FROM roles WHERE knowledge IS NOT NULL")}


def test_the_old_default_page_limit_becomes_the_safety_cap_and_back(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0136")
    with sqlite3.connect(db) as conn:
        for name, most in (("Old expert", 20), ("Pay expert", 7)):
            _role(conn, name, "", 0, "plan")
            conn.execute("UPDATE roles SET knowledge = ? WHERE name = ?", (json.dumps(
                {"topic": name, "sources": ["https://docs.test"], "max_pages": most}), name))
        _role(conn, "Coder", "", 0, "plan")
    command.upgrade(cfg, "0137")
    assert _pages(db) == {"MLflow expert": 500, "Databricks expert": 500, "Old expert": 500,
                          "Pay expert": 7}
    command.downgrade(cfg, "0136")
    assert _pages(db) == {"MLflow expert": 20, "Databricks expert": 20, "Old expert": 20,
                          "Pay expert": 7}
    # One set past the old schema's 200 while upgraded: back within it.
    command.upgrade(cfg, "0137")
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE roles SET knowledge = json_set(knowledge, '$.max_pages', 700) "
                     "WHERE name = 'Pay expert'")
    command.downgrade(cfg, "0136")
    assert _pages(db)["Pay expert"] == 200
