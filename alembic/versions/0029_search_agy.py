"""a project: whether a web search may be handed to agy, which cannot be held to its search tool

Revision ID: 0029
Revises: 0028
"""
import sqlalchemy as sa
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Off for a project from before this: the user has not said agy may search for it.
    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column(
            "search_agy", sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("search_agy")
