"""MCP servers the user connects: the servers, and which a role and an agent may use

Revision ID: 0035
Revises: 0034
"""
import sqlalchemy as sa
from alembic import op

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mcp_servers",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=16), nullable=False),
        sa.Column("command", sa.JSON(), nullable=False),
        sa.Column("env", sa.JSON(), nullable=False),
        sa.Column("tools", sa.JSON(), nullable=False),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.Column("read_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    # A role, and an agent, from before this may use no server.
    for table in ("roles", "agents"):
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("mcp", sa.JSON(), server_default="[]", nullable=False))


def downgrade() -> None:
    for table in ("agents", "roles"):
        with op.batch_alter_table(table) as batch:
            batch.drop_column("mcp")
    op.drop_table("mcp_servers")
