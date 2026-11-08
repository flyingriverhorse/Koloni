"""discussions: a shared place where several agents talk about one topic

Revision ID: 0010
Revises: 0009
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

TOOL = "discuss"
CALLERS = ("Lead", "Planner")  # the built-in roles that may open a discussion


def _retool(change) -> None:
    """Rewrite each role's tool list with `change(tools, name, builtin)`."""
    conn = op.get_bind()
    for role_id, name, tools, builtin in conn.execute(
        sa.text("SELECT id, name, tools, builtin FROM roles")
    ).fetchall():
        before = json.loads(tools) if isinstance(tools, str) else list(tools)
        after = change(before, name, bool(builtin))
        if after != before:
            conn.execute(
                sa.text("UPDATE roles SET tools = :tools WHERE id = :id"),
                {"tools": json.dumps(after), "id": role_id},
            )


def upgrade() -> None:
    op.create_table(
        "discussions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("run_id", sa.String(length=32), nullable=False),
        sa.Column("agent_id", sa.String(length=32), nullable=False),
        sa.Column("tool_call_id", sa.String(length=32), nullable=False),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("max_rounds", sa.Integer(), nullable=False),
        sa.Column("round", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("discussions") as batch:
        batch.create_index(batch.f("ix_discussions_run_id"), ["run_id"], unique=False)
    op.create_table(
        "discussion_members",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("discussion_id", sa.String(length=32), nullable=False),
        sa.Column("agent_id", sa.String(length=32), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=8), nullable=False),
        sa.Column("opened_here", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"]),
        sa.ForeignKeyConstraint(["discussion_id"], ["discussions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "discussion_posts",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("discussion_id", sa.String(length=32), nullable=False),
        sa.Column("agent_id", sa.String(length=32), nullable=True),
        sa.Column("round", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["discussion_id"], ["discussions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("discussion_posts") as batch:
        batch.create_index(
            batch.f("ix_discussion_posts_discussion_id"), ["discussion_id"], unique=False)
    with op.batch_alter_table("messages") as batch:
        batch.add_column(sa.Column("discussion_id", sa.String(length=32), nullable=True))
    _retool(lambda tools, name, builtin: [*tools, TOOL]
            if builtin and name in CALLERS and TOOL not in tools else tools)


def downgrade() -> None:
    _retool(lambda tools, name, builtin: [tool for tool in tools if tool != TOOL])
    # What was said in a discussion belongs to no agent's own conversation.
    op.execute("DELETE FROM messages WHERE discussion_id IS NOT NULL")
    with op.batch_alter_table("messages") as batch:
        batch.drop_column("discussion_id")
    op.drop_table("discussion_posts")
    op.drop_table("discussion_members")
    op.drop_table("discussions")
