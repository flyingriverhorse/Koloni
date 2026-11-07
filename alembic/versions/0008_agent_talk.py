"""agents have names and can message each other

Revision ID: 0008
Revises: 0007
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

TOOL = "message_agent"


def _retool(change) -> None:
    """Rewrite each role's tool list with `change(tools, builtin)`."""
    conn = op.get_bind()
    for role_id, tools, builtin in conn.execute(
        sa.text("SELECT id, tools, builtin FROM roles")
    ).fetchall():
        before = json.loads(tools) if isinstance(tools, str) else list(tools)
        after = change(before, bool(builtin))
        if after != before:
            conn.execute(
                sa.text("UPDATE roles SET tools = :tools WHERE id = :id"),
                {"tools": json.dumps(after), "id": role_id},
            )


def upgrade() -> None:
    with op.batch_alter_table("agents") as batch:
        batch.add_column(sa.Column(
            "name", sa.String(length=80), nullable=False, server_default=""))
    with op.batch_alter_table("messages") as batch:
        batch.add_column(sa.Column("from_agent_id", sa.String(length=32), nullable=True))
    # An agent is named after its role; the second of a role in one turn is "Role 2".
    conn = op.get_bind()
    seen: dict[tuple[str, str], int] = {}
    for agent_id, run_id, role in conn.execute(sa.text(
        "SELECT id, run_id, role_name FROM agents ORDER BY created_at, rowid"
    )).fetchall():
        count = seen[run_id, role] = seen.get((run_id, role), 0) + 1
        conn.execute(
            sa.text("UPDATE agents SET name = :name WHERE id = :id"),
            {"name": role if count == 1 else f"{role} {count}", "id": agent_id},
        )
    # Built-in roles may message other agents from now on; the user's own roles are theirs.
    _retool(lambda tools, builtin: [*tools, TOOL] if builtin and TOOL not in tools else tools)


def downgrade() -> None:
    _retool(lambda tools, builtin: [tool for tool in tools if tool != TOOL])
    op.execute("DELETE FROM messages WHERE role = 'agent'")
    op.execute("DELETE FROM channel_messages WHERE kind IN ('message', 'reply')")
    with op.batch_alter_table("messages") as batch:
        batch.drop_column("from_agent_id")
    with op.batch_alter_table("agents") as batch:
        batch.drop_column("name")
