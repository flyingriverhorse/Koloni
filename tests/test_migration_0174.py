"""Migration 0174 (K-rol-adlari): the built-in Product owner is the Hive keeper, the Assistant product
owner the Scout - their rows, their descriptions where KOLONİ's, and what names them: the recipes'
steps and the saved commands. A role of the user's own by a new name keeps it (the built-in bears
" (built-in)"); going back gives the old names where they are free."""

import json
import sqlite3
import uuid

from alembic import command

from app.roles import BUILTIN_ROLES, HIVE_KEEPER, SCOUT
from tests.test_migration_0002 import _config

OLD = {
    "Product owner": "Keeps the project's To-do list: breaks a goal into tasks, each with what "
    "makes it done, and puts them in order.",
    "Assistant product owner": "Helps keep the To-do list: splits vague tasks, asks what is "
    "missing, flags problems and assesses finished work against what makes it done.",
}


def _role(conn, name, builtin, description="mine"):
    """A role row as an install has it, its other columns a ready lead's."""
    columns = [row[1] for row in conn.execute("PRAGMA table_info(roles)")]
    row = dict(zip(columns, conn.execute("SELECT * FROM roles LIMIT 1").fetchone(), strict=True))
    row |= {"id": uuid.uuid4().hex, "name": name, "builtin": builtin, "description": description}
    conn.execute(
        f"INSERT INTO roles ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})",
        [row[one] for one in columns],
    )


def _install(db, *own):
    """At 0173: the two built-ins by their old names, the user's own roles `own`, a recipe of the
    user's naming both old ones (a step, a room), and a saved command for each."""
    cfg = _config(db)
    command.upgrade(cfg, "0173")
    with sqlite3.connect(db) as conn:
        for name, description in OLD.items():
            _role(conn, name, 1, description)
        for name in own:
            _role(conn, name, 0)
        steps = [
            {"id": "a", "name": "A", "who": {"role": "product owner"}},
            {"id": "b", "name": "B", "who": {"room": ["Assistant product owner", "Coder"]}},
            {"id": "c", "name": "C", "who": {"role": "Scout"}},
        ]
        conn.execute(
            "INSERT INTO recipes (id, name, ready, graph, created_at, updated_at) "
            "VALUES ('mine', 'Mine', 0, ?, '2026-11-23', '2026-11-23')",
            (json.dumps({"version": 1, "steps": steps}),),
        )
        for at, role in enumerate(("Product owner", "Assistant product owner", "Coder")):
            conn.execute(
                "INSERT INTO own_commands (id, name, description, template, role, created_at) "
                "VALUES (?, ?, '', 'x', ?, '2026-11-23')",
                (f"c{at}", f"c{at}", role),
            )
    return cfg


def _read(db):
    with sqlite3.connect(db) as conn:
        roles = dict(
            conn.execute("SELECT name, description FROM roles WHERE builtin = 1").fetchall()
        )
        own = sorted(name for (name,) in conn.execute("SELECT name FROM roles WHERE builtin = 0"))
        mine = json.loads(conn.execute("SELECT graph FROM recipes WHERE id = 'mine'").fetchone()[0])
        spec = json.loads(
            conn.execute("SELECT graph FROM recipes WHERE name = 'Spec'").fetchone()[0]
        )
        commands = [role for (role,) in conn.execute("SELECT role FROM own_commands ORDER BY id")]
    return roles, own, [s["who"] for s in mine["steps"]], spec["steps"][0]["who"], commands


def test_the_two_roles_are_renamed_with_what_names_them_and_back(tmp_path):
    db = tmp_path / "r.db"
    cfg = _install(db)
    before = _read(db)
    command.upgrade(cfg, "0174")
    roles, own, mine, spec, commands = _read(db)
    assert roles == {
        HIVE_KEEPER: BUILTIN_ROLES[HIVE_KEEPER].description,
        SCOUT: BUILTIN_ROLES[SCOUT].description,
    }
    assert not {"Product owner", "Assistant product owner", HIVE_KEEPER, SCOUT} & set(own)
    assert mine == [{"role": HIVE_KEEPER}, {"room": [SCOUT, "Coder"]}, {"role": SCOUT}]
    assert spec == {"role": HIVE_KEEPER}
    assert commands == [HIVE_KEEPER, SCOUT, "Coder"]
    command.downgrade(cfg, "0173")
    after = _read(db)
    # (back: the old names - a step that named "Scout" now names the role it meant then, the old
    # Assistant product owner, as there was no "Scout" of the user's)
    assert after[:2] == before[:2] and after[3:] == before[3:]
    assert after[2] == [
        {"role": "Product owner"},
        {"room": ["Assistant product owner", "Coder"]},
        {"role": "Assistant product owner"},
    ]


def test_a_role_of_the_users_by_a_new_name_keeps_it(tmp_path):
    db = tmp_path / "r.db"
    cfg = _install(db, "scout")
    command.upgrade(cfg, "0174")
    roles, own, mine, _spec, commands = _read(db)
    assert set(roles) == {HIVE_KEEPER, f"{SCOUT} (built-in)"} and "scout" in own
    # (what named the old built-in names it still; the user's own "Scout" is theirs)
    assert mine == [
        {"role": HIVE_KEEPER},
        {"room": [f"{SCOUT} (built-in)", "Coder"]},
        {"role": SCOUT},
    ]
    assert commands == [HIVE_KEEPER, f"{SCOUT} (built-in)", "Coder"]
    command.downgrade(cfg, "0173")
    roles, own, mine, _spec, commands = _read(db)
    assert set(roles) == set(OLD) and "scout" in own
    assert mine[1] == {"room": ["Assistant product owner", "Coder"]} and mine[2] == {
        "role": "Scout"
    }


