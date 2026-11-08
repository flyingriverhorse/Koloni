"""a room an agent opens is given at least 60000 tokens, whatever it asks (B-414)

B-414 (live): a room asked for with 5000 tokens ended with no post - one member's step, with its
context, came to some 8,500. Projects and conversations get the least tokens an agent's room is
given, 60000 for every one - none had any before; null is none. Going back drops it.

Revision ID: 0154
Revises: 0153
"""
import sqlalchemy as sa
from alembic import op

revision = "0154"
# (Written on the k-b412 branch: re-chained after main's newest at its merge.)
down_revision = "0153"
branch_labels = None
depends_on = None

TABLES = ("projects", "conversations")


def upgrade() -> None:
    for table in TABLES:
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("room_min_tokens", sa.Integer(), nullable=True,
                                       server_default="60000"))


def downgrade() -> None:
    for table in TABLES:
        with op.batch_alter_table(table) as batch:
            batch.drop_column("room_min_tokens")
