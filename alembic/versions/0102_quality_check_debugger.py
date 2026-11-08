"""the ready "Quality check" recipe gets its Debugger (the conditional recipe step, the user's)

The Tester runs the tests; only if it found a problem, the Debugger finds and fixes the cause and
the Tester runs them again - at most 2 rounds - then the Reviewer and the Security reviewer
review together. Only the ready recipe still drawn as 0098 made it is changed: a copy of the
user's, or one changed since, is left alone. A row under way runs by its own copy of the graph.

Revision ID: 0102
Revises: 0099
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0102"
down_revision = "0099"
branch_labels = None
depends_on = None


def _step(id, name, role, **more):
    return {"id": id, "name": name, "who": {"role": role}, "done_when": "no_findings",
            "if_fails": "ask", "ask_me": False, "group": None, **more}


REVIEWS = [
    _step("code", "Code review", "Reviewer", group="reviews"),
    _step("security", "Security review", "Security reviewer", group="reviews"),
]
# As 0098 made it (`app.schemas.RecipeGraph`, version 1).
WAS = {
    "version": 1,
    "steps": [_step("test", "Run the tests", "Tester"), *REVIEWS],
    "groups": [{"id": "reviews", "name": "All at once, wait for all"}],
    "ends": [{"id": "end", "then": "report"}],
    "arrows": [{"from": a, "to": b} for a, b in (
        ("start", "test"), ("test", "reviews"), ("reviews", "end"))],
    "loops": [],
}
NOW = {
    **WAS,
    "steps": [_step("test", "Run the tests", "Tester"),
              _step("fix", "Find and fix the cause", "Debugger", done_when="done",
                    when="problem"),
              *REVIEWS],
    "arrows": [{"from": a, "to": b} for a, b in (
        ("start", "test"), ("test", "fix"), ("fix", "reviews"), ("reviews", "end"))],
    "loops": [{"from": "fix", "to": "test", "rounds": 2}],
}


def _swap(was: dict, now: dict) -> None:
    bind = op.get_bind()
    for id_, graph in bind.execute(sa.text(
            "SELECT id, graph FROM recipes WHERE name = 'Quality check' AND ready = 1")):
        # (Compared as data: the same drawing whatever its JSON's spacing.)
        if (json.loads(graph) if isinstance(graph, str) else graph) == was:
            bind.execute(sa.text("UPDATE recipes SET graph = :graph WHERE id = :id"),
                         {"graph": json.dumps(now), "id": id_})


def upgrade() -> None:
    _swap(WAS, NOW)


def downgrade() -> None:
    _swap(NOW, WAS)
