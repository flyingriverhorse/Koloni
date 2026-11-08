"""what one agent's work hands on to the next (K-devir): a sub-agent's reads before its
first write, and the ended agents whose work its briefing carried

Revision ID: 0116
Revises: 0115
"""
import sqlalchemy as sa
from alembic import op

revision = "0116"
down_revision = "0115"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agents") as batch:
        batch.add_column(sa.Column("rediscovery", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("handed_from", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("agents") as batch:
        batch.drop_column("handed_from")
        batch.drop_column("rediscovery")
