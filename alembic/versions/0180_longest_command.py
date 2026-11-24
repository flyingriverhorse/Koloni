"""a project's longest command (0.1.8)

`MAX_TIMEOUT` cut every command at 10 minutes - a long test suite too, KOLONİ's own test run
among them. Projects get `longest_command`, in minutes (10 to 60), 10 for every one: as before
until the user raises it. Going back drops it.

Revision ID: 0176
Revises: 0175
"""

import sqlalchemy as sa
from alembic import op

revision = "0180"
# (Written on the k-araclar-018 branch: re-chained after main's newest at its merge.)
down_revision = "0179"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.add_column(
            sa.Column("longest_command", sa.Integer(), nullable=False, server_default="10")
        )


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("longest_command")
