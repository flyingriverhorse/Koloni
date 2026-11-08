"""Where a CLI ran a command of its own is not known, and the record no longer says "."."""

import sqlite3

from alembic import command

from tests.test_migration_0002 import _config

INSERT = (
    "INSERT INTO commands (id, run_id, agent_id, tool_call_id, command, cwd, location, "
    "status, timeout_seconds, origin, output, output_truncated, created_at) "
    "VALUES (?, 'r', 'a', ?, 'echo hi', ?, 'host', 'exited', 0, ?, '', 0, "
    "'2026-10-06 10:00:00')"
)


def test_migration_0015_and_back(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0014")
    with sqlite3.connect(db) as conn:
        conn.execute(INSERT, ("k1", "t1", "pkg", "koloni"))
        conn.execute(INSERT, ("k2", "t2", ".", "cli"))
    command.upgrade(cfg, "0015")
    with sqlite3.connect(db) as conn:
        # KOLONİ's own command keeps the folder it ran in; the CLI's never had a known one
        assert conn.execute("SELECT id, cwd FROM commands ORDER BY id").fetchall() == [
            ("k1", "pkg"), ("k2", None)]
        conn.execute(INSERT, ("k3", "t3", None, "cli"))
    command.downgrade(cfg, "0014")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT id, cwd FROM commands ORDER BY id").fetchall() == [
            ("k1", "pkg"), ("k2", "."), ("k3", ".")]
