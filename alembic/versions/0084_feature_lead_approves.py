"""the ready Feature recipe: the Lead gives the approval itself (batch-16)

0074's Feature had an "Approve it" step whose Who was "the Lead picks": the Lead opened one
more agent for it - live, a "Reviewer 3" nobody asked for. The user (25 Oct): the Lead
approves itself. Its approval is its own word on the reviews before Ready for you, so the step
goes, and the reviews lead to the end. A ready recipe is not changed by the user (a change is
saved as a copy): only one still as 0074 drew it is changed.

Revision ID: 0084
Revises: 0083
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0084"
down_revision = "0083"
branch_labels = None
depends_on = None

# As 0074 drew them (a migration does not follow later code).
APPROVE = {"id": "approve", "name": "Approve it", "who": {"lead": True}, "done_when": "done",
           "if_fails": "ask", "ask_me": False, "group": None}
WITH = [{"from": "reviews", "to": "approve"}, {"from": "approve", "to": "end"}]
WITHOUT = [{"from": "reviews", "to": "end"}]


def _change(were: dict | None, now: dict | None, arrows_were: list, arrows_now: list) -> None:
    bind = op.get_bind()
    for recipe_id, graph in bind.execute(sa.text(
            "SELECT id, graph FROM recipes WHERE ready AND name = 'Feature'")).fetchall():
        graph = json.loads(graph) if isinstance(graph, str) else graph
        steps, arrows = graph["steps"], graph["arrows"]
        drawn = were in steps if were else not any(step["id"] == "approve" for step in steps)
        if not drawn or not all(arrow in arrows for arrow in arrows_were):
            continue  # (not as it was drawn: left as it is)
        graph["steps"] = [step for step in steps if step != were] + ([now] if now else [])
        graph["arrows"] = [arrow for arrow in arrows if arrow not in arrows_were] + arrows_now
        bind.execute(sa.text("UPDATE recipes SET graph = :graph WHERE id = :id"),
                     {"graph": json.dumps(graph), "id": recipe_id})


def upgrade() -> None:
    _change(APPROVE, None, WITH, WITHOUT)


def downgrade() -> None:
    _change(None, APPROVE, WITHOUT, WITH)