def test_going_back_keeps_a_users_role_that_took_an_old_name_since(tmp_path):
    db = tmp_path / "r.db"
    cfg = _install(db)
    command.upgrade(cfg, "0174")
    with sqlite3.connect(db) as conn:
        _role(conn, "Product owner", 0)
    command.downgrade(cfg, "0173")
    roles, own, *_ = _read(db)
    assert set(roles) == {HIVE_KEEPER, "Assistant product owner"} and "Product owner" in own


def test_a_built_in_by_its_new_name_after_a_users_role_resets_and_is_listed_in_its_place(
    make_client,
):
    # (the built-in "Scout (built-in)" beside the user's "Scout": Reset knows it, and it stands
    # where the Scout does among the built-ins - never added again beside it)
    from sqlalchemy import update

    from app.db.models import Role
    from app.roles import list_roles, seed_builtin_roles
    from tests.test_chat_teams_scenarios import OWN

    client, _model = make_client([])
    with client.app.state.session_factory() as session:
        session.execute(
            update(Role).where(Role.name == SCOUT).values(name=f"{SCOUT} (built-in)", tools=[])
        )
        session.add(Role(name=SCOUT, description="mine", instructions="", tools=[]))
        session.commit()
        seed_builtin_roles(session)
        names = [role.name for role in list_roles(session) if role.builtin]
        built_in = session.query(Role).filter_by(name=f"{SCOUT} (built-in)").one().id
    assert names.count(f"{SCOUT} (built-in)") == 1 and SCOUT not in names
    assert names.index(f"{SCOUT} (built-in)") == list(BUILTIN_ROLES).index(SCOUT), names
    reset = client.post(f"/api/roles/{built_in}/reset", headers=OWN)
    assert reset.status_code == 200 and reset.json()["tools"] == list(BUILTIN_ROLES[SCOUT].tools)


def test_a_users_own_role_by_an_old_name_keeps_what_names_it(tmp_path):
    # (review: the user's own "Product owner" - no built-in was ever added beside it - lost its
    # recipe step and its saved command to the Hive keeper)
    db = tmp_path / "r.db"
    cfg = _config(db)
    command.upgrade(cfg, "0173")
    with sqlite3.connect(db) as conn:
        _role(conn, "Product owner", 0, "MY OWN")
        _role(conn, "Assistant product owner", 1, OLD["Assistant product owner"])
        conn.execute(
            "INSERT INTO recipes (id, name, ready, graph, created_at, updated_at) VALUES ('mine', "
            "'Mine', 0, ?, '2026-11-23', '2026-11-23')",
            (
                json.dumps(
                    {
                        "version": 1,
                        "steps": [{"id": "a", "name": "A", "who": {"role": "Product owner"}}],
                    }
                ),
            ),
        )
        conn.execute(
            "INSERT INTO own_commands (id, name, description, template, role, created_at) "
            "VALUES ('c', 'groom', '', 'x', 'Product owner', '2026-11-23')"
        )
    command.upgrade(cfg, "0174")
    roles, own, mine, spec, commands = _read(db)
    assert "Product owner" in own and set(roles) == {SCOUT}
    assert mine == [{"role": "Product owner"}] and commands == ["Product owner"]
    assert spec == {"role": "Product owner"}  # (the ready Spec named it too: the user's, now)


def test_names_told_apart_as_kolonis_are_and_a_free_name_each(tmp_path):
    # (review: "Scout " is a Scout to `find_role`; one with both "Scout" and "Scout (built-in)"
    # got an IntegrityError at start)
    db = tmp_path / "r.db"
    cfg = _install(db, "Scout ", "scout (built-in)")
    command.upgrade(cfg, "0174")
    roles, *_ = _read(db)
    assert set(roles) == {HIVE_KEEPER, f"{SCOUT} (built-in 2)"}
    command.downgrade(cfg, "0173")
    roles, *_ = _read(db)
    assert set(roles) == set(OLD)


def test_a_saved_command_named_as_the_scout_takes_a_free_name(tmp_path):
    # (review: a saved /scout would hide behind the Scout's chip in the message box)
    db = tmp_path / "r.db"
    cfg = _install(db)
    with sqlite3.connect(db) as conn:
        for at, name in enumerate(("scout", "Scout-command", "hive-keeper")):
            conn.execute(
                "INSERT INTO own_commands (id, name, description, template, created_at) "
                "VALUES (?, ?, '', 'x', '2026-11-23')",
                (f"n{at}", name),
            )
    command.upgrade(cfg, "0174")
    with sqlite3.connect(db) as conn:
        names = dict(conn.execute("SELECT id, name FROM own_commands WHERE id LIKE 'n%'"))
    assert names == {"n0": "scout-command-2", "n1": "Scout-command", "n2": "hive-keeper"}


def test_an_agent_asking_for_an_old_name_is_told_the_new_one():
    from app.roles import was_named

    assert was_named("Product owner") == " - Product owner is now the Hive keeper"
    assert (
        was_named(" assistant   product owner ") == " - assistant   product owner is now the Scout"
    )
    assert was_named("Coder") == ""
