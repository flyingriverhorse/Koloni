"""the core roles are always on with the tools their job needs; the ready Bugfix tests its fix
(kanıtlı bitiş S4)

Karar 5 (the user, 21 Nov: some roles must always be there): the Coder, Tester, Reviewer,
Debugger and Security reviewer - KOLONİ's own, not a role of the user's by such a name - are
switched on, and each is given back the tools of its job it was left without (`app.roles.CORE`);
its other tools, the user's, are kept. The ready Bugfix still drawn as 0074 made it sends a
failing test back to Fix it (at most 2 rounds, as its review does) and starts with a failing test
("Reproduce it with a failing test"); one changed since is left alone. A row under way runs by its
own copy of the graph.

Going back draws Bugfix as before; the roles stay as they are - a switch or a tool is the user's
to change again on the old app, and taking one away by migration would take what the user may
have given since.

Revision ID: 0161
Revises: 0159
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0161"
# (Written on the k-kanit-tarif branch beside k-kanit-son's 0160: re-chained after main's newest
# at its merge.)
down_revision = "0159"
branch_labels = None
depends_on = None

# As they were when this was written (`app.roles.CORE`): a migration does not follow later code.
READ = ["list_dir", "read_file", "search", "view_image"]
WRITE = ["write_file", "edit_file"]
CORE = {
    "Coder": [*READ, *WRITE, "run_command"],
    "Tester": [*READ, "run_command"],
    "Reviewer": READ,
    "Debugger": [*READ, *WRITE, "run_command"],
    "Security reviewer": READ,
}


def _step(id, name, role, **more):
    return {"id": id, "name": name, "who": {"role": role}, "done_when": "done",
            "if_fails": "ask", "ask_me": False, "group": None, **more}


def _bugfix(first: str, loops: list[dict]) -> dict:
    # As 0074 made it (`app.schemas.RecipeGraph`, version 1), but for its first step's name and
    # its loops.
    return {
        "version": 1,
        "steps": [
            _step("reproduce", first, "Debugger"),
            _step("fix", "Fix it", "Coder"),
            _step("test", "Test it", "Tester", done_when="no_findings"),
            _step("review", "Review it", "Reviewer", done_when="no_findings"),
        ],
        "groups": [],
        "ends": [{"id": "end", "then": "in"}],
        "arrows": [{"from": a, "to": b} for a, b in (
            ("start", "reproduce"), ("reproduce", "fix"), ("fix", "test"), ("test", "review"),
            ("review", "end"))],
        "loops": loops,
    }


REVIEW_LOOP = {"from": "review", "to": "fix", "rounds": 2}
WAS = _bugfix("Reproduce it", [REVIEW_LOOP])
NOW = _bugfix("Reproduce it with a failing test",
              [REVIEW_LOOP, {"from": "test", "to": "fix", "rounds": 2}])


def _swap(was: dict, now: dict) -> None:
    bind = op.get_bind()
    for id_, graph in bind.execute(sa.text(
            "SELECT id, graph FROM recipes WHERE name = 'Bugfix' AND ready = 1")):
        # (Compared as data: the same drawing whatever its JSON's spacing.)
        if (json.loads(graph) if isinstance(graph, str) else graph) == was:
            bind.execute(sa.text("UPDATE recipes SET graph = :graph WHERE id = :id"),
                         {"graph": json.dumps(now), "id": id_})


def _core_roles() -> None:
    bind = op.get_bind()
    for name, needs in CORE.items():
        for id_, held in bind.execute(sa.text(
                "SELECT id, tools FROM roles WHERE builtin = 1 AND name = :name"), {"name": name}):
            tools = json.loads(held) if isinstance(held, str) else held
            bind.execute(sa.text("UPDATE roles SET enabled = 1, tools = :tools WHERE id = :id"),
                         {"tools": json.dumps([*tools, *(one for one in needs if one not in tools)]),
                          "id": id_})


def upgrade() -> None:
    _core_roles()
    _swap(WAS, NOW)


def downgrade() -> None:
    _swap(NOW, WAS)
