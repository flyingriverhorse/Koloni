"""a trigger's end, its skip when nothing changed, and the Lead's proposed triggers
(K-tetik-bitis, K-tetik-degismedi, 69)

A trigger may end by itself - after a day or after so many runs - and keeps the turns it
started since; a schedule keeps the key of its last completed turn, and whether it runs even
when nothing changed since (those made before this run even so, as they did). An agent's
proposed trigger waits on a card for the user's word;
the built-in Lead and Planner get `propose_trigger`.

Revision ID: 0097
Revises: 0096
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0097"
# shortcut: chained to 0093, main's head when this was merged; re-point at the final merge.
down_revision = "0096"
branch_labels = None
depends_on = None

TOOL = "propose_trigger"


def _retool(change) -> None:
    """Rewrite the built-in Lead's and Planner's tool lists with `change(tools)`, as 0062
    does: a sub-agent never has a tool its opener has not."""
    conn = op.get_bind()
    for role_id, tools in conn.execute(sa.text(
        "SELECT id, tools FROM roles WHERE builtin AND name IN ('Lead', 'Planner')"
    )).fetchall():
        before = json.loads(tools) if isinstance(tools, str) else list(tools)
        after = change(before)
        if after != before:
            conn.execute(sa.text("UPDATE roles SET tools = :tools WHERE id = :id"),
                         {"tools": json.dumps(after), "id": role_id})


def upgrade() -> None:
    with op.batch_alter_table("triggers") as batch:
        batch.add_column(sa.Column("ends", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("ran", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("last_key", sa.String(64), nullable=True))
        batch.add_column(sa.Column("run_unchanged", sa.Boolean(), nullable=False,
                                   server_default=sa.false()))
    # The triggers there are already run as they always did; a new one skips by default.
    op.execute("UPDATE triggers SET run_unchanged = 1")
    op.create_table(
        "trigger_proposals",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("conversation_id", sa.String(length=32), nullable=False),
        sa.Column("run_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("ends", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("trigger_id", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_trigger_proposals_conversation_id", "trigger_proposals",
                    ["conversation_id"])
    _retool(lambda tools: tools if TOOL in tools else [*tools, TOOL])


def downgrade() -> None:
    _retool(lambda tools: [tool for tool in tools if tool != TOOL])
    op.drop_index("ix_trigger_proposals_conversation_id", table_name="trigger_proposals")
    op.drop_table("trigger_proposals")
    with op.batch_alter_table("triggers") as batch:
        batch.drop_column("run_unchanged")
        batch.drop_column("last_key")
        batch.drop_column("ran")
        batch.drop_column("ends")
