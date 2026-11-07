"""rooms an agent opens: who opened one (none: the user), and the lead may open them

Revision ID: 0044
Revises: 0043
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None

TOOL = "open_room"


def _retool(change) -> None:
    """Rewrite the built-in Lead's tool list with `change(tools)`: another role is given the
    tool only by the user."""
    conn = op.get_bind()
    for role_id, tools in conn.execute(
        sa.text("SELECT id, tools FROM roles WHERE builtin AND name = 'Lead'")
    ).fetchall():
        before = json.loads(tools) if isinstance(tools, str) else list(tools)
        after = change(before)
        if after != before:
            conn.execute(
                sa.text("UPDATE roles SET tools = :tools WHERE id = :id"),
                {"tools": json.dumps(after), "id": role_id},
            )


def upgrade() -> None:
    with op.batch_alter_table("rooms") as batch:
        batch.add_column(sa.Column("agent_id", sa.String(length=32), nullable=True))
    _retool(lambda tools: tools if TOOL in tools else [*tools, TOOL])


def downgrade() -> None:
    _retool(lambda tools: [tool for tool in tools if tool != TOOL])
    with op.batch_alter_table("rooms") as batch:
        batch.drop_column("agent_id")
