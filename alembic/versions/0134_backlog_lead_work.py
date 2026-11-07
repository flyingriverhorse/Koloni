"""K-r144: who changes the files in the chats a project's backlog opens

Revision ID: 0134
Revises: 0133
"""
import sqlalchemy as sa
from alembic import op

revision = "0134"
# (Written on the k-r144 branch: re-chained after main's newest at its merge.)
down_revision = "0133"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column("backlog_lead_work", sa.String(9), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("backlog_lead_work")
