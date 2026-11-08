"""triggers: turns that start by themselves, and what such a turn may do unasked

Revision ID: 0019
Revises: 0018
"""
import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "triggers",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("project_id", sa.String(length=32), nullable=False),
        sa.Column("conversation_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("permissions", sa.JSON(), nullable=False),
        sa.Column("budget", sa.JSON(), nullable=False),
        sa.Column("catch_up", sa.Boolean(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("failures", sa.Integer(), nullable=False),
        sa.Column("off_because", sa.Text(), nullable=True),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("last_result", sa.String(length=16), nullable=True),
        sa.Column("anchor_at", sa.DateTime(), nullable=True),
        sa.Column("next_at", sa.DateTime(), nullable=True),
        # Only the digest of a webhook's key is kept.
        sa.Column("key_hash", sa.String(length=64), nullable=True),
        sa.Column("last_words", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("triggers") as batch:
        batch.create_index(batch.f("ix_triggers_project_id"), ["project_id"], unique=False)
    op.create_table(
        "trigger_runs",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("trigger_id", sa.String(length=32), nullable=False),
        sa.Column("run_id", sa.String(length=32), nullable=True),
        sa.Column("at", sa.DateTime(), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=True),
        sa.Column("late", sa.Boolean(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["trigger_id"], ["triggers.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("trigger_runs") as batch:
        batch.create_index(batch.f("ix_trigger_runs_trigger_id"), ["trigger_id"], unique=False)
    op.create_table(
        "flags",
        sa.Column("name", sa.String(length=40), nullable=False),
        sa.Column("value", sa.String(length=200), nullable=False),
        sa.PrimaryKeyConstraint("name"),
    )
    # Every turn there already is was started by the user, and every note written in one.
    with op.batch_alter_table("runs") as batch:
        batch.add_column(
            sa.Column("unattended", sa.Boolean(), server_default=sa.false(), nullable=False)
        )
        batch.add_column(sa.Column("trigger_id", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("trigger_name", sa.String(length=80), nullable=True))
    with op.batch_alter_table("memories") as batch:
        batch.add_column(
            sa.Column("unattended", sa.Boolean(), server_default=sa.false(), nullable=False)
        )


def downgrade() -> None:
    with op.batch_alter_table("memories") as batch:
        batch.drop_column("unattended")
    with op.batch_alter_table("runs") as batch:
        batch.drop_column("trigger_name")
        batch.drop_column("trigger_id")
        batch.drop_column("unattended")
    op.drop_table("flags")
    op.drop_table("trigger_runs")
    op.drop_table("triggers")
