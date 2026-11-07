"""a Take in card of a line's work on a git branch of its own (K-dal-takim)

`merges.branch_state`: the branch, the project's branch it would merge into, the files that
clash, the user's files in the way, and why git did not say. None for a copy's card.

Revision ID: 0135
Revises: 0134
"""
import sqlalchemy as sa
from alembic import op

revision = "0135"
# (Written on the k-dal-takim branch: re-chained after main's newest at its merge.)
down_revision = "0134"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("merges") as batch:
        batch.add_column(sa.Column("branch_state", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("merges") as batch:
        batch.drop_column("branch_state")
