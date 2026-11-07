"""the part of the project's map a conversation's agents work in (K-buyuk-proje)

Revision ID: 0115
Revises: 0114
"""
import sqlalchemy as sa
from alembic import op

revision = "0115"
down_revision = "0114"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("conversations") as batch:
        batch.add_column(sa.Column("part", sa.String(length=500), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("conversations") as batch:
        batch.drop_column("part")
