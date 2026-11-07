"""agents work at the same time; notes are delivered when they are read

Revision ID: 0009
Revises: 0008
"""
import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("conversations") as batch:
        batch.add_column(sa.Column(
            "spawn_max_parallel", sa.Integer(), nullable=False, server_default="2"))
    with op.batch_alter_table("messages") as batch:
        batch.add_column(sa.Column("delivered_at", sa.DateTime(), nullable=True))
    # What agents sent each other so far was read by its receiver as it was sent.
    op.execute("UPDATE messages SET delivered_at = created_at WHERE role = 'agent'")


def downgrade() -> None:
    op.execute("DELETE FROM channel_messages WHERE kind = 'note'")
    op.execute("UPDATE agents SET status = 'interrupted' WHERE status = 'queued'")
    with op.batch_alter_table("messages") as batch:
        batch.drop_column("delivered_at")
    with op.batch_alter_table("conversations") as batch:
        batch.drop_column("spawn_max_parallel")
