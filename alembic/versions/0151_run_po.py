"""The Assistant PO's outcome on the turn it was asked about, for the canvas: the model asked,
whether it was heard out and what it spent, how many it proposed, and why each other was dropped

Revision ID: 0151
Revises: 0150
"""
import sqlalchemy as sa
from alembic import op

revision = "0151"
# (Written on the k-po-node branch: re-chained after main's newest at its merge.)
down_revision = "0150"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("runs") as batch:
        batch.add_column(sa.Column("po", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("runs") as batch:
        batch.drop_column("po")
