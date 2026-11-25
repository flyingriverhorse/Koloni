"""What Full auto's judge does with a command it finds risky (0.1.9, the user's 25 Nov): refuse it
and let the agent go on, as Claude Code's auto mode does ("refuse") - the default, existing projects
too -, or put it on a card as before ("ask"). Going back, the choice goes.

Revision ID: 0187
Revises: 0186
"""

import sqlalchemy as sa
from alembic import op

revision = "0187"
# (Written on the k-judge-ret branch on 0185; re-chained after 0186, k-away-park's, at its merge of
# 0.1.9.)
down_revision = "0186"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.add_column(
            sa.Column("judge_risky", sa.String(6), nullable=False, server_default="refuse")
        )


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("judge_risky")
