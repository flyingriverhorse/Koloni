"""an MCP server the user adds is watched until they trust it; those there were are (92)

Revision ID: 0113
Revises: 0112 (slice 97)
"""
import sqlalchemy as sa
from alembic import op

revision = "0113"
down_revision = "0112"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("mcp_servers") as batch:
        batch.add_column(sa.Column("trusted", sa.Boolean(), nullable=False,
                                   server_default=sa.true()))


def downgrade() -> None:
    with op.batch_alter_table("mcp_servers") as batch:
        batch.drop_column("trusted")
