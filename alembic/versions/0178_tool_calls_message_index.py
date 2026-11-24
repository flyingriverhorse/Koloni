"""An index on `tool_calls.message_id`: each model step's history loads the tool calls of the
messages it sends, by their ids (`AgentRunner._history_calls`) - it loaded the whole chat's.

Going back drops it.

Revision ID: 0176
Revises: 0175
"""

from alembic import op

revision = "0178"
# (Written on the k-kucuk-018 branch: re-chained after main's newest at its merge.)
down_revision = "0177"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_tool_calls_message_id", "tool_calls", ["message_id"])


def downgrade() -> None:
    op.drop_index("ix_tool_calls_message_id", "tool_calls")
