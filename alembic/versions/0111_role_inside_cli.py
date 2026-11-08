"""a role may also run inside a Claude Code Lead as one of its own sub-agents (89g)

Revision ID: 0111
Revises: 0110
"""
import sqlalchemy as sa
from alembic import op

revision = "0111"
down_revision = "0110"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("roles") as batch:
        batch.add_column(sa.Column("inside_cli", sa.Boolean(), nullable=False,
                                   server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("roles") as batch:
        batch.drop_column("inside_cli")
