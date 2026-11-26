"""The search by meaning goes (0.1.10, the user's 26 Nov): the vectors it kept, and a project's
provider and model for it, are dropped. The search by words, and the linked projects, stay.

Going back, the table and the two columns come back empty: no provider chosen (word search
alone), the default model name.

Revision ID: 0192
Revises: 0191
"""

import sqlalchemy as sa
from alembic import op

revision = "0192"
# (Written on the k-kes-anlam branch on 0187; chained after 0191 when it went into 0.1.10.)
down_revision = "0191"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("embeddings")
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("embedding_model")
        batch.drop_column("embedding_provider_id")


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column("embedding_provider_id", sa.String(32), nullable=True))
        batch.add_column(
            sa.Column(
                "embedding_model",
                sa.String(200),
                nullable=False,
                server_default="text-embedding-3-small",
            )
        )
    op.create_table(
        "embeddings",
        sa.Column("kind", sa.String(8), primary_key=True),
        sa.Column("record_id", sa.String(32), primary_key=True),
        sa.Column("project_id", sa.String(32), nullable=False, index=True),
        sa.Column("model", sa.String(200), primary_key=True),
        sa.Column("vector", sa.JSON(), nullable=False),
    )
