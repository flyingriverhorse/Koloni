"""whether the Lead follows a room the user opened (K-oda-izle): off, on, or stopped

Revision ID: 0105
Revises: 0104
"""
import sqlalchemy as sa
from alembic import op

revision = "0105"
# (Written on the k-oda-izle branch: re-chained after main's newest at its merge.)
down_revision = "0104"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("rooms") as batch:
        batch.add_column(sa.Column(
            "lead_follows", sa.String(8), nullable=False, server_default="off"))


def downgrade() -> None:
    with op.batch_alter_table("rooms") as batch:
        batch.drop_column("lead_follows")
