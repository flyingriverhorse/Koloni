"""Test before adding goes (the user, 23 Nov: "the sub-agent should run only the tests it created -
running everything would choke us; make it automatic")

Take in's check runs the test files a sub-agent wrote, each with its part's test command narrowed
to them (`AgentRunner._own_runs`) - no command of the user's for it. `projects.check_command` is
dropped with what it held (one command; the end gate runs each part's tests, as without it).

Going back adds the column again, empty.

Revision ID: 0174
Revises: 0173
"""

import sqlalchemy as sa
from alembic import op

revision = "0174"
# (Written on the k-parca-test branch: re-chained after main's newest at its merge.)
down_revision = "0173"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("check_command")


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column("check_command", sa.String(500), nullable=True))
