"""To-do proposals at a turn's end (the Assistant PO): whether a project's chats get them and
from which tier, the proposals turned down, and a proposal's record on its task

Revision ID: 0150
Revises: 0149
"""
import sqlalchemy as sa
from alembic import op

revision = "0150"
# (Written on the k-todo-po branch: re-chained after main's newest at its merge.)
down_revision = "0149"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        # On by default (the user, 6 Nov): one small request after a turn that did something.
        batch.add_column(sa.Column("suggest_tasks", sa.Boolean(), nullable=False,
                                   server_default=sa.true()))
        batch.add_column(sa.Column("suggest_tier", sa.String(10), nullable=False,
                                   server_default="fast"))
        batch.add_column(sa.Column("po_rejected", sa.JSON(), nullable=True))
    with op.batch_alter_table("backlog_tasks") as batch:
        batch.add_column(sa.Column("po", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("backlog_tasks") as batch:
        batch.drop_column("po")
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("po_rejected")
        batch.drop_column("suggest_tier")
        batch.drop_column("suggest_tasks")
