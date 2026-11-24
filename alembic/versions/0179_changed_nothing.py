"""L1, "Done" but nothing changed (Codex's live run, 24 Nov: a Coder said it was done having
changed no file, and its opener passed the report on)

`agents.changed_nothing`: a sub-agent whose role writes finished with no file change on KOLONİ's
record (`app.ledger.changed_nothing`) - its card says "No file changed". None: not judged so (every
other agent, and those from before this).

Going back drops it.

Revision ID: 0176
Revises: 0175
"""

import sqlalchemy as sa
from alembic import op

revision = "0179"
# (Written on the k-bitti-bos branch: re-chained after main's newest at its merge.)
down_revision = "0178"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agents") as batch:
        batch.add_column(sa.Column("changed_nothing", sa.Boolean(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("agents") as batch:
        batch.drop_column("changed_nothing")
