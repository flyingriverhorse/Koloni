"""B-350: the level and the model the chats a project's backlog opens start with

Revision ID: 0130
Revises: 0129
"""
import sqlalchemy as sa
from alembic import op

revision = "0130"
# (Written on the k-r135 branch: re-chained after main's newest at its merge.)
down_revision = "0129"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column("backlog_mode", sa.String(12), nullable=False,
                                   server_default="ask"))
        batch.add_column(sa.Column("backlog_provider_id", sa.String(32), nullable=True))
        batch.add_column(sa.Column("backlog_model_id", sa.String(200), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("backlog_model_id")
        batch.drop_column("backlog_provider_id")
        batch.drop_column("backlog_mode")
