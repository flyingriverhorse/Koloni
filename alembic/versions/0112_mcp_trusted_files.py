"""an MCP server's files in a folder agents write in, as the user said to start them (97)

Revision ID: 0112
Revises: 0111
"""
import sqlalchemy as sa
from alembic import op

revision = "0112"
down_revision = "0111"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("mcp_servers") as batch:
        batch.add_column(sa.Column("trusted_files", sa.JSON(), nullable=False,
                                   server_default="{}"))


def downgrade() -> None:
    with op.batch_alter_table("mcp_servers") as batch:
        batch.drop_column("trusted_files")
