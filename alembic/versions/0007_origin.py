"""who did a thing: KOLONİ for an agent, or a CLI agent with a tool of its own

Revision ID: 0007
Revises: 0006
"""
import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

TABLES = ("tool_calls", "commands", "file_changes")


def upgrade() -> None:
    for table in TABLES:
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column(
                "origin", sa.String(length=8), nullable=False, server_default="koloni"))


def downgrade() -> None:
    for table in TABLES:
        with op.batch_alter_table(table) as batch:
            batch.drop_column("origin")
