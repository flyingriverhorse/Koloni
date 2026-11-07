"""Migration 0103 (K-takim-duzen): the Data, ML and Ops categories after Build, the built-in roles
moved there that were still where they began; the ready ML and DataOps teams with the MLflow and
Databricks experts in ML; the ready Ops named DevOps; eight ready recipes, each its ready team's
default. What the user changed is left: a renamed team, a recipe they picked or made by the name,
a role or a category of their own by a new one's name. Going back puts it all back - an expert
the user changed is theirs - and up again is as the first time."""

import json
import sqlite3

from alembic import command
from sqlalchemy import select

from app import roles
from app.db.models import Role, RoleTeam, Team
from app.db.session import make_engine, make_session_factory
from tests.test_migration_0002 import _config
from tests.test_migration_0093 import AT, _defaults

NEW = {"ML": "Model change", "DataOps": "Pipeline change", "DevOps": "Infra change",
       "Docs": "Docs", "Research": "Research", "Product": "Spec", "Data": "Analysis",
       "Maintenance": "Upkeep"}


def _categories(conn):
    return conn.execute("SELECT key, name, position FROM categories ORDER BY position").fetchall()


def _members(conn, team):
    return sorted(name for (name,) in conn.execute(
        "SELECT roles.name FROM roles JOIN role_teams ON role_teams.role_id = roles.id "
        "JOIN teams ON teams.id = role_teams.team_id WHERE teams.name = ?", (team,)))


# A role's knowledge, as data: since 0136 the row of `knowledge` it uses (K-bilgi).
KNOWS = ("(SELECT json_object('topic', topic, 'sources', json(sources)) FROM knowledge "
         "WHERE id = json_extract(roles.knows, '$[0].knowledge_id'))")


def _all(conn):
    return (_categories(conn), _defaults(conn), sorted(conn.execute(
        f"SELECT name, kind, builtin, {KNOWS} FROM roles WHERE kind != 'lead'").fetchall()))


def test_a_fresh_database_up_down_and_up_again(tmp_path):
    db = tmp_path / "fresh.db"
    cfg = _config(db)
    command.upgrade(cfg, "head")
    with sqlite3.connect(db) as conn:
        first = _all(conn)
        assert [key for key, _name, _at in _categories(conn)] == [
            "plan", "build", "data", "ml", "ops", "check", "write"]
        assert {team: _defaults(conn)[team] for team in NEW} == NEW
        assert "Ops" not in _defaults(conn)
        leads = {name for (name,) in conn.execute("SELECT name FROM roles WHERE kind = 'lead'")}
        assert {"ML lead", "DataOps lead", "DevOps lead"} <= leads and "Ops lead" not in leads
        experts = dict(conn.execute(f"SELECT name, {KNOWS} FROM roles WHERE {KNOWS} IS NOT NULL"))
        assert {name: json.loads(known)["sources"] for name, known in experts.items()} == {
            "MLflow expert": ["https://mlflow.org/docs/latest/"],
            "Databricks expert": ["https://docs.databricks.com/aws/en/"]}
        # The user's: AWS for now, and Azure or GCP told apart when named.
        does = dict(conn.execute(
            f"SELECT name, instructions FROM roles WHERE {KNOWS} IS NOT NULL"))
        assert does["MLflow expert"] == "" and "unless told otherwise" in does["Databricks expert"]
        assert all(one in does["Databricks expert"] for one in (
            "https://learn.microsoft.com/azure/databricks/", "https://docs.databricks.com/gcp/en/"))
        assert _members(conn, "ML") == ["Databricks expert", "MLflow expert"]  # (no built-in yet)
        # Each new team as one the Agents page makes: its four stages.
        assert conn.execute("SELECT COUNT(*) FROM team_stages JOIN teams ON teams.id = team_id "
                            "WHERE teams.name IN ('ML', 'DataOps')").fetchone() == (8,)

    command.downgrade(cfg, "0102")
    with sqlite3.connect(db) as conn:
        assert [key for key, _name, _at in _categories(conn)] == ["plan", "build", "check", "write"]
        found = _defaults(conn)
        assert (found["Ops"], found["Docs"]) == (None, None)
        assert not {"DevOps", "ML", "DataOps"} & set(found)
        assert conn.execute("SELECT COUNT(*) FROM recipes WHERE name IN "
                            f"({', '.join('?' * len(NEW))})", list(NEW.values())).fetchone() == (0,)
        assert conn.execute("SELECT name FROM roles WHERE name LIKE '%expert' OR name LIKE "
                            "'ML%' OR name LIKE 'DataOps%'").fetchall() == []

    command.upgrade(cfg, "head")
    with sqlite3.connect(db) as conn:
        assert _all(conn) == first


def _role(conn, name, kind, builtin=1):
    conn.execute("INSERT INTO roles (id, name, description, instructions, tools, builtin, "
                 "created_by_agent, kind, created_at, updated_at) "
                 "VALUES (?, ?, '', '', '[]', ?, 0, ?, ?, ?)", (name, name, builtin, kind, AT, AT))


