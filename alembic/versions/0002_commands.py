"""commands, allow list, permission levels, execution location

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.add_column(
            sa.Column("exec_location", sa.String(length=8), nullable=False, server_default="host")
        )
        batch.add_column(sa.Column("docker_image", sa.String(length=200), nullable=True))
        batch.add_column(
            sa.Column("docker_network", sa.Boolean(), nullable=False, server_default=sa.false())
        )

    # edit_mode (ask | auto) becomes permission_mode (ask | auto_edit | full_auto).
    with op.batch_alter_table("conversations") as batch:
        batch.add_column(
            sa.Column("permission_mode", sa.String(length=12), nullable=False, server_default="ask")
        )
    op.execute(
        "UPDATE conversations SET permission_mode = "
        "CASE edit_mode WHEN 'auto' THEN 'auto_edit' ELSE 'ask' END"
    )
    with op.batch_alter_table("conversations") as batch:
        batch.drop_column("edit_mode")

    op.create_table(
        "commands",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("run_id", sa.String(length=32), nullable=False),
        sa.Column("tool_call_id", sa.String(length=32), nullable=False),
        sa.Column("command", sa.Text(), nullable=False),
        sa.Column("cwd", sa.Text(), nullable=False),
        sa.Column("location", sa.String(length=8), nullable=False),
        sa.Column("image", sa.String(length=200), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("output", sa.Text(), nullable=False),
        sa.Column("output_truncated", sa.Boolean(), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"]),
        sa.ForeignKeyConstraint(["tool_call_id"], ["tool_calls.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("commands") as batch:
        batch.create_index(batch.f("ix_commands_run_id"), ["run_id"], unique=False)

    op.create_table(
        "allowed_commands",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("conversation_id", sa.String(length=32), nullable=False),
        sa.Column("prefix", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("conversation_id", "prefix", name="uq_allowed_commands_prefix"),
    )
    with op.batch_alter_table("allowed_commands") as batch:
        batch.create_index(
            batch.f("ix_allowed_commands_conversation_id"), ["conversation_id"], unique=False
        )


def downgrade() -> None:
    op.drop_table("allowed_commands")
    op.drop_table("commands")
    with op.batch_alter_table("conversations") as batch:
        batch.add_column(
            sa.Column("edit_mode", sa.String(length=8), nullable=False, server_default="ask")
        )
    op.execute(
        "UPDATE conversations SET edit_mode = "
        "CASE permission_mode WHEN 'ask' THEN 'ask' ELSE 'auto' END"
    )
    with op.batch_alter_table("conversations") as batch:
        batch.drop_column("permission_mode")
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("docker_network")
        batch.drop_column("docker_image")
        batch.drop_column("exec_location")
