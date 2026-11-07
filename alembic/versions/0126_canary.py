"""101: a project's planted test key (canary) - on by default

Revision ID: 0126
Revises: 0125
"""
import sqlalchemy as sa
from alembic import op

revision = "0126"
# (Written on the k-kanarya branch: re-chained after main's newest at its merge.)
down_revision = "0125"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column("canary", sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("canary")