def test_an_old_database_keeps_what_the_user_changed(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0102")
    with sqlite3.connect(db) as conn:
        # The built-in roles as they were, DevOps moved by the user; roles of the user's own by a
        # new role's and an expert's name; a category of theirs named Ops.
        for name, kind in (("Tester", "check"), ("Data analyst", "check"),
                           ("Database engineer", "build"), ("Dependency keeper", "write"),
                           ("DevOps", "check")):
            _role(conn, name, kind)
        _role(conn, "Data engineer", "build", builtin=0)
        _role(conn, "MLflow expert", "plan", builtin=0)
        conn.execute("INSERT INTO categories (key, name, colour, position) VALUES ('u', 'Ops', 'rose', 4)")
        # Docs renamed; Research's recipe picked; a recipe of the user's own named Analysis.
        conn.execute("UPDATE teams SET name = 'Writing' WHERE name = 'Docs'")
        conn.execute("INSERT INTO recipes (id, name, ready, graph, created_at, updated_at) "
                     "VALUES ('mine', 'Mine', 0, '{}', ?, ?), ('own', 'analysis', 0, '{}', ?, ?)",
                     (AT, AT, AT, AT))
        conn.execute("UPDATE teams SET default_recipe_id = 'mine' WHERE name = 'Research'")

    command.upgrade(cfg, "head")
    with sqlite3.connect(db) as conn:
        assert [(key, name) for key, name, _at in _categories(conn)] == [
            ("plan", "Plan"), ("build", "Build"), ("data", "Data"), ("ml", "ML"), ("ops", "Ops 2"),
            ("check", "Check"), ("write", "Write & keep up"), ("u", "Ops")]
        kinds = dict(conn.execute("SELECT name, kind FROM roles WHERE kind != 'lead'"))
        assert kinds == {"Tester": "check", "Data analyst": "check", "Database engineer": "data",
                         "Dependency keeper": "ops", "DevOps": "check", "Data engineer": "build",
                         "MLflow expert": "plan", "Databricks expert": "plan"}
        found = _defaults(conn)
        assert (found["Writing"], found["Research"], found["Data"]) == (None, "Mine", None)
        assert (found["DevOps"], found["ML"], found["Maintenance"]) == (
            "Infra change", "Model change", "Upkeep")
        assert conn.execute(f"SELECT {KNOWS} FROM roles WHERE name = 'MLflow expert'").fetchone() == (None,)
        assert _members(conn, "ML") == ["Databricks expert", "Tester"]
        assert _members(conn, "DataOps") == ["Data analyst", "Database engineer", "Tester"]

    # At the next start: the new built-in roles join, each in its stage; the user's own
    # Data engineer is left as it is.
    with make_session_factory(make_engine(db))() as session:
        roles.seed_builtin_roles(session)
        mine = session.scalar(select(Role).where(Role.name == "Data engineer"))
        assert (mine.builtin, mine.teams) == (False, [])
        ml = session.scalar(select(Team).where(Team.name == "ML"))
        stage = {s.id: s.name for s in ml.stages}
        placed = {session.get_one(Role, link.role_id).name: stage[link.stage_id] for link in
                  session.scalars(select(RoleTeam).where(RoleTeam.team_id == ml.id))}
        assert placed == {"Data scientist": "Plan", "ML engineer": "Build", "MLOps engineer": "Build",
                          "Model evaluator": "Check", "Tester": "Check", "Databricks expert": "Plan"}

    command.downgrade(cfg, "0102")
    with sqlite3.connect(db) as conn:
        kinds = dict(conn.execute("SELECT name, kind FROM roles WHERE kind != 'lead'"))
        assert (kinds["Database engineer"], kinds["Dependency keeper"], kinds["DevOps"]) == (
            "build", "write", "check")
        assert _categories(conn)[-1] == ("u", "Ops", 4)
        assert _defaults(conn)["Research"] == "Mine"
        # (The user's own MLflow expert stays; the Databricks expert, as made, goes.)
        assert conn.execute("SELECT name FROM roles WHERE name LIKE '%expert'").fetchall() == [
            ("MLflow expert",)]


def test_a_users_own_ml_team_is_given_no_role_and_an_expert_they_changed_stays(tmp_path):
    db = tmp_path / "own.db"
    cfg = _config(db)
    command.upgrade(cfg, "0102")
    with sqlite3.connect(db) as conn:
        _role(conn, "Mine", "build", builtin=0)
        conn.execute("INSERT INTO teams (id, name, created_at, lead_on, lead_may_pick) "
                     "VALUES ('u', 'ML', ?, 1, 1)", (AT,))
        conn.execute("INSERT INTO role_teams (role_id, team_id) VALUES ('Mine', 'u')")

    command.upgrade(cfg, "head")
    for _start in range(2):  # (each start seeds: a built-in role joins only a ready team)
        with make_session_factory(make_engine(db))() as session:
            roles.seed_builtin_roles(session)
    with sqlite3.connect(db) as conn:
        assert _members(conn, "ML") == ["Mine"] and _defaults(conn)["ML"] is None
        assert "Tester" in _members(conn, "DataOps")
        conn.execute("UPDATE roles SET updated_at = ? WHERE name = 'Databricks expert'", (AT,))

    command.downgrade(cfg, "0102")
    with sqlite3.connect(db) as conn:
        # (One saved since it was made is the user's; the other, as made, goes.)
        assert conn.execute("SELECT name FROM roles WHERE name LIKE '%expert'").fetchall() == [
            ("Databricks expert",)]
        assert _members(conn, "ML") == ["Mine"]
