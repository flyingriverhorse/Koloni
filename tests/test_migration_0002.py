import sqlite3

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext

from app.config import REPO_ROOT
from app.db.models import Base, in_the_models
from app.db.session import make_engine


def _config(db) -> Config:
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db.as_posix()}")
    return cfg


def test_slice_1_data_is_carried_into_permission_modes(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0001")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO projects (id, name, root_path, created_at) "
                     "VALUES ('p', 'p', 'C:/p', '2026-10-05 10:00:00')")
        for cid, mode in (("a", "ask"), ("b", "auto")):
            conn.execute(
                "INSERT INTO conversations (id, project_id, title, edit_mode, created_at, updated_at)"
                " VALUES (?, 'p', 't', ?, '2026-10-05 10:00:00', '2026-10-05 10:00:00')",
                (cid, mode))

    command.upgrade(cfg, "head")

    with sqlite3.connect(db) as conn:
        modes = dict(conn.execute("SELECT id, permission_mode FROM conversations"))
        project = conn.execute(
            "SELECT exec_location, docker_image, docker_network FROM projects").fetchone()
        columns = [row[1] for row in conn.execute("PRAGMA table_info(conversations)")]
    assert modes == {"a": "ask", "b": "auto_edit"}
    assert project == ("host", None, 0)
    assert "edit_mode" not in columns

    with make_engine(db).connect() as conn:
        assert compare_metadata(MigrationContext.configure(conn, opts={"include_name": in_the_models}), Base.metadata) == []
