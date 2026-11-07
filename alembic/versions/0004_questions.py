"""questions an agent asks the user; built-in roles may ask

Revision ID: 0004
Revises: 0003
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


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
    op.create_table(
        "questions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("run_id", sa.String(length=32), nullable=False),
        sa.Column("agent_id", sa.String(length=32), nullable=False),
        sa.Column("tool_call_id", sa.String(length=32), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("options", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("answered_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"]),
        sa.ForeignKeyConstraint(["tool_call_id"], ["tool_calls.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("questions") as batch:
        batch.create_index(batch.f("ix_questions_run_id"), ["run_id"], unique=False)
    # Built-in roles may ask the user from now on; roles the user made are theirs to change.
    _retool(lambda tools, builtin: [*tools, "ask_user"]
            if builtin and "ask_user" not in tools else tools)


def downgrade() -> None:
    _retool(lambda tools, builtin: [tool for tool in tools if tool != "ask_user"])
    op.drop_table("questions")
