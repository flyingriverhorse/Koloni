"""day_note_at, day_note_sent: the day's summary sent at a time of day (slice 56)

Revision ID: 0055
Revises: 0054
"""
import sqlalchemy as sa
from alembic import op

revision = "0055"
down_revision = "0054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column("day_note_at", sa.String(5), nullable=True))
        batch.add_column(sa.Column("day_note_sent", sa.Date(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("day_note_sent")
        batch.drop_column("day_note_at")
