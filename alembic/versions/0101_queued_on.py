"""an agent queued for its provider's room says which is full (K-paralel-saglayici)

Revision ID: 0101
Revises: 0103
"""
import sqlalchemy as sa
from alembic import op

revision = "0101"
down_revision = "0103"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agents") as batch:
        batch.add_column(sa.Column("queued_on", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("agents") as batch:
        batch.drop_column("queued_on")
