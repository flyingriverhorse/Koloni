"""a project says whether its agents finish only when the tests pass (89m); null: automatic

Revision ID: 0110
Revises: 0109
"""
import sqlalchemy as sa
from alembic import op

revision = "0110"
down_revision = "0109"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column("finish_tests", sa.Boolean(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("finish_tests")
