"""lead_hands_code: the Lead hands every change to files to a sub-agent (slice 48)

Revision ID: 0050
Revises: 0049
"""
import sqlalchemy as sa
from alembic import op

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # On for the conversations there are, as for new ones.
    with op.batch_alter_table("conversations") as batch:
        batch.add_column(sa.Column(
            "lead_hands_code", sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    with op.batch_alter_table("conversations") as batch:
        batch.drop_column("lead_hands_code")
