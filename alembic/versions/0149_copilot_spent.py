"""an agent: what Copilot says it spent in its own units - AI credits (in billionths, as it says
them) and premium requests, its older unit

Revision ID: 0149
Revises: 0148
"""
import sqlalchemy as sa
from alembic import op

revision = "0149"
# (Written on the k-copilot-token branch: re-chained after main's newest at its merge.)
down_revision = "0148"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nobody said it of what ran before this: unknown, not a zero.
    with op.batch_alter_table("agents") as batch:
        batch.add_column(sa.Column("nano_aiu", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("premium_requests", sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("agents") as batch:
        batch.drop_column("premium_requests")
        batch.drop_column("nano_aiu")
