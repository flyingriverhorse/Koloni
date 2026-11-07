"""skills for roles: the skills KOLONİ keeps, the ones a role is given, and the Lead may add one (slice 45)

Revision ID: 0051
Revises: 0050
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0051"
down_revision = "0050"
branch_labels = None
depends_on = None

TOOL = "add_skill"


def _retool(change) -> None:
    """Rewrite the built-in Lead's tool list with `change(tools)`, as 0044 does: another
    role is given the tool only by the user."""
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
        "skills",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("license", sa.Text(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("folder", sa.Text(), nullable=False),
        sa.Column("files", sa.JSON(), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("scripts", sa.JSON(), nullable=False),
        sa.Column("hashes", sa.JSON(), nullable=False),
        sa.Column("scripts_run_unasked", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    # A role from before this has no skill (built-in ones get none: the user adds them).
    with op.batch_alter_table("roles") as batch:
        batch.add_column(sa.Column("skills", sa.JSON(), server_default="[]", nullable=False))
    _retool(lambda tools: tools if TOOL in tools else [*tools, TOOL])


def downgrade() -> None:
    _retool(lambda tools: [tool for tool in tools if tool != TOOL])
    with op.batch_alter_table("roles") as batch:
        batch.drop_column("skills")
    op.drop_table("skills")
