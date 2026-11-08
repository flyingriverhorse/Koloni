"""a project's monthly budget, and the month its desktop was told it is 80% used (slice 55)

Revision ID: 0054
Revises: 0053
"""
import sqlalchemy as sa
from alembic import op

revision = "0054"
down_revision = "0053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column("monthly_budget", sa.Float(), nullable=True))
        batch.add_column(sa.Column("budget_told", sa.String(7), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("budget_told")
        batch.drop_column("monthly_budget")
