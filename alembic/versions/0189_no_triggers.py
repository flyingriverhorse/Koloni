"""Triggers are gone (the user's 25 Nov: KOLONİ is agents working together, not scheduled
automation): their four tables, the switch that paused them all, and `propose_trigger` from every
role's tools. A turn a trigger started stays as it was (`runs.unattended`, `runs.trigger_id`,
`runs.trigger_name`, `topics.trigger_id` and the "trigger" message are its record). Going back,
the tables come back as they were, empty, and the built-in Lead and Planner get the tool again.

Revision ID: 0189
Revises: 0187
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "0189"
# (Written on the k-tetik-sil branch on 0187, 0.1.9's head; 0188 was reverted and is no revision.)
down_revision = "0187"
branch_labels = None
depends_on = None

TOOL = "propose_trigger"
PAUSED = "triggers_paused"
# Where app.roles had the tool when this was written: after this one, else last.
AFTER = {"Lead": "assess_task", "Planner": "discuss"}


def _tools(held) -> list:
    return json.loads(held) if isinstance(held, str) else list(held)


def upgrade() -> None:
    bind = op.get_bind()
    # Every role, the user's own too: a role holding a tool that is gone is not saved again.
    for role_id, held in bind.execute(sa.text("SELECT id, tools FROM roles")).fetchall():
        tools = _tools(held)
        if TOOL in tools:
            bind.execute(
                sa.text("UPDATE roles SET tools = :tools WHERE id = :id"),
                {"tools": json.dumps([tool for tool in tools if tool != TOOL]), "id": role_id},
            )
    bind.execute(sa.text("DELETE FROM flags WHERE name = :name"), {"name": PAUSED})
    op.drop_index("ix_trigger_runs_trigger_id", table_name="trigger_runs")
    op.drop_table("trigger_runs")
    op.drop_index("ix_trigger_proposals_conversation_id", table_name="trigger_proposals")
    op.drop_table("trigger_proposals")
    op.drop_index("ix_trigger_changes_trigger_id", table_name="trigger_changes")
    op.drop_index("ix_trigger_changes_project_id", table_name="trigger_changes")
    op.drop_table("trigger_changes")
    op.drop_index("ix_triggers_project_id", table_name="triggers")
    op.drop_table("triggers")


def downgrade() -> None:
    # As 0019, 0020, 0097 and 0124 left them.
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
        sa.Column("key_hash", sa.String(length=64), nullable=True),
        sa.Column("last_words", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("ends", sa.JSON(), nullable=True),
        sa.Column("ran", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_key", sa.String(64), nullable=True),
        sa.Column("run_unchanged", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("idle", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_triggers_project_id", "triggers", ["project_id"])
    op.create_table(
        "trigger_changes",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("project_id", sa.String(length=32), nullable=False),
        sa.Column("trigger_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("at", sa.DateTime(), nullable=False),
        sa.Column("what", sa.String(length=24), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_trigger_changes_project_id", "trigger_changes", ["project_id"])
    op.create_index("ix_trigger_changes_trigger_id", "trigger_changes", ["trigger_id"])
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
    op.create_index(
        "ix_trigger_proposals_conversation_id", "trigger_proposals", ["conversation_id"]
    )
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
    op.create_index("ix_trigger_runs_trigger_id", "trigger_runs", ["trigger_id"])
    # The built-in Lead and Planner had the tool (0097); a role of the user's own that had it
    # does not get it back.
    bind = op.get_bind()
    for role_id, name, held in bind.execute(
        sa.text("SELECT id, name, tools FROM roles WHERE builtin AND name IN ('Lead', 'Planner')")
    ).fetchall():
        tools = _tools(held)
        if TOOL in tools:
            continue
        after = AFTER[name]
        at = tools.index(after) + 1 if after in tools else len(tools)
        bind.execute(
            sa.text("UPDATE roles SET tools = :tools WHERE id = :id"),
            {"tools": json.dumps([*tools[:at], TOOL, *tools[at:]]), "id": role_id},
        )
