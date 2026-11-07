"""K-bilgi-repo: how many of a repository's code files new to its guide a learning reads at most

Revision ID: 0152
Revises: 0151
"""
import sqlalchemy as sa
from alembic import op

revision = "0152"
# (Written on the k-repo-knowledge branch: re-chained after main's newest at its merge.)
down_revision = "0151"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("knowledge") as batch:
        batch.add_column(sa.Column("max_code_files", sa.Integer(), nullable=False,
                                   server_default="100"))


def downgrade() -> None:
    with op.batch_alter_table("knowledge") as batch:
        batch.drop_column("max_code_files")
