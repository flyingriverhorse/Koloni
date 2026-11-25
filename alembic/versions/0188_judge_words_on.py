"""Check what I said first's box (`judge_words`, 0.1.9 §8) is ticked in a new project, now that a
judge model's measurement passed (Claude Code's haiku, 25 Nov 2026): it works where the Judge model
is a measured one (`judge.MEASURED_MODELS`), and asks nothing on another. A project there already
keeps its box as it is. Going back, a new project's box is unticked again.

Revision ID: 0188
Revises: 0187
"""

import sqlalchemy as sa
from alembic import op

revision = "0188"
# (Written on the k-judge-olcum branch on 0187: re-chain it at its merge where another took 0188.)
down_revision = "0187"
branch_labels = None
depends_on = None


def _default(value: sa.sql.elements.ColumnElement) -> None:
    with op.batch_alter_table("projects") as batch:
        batch.alter_column(
            "judge_words", existing_type=sa.Boolean(), existing_nullable=False, server_default=value
        )


def upgrade() -> None:
    _default(sa.true())


def downgrade() -> None:
    _default(sa.false())
