"""limit readings: what each account last said of its plan, kept across restarts (slice 60a)

Revision ID: 0058
Revises: 0057
"""
import sqlalchemy as sa
from alembic import op

revision = "0058"
down_revision = "0057"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "limit_readings",
        sa.Column("account", sa.Text(), nullable=False),
        sa.Column("reading", sa.JSON(), nullable=False),
        sa.Column("read_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("account"),
    )


def downgrade() -> None:
    op.drop_table("limit_readings")
