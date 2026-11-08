"""an expert role's knowledge sources, and the ready "Integration" recipe (K-uzman)

Revision ID: 0090
Revises: 0089
"""
import json
import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0090"
down_revision = "0089"
branch_labels = None
depends_on = None


def _step(id, name, who, **more):
    return {"id": id, "name": name, "who": who, "done_when": "done", "if_fails": "ask",
            "ask_me": False, "group": None, **more}


# As it was when this was written (`app.schemas.RecipeGraph`, version 1). The mockup's flow
# (x-uzmanlar.html): the experts learn only where a guide is missing or old, check the plan at
# once - back to the Planner at most twice - and are asked during the build.
INTEGRATION = {
    "version": 1,
    "steps": [
        _step("learn", "Learn", {"experts": "stale"}),
        _step("plan", "Plan", {"role": "Planner"}),
        _step("check", "Experts check the plan", {"experts": "all"}, done_when="no_findings"),
        _step("build", "Build", {"role": "Coder"}),
        _step("test", "Test", {"role": "Tester"}, done_when="no_findings"),
    ],
    "groups": [],
    "ends": [{"id": "end", "then": "in"}],
    "arrows": [{"from": a, "to": b} for a, b in (
        ("start", "learn"), ("learn", "plan"), ("plan", "check"), ("check", "build"),
        ("build", "test"), ("test", "end"))],
    "loops": [{"from": "check", "to": "plan", "rounds": 2}],
}


def upgrade() -> None:
    with op.batch_alter_table("roles") as batch:
        batch.add_column(sa.Column("knowledge", sa.JSON(), nullable=True))
    made = datetime.now(UTC).replace(tzinfo=None).isoformat(" ", "microseconds")
    # (A recipe of the user's own by that name keeps it: the ready one is not added.)
    op.get_bind().execute(sa.text(
        "INSERT INTO recipes (id, name, ready, graph, created_at, updated_at) "
        "SELECT :id, 'Integration', 1, :graph, :at, :at "
        "WHERE NOT EXISTS (SELECT 1 FROM recipes WHERE lower(name) = 'integration')"
    ), {"id": uuid.uuid4().hex, "graph": json.dumps(INTEGRATION), "at": made})


def downgrade() -> None:
    # (What names the ready recipe goes back to none first: the team's default, a chat's row.)
    ready = "(SELECT id FROM recipes WHERE name = 'Integration' AND ready = 1)"
    op.execute(f"UPDATE teams SET default_recipe_id = NULL WHERE default_recipe_id IN {ready}")
    op.execute(f"UPDATE conversation_teams SET recipe_id = NULL WHERE recipe_id IN {ready}")
    op.execute("DELETE FROM recipes WHERE name = 'Integration' AND ready = 1")
    with op.batch_alter_table("roles") as batch:
        batch.drop_column("knowledge")
