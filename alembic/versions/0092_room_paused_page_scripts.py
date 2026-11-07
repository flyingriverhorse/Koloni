"""a room the user paused (29c); a conversation whose pages' scripts run without asking (K-39-betik)

Revision ID: 0092
Revises: 0091
"""
import sqlalchemy as sa
from alembic import op

revision = "0092"
# (Written beside K-vekil-karar's 0091 and put after it once that was on main, before this one
# reached main: no database had applied it.)
down_revision = "0091"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("rooms") as batch:
        batch.add_column(sa.Column(
            "paused", sa.Boolean(), nullable=False, server_default=sa.false()))
    with op.batch_alter_table("conversations") as batch:
        batch.add_column(sa.Column(
            "page_scripts", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("conversations") as batch:
        batch.drop_column("page_scripts")
    with op.batch_alter_table("rooms") as batch:
        batch.drop_column("paused")
