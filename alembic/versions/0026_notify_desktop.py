"""a notification: shown on the desktop, and the form of the body posted to the address

Revision ID: 0026
Revises: 0025
"""
import sqlalchemy as sa
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column(
            "notify_format", sa.String(length=8), server_default="slack", nullable=False))
        batch.add_column(sa.Column(
            "notify_desktop", sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("notify_desktop")
        batch.drop_column("notify_format")
