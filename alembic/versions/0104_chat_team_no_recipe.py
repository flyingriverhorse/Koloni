"""a chat's team run with no recipe, not even its team's default (K-tarifsiz)

Revision ID: 0104
Revises: 0101
"""
import sqlalchemy as sa
from alembic import op

revision = "0104"
down_revision = "0101"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("conversation_teams") as batch:
        batch.add_column(sa.Column("no_recipe", sa.Boolean(), nullable=False,
                                   server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("conversation_teams") as batch:
        batch.drop_column("no_recipe")
