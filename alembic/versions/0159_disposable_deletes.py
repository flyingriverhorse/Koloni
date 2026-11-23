"""a project's disposable deletes, and what of a command was disposable (coordination §4)

A delete KOLONİ can check by itself - a build or cache folder, a clean worktree, a merged branch -
may go without a card at Auto-edit and Full auto in a watched turn, where the user allowed it.
Projects get `disposable_deletes`, off for every one (as before: each such delete is asked until
the user allows it); commands get `disposable`, what of one was disposable and whether it ran
unasked for that (null: nothing). Going back drops both.

Revision ID: 0159
Revises: 0158
"""

import sqlalchemy as sa
from alembic import op

revision = "0159"
# (Written on the k-atilabilir branch: re-chained after main's newest at its merge.)
down_revision = "0158"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.add_column(
            sa.Column("disposable_deletes", sa.Boolean(), nullable=False, server_default=sa.false())
        )
    with op.batch_alter_table("commands") as batch:
        batch.add_column(sa.Column("disposable", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("commands") as batch:
        batch.drop_column("disposable")
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("disposable_deletes")
