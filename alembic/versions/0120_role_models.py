"""K-rol-model-sirasi: a role's ordered list of preferred models, tried before its own model
and its tier

Revision ID: 0120
Revises: 0119
"""
import sqlalchemy as sa
from alembic import op

revision = "0120"
down_revision = "0119"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("roles", sa.Column("models", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("roles") as batch:
        batch.drop_column("models")
