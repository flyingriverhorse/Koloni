"""also in: the folders outside the project that a project's agents, and a conversation's,
also work in; and the folder a call outside them asked for (slice 41)

Revision ID: 0045
Revises: 0044
"""
import sqlalchemy as sa
from alembic import op

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("projects", "conversations"):
        with op.batch_alter_table(table) as batch:
            batch.add_column(
                sa.Column("also_in", sa.JSON(), nullable=False, server_default="[]"))
    with op.batch_alter_table("tool_calls") as batch:
        batch.add_column(sa.Column("outside_folder", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("tool_calls") as batch:
        batch.drop_column("outside_folder")
    for table in ("projects", "conversations"):
        with op.batch_alter_table(table) as batch:
            batch.drop_column("also_in")
