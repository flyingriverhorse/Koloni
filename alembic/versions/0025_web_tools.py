"""agent tools: a project's search and notification addresses, what was asked about, what is allowed

Revision ID: 0025
Revises: 0024
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None

# The built-in roles that get the new tools, as a new database's have them. A role of the
# user's own is given none: what goes out of this machine is theirs to add.
TOOLS = {
    "Lead": ("web_search", "http_request", "notify"),
    "Researcher": ("web_search", "http_request"),
}
ALL = ("web_search", "http_request", "notify")
# The tools they come after in a role's list (`app.roles.ALL_TOOLS`, as it stood then).
BEFORE = ("list_dir", "read_file", "search", "write_file", "edit_file", "run_command")


def _retool(change) -> None:
    """Rewrite each role's tool list with `change(its name if it is built in, tools)`."""
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, name, builtin, tools FROM roles")).fetchall()
    for role_id, name, builtin, tools in rows:
        before = json.loads(tools) if isinstance(tools, str) else list(tools)
        after = change(name if builtin else None, before)
        if after != before:
            conn.execute(
                sa.text("UPDATE roles SET tools = :tools WHERE id = :id"),
                {"tools": json.dumps(after), "id": role_id},
            )


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column("search_url", sa.Text(), nullable=True))
        batch.add_column(sa.Column(
            "search_order", sa.String(length=8), server_default="builtin", nullable=False))
        batch.add_column(sa.Column("notify_url", sa.Text(), nullable=True))
    op.create_table(
        "web_requests",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("run_id", sa.String(length=32), nullable=False),
        sa.Column("agent_id", sa.String(length=32), nullable=False),
        sa.Column("tool_call_id", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("method", sa.String(length=8), nullable=True),
        sa.Column("target", sa.Text(), nullable=False),
        sa.Column("host", sa.String(length=253), nullable=True),
        sa.Column("headers", sa.JSON(), nullable=False),
        sa.Column("body_chars", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"]),
        sa.ForeignKeyConstraint(["tool_call_id"], ["tool_calls.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("web_requests") as batch:
        batch.create_index(batch.f("ix_web_requests_run_id"), ["run_id"], unique=False)
    op.create_table(
        "allowed_web",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("conversation_id", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("host", sa.String(length=253), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("conversation_id", "kind", "host", name="uq_allowed_web"),
    )
    with op.batch_alter_table("allowed_web") as batch:
        batch.create_index(
            batch.f("ix_allowed_web_conversation_id"), ["conversation_id"], unique=False)
    def add(name, tools):
        added = [tool for tool in TOOLS.get(name, ()) if tool not in tools]
        if not added:
            return tools
        # Where a new database has them: after the tools that act on the project.
        at = max((tools.index(tool) + 1 for tool in BEFORE if tool in tools), default=0)
        return [*tools[:at], *added, *tools[at:]]

    _retool(add)


def downgrade() -> None:
    _retool(lambda name, tools: [tool for tool in tools if tool not in ALL])
    op.drop_table("allowed_web")
    op.drop_table("web_requests")
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("notify_url")
        batch.drop_column("search_order")
        batch.drop_column("search_url")
