"""hide_secrets and pass_env on a project: its commands are kept from its secret files and
variables (slices 103-105)

Revision ID: 0070
Revises: 0069
"""
import sqlalchemy as sa
from alembic import op

revision = "0070"
down_revision = "0069"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column(
            "hide_secrets", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch.add_column(sa.Column("pass_env", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("pass_env")
        batch.drop_column("hide_secrets")
