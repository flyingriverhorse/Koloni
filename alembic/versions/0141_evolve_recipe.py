"""the ready "Evolve" recipe (K-evrim): three Coders try it each their own way, each scored by the
project's measure command; the best goes on, round after round, until one scores 80 - at most
four rounds - and the best is the user's to take in

Added only where no recipe has its name. Going back takes it away where nothing names it.

Revision ID: 0141
Revises: 0140
"""
import json
import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0141"
# (Written on the k-evrim-4 branch: re-chained after main's newest at its merge.)
down_revision = "0140"
branch_labels = None
depends_on = None

# As it was when this was written (`app.schemas.RecipeGraph`, version 1).
EVOLVE = {
    "version": 1,
    "steps": [{"id": "try", "name": "Try it three ways",
               "who": {"candidates": "Coder", "most": 3, "target": 80}, "done_when": "done",
               "if_fails": "ask", "ask_me": False, "group": None}],
    "groups": [],
    "ends": [{"id": "end", "then": "in"}],
    "arrows": [{"from": "start", "to": "try"}, {"from": "try", "to": "end"}],
    "loops": [{"from": "try", "to": "try", "rounds": 3}],
}


def upgrade() -> None:
    made = datetime.now(UTC).replace(tzinfo=None).isoformat(" ", "microseconds")
    # (A recipe of the user's own by that name keeps it: the ready one is not added.)
    op.get_bind().execute(sa.text(
        "INSERT INTO recipes (id, name, ready, graph, created_at, updated_at) "
        "SELECT :id, 'Evolve', 1, :graph, :at, :at "
        "WHERE NOT EXISTS (SELECT 1 FROM recipes WHERE lower(name) = 'evolve')"
    ), {"id": uuid.uuid4().hex, "graph": json.dumps(EVOLVE), "at": made})


def downgrade() -> None:
    # (Gone only where nothing names it: no team's default, no chat's row.)
    op.execute("DELETE FROM recipes WHERE name = 'Evolve' AND ready = 1 "
               "AND id NOT IN (SELECT default_recipe_id FROM teams "
               "WHERE default_recipe_id IS NOT NULL) "
               "AND id NOT IN (SELECT recipe_id FROM conversation_teams "
               "WHERE recipe_id IS NOT NULL)")
