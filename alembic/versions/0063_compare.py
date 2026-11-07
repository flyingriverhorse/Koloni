"""compares: one message to two models side by side, each turn in a working copy of its own
(slice 54)

Revision ID: 0063
Revises: 0062
"""
import sqlalchemy as sa
from alembic import op

revision = "0063"
down_revision = "0062"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "compares",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("conversation_id", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("chosen_run_id", sa.String(length=32), nullable=True),
        sa.Column("sides", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_compares_conversation_id", "compares", ["conversation_id"])
    with op.batch_alter_table("runs") as batch:
        batch.add_column(sa.Column("compare_id", sa.String(length=32), nullable=True))
        batch.create_index("ix_runs_compare_id", ["compare_id"])


def downgrade() -> None:
    with op.batch_alter_table("runs") as batch:
        batch.drop_index("ix_runs_compare_id")
        batch.drop_column("compare_id")
    op.drop_index("ix_compares_conversation_id", table_name="compares")
    op.drop_table("compares")
