"""a chat team's row keeps where its recipe is - its step, its rounds back, the step's agents,
and whether it is done, failed or waits - across a restart (slice 84b-2)

Revision ID: 0076
Revises: 0075
"""
import sqlalchemy as sa
from alembic import op

revision = "0076"
down_revision = "0075"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("conversation_teams") as batch:
        batch.add_column(sa.Column("state", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("conversation_teams") as batch:
        batch.drop_column("state")
