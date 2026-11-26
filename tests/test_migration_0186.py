"""Migration 0186 (0.1.9, ☾ Away's park and continue): the `parked` table and its two indexes come;
going back, a parked command is "rejected" and a parked question "cancelled" - the statuses before
it - and the table goes. It follows 0185, and 0187 follows it."""

import sqlite3

from alembic import command
from alembic.script import ScriptDirectory

from tests.test_migration_0002 import _config
from tests.test_migration_0177 import AT, tables


def _row(conn, table: str, **given) -> None:
    """A row of `table` with `given`, and a stand-in in each other column that must have one."""
    needed = {
        name: "x"
        for _cid, name, _type, notnull, default, key in conn.execute(f"PRAGMA table_info({table})")
        if notnull and default is None and not key
    }
    values = {**needed, **given}
    conn.execute(
        f"INSERT INTO {table} ({', '.join(values)}) VALUES ({', '.join('?' * len(values))})",
        list(values.values()),
    )


def _indexes(conn) -> set[str]:
    found = conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='parked'")
    return {name for (name,) in found}


def test_the_parked_table_comes_and_goes_and_parked_rows_go_back_to_their_old_statuses(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0185")
    with sqlite3.connect(db) as conn:
        assert "parked" not in tables(conn)

    command.upgrade(cfg, "0186")
    with sqlite3.connect(db) as conn:
        assert "parked" in tables(conn)
        assert _indexes(conn) >= {"ix_parked_away_run_id", "ix_parked_task_id"}
        _row(conn, "commands", id="c1", status="parked", command="python q.py", created_at=AT)
        _row(conn, "commands", id="c2", status="exited", command="echo hi", created_at=AT)
        _row(conn, "questions", id="q1", status="parked", question="which?", options="[]")
        _row(conn, "questions", id="q2", status="pending", question="why?", options="[]")
        _row(conn, "parked", id="p", seq=1, kind="command", what="python q.py", data="{}")

    command.downgrade(cfg, "0185")
    with sqlite3.connect(db) as conn:
        assert "parked" not in tables(conn)
        assert conn.execute("SELECT id, status FROM commands ORDER BY id").fetchall() == [
            ("c1", "rejected"),
            ("c2", "exited"),
        ]
        assert conn.execute("SELECT id, status FROM questions ORDER BY id").fetchall() == [
            ("q1", "cancelled"),
            ("q2", "pending"),
        ]


def test_it_follows_0185_and_0187_follows_it(tmp_path):
    # (which is the head is `test_migration_0089.test_one_head`'s)
    script = ScriptDirectory.from_config(_config(tmp_path / "x.db"))
    assert script.get_revision("0186").down_revision == "0185"
    assert script.get_revision("0187").down_revision == "0186"
