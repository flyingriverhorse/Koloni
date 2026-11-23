"""Fix rounds: how often a turn's end check sends work back (kanıtlı bitiş S3, decisions 14a, 19)

`projects.fix_rounds`: failing tests and a Reviewer's blocking findings go back to the
Orchestrator at most this many times a turn, one count for both - 1 to 5, every project starting
on 2, the number it was. Going back drops it.

Revision ID: 0165
Revises: 0164
"""
import sqlalchemy as sa
from alembic import op

revision = "0165"
# (Written on the k-kanit-inceleme branch: re-chained after main's newest at its merge.)
down_revision = "0164"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column("fix_rounds", sa.Integer(), nullable=False,
                                   server_default="2"))


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("fix_rounds")
