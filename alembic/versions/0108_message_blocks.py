"""an answer that thought, kept as its API gave it to be sent back so (K-dusunme-blok)

Revision ID: 0108
Revises: 0107
"""
import sqlalchemy as sa
from alembic import op

revision = "0108"
# (Written on the k-dusunme-blok branch: re-chained after main's newest at its merge.)
down_revision = "0107"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("messages") as batch:
        batch.add_column(sa.Column("blocks", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("messages") as batch:
        batch.drop_column("blocks")
