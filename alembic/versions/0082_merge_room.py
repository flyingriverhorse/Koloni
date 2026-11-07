"""merges get room_id: the room whose copy it takes into the project - a room's card shows
its own and no other merge of the agent that opened it (batch-15)

Revision ID: 0082
Revises: 0081
"""
import sqlalchemy as sa
from alembic import op

revision = "0082"
down_revision = "0081"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("merges") as batch:
        # (No foreign key: a conversation's rooms and merges are deleted together.)
        batch.add_column(sa.Column("room_id", sa.String(length=32), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("merges") as batch:
        batch.drop_column("room_id")
