"""what KOLONİ found as a project's test command, and its one look for one (kanıtlı bitiş, S1b)

`tests_found`: by folder ("." the root), the test command KOLONİ saved itself the first time it
really ran tests - its guess from the project's files, an agent's run, or the look - with where it
came from and when ({folder: {"command", "from", "at"}}). It is the end check's, never the user's
own: the user's check command and a part's test command win, and it gets none of their leave.
`tests_look`: the one read-only look by the project's Fast-tier model, once a project (null: none
yet). Going back drops both.

Revision ID: 0163
Revises: 0162
"""

import sqlalchemy as sa
from alembic import op

revision = "0163"
# (Written on the k-kanit-ogren branch: re-chained after main's newest at its merge.)
down_revision = "0162"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column("tests_found", sa.JSON(), nullable=False, server_default="{}"))
        batch.add_column(sa.Column("tests_look", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("tests_look")
        batch.drop_column("tests_found")
