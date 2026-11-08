"""A chat in no project has no room or discussion token limit unless someone set one (R188): the
user's decision 0147 applied to projects only. Nothing in the app sets a plain chat's own limits
any more (`models.settings_of`), so 400000 / 200000 there is the old default, untouched.

Revision ID: 0148
Revises: 0147
"""
from alembic import op

revision = "0148"
# (Written on the k-r188 branch: re-chained after main's newest at its merge.)
down_revision = "0147"
branch_labels = None
depends_on = None

OLD_DEFAULTS = (("room_tokens", 400_000), ("discussion_budget", 200_000))


def upgrade() -> None:
    for name, old in OLD_DEFAULTS:
        op.execute(f"UPDATE conversations SET {name} = NULL "
                   f"WHERE project_id IS NULL AND {name} = {old}")


def downgrade() -> None:
    # A null here cannot be told from one set so before: each gets the old default - stricter, never
    # looser, than it was.
    for name, old in OLD_DEFAULTS:
        op.execute(f"UPDATE conversations SET {name} = {old} "
                   f"WHERE project_id IS NULL AND {name} IS NULL")
