"""a conversation has no lane any more, nor a change one outside it: each chat has its own
folders and its agents work in their own copies (slice 86b)

Revision ID: 0072
Revises: 0071
"""
import sqlalchemy as sa
from alembic import op

revision = "0072"
down_revision = "0071"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("file_changes") as batch:
        batch.drop_column("outside_lane")
    with op.batch_alter_table("conversations") as batch:
        batch.drop_column("lane")


def downgrade() -> None:
    with op.batch_alter_table("conversations") as batch:
        batch.add_column(sa.Column("lane", sa.Text(), nullable=True))
    with op.batch_alter_table("file_changes") as batch:
        batch.add_column(sa.Column(
            "outside_lane", sa.Boolean(), server_default=sa.false(), nullable=False))
