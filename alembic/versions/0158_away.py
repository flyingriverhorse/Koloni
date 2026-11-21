"""☾ Away: a To-do task keeps the chat it was proposed in, an away run what its chat had spent
before Go away; a new project lets the Orchestrator decide a waiting card after 5 minutes

The night card goes: the Orchestrator puts the work on To-do (`backlog_tasks.proposed_in`, the
chat it came from, ticked in that chat's Away panel) and the user's Go away works it through.
`away_runs.spent_before`: what the away chat had spent at Go away, not counted to its money.
New projects default to `when_away` "lead" after 5 minutes; rows from before keep theirs (as 0147
kept a chat's own). A chat's own stays "waits": a plain chat reads it and cannot change it.
Going back drops both columns and the old default returns.

Revision ID: 0158
Revises: 0156
"""
import sqlalchemy as sa
from alembic import op

revision = "0158"
# (Written on the k-away branch: re-chained after the newest at its merge.)
down_revision = "0156"
branch_labels = None
depends_on = None


def _defaults(when: str, minutes: str) -> None:
    # (A project's only: a plain chat has no way to change its own, so everything waits there.)
    with op.batch_alter_table("projects") as batch:
        batch.alter_column("when_away", existing_type=sa.String(length=5),
                           server_default=when, existing_nullable=False)
        batch.alter_column("away_minutes", existing_type=sa.Integer(),
                           server_default=minutes, existing_nullable=False)


def upgrade() -> None:
    with op.batch_alter_table("backlog_tasks") as batch:
        batch.add_column(sa.Column("proposed_in", sa.String(length=32), nullable=True))
    with op.batch_alter_table("away_runs") as batch:
        batch.add_column(sa.Column("spent_before", sa.Float(), nullable=True))
    _defaults("lead", "5")


def downgrade() -> None:
    _defaults("waits", "10")
    with op.batch_alter_table("away_runs") as batch:
        batch.drop_column("spent_before")
    with op.batch_alter_table("backlog_tasks") as batch:
        batch.drop_column("proposed_in")
