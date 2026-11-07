"""22c: the other projects a project's recall also looks in, read only; the provider and
model a search by meaning embeds with; and the vectors it compares

Revision ID: 0119
Revises: 0118
"""
import sqlalchemy as sa
from alembic import op

revision = "0119"
down_revision = "0118"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column(
            "memory_links", sa.JSON(), nullable=False, server_default="[]"))
        batch.add_column(sa.Column("embedding_provider_id", sa.String(32), nullable=True))
        batch.add_column(sa.Column(
            "embedding_model", sa.String(200), nullable=False,
            server_default="text-embedding-3-small"))
    op.create_table(
        "embeddings",
        sa.Column("kind", sa.String(8), primary_key=True),
        sa.Column("record_id", sa.String(32), primary_key=True),
        sa.Column("project_id", sa.String(32), nullable=False, index=True),
        sa.Column("model", sa.String(200), primary_key=True),
        sa.Column("vector", sa.JSON(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("embeddings")
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("embedding_model")
        batch.drop_column("embedding_provider_id")
        batch.drop_column("memory_links")
