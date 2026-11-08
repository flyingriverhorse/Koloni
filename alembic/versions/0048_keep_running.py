"""commands.keep_running and commands.preview_url: a command that keeps running, and the
address on this machine it said it serves on (slice 42b)

Revision ID: 0048
Revises: 0047
"""
import sqlalchemy as sa
from alembic import op

revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("commands") as batch:
        batch.add_column(
            sa.Column("keep_running", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch.add_column(sa.Column("preview_url", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("commands") as batch:
        batch.drop_column("preview_url")
        batch.drop_column("keep_running")
