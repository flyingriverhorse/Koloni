"""context: a model's window set in a role, and an agent's window, how many of its
messages were summarised and the latest summary (slice 59b)

Revision ID: 0057
Revises: 0056
"""
import sqlalchemy as sa
from alembic import op

revision = "0057"
down_revision = "0056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # None: as found (the model's own window, or unknown).
    with op.batch_alter_table("roles") as batch:
        batch.add_column(sa.Column("context_window", sa.Integer(), nullable=True))
    with op.batch_alter_table("agents") as batch:
        batch.add_column(sa.Column("context_window", sa.Integer(), nullable=True))
        batch.add_column(
            sa.Column("summarised", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("summary", sa.Text(), nullable=True))
        batch.add_column(sa.Column("summary_note", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("agents") as batch:
        batch.drop_column("summary_note")
        batch.drop_column("summary")
        batch.drop_column("summarised")
        batch.drop_column("context_window")
    with op.batch_alter_table("roles") as batch:
        batch.drop_column("context_window")
