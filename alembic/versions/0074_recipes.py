"""recipes - the steps of a piece of work, three of them ready - and a team's default recipe
(slice 84a)

Revision ID: 0074
Revises: 0073
"""
import json
import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0074"
down_revision = "0073"
branch_labels = None
depends_on = None


def _step(id, name, role=None, **more):
    return {"id": id, "name": name, "who": {"role": role} if role else {"lead": True},
            "done_when": "done", "if_fails": "ask", "ask_me": False, "group": None, **more}


def _arrows(*pairs):
    return [{"from": a, "to": b} for a, b in pairs]


REVIEW = {"done_when": "no_findings"}
# As they were when this was written (`app.schemas.RecipeGraph`, version 1): a migration does
# not follow later code. Who is named by the ready roles' names.
READY = {
    # The user's flow (23 October): a spec, the build, four reviews at once, at most two
    # rounds of fixes, an approval, then the user's word before it goes in.
    "Feature": {
        "version": 1,
        "steps": [
            _step("spec", "Write the spec", "Spec writer", ask_me=True),
            _step("build", "Build it", "Coder"),
            _step("code", "Code review", "Reviewer", group="reviews", **REVIEW),
            _step("security", "Security review", "Security reviewer", group="reviews", **REVIEW),
            _step("ui", "UI review", "UI designer", group="reviews", **REVIEW),
            _step("tests", "Test it", "Tester", group="reviews", **REVIEW),
            _step("approve", "Approve it"),
        ],
        "groups": [{"id": "reviews", "name": "All at once, wait for all"}],
        "ends": [{"id": "end", "then": "in"}],
        "arrows": _arrows(("start", "spec"), ("spec", "build"), ("build", "reviews"),
                          ("reviews", "approve"), ("approve", "end")),
        "loops": [{"from": "reviews", "to": "build", "rounds": 2}],
    },
    "Bugfix": {
        "version": 1,
        "steps": [
            _step("reproduce", "Reproduce it", "Debugger"),
            _step("fix", "Fix it", "Coder"),
            _step("test", "Test it", "Tester", **REVIEW),
            _step("review", "Review it", "Reviewer", **REVIEW),
        ],
        "groups": [],
        "ends": [{"id": "end", "then": "in"}],
        "arrows": _arrows(("start", "reproduce"), ("reproduce", "fix"), ("fix", "test"),
                          ("test", "review"), ("review", "end")),
        "loops": [{"from": "review", "to": "fix", "rounds": 2}],
    },
    "Review only": {
        "version": 1,
        "steps": [
            _step("code", "Code review", "Reviewer", group="reviews", **REVIEW),
            _step("security", "Security review", "Security reviewer", group="reviews", **REVIEW),
            _step("ui", "UI review", "UI designer", group="reviews", **REVIEW),
        ],
        "groups": [{"id": "reviews", "name": "All at once, wait for all"}],
        "ends": [{"id": "end", "then": "report"}],
        "arrows": _arrows(("start", "reviews"), ("reviews", "end")),
        "loops": [],
    },
}


def upgrade() -> None:
    op.create_table(
        "recipes",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("ready", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("graph", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    with op.batch_alter_table("teams") as batch:
        batch.add_column(sa.Column("default_recipe_id", sa.String(length=32), nullable=True))
        batch.create_foreign_key(
            "fk_teams_default_recipe_id", "recipes", ["default_recipe_id"], ["id"],
            ondelete="SET NULL")
    made = datetime.now(UTC).replace(tzinfo=None).isoformat(" ", "microseconds")
    for name, graph in READY.items():
        op.get_bind().execute(sa.text(
            "INSERT INTO recipes (id, name, ready, graph, created_at, updated_at) "
            "VALUES (:id, :name, 1, :graph, :at, :at)"
        ), {"id": uuid.uuid4().hex, "name": name, "graph": json.dumps(graph), "at": made})


def downgrade() -> None:
    with op.batch_alter_table("teams") as batch:
        batch.drop_constraint("fk_teams_default_recipe_id", type_="foreignkey")
        batch.drop_column("default_recipe_id")
    op.drop_table("recipes")
