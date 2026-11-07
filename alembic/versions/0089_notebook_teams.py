"""a note carries its team, "to everyone", and KOLONİ's own continuation note (K-not-oda)

Revision ID: 0089
Revises: 0088
"""
import sqlalchemy as sa
from alembic import op

revision = "0089"
down_revision = "0088"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("board_posts") as batch:
        batch.add_column(sa.Column("team_id", sa.String(32), nullable=True))
        batch.add_column(sa.Column("team", sa.String(60), nullable=True))
        batch.add_column(sa.Column("everyone", sa.Boolean(), nullable=False,
                                   server_default=sa.false()))
        batch.add_column(sa.Column("koloni", sa.Boolean(), nullable=False,
                                   server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("board_posts") as batch:
        for name in ("koloni", "everyone", "team", "team_id"):
            batch.drop_column(name)
