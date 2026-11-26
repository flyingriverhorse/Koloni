"""One judge (0.1.9 §8): Check what I said first is a question of Full auto's judge now - its own
box under the judge's switch, `judge_words`: on in a project whose old choice was "judge"
(`full_auto_check`, kept as a carrier), off in any other until its measurement. Going back, the
box goes; the old choice was never changed.

Revision ID: 0185
Revises: 0183
"""

import sqlalchemy as sa
from alembic import op

revision = "0185"
# (Written on the k-judge-sozun branch beside 0184 (k-away-park): re-chained at its merge.)
down_revision = "0183"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.add_column(
            sa.Column("judge_words", sa.Boolean(), nullable=False, server_default=sa.false())
        )
    op.execute("UPDATE projects SET judge_words = 1 WHERE full_auto_check = 'judge'")


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("judge_words")
