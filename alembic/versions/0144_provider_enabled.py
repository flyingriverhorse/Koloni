"""A provider switched off without being deleted: nobody uses it, its key and settings stay.
Each one from before is on. (A model of it is switched off in its row of `models`.)

Revision ID: 0144
Revises: 0143
"""
import sqlalchemy as sa
from alembic import op

revision = "0144"
# (Written on the k-ac-kapa branch: re-chained after main's newest at its merge.)
down_revision = "0143"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("providers") as batch:
        batch.add_column(sa.Column(
            "enabled", sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    with op.batch_alter_table("providers") as batch:
        batch.drop_column("enabled")
