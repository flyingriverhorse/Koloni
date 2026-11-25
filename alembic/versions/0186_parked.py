"""☾ Away, park and continue (0.1.9): what a job parked for the user while they were away - a
command's card, a question the Orchestrator could not answer - each on a row of its own until the
user decides it under Waiting for you.

Going back, a parked command is "rejected" and a parked question "cancelled" (the statuses before
this), and the table goes.

Revision ID: 0186
Revises: 0185
"""

import sqlalchemy as sa
from alembic import op

revision = "0186"
# (Written on the k-away-park branch as 0184: re-chained after 0185, k-judge-sozun's, at its
# merge of 0.1.9.)
down_revision = "0185"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "parked",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("away_run_id", sa.String(32), sa.ForeignKey("away_runs.id"), nullable=False),
        sa.Column("task_id", sa.String(32), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("ref_id", sa.String(32), nullable=True),
        sa.Column("what", sa.Text(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("decision", sa.String(8), nullable=True),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("went_on", sa.String(32), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_parked_away_run_id", "parked", ["away_run_id"])
    op.create_index("ix_parked_task_id", "parked", ["task_id"])


def downgrade() -> None:
    op.execute("UPDATE commands SET status = 'rejected' WHERE status = 'parked'")
    op.execute("UPDATE questions SET status = 'cancelled' WHERE status = 'parked'")
    op.drop_index("ix_parked_task_id", table_name="parked")
    op.drop_index("ix_parked_away_run_id", table_name="parked")
    op.drop_table("parked")
