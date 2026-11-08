"""a provider's limits: a key that is a plan, a subscription's step down, the most an API key
may spend in a day and in a month (slice 81c)

Revision ID: 0066
Revises: 0065
"""
import sqlalchemy as sa
from alembic import op

revision = "0066"
down_revision = "0065"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("providers") as batch:
        batch.add_column(sa.Column("plan", sa.Boolean(), server_default=sa.false(), nullable=False))
        batch.add_column(sa.Column("step_down_at", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("day_limit", sa.Float(), nullable=True))
        batch.add_column(sa.Column("month_limit", sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("providers") as batch:
        for column in ("month_limit", "day_limit", "step_down_at", "plan"):
            batch.drop_column(column)
