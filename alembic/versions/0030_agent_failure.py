"""an agent: why its model failed, as the provider itself said, and when a limit resets

Revision ID: 0030
Revises: 0029
"""
import sqlalchemy as sa
from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nothing for an agent from before this: why it failed was not put on record.
    with op.batch_alter_table("agents") as batch:
        batch.add_column(sa.Column("failure", sa.String(20), nullable=True))
        batch.add_column(sa.Column("failure_resets_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("agents") as batch:
        batch.drop_column("failure_resets_at")
        batch.drop_column("failure")
