"""usage: an agent whose step or CLI run ended before saying what it spent

Revision ID: 0028
Revises: 0027
"""
import sqlalchemy as sa
from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # False for an agent from before this: whether one of its steps was cut is not on
    # record, and it is not said to have been.
    with op.batch_alter_table("agents") as batch:
        batch.add_column(sa.Column(
            "cut_short", sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("agents") as batch:
        batch.drop_column("cut_short")
