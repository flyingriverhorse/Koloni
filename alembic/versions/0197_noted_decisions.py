"""The Orchestrator's noted decisions (0.1.11, note_decision)

- `noted_decisions`: a decision the Orchestrator noted for the user while it worked - what it
  decided and why, its words masked, on one line and cut - read as a fifth source of the decision
  log (Decided for you on the Work page's Ready for you), with the user's OK.

Going back drops the table and the decisions noted in it.

Revision ID: 0197
Revises: 0196
"""

import sqlalchemy as sa
from alembic import op

revision = "0197"
# (Written on the k-turn-tools branch: re-chained after main's newest at its merge.)
down_revision = "0196"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "noted_decisions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("run_id", sa.String(32), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("agent_id", sa.String(32), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("tool_call_id", sa.String(32), nullable=True),
        sa.Column("what", sa.String(200), nullable=False),
        sa.Column("why", sa.String(200), nullable=False),
        sa.Column("seen_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_noted_decisions_run_id", "noted_decisions", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_noted_decisions_run_id", table_name="noted_decisions")
    op.drop_table("noted_decisions")
