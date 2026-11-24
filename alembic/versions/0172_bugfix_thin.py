"""The ready Bugfix is Reproduce it -> Fix it -> Checks (tarif maliyeti T1)

KOLONİ's own checks at a recipe's end (its Checks step: tests and a review, 0170) run the tests
and have a big or security-touching change reviewed; Bugfix's Test it and Review it were a second
layer over them - an agent to run the same tests, a Reviewer for every change however small, and
their loops back to Fix it. The ready Bugfix still drawn as 0161 and 0170 made it loses them: a
failing test with its own run on record first, then the fix, then KOLONİ's checks. One changed
since is left alone (a ready one is KOLONİ's own; the user's are copies). A row under way runs by
its own copy of the graph.

Going back draws it as before.

Revision ID: 0172
Revises: 0171
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "0172"
# (Written on the k-bugfix-ince branch: re-chained after main's newest at its merge.)
down_revision = "0171"
branch_labels = None
depends_on = None


# As 0161 and 0170 wrote it (`app.schemas.RecipeGraph`, version 1): a migration does not follow
# later code.
def _step(id, name, role, **more):
    return {
        "id": id,
        "name": name,
        "who": {"role": role},
        "done_when": "done",
        "if_fails": "ask",
        "ask_me": False,
        "group": None,
        **more,
    }


def _bugfix(steps: list[dict], loops: list[dict]) -> dict:
    ids = ["start", *(one["id"] for one in steps), "end"]
    return {
        "version": 1,
        "steps": steps,
        "groups": [],
        "ends": [{"id": "end", "then": "in"}],
        "arrows": [{"from": a, "to": b} for a, b in zip(ids, ids[1:], strict=False)],
        "loops": loops,
        "checks": {
            "tests": True,
            "review": True,
            "docs": False,
            "diagram": False,
            "data": False,
            "slides": False,
            "fix_rounds": None,
        },
    }


FIRST = [
    _step("reproduce", "Reproduce it with a failing test", "Debugger"),
    _step("fix", "Fix it", "Coder"),
]
WAS = _bugfix(
    [
        *FIRST,
        _step("test", "Test it", "Tester", done_when="no_findings"),
        _step("review", "Review it", "Reviewer", done_when="no_findings"),
    ],
    [{"from": "review", "to": "fix", "rounds": 2}, {"from": "test", "to": "fix", "rounds": 2}],
)
NOW = _bugfix(FIRST, [])


def _swap(was: dict, now: dict) -> None:
    bind = op.get_bind()
    for id_, graph in bind.execute(
        sa.text("SELECT id, graph FROM recipes WHERE name = 'Bugfix' AND ready = 1")
    ):
        # (Compared as data: the same drawing whatever its JSON's spacing.)
        if (json.loads(graph) if isinstance(graph, str) else graph) == was:
            bind.execute(
                sa.text("UPDATE recipes SET graph = :graph WHERE id = :id"),
                {"graph": json.dumps(now), "id": id_},
            )


def upgrade() -> None:
    _swap(WAS, NOW)


def downgrade() -> None:
    _swap(NOW, WAS)
