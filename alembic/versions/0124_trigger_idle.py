"""93-B2: a schedule whose runs find nothing slows down - its runs in a row that found nothing

A column of its own: the trigger's JSON fields are what the user set, and each of them goes
into the key a schedule is skipped by (`app.triggers.job_key`) - a count kept there would
change that key at every run.

Revision ID: 0124
Revises: 0123
"""
import sqlalchemy as sa
from alembic import op

revision = "0124"
# (Written on the k-kucukler2 branch: re-chained after main's newest at its merge.)
down_revision = "0123"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("triggers", sa.Column("idle", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    with op.batch_alter_table("triggers") as batch:
        batch.drop_column("idle")
