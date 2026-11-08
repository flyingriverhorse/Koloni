"""why a tool call waits for the user, where it is not a path outside the project: a secret
file in it (slice 88)

Revision ID: 0068
Revises: 0067
"""
import sqlalchemy as sa
from alembic import op

revision = "0068"
down_revision = "0067"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tool_calls") as batch:
        batch.add_column(sa.Column("why_asked", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("tool_calls") as batch:
        batch.drop_column("why_asked")
