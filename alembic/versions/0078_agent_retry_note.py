"""agents get retry_note: a step asked again after a short failure of its provider (93-B3)

Revision ID: 0078
Revises: 0077
"""
import sqlalchemy as sa
from alembic import op

revision = "0078"
down_revision = "0077"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agents") as batch:
        batch.add_column(sa.Column("retry_note", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("agents") as batch:
        batch.drop_column("retry_note")
