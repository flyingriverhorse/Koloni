"""a card of KOLONİ's may be the turn's own, under no agent's call (K-yavas)

K-yavas: the Orchestrator's model, silent for minutes in a turn the user watches, is asked about
on a card - Keep waiting, or Stop and pick another model - before its model has made any call.
Such a question hangs off no call: its `tool_call_id` may be null. Questions from before keep
theirs. Going back, the turn's own cards go.

Revision ID: 0155
Revises: 0154
"""

import sqlalchemy as sa
from alembic import op

revision = "0155"
# (Written on the k-slow-model branch: re-chained after main's newest at its merge.)
down_revision = "0154"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("questions") as batch:
        batch.alter_column("tool_call_id", existing_type=sa.String(length=32), nullable=True)


def downgrade() -> None:
    op.execute("DELETE FROM questions WHERE tool_call_id IS NULL")
    with op.batch_alter_table("questions") as batch:
        batch.alter_column("tool_call_id", existing_type=sa.String(length=32), nullable=False)
