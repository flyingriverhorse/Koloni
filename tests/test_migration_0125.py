"""28e: migration 0125 gives each role that reads files view_image, where app.roles puts it -
one the user made too."""

import json
import sqlite3

from alembic import command

from app.roles import BUILTIN_ROLES
from tests.test_migration_0002 import _config
from tests.test_migration_0109 import _role


def _held(conn):
    return {name: json.loads(tools) for name, tools in conn.execute("SELECT name, tools FROM roles")}


def test_readers_gain_view_image_as_app_roles_has_it_and_going_back_is_exact(tmp_path):
    cfg = _config(db := tmp_path / "r.db")
    command.upgrade(cfg, "0124")
    with sqlite3.connect(db) as conn:
        conn.execute("DELETE FROM roles")
        for at, (name, spec) in enumerate(BUILTIN_ROLES.items()):
            _role(conn, str(at), name, [t for t in spec.tools if t != "view_image"], "as given")
        _role(conn, "mine", "Mine", ["read_file", "ask_user"], "as given", builtin=0)
        before = _held(conn)
    command.upgrade(cfg, "0125")
    with sqlite3.connect(db) as conn:
        after = _held(conn)
    assert {name: after[name] for name in BUILTIN_ROLES} == {
        name: list(spec.tools) for name, spec in BUILTIN_ROLES.items()}
    assert after["Mine"] == ["read_file", "view_image", "ask_user"]
    assert "view_image" not in after["Observer"]  # (it reads nothing)
    command.downgrade(cfg, "0124")
    with sqlite3.connect(db) as conn:
        assert _held(conn) == before
