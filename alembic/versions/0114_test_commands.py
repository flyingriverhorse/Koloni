"""the user's test command for a part of the project, by the part's path (K-buyuk-proje)

Revision ID: 0114
Revises: 0113
"""
import sqlalchemy as sa
from alembic import op

revision = "0114"
down_revision = "0113"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.add_column(
            sa.Column("test_commands", sa.JSON(), nullable=False, server_default="{}"))


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("test_commands")
