"""K-skill-uyum / K-skill-puan: a skill switched off on the Tools page, and the skills an agent
was given (and left out, with why) when it started

A skill's switch is its own column, not a Flag row: a Flag's name holds 40 characters, a
skill's name 64. The agent's skills are kept on its record as its tools and MCP servers are,
so its track record says what it had then, whatever the role has now.

Revision ID: 0123
Revises: 0122
"""
import sqlalchemy as sa
from alembic import op

revision = "0123"
# (Written on the k-skill branch: re-chained after main's newest at its merge.)
down_revision = "0122"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("skills", sa.Column(
        "enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("agents", sa.Column("skills", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("agents") as batch:
        batch.drop_column("skills")
    with op.batch_alter_table("skills") as batch:
        batch.drop_column("enabled")
