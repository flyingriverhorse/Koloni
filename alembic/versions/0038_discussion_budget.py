"""a conversation: the most tokens the speakers of one discussion may report before it is ended

Revision ID: 0038
Revises: 0037
"""
import sqlalchemy as sa
from alembic import op

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A conversation from before this gets the budget a new one starts with.
    with op.batch_alter_table("conversations") as batch:
        batch.add_column(sa.Column(
            "discussion_budget", sa.Integer(), nullable=True, server_default="200000"))


def downgrade() -> None:
    with op.batch_alter_table("conversations") as batch:
        batch.drop_column("discussion_budget")
