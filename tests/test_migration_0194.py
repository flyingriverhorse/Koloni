"""Migration 0194: three ready teams. The other eight KOLONİ made go where they are as they came -
their stages, lead and the Lead's rows with them, their roles kept; one the user changed or uses
stays as theirs. A chat the Lead picked a gone team for keeps its other rows."""

import json
import sqlite3

from alembic import command

from app import roles
from app.db.session import make_engine, make_session_factory
from tests.test_chat_teams_scenarios import FORMER
from tests.test_migration_0002 import _config
from tests.test_migration_0109 import _role
from tests.test_migration_0177 import AT

READY = {
    "Web app": ("Coder", "Tester", "Reviewer"),
    "Docs": ("Docs writer", "Spec writer"),
    "Quality": ("Tester", "Reviewer", "Security reviewer", "Debugger"),
    "Backend / API": (
        "Coder",
        "Architect",
        "Database engineer",
        "Tester",
        "Reviewer",
        "Security reviewer",
        "Performance engineer",
    ),
    "Data": ("Data analyst", "Database engineer", "Researcher", "Reviewer"),
    "DevOps": ("DevOps", "Security reviewer", "Dependency keeper", "Performance engineer"),
    "Research": ("Researcher", "Summarizer", "Spec writer"),
    "Product": ("Hive keeper", "Scout", "Spec writer"),
    "Maintenance": ("Refactorer", "Dependency keeper", "Debugger", "Tester"),
    # ("MLOps engineer" is not made: an older install's - not a role taken out of the team)
    "ML": ("Data scientist", "ML engineer", "Model evaluator", "Tester"),
    "DataOps": ("Data engineer", "Database engineer", "Data analyst", "Tester"),
}


def _seeded(tmp_path):
    """A database at 0193 whose ready teams hold their built-in roles, as after a start."""
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0193")
    with sqlite3.connect(db) as conn:
        teams = dict(conn.execute("SELECT name, id FROM teams"))
        names = sorted({name for held in READY.values() for name in held})
        for at, name in enumerate(names):
            _role(conn, f"r{at}", name, [], "Work.")
        ids = {name: f"r{at}" for at, name in enumerate(names)}
        for team, held in READY.items():
            conn.executemany(
                "INSERT INTO role_teams (role_id, team_id) VALUES (?, ?)",
                [(ids[name], teams[team]) for name in held],
            )
    return db, cfg, teams, ids


def _left(conn) -> set[str]:
    return {name for (name,) in conn.execute("SELECT name FROM teams")}


def test_only_the_ready_teams_as_they_came_go_and_their_roles_stay(tmp_path):
    db, cfg, teams, ids = _seeded(tmp_path)
    with sqlite3.connect(db) as conn:
        leads = dict(conn.execute("SELECT name, lead_role_id FROM teams"))
        # Data: a role of the user's own put in.
        _role(conn, "mine", "My analyst", [], "Mine.", builtin=0)
        conn.execute(
            "INSERT INTO role_teams (role_id, team_id) VALUES ('mine', ?)", (teams["Data"],)
        )
        # Research: a ready role taken out.
        conn.execute(
            "DELETE FROM role_teams WHERE team_id = ? AND role_id = ?",
            (teams["Research"], ids["Summarizer"]),
        )
        # Product: a stage renamed.
        conn.execute(
            "UPDATE team_stages SET name = 'Code' WHERE team_id = ? AND name = 'Build'",
            (teams["Product"],),
        )
        # Maintenance: picked by the user in a chat; Backend / API by the Lead beside Web app.
        conn.execute(
            "INSERT INTO conversations (id, title, teams_mode, created_at, updated_at) "
            "VALUES ('c', 't', 'manual', ?, ?), ('d', 't', 'lead', ?, ?)",
            (AT, AT, AT, AT),
        )
        conn.executemany(
            "INSERT INTO conversation_teams (id, conversation_id, team_id, picked_by, position) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                ("u", "c", teams["Maintenance"], "user", 0),
                ("w", "d", teams["Web app"], "lead", 0),
                ("b", "d", teams["Backend / API"], "lead", 1),
            ],
        )
        # DevOps: kept for a project's new chats.
        conn.execute(
            "INSERT INTO projects (id, name, root_path, created_at, teams_mode, teams) "
            "VALUES ('p', 'p', 'C:/p', ?, 'manual', ?)",
            (AT, json.dumps([{"team_id": teams["DevOps"], "recipe_id": None}])),
        )
        # DataOps: named by a recipe's step (whatever its case).
        conn.execute(
            "INSERT INTO recipes (id, name, ready, graph, created_at, updated_at) "
            "VALUES ('x', 'Mine', 0, ?, ?, ?)",
            (json.dumps({"steps": [{"id": "s", "who": {"team": "dataops"}}]}), AT, AT),
        )
        roles_before = {row for row in conn.execute("SELECT id FROM roles WHERE kind != 'lead'")}

    command.upgrade(cfg, "0194")
    with sqlite3.connect(db) as conn:
        assert _left(conn) == {
            "Web app",
            "Docs",
            "Quality",
            "Data",
            "Research",
            "Product",
            "Maintenance",
            "DevOps",
            "DataOps",
        }
        gone = (teams["Backend / API"], teams["ML"])
        for table in ("role_teams", "team_stages", "conversation_teams"):
            assert conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE team_id IN (?, ?)", gone
            ).fetchone() == (0,), table
        # Their leads go with them; every other role stays - the ML experts too, in no team now.
        assert {
            name
            for (name,) in conn.execute(
                "SELECT name FROM roles WHERE id IN (?, ?)",
                (leads["Backend / API"], leads["ML"]),
            )
        } == set()
        assert {row for row in conn.execute("SELECT id FROM roles WHERE kind != 'lead'")} == (
            roles_before
        )
        assert {
            name for (name,) in conn.execute("SELECT name FROM roles WHERE name LIKE '%expert'")
        } == {
            "MLflow expert",
            "Databricks expert",
        }
        # The Lead's chat keeps its other row; the user's chat keeps its team.
        assert conn.execute("SELECT id FROM conversation_teams ORDER BY id").fetchall() == [
            ("u",),
            ("w",),
        ]
        # A kept team keeps what it had.
        assert conn.execute(
            "SELECT COUNT(*) FROM role_teams WHERE team_id = ?", (teams["Data"],)
        ).fetchone() == (5,)

    command.downgrade(cfg, "0193")
    with sqlite3.connect(db) as conn:
        assert "Backend / API" not in _left(conn)  # (put back the copy made before, to go back)


