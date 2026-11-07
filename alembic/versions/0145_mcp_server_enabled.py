"""An MCP server switched off without being deleted: no agent is given it, its tools'
marks and its trust stay. Each one from before is on.

Revision ID: 0145
Revises: 0144
"""
import sqlalchemy as sa
from alembic import op

revision = "0145"
# (Written on the k-tools-a branch: re-chained after main's newest at its merge.)
down_revision = "0144"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("mcp_servers") as batch:
        batch.add_column(sa.Column(
            "enabled", sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    with op.batch_alter_table("mcp_servers") as batch:
        batch.drop_column("enabled")
