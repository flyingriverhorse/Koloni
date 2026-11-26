"""Migration 0192 (0.1.10): the search by meaning's vectors and a project's provider and model
for it go, the project and its linked projects stay; going back, they come back empty."""

import sqlite3

from alembic import command

from tests.test_migration_0002 import _config
from tests.test_migration_0177 import AT, columns


def test_the_vectors_and_the_choice_go_and_come_back_empty(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0191")
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO projects (id, name, root_path, created_at, memory_links, "
            "embedding_provider_id, embedding_model) VALUES ('p', 'p', 'C:/p', ?, '[\"q\"]', "
            "'prov', 'my-embed')",
            (AT,),
        )
        conn.execute(
            "INSERT INTO embeddings (kind, record_id, project_id, model, vector) "
            "VALUES ('memory', 'm', 'p', 'my-embed', '[0.1, 0.2]')"
        )

    command.upgrade(cfg, "0192")
    with sqlite3.connect(db) as conn:
        assert not {"embedding_provider_id", "embedding_model"} & columns(conn, "projects")
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'embeddings'"
        ).fetchone()
        assert conn.execute("SELECT id, memory_links FROM projects").fetchall() == [("p", '["q"]')]

    command.downgrade(cfg, "0191")
    with sqlite3.connect(db) as conn:
        assert conn.execute(
            "SELECT embedding_provider_id, embedding_model FROM projects"
        ).fetchall() == [(None, "text-embedding-3-small")]
        assert conn.execute("SELECT count(*) FROM embeddings").fetchone() == (0,)
    command.upgrade(cfg, "0192")  # (and up again)
