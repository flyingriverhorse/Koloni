"""roles, agents, channel messages; every record is tied to the agent that made it

Revision ID: 0003
Revises: 0002
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

# What the single agent of slices 1 and 2 could use; later tools did not exist yet.
_LEAD_TOOLS = json.dumps([
    "list_dir", "read_file", "search", "write_file", "edit_file", "run_command",
])


def upgrade() -> None:
    op.create_table(
        "roles",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("tools", sa.JSON(), nullable=False),
        sa.Column("builtin", sa.Boolean(), nullable=False),
        sa.Column("created_by_agent", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "agents",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("run_id", sa.String(length=32), nullable=False),
        sa.Column("parent_agent_id", sa.String(length=32), nullable=True),
        sa.Column("tool_call_id", sa.String(length=32), nullable=True),
        sa.Column("role_name", sa.String(length=60), nullable=False),
        sa.Column("tools", sa.JSON(), nullable=False),
        sa.Column("task", sa.Text(), nullable=True),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("report", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["parent_agent_id"], ["agents.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("agents") as batch:
        batch.create_index(batch.f("ix_agents_run_id"), ["run_id"], unique=False)
    op.create_table(
        "channel_messages",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("run_id", sa.String(length=32), nullable=False),
        sa.Column("from_agent_id", sa.String(length=32), nullable=False),
        sa.Column("to_agent_id", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["from_agent_id"], ["agents.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"]),
        sa.ForeignKeyConstraint(["to_agent_id"], ["agents.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("channel_messages") as batch:
        batch.create_index(batch.f("ix_channel_messages_run_id"), ["run_id"], unique=False)

    with op.batch_alter_table("conversations") as batch:
        batch.add_column(
            sa.Column("spawn_approval", sa.String(length=8), nullable=False, server_default="auto")
        )
        batch.add_column(
            sa.Column("spawn_max_depth", sa.Integer(), nullable=False, server_default="2")
        )
        batch.add_column(
            sa.Column("spawn_max_agents", sa.Integer(), nullable=False, server_default="6")
        )

    # Every turn that started gets the lead agent it implicitly had, and its records
    # are tied to that agent. A turn still queued (or removed from the queue) has none.
    op.execute(
        "INSERT INTO agents (id, run_id, parent_agent_id, role_name, tools, task, depth, status, "
        "report, error, input_tokens, output_tokens, created_at, started_at, ended_at) "
        "SELECT lower(hex(randomblob(16))), id, NULL, 'Lead', '" + _LEAD_TOOLS + "', NULL, 0, "
        "CASE status WHEN 'waiting_approval' THEN 'running' ELSE status END, "
        "NULL, error, input_tokens, output_tokens, created_at, started_at, ended_at "
        "FROM runs WHERE started_at IS NOT NULL"
    )
    lead_of_run = "(SELECT agents.id FROM agents WHERE agents.run_id = {table}.run_id)"
    for table, nullable in (
        ("messages", True), ("tool_calls", False), ("commands", False), ("file_changes", False),
    ):
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("agent_id", sa.String(length=32), nullable=True))
        only_agents = " WHERE role = 'assistant'" if table == "messages" else ""
        op.execute(
            f"UPDATE {table} SET agent_id = {lead_of_run.format(table=table)}{only_agents}"
        )
        with op.batch_alter_table(table) as batch:
            batch.alter_column("agent_id", existing_type=sa.String(length=32), nullable=nullable)
            batch.create_foreign_key(f"fk_{table}_agent_id_agents", "agents", ["agent_id"], ["id"])


def downgrade() -> None:
    for table in ("file_changes", "commands", "tool_calls", "messages"):
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(f"fk_{table}_agent_id_agents", type_="foreignkey")
            batch.drop_column("agent_id")
    with op.batch_alter_table("conversations") as batch:
        batch.drop_column("spawn_max_agents")
        batch.drop_column("spawn_max_depth")
        batch.drop_column("spawn_approval")
    op.drop_table("channel_messages")
    op.drop_table("agents")
    op.drop_table("roles")