def test_a_ready_team_whose_lead_recipe_or_name_the_user_changed_or_a_manual_chat_has_stays(
    tmp_path,
):
    db, cfg, teams, _ids = _seeded(tmp_path)
    with sqlite3.connect(db) as conn:
        leads = dict(conn.execute("SELECT name, lead_role_id FROM teams"))
        conn.execute("UPDATE teams SET lead_on = 0 WHERE id = ?", (teams["Backend / API"],))
        conn.execute("UPDATE teams SET lead_may_pick = 0 WHERE id = ?", (teams["Data"],))
        conn.execute("UPDATE teams SET default_recipe_id = NULL WHERE id = ?", (teams["DevOps"],))
        conn.execute(
            "UPDATE roles SET updated_at = '2026-11-25 09:00:00' WHERE id = ?",
            (leads["Research"],),
        )
        conn.execute("UPDATE teams SET name = 'Our product' WHERE id = ?", (teams["Product"],))
        conn.execute(
            "UPDATE team_stages SET together = 1 WHERE team_id = ? AND name = 'Check'",
            (teams["Maintenance"],),
        )
        # ML: picked by the Lead in a chat the user then put in Manual - kept for them to change.
        conn.execute(
            "INSERT INTO conversations (id, title, teams_mode, created_at, updated_at) "
            "VALUES ('m', 't', 'manual', ?, ?)",
            (AT, AT),
        )
        conn.execute(
            "INSERT INTO conversation_teams (id, conversation_id, team_id, picked_by, position) "
            "VALUES ('r', 'm', ?, 'lead', 0)",
            (teams["ML"],),
        )

    command.upgrade(cfg, "0194")
    with sqlite3.connect(db) as conn:
        assert _left(conn) == {
            "Web app",
            "Docs",
            "Quality",
            "Backend / API",
            "Data",
            "DevOps",
            "Research",
            "Our product",
            "Maintenance",
            "ML",
        }


def test_a_new_database_has_the_three(tmp_path):
    cfg = _config(tmp_path / "new.db")
    command.upgrade(cfg, "head")
    with sqlite3.connect(tmp_path / "new.db") as conn:
        assert _left(conn) == {"Web app", "Docs", "Quality"}
        assert conn.execute("SELECT COUNT(*) FROM roles WHERE kind = 'lead'").fetchone() == (3,)


def test_where_a_role_sits_and_an_expert_taken_out_tell_a_changed_team(tmp_path, monkeypatch):
    """Seeded as 0.1.9 seeds a start - each role in its kind's stage - then: a role moved to
    another stage, and an expert taken out of ML, are the user's changes; a placement from
    before 0103 moved a role's kind (the Dependency keeper in Write & keep up) is not."""
    db = tmp_path / "seeded.db"
    cfg = _config(db)
    command.upgrade(cfg, "0193")
    eleven = dict(roles.READY_TEAMS) | {
        name: tuple(one for one in held if not one.endswith(" expert"))
        for name, (held, _recipe) in FORMER.items()
    }
    monkeypatch.setattr(roles, "READY_TEAMS", eleven)
    with make_session_factory(make_engine(db))() as session:
        roles.seed_builtin_roles(session)
    with sqlite3.connect(db) as conn:
        teams = dict(conn.execute("SELECT name, id FROM teams"))
        ids = dict(conn.execute("SELECT name, id FROM roles"))

        def stage(team: str, name: str) -> str:
            return conn.execute(
                "SELECT id FROM team_stages WHERE team_id = ? AND name = ?", (teams[team], name)
            ).fetchone()[0]

        def sit(team: str, role: str, at: str) -> None:
            conn.execute(
                "UPDATE role_teams SET stage_id = ? WHERE team_id = ? AND role_id = ?",
                (stage(team, at), teams[team], ids[role]),
            )

        sit("Backend / API", "Tester", "Build")  # (its kind's is Check)
        conn.execute(
            "DELETE FROM role_teams WHERE team_id = ? AND role_id = ?",
            (teams["ML"], ids["MLflow expert"]),
        )
        sit("Maintenance", "Dependency keeper", "Write & keep up")  # (before 0103)

    command.upgrade(cfg, "0194")
    with sqlite3.connect(db) as conn:
        assert _left(conn) == {"Web app", "Docs", "Quality", "Backend / API", "ML"}
