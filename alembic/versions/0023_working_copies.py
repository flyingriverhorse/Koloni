"""working copies: where an agent changes files, and a copy on its way into the project

Revision ID: 0023
Revises: 0022
"""
import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Empty for every agent there already is: each of them worked in the project.
    with op.batch_alter_table("agents") as batch:
        batch.add_column(sa.Column("copy", sa.JSON(), nullable=True))
    op.create_table(
        "merges",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("run_id", sa.String(32), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("agent_id", sa.String(32), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("files", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_merges_run_id", "merges", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_merges_run_id", table_name="merges")
    op.drop_table("merges")
    with op.batch_alter_table("agents") as batch:
        batch.drop_column("copy")
