"""a tool call made inside a CLI's own sub-agent names the call that started it

Revision ID: 0012
Revises: 0011
"""
import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tool_calls") as batch:
        batch.add_column(sa.Column("parent_call_id", sa.String(length=32), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("tool_calls") as batch:
        batch.drop_column("parent_call_id")
