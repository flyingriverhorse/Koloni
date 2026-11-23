"""The ready recipes' Checks step (kanıtlı bitiş S5c, plan decision 16)

Every recipe ends in a locked Checks step: what KOLONİ checks at its end, kept in its graph as
`checks` (`app.schemas.RecipeChecks`; none: it follows the project's After a change). The ready
ones come with the choice that fits what they make: Bugfix and Feature their tests and a review,
Docs its documents and a review, Evolve its tests. A ready recipe is KOLONİ's own (the user's are
copies); one that already says its checks is left alone. A row under way runs by its own copy of
the graph.

Going back takes the step's choice out of those four again.

Revision ID: 0170
Revises: 0167
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "0170"
# (Written on the k-kanit-tarif-son branch beside k-kanit-yukselt's 0169: re-chained after main's
# newest at its merge.)
down_revision = "0167"
branch_labels = None
depends_on = None

# As `app.schemas.RecipeChecks` was when this was written: a migration does not follow later code.
_OFF = {
    "tests": False,
    "review": False,
    "docs": False,
    "diagram": False,
    "data": False,
    "slides": False,
    "fix_rounds": None,
}
READY = {
    "Bugfix": {**_OFF, "tests": True, "review": True},
    "Feature": {**_OFF, "tests": True, "review": True},
    "Docs": {**_OFF, "docs": True, "review": True},
    "Evolve": {**_OFF, "tests": True},
}


def _graphs(name: str):
    bind = op.get_bind()
    for id_, graph in bind.execute(
        sa.text("SELECT id, graph FROM recipes WHERE name = :name AND ready = 1"), {"name": name}
    ):
        yield bind, id_, json.loads(graph) if isinstance(graph, str) else graph


def upgrade() -> None:
    for name, checks in READY.items():
        for bind, id_, graph in _graphs(name):
            if "checks" not in graph:
                bind.execute(
                    sa.text("UPDATE recipes SET graph = :graph WHERE id = :id"),
                    {"graph": json.dumps({**graph, "checks": checks}), "id": id_},
                )


def downgrade() -> None:
    for name, checks in READY.items():
        for bind, id_, graph in _graphs(name):
            if graph.get("checks") == checks:
                bind.execute(
                    sa.text("UPDATE recipes SET graph = :graph WHERE id = :id"),
                    {
                        "graph": json.dumps({k: v for k, v in graph.items() if k != "checks"}),
                        "id": id_,
                    },
                )
