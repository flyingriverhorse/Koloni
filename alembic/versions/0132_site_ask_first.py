"""K-tarayici-disari: a site the agent's browser may open (`allowed_web` kind "page") can be
marked Ask first - asked at every level, Full auto too

Revision ID: 0132
Revises: 0131
"""
import sqlalchemy as sa
from alembic import op

revision = "0132"
# (Written on the k-tarayici branch: re-chained after main's newest at its merge.)
down_revision = "0131"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("allowed_web") as batch:
        batch.add_column(sa.Column("ask_first", sa.Boolean(), nullable=False,
                                   server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("allowed_web") as batch:
        batch.drop_column("ask_first")
