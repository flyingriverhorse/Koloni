"""the ready "Quality check" recipe, the ready Quality team's default in place of Review only
(B-172, the user's)

Review only called the Reviewer, the Security reviewer and the UI designer - no UI designer is
in Quality, and its Tester was never called. Quality check is Quality's own: the Tester runs the
tests, then the Reviewer and the Security reviewer review together. Only the stock Quality team
whose default is still the ready Review only is changed: a recipe the user chose is kept, a
renamed team is left alone.
shortcut: no Debugger - the recipes have no step that runs only when the tests fail; its fix
branch waits for the conditional recipe step
(tasarim/specs/2026-10-28-takimlar-roller-tarifler-design.md), which gives it the Debugger.

Revision ID: 0098
Revises: 0093
"""
import json
import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0098"
down_revision = "0093"
branch_labels = None
depends_on = None


def _step(id, name, role, **more):
    return {"id": id, "name": name, "who": {"role": role}, "done_when": "no_findings",
            "if_fails": "ask", "ask_me": False, "group": None, **more}


# As it was when this was written (`app.schemas.RecipeGraph`, version 1).
QUALITY_CHECK = {
    "version": 1,
    "steps": [
        _step("test", "Run the tests", "Tester"),
        _step("code", "Code review", "Reviewer", group="reviews"),
        _step("security", "Security review", "Security reviewer", group="reviews"),
    ],
    "groups": [{"id": "reviews", "name": "All at once, wait for all"}],
    "ends": [{"id": "end", "then": "report"}],
    "arrows": [{"from": a, "to": b} for a, b in (
        ("start", "test"), ("test", "reviews"), ("reviews", "end"))],
    "loops": [],
}
READY = "(SELECT id FROM recipes WHERE name = '{}' AND ready = 1)"
NEW, OLD = READY.format("Quality check"), READY.format("Review only")
# As 0093's: the ready teams are the first ever made, all at once by 0065.
STOCK = "name = 'Quality' AND created_at = (SELECT MIN(created_at) FROM teams)"


def upgrade() -> None:
    made = datetime.now(UTC).replace(tzinfo=None).isoformat(" ", "microseconds")
    # (A recipe of the user's own by that name keeps it: the ready one is not added.)
    op.get_bind().execute(sa.text(
        "INSERT INTO recipes (id, name, ready, graph, created_at, updated_at) "
        "SELECT :id, 'Quality check', 1, :graph, :at, :at "
        "WHERE NOT EXISTS (SELECT 1 FROM recipes WHERE lower(name) = 'quality check')"
    ), {"id": uuid.uuid4().hex, "graph": json.dumps(QUALITY_CHECK), "at": made})
    op.execute(f"UPDATE teams SET default_recipe_id = {NEW} "
               f"WHERE {STOCK} AND default_recipe_id = {OLD} AND {NEW} IS NOT NULL")


def downgrade() -> None:
    op.execute(f"UPDATE teams SET default_recipe_id = {OLD} "
               f"WHERE {STOCK} AND default_recipe_id = {NEW}")
    # (Gone only where nothing names it: no team's default, no chat's row.)
    op.execute(f"DELETE FROM recipes WHERE id IN {NEW} "
               "AND id NOT IN (SELECT default_recipe_id FROM teams "
               "WHERE default_recipe_id IS NOT NULL) "
               "AND id NOT IN (SELECT recipe_id FROM conversation_teams "
               "WHERE recipe_id IS NOT NULL)")
