"""the tokens a room's opener spent following it (K-oda-lead S7)

Revision ID: 0099
Revises: 0097
"""
import sqlalchemy as sa
from alembic import op

revision = "0099"
# (Written on the k-oda branch: re-chained after main's newest at its merge.)
down_revision = "0097"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("rooms") as batch:
        batch.add_column(sa.Column("opener_tokens", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("rooms") as batch:
        batch.drop_column("opener_tokens")
