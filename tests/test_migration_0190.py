"""Migration 0190: the Observer is gone - the project's switch, what it said on each agent and the
built-in role; a role of the user's own named "Observer" stays. Going back, the columns come back
as 0049 made them, and nothing else of the tables it rebuilt has changed either way."""

import json
import sqlite3

from alembic import command

from tests.test_migration_0002 import _config
from tests.test_migration_0109 import _role
from tests.test_migration_0177 import AT, columns

GONE = {
    "agents": {"observation", "observation_note", "observed_by"},
    "projects": {"observe_reports"},
}


def shape(conn, table: str) -> tuple:
    """A table as SQLite has it: its columns (in no order: one added back comes last), its
    indexes and its foreign keys."""
    return (
        sorted(row[1:] for row in conn.execute(f"PRAGMA table_info({table})")),
        sorted(
            (name, unique, conn.execute(f"PRAGMA index_info({name})").fetchall())
            for _, name, unique, *_ in conn.execute(f"PRAGMA index_list({table})")
        ),
        sorted(row[2:] for row in conn.execute(f"PRAGMA foreign_key_list({table})")),
    )


def test_the_switch_the_observations_and_the_built_in_role_go_and_come_back(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0189")
    with sqlite3.connect(db) as conn:
        conn.execute("DELETE FROM role_teams")
        conn.execute("DELETE FROM roles")
        _role(conn, "obs", "Observer", [], "Compare the report with the record.")
        _role(conn, "rev", "Reviewer", ["read_file"], "Review it.")
        conn.execute(
            "INSERT INTO projects (id, name, root_path, created_at, observe_reports) "
            "VALUES ('p', 'p', 'C:/p', ?, 1)",
            (AT,),
        )
        conn.execute(
            "INSERT INTO agents (id, run_id, role_name, tools, depth, status, created_at, "
            "observation, observation_note, observed_by) VALUES "
            "('a', 'r', 'Coder', '[]', 1, 'completed', ?, 'The tests pass.', NULL, ?)",
            (AT, json.dumps({"provider_name": "Local", "model_id": "m"})),
        )
        conn.executemany(
            "INSERT INTO role_teams (role_id, team_id) VALUES (?, 'g')", [("obs",), ("rev",)]
        )
        before = {table: shape(conn, table) for table in GONE}

    command.upgrade(cfg, "0190")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT id FROM roles").fetchall() == [("rev",)]
        assert conn.execute("SELECT role_id FROM role_teams").fetchall() == [("rev",)]
        for table, gone in GONE.items():
            assert not gone & columns(conn, table)
            # (all else as it was: the rebuild kept the other columns, indexes and keys)
            kept = shape(conn, table)
            assert kept[0] == [row for row in before[table][0] if row[0] not in gone]
            assert kept[1:] == before[table][1:]
        assert conn.execute("SELECT id, status FROM agents").fetchall() == [("a", "completed")]
        assert conn.execute("SELECT id, name FROM projects").fetchall() == [("p", "p")]

    command.downgrade(cfg, "0189")
    with sqlite3.connect(db) as conn:
        assert {table: shape(conn, table) for table in GONE} == before
        assert conn.execute(
            "SELECT observe_reports FROM projects UNION ALL "
            "SELECT observation IS NULL AND observation_note IS NULL AND observed_by IS NULL "
            "FROM agents"
        ).fetchall() == [(0,), (1,)]


def test_a_role_of_the_users_own_named_observer_stays(tmp_path):
    db = tmp_path / "mine.db"
    cfg = _config(db)
    command.upgrade(cfg, "0189")
    with sqlite3.connect(db) as conn:
        conn.execute("DELETE FROM role_teams")
        conn.execute("DELETE FROM roles")
        _role(conn, "mine", "Observer", ["read_file"], "Mine.", builtin=0)
    command.upgrade(cfg, "0190")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT id, tools FROM roles").fetchall() == [("mine", '["read_file"]')]
