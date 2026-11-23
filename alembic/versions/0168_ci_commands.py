"""The CI commands of a project, offered and approved once (kanıtlı bitiş S8, decision 3)

`projects.ci_commands`: the lint, typecheck and test lines KOLONİ found in the project's
`.github/workflows`, offered once ("offered": their hash and lines) and, after the user's Run
these, "approved" - the end check runs exactly those; a change to a workflow asks again. Every
project starts with none. Going back drops it.

Revision ID: 0168
Revises: 0165
"""

import sqlalchemy as sa
from alembic import op

revision = "0168"
# (Written on the k-kanit-ci branch: 0168, after S7's 0166 and S5a's 0167 - re-chained after
# main's newest at its merge.)
down_revision = "0165"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column("ci_commands", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("ci_commands")
