"""the shared notebook: notes every agent of a turn, and the user, leave for the others

Revision ID: 0014
Revises: 0013
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

TOOLS = ("post_note", "read_notes")


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
        "board_posts",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("run_id", sa.String(length=32), nullable=False),
        sa.Column("conversation_id", sa.String(length=32), nullable=False),
        sa.Column("agent_id", sa.String(length=32), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "seq", name="uq_board_posts_seq"),
    )
    with op.batch_alter_table("board_posts") as batch:
        batch.create_index(batch.f("ix_board_posts_run_id"), ["run_id"], unique=False)
    with op.batch_alter_table("messages") as batch:
        batch.add_column(sa.Column("board_post_id", sa.String(length=32), nullable=True))
    with op.batch_alter_table("agents") as batch:
        batch.add_column(sa.Column(
            "board_seen", sa.Integer(), nullable=False, server_default="0"))
    # Every role there is, also one the user changed or an agent created: a note
    # changes nothing, so a role that only reads may write one too.
    _retool(lambda tools: [*tools, *(tool for tool in TOOLS if tool not in tools)])


def downgrade() -> None:
    _retool(lambda tools: [tool for tool in tools if tool not in TOOLS])
    # A note handed to an agent would read as a message from another agent without this.
    op.execute("DELETE FROM messages WHERE board_post_id IS NOT NULL")
    with op.batch_alter_table("agents") as batch:
        batch.drop_column("board_seen")
    with op.batch_alter_table("messages") as batch:
        batch.drop_column("board_post_id")
    op.drop_table("board_posts")
