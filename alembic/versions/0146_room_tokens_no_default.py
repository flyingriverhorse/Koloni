"""A new conversation's rooms have no token limit (the user, R185): its posts and minutes, and the
turn's and the project's own limits, hold them. A conversation's own value, 400000 or another,
is kept as it is.

Revision ID: 0146
Revises: 0145
"""
import sqlalchemy as sa
from alembic import op

revision = "0146"
# (Written on the k-r185 branch: re-chained after main's newest at its merge.)
down_revision = "0145"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("conversations") as batch:
        batch.alter_column("room_tokens", existing_type=sa.Integer(), server_default=None,
                           existing_nullable=True)


def downgrade() -> None:
    with op.batch_alter_table("conversations") as batch:
        batch.alter_column("room_tokens", existing_type=sa.Integer(), server_default="400000",
                           existing_nullable=True)
