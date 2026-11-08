"""usage: all an agent sent, the user's prices for models, a limit on a turn's tokens

Revision ID: 0027
Revises: 0026
"""
import sqlalchemy as sa
from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No default: an agent from before this stays unknown, not zero.
    with op.batch_alter_table("agents") as batch:
        batch.add_column(sa.Column("input_tokens_total", sa.Integer(), nullable=True))
    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column("turn_token_limit", sa.Integer(), nullable=True))
    op.create_table(
        "prices",
        sa.Column("model_id", sa.String(length=200), primary_key=True),
        sa.Column("input", sa.Float(), nullable=False),
        sa.Column("output", sa.Float(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("prices")
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("turn_token_limit")
    with op.batch_alter_table("agents") as batch:
        batch.drop_column("input_tokens_total")
