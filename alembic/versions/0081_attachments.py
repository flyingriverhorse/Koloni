"""attachments: files the user adds to a message; providers get tried_inputs, what a model
took or refused of them; file_changes get after_from, an attached file saved into the
project (slice 85b)

Revision ID: 0081
Revises: 0080
"""
import sqlalchemy as sa
from alembic import op

revision = "0081"
down_revision = "0080"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "attachments",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("conversation_id", sa.String(length=32), nullable=False),
        sa.Column("message_id", sa.String(length=32), nullable=True),
        sa.Column("frame_of", sa.String(length=32), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=12), nullable=False),
        sa.Column("mime", sa.String(length=100), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("given_to", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("keep_in_project", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"]),
        sa.ForeignKeyConstraint(["frame_of"], ["attachments.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_attachments_conversation_id", "attachments", ["conversation_id"])
    op.create_index("ix_attachments_message_id", "attachments", ["message_id"])
    with op.batch_alter_table("providers") as batch:
        batch.add_column(sa.Column("tried_inputs", sa.JSON(), nullable=True))
    with op.batch_alter_table("file_changes") as batch:
        batch.add_column(sa.Column("after_from", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("file_changes") as batch:
        batch.drop_column("after_from")
    with op.batch_alter_table("providers") as batch:
        batch.drop_column("tried_inputs")
    op.drop_index("ix_attachments_message_id", table_name="attachments")
    op.drop_index("ix_attachments_conversation_id", table_name="attachments")
    op.drop_table("attachments")
