"""shown files: what an agent put before the user with `show` - a file of the project, by
conversation, with a note of one line, and the working copy it was shown from (slice 39)

Revision ID: 0043
Revises: 0042
"""
import sqlalchemy as sa
from alembic import op

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shown_files",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("conversation_id", sa.String(length=32), nullable=False),
        sa.Column("agent_id", sa.String(length=32), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("copy_owner", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"]),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("shown_files") as batch:
        batch.create_index(
            batch.f("ix_shown_files_conversation_id"), ["conversation_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("shown_files") as batch:
        batch.drop_index(batch.f("ix_shown_files_conversation_id"))
    op.drop_table("shown_files")
