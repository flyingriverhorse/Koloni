"""An install upgraded migration by migration has the tools a fresh install has (B-335).

The fixture `tests/fixtures/upgraded-0111.db` is a live install's database (the REA copy's,
taken through every migration from the first to 0111 the way a user's is), shrunk to its
schema and its built-in roles: every other row is gone, the search table is made again
empty, and the roles' provider, model, skills and knowledge are cleared. It keeps what the
migrations made of the tools - 0097 put `propose_trigger` at the end of the Lead's list, an
order no fresh install has - which is what a later migration comparing whole lists missed
(0122, B-335: the Lead was left without the browser tools on every upgraded install)."""
import json
import shutil
import sqlite3
from pathlib import Path

from alembic import command

from app.db.session import make_engine, make_session_factory
from app.roles import BUILTIN_ROLES, seed_builtin_roles
from tests.test_migration_0002 import _config

FIXTURE = Path(__file__).parent / "fixtures" / "upgraded-0111.db"
# Built-in roles whose upgraded tools are known to fall short of a fresh install's: the tools
# the upgrade leaves out, and why. Take an entry out once a corrective migration lands - the
# test allows the gap, it does not demand it.
KNOWN_MISSING: dict[str, tuple[set[str], str]] = {}


def _tools(db: Path) -> dict[str, set[str]]:
    with sqlite3.connect(db) as conn:
        return {name: set(json.loads(tools)) for name, tools in conn.execute(
            "SELECT name, tools FROM roles WHERE builtin = 1")}


def _at_head(db: Path) -> None:
    """Upgraded to the newest migration and seeded as KOLONİ does when it starts."""
    command.upgrade(_config(db), "head")
    with make_session_factory(make_engine(db))() as session:
        seed_builtin_roles(session)


def test_the_fixture_is_an_upgraded_install_with_nothing_of_the_users():
    with sqlite3.connect(FIXTURE) as conn:
        assert conn.execute("SELECT version_num FROM alembic_version").fetchall() == [("0111",)]
        assert conn.execute("SELECT count(*) FROM roles WHERE builtin != 1").fetchone() == (0,)
        for table in ("providers", "projects", "conversations", "messages", "memories", "attachments"):
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone() == (0,), table
        lead = json.loads(conn.execute("SELECT tools FROM roles WHERE name = 'Lead'").fetchone()[0])
    assert lead[-1] == "propose_trigger"  # (0097's order: what a fresh install never has)
    assert FIXTURE.stat().st_size < 400_000


def test_an_upgraded_install_has_every_tool_a_fresh_one_has(tmp_path):
    fresh, upgraded = tmp_path / "fresh.db", tmp_path / "upgraded.db"
    shutil.copy(FIXTURE, upgraded)
    _at_head(fresh)
    _at_head(upgraded)
    new, old = _tools(fresh), _tools(upgraded)
    assert set(new) == set(BUILTIN_ROLES) == set(old)
    gaps = {}
    for name in BUILTIN_ROLES:
        missing, extra = new[name] - old[name], old[name] - new[name]
        allowed, _why = KNOWN_MISSING.get(name, (set(), ""))
        if missing - allowed or extra:
            gaps[name] = {"missing": sorted(missing - allowed), "extra": sorted(extra)}
    assert not gaps, f"an upgraded install's tools differ from a fresh install's: {gaps}"
