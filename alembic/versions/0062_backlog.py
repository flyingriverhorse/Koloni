"""a project's backlog, and the Lead may read it and propose, change and assess tasks; and
whether the backlog works itself, and why it stopped (slice 52)

Revision ID: 0062
Revises: 0061
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0062"
down_revision = "0061"
branch_labels = None
depends_on = None

TOOLS = ("read_backlog", "add_task", "change_task", "assess_task")


def _retool(change) -> None:
    """Rewrite the built-in Lead's tool list with `change(tools)`, as 0051 does: a
    sub-agent never has a tool its opener has not, so a Product owner opened by a Lead
    without these could propose nothing."""
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
    op.create_table(
        "backlog_tasks",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("project_id", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("criteria", sa.Text(), nullable=True),
        sa.Column("priority", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.String(length=32), nullable=True),
        sa.Column("created_by", sa.String(length=8), nullable=False),
        sa.Column("pending", sa.JSON(), nullable=True),
        sa.Column("assessment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_backlog_tasks_project_id", "backlog_tasks", ["project_id"])
    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column(
            "backlog_auto", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("backlog_halt", sa.Text(), nullable=True))
    _retool(lambda tools: [*tools, *(tool for tool in TOOLS if tool not in tools)])


def downgrade() -> None:
    _retool(lambda tools: [tool for tool in tools if tool not in TOOLS])
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("backlog_halt")
        batch.drop_column("backlog_auto")
    op.drop_index("ix_backlog_tasks_project_id", table_name="backlog_tasks")
    op.drop_table("backlog_tasks")
