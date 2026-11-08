"""folders: the folders every project's agents may also use, a project's and a conversation's
folders to read only, and ask_folder for the Lead and the Planner (slice 75)

Numbered after main's newest (0059); renumbered when it is merged after another migration.

Revision ID: 0060
Revises: 0059
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0060"
down_revision = "0059"
branch_labels = None
depends_on = None

TOOL = "ask_folder"


def _retool(change) -> None:
    """Rewrite the built-in Lead's and Planner's tool lists with `change(tools)`, as 0048
    does: another role is given the tool only by the user."""
    conn = op.get_bind()
    for role_id, tools in conn.execute(
        sa.text("SELECT id, tools FROM roles WHERE builtin AND name IN ('Lead', 'Planner')")
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
        "open_folders",
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("access", sa.String(length=5), nullable=False),
        sa.PrimaryKeyConstraint("path"),
    )
    for table in ("projects", "conversations"):
        with op.batch_alter_table(table) as batch:
            batch.add_column(
                sa.Column("read_in", sa.JSON(), nullable=False, server_default="[]"))
    _retool(lambda tools: tools if TOOL in tools else [*tools, TOOL])


def downgrade() -> None:
    _retool(lambda tools: [tool for tool in tools if tool != TOOL])
    for table in ("projects", "conversations"):
        with op.batch_alter_table(table) as batch:
            batch.drop_column("read_in")
    op.drop_table("open_folders")
