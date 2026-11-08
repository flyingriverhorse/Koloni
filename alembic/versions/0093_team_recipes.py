"""ready teams' default recipes: Web app by Feature, Backend / API by Bugfix, Quality by Review
only (K-takim-tarif)

Only where the team is still the ready one and has none: a recipe the user chose is kept, and a
team the user made or renamed is left as it is.

Revision ID: 0093
Revises: 0092
"""
import sqlalchemy as sa
from alembic import op

revision = "0093"
down_revision = "0092"
branch_labels = None
depends_on = None

DEFAULTS = {"Web app": "Feature", "Backend / API": "Bugfix", "Quality": "Review only"}
READY = "(SELECT id FROM recipes WHERE name = :recipe AND ready = 1)"
# The ready teams are the first ever made, all at once by 0065: one of the user's is newer.
# shortcut: a team the user made by that name once every ready team was deleted is taken
# for the ready one; tell them apart by a column if that is ever seen.
STOCK = "name = :team AND created_at = (SELECT MIN(created_at) FROM teams)"


def upgrade() -> None:
    for team, recipe in DEFAULTS.items():
        op.get_bind().execute(sa.text(
            f"UPDATE teams SET default_recipe_id = {READY} "
            f"WHERE {STOCK} AND default_recipe_id IS NULL"), {"team": team, "recipe": recipe})


def downgrade() -> None:
    # (A user who chose that very recipe for the team since loses it too: not told apart.)
    for team, recipe in DEFAULTS.items():
        op.get_bind().execute(sa.text(
            f"UPDATE teams SET default_recipe_id = NULL "
            f"WHERE {STOCK} AND default_recipe_id = {READY}"), {"team": team, "recipe": recipe})
