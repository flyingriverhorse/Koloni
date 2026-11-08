"""K-symphony: how a backlog task stands in a run of the backlog - the tasks it waits for, queued by
Run the backlog, a fix round due or had, stuck and why - in one JSON field

Revision ID: 0127
Revises: 0126
"""
import sqlalchemy as sa
from alembic import op

revision = "0127"
# (Written on the k-symphony branch beside another's 0125: re-chained after main's newest at its
# merge.)
down_revision = "0126"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("backlog_tasks", sa.Column("flow", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("backlog_tasks") as batch:
        batch.drop_column("flow")
