"""memory: what agents noted and the user approved, per project; the user's standing rules

Revision ID: 0016
Revises: 0015
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

TOOLS = ("remember", "recall")


def _retool(change) -> None:
    """Rewrite each role's tool list with `change(tools)`."""
    conn = op.get_bind()
    for role_id, tools in conn.execute(sa.text("SELECT id, tools FROM roles")).fetchall():
        before = json.loads(tools) if isinstance(tools, str) else list(tools)
        after = change(before)
        if after != before:
            conn.execute(
                sa.text("UPDATE roles SET tools = :tools WHERE id = :id"),
                {"tools": json.dumps(after), "id": role_id},
            )


def upgrade() -> None:
    op.create_table(
        "memories",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("project_id", sa.String(length=32), nullable=False),
        sa.Column("tier", sa.String(length=8), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("about", sa.String(length=80), nullable=True),
        sa.Column("about_key", sa.String(length=80), nullable=True),
        sa.Column("origin", sa.String(length=8), nullable=False),
        sa.Column("agent_id", sa.String(length=32), nullable=True),
        sa.Column("run_id", sa.String(length=32), nullable=True),
        sa.Column("conversation_id", sa.String(length=32), nullable=True),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.Column("source_kind", sa.String(length=8), nullable=True),
        sa.Column("source_path", sa.Text(), nullable=True),
        sa.Column("source_start", sa.Integer(), nullable=True),
        sa.Column("source_end", sa.Integer(), nullable=True),
        sa.Column("source_hash", sa.String(length=64), nullable=True),
        sa.Column("checked_how", sa.String(length=80), nullable=True),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("supersedes_id", sa.String(length=32), nullable=True),
        sa.Column("wants_core", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("decided_by", sa.String(length=8), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("memories") as batch:
        batch.create_index(batch.f("ix_memories_project_id"), ["project_id"], unique=False)
    # One record in effect on a subject, in the journal and in the core: two agents
    # writing at once cannot both win.
    op.create_index(
        "uq_memories_active_subject", "memories", ["project_id", "tier", "about_key"],
        unique=True, sqlite_where=sa.text("status = 'active'"),
    )
    with op.batch_alter_table("agents") as batch:
        # The core records an agent was given when it started; empty for an agent from
        # before there was a memory, where that is not on record.
        batch.add_column(sa.Column("facts_given", sa.JSON(), nullable=True))
    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column("rules", sa.Text(), nullable=True))
    # Every role there is: a note in the journal changes nothing in the project, and
    # looking something up changes nothing at all.
    _retool(lambda tools: [*tools, *(tool for tool in TOOLS if tool not in tools)])


def downgrade() -> None:
    _retool(lambda tools: [tool for tool in tools if tool not in TOOLS])
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("rules")
    with op.batch_alter_table("agents") as batch:
        batch.drop_column("facts_given")
    op.drop_index("uq_memories_active_subject", table_name="memories")
    op.drop_table("memories")
