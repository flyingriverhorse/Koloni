"""K-bilgi 6: what turns found for a project's Project notes, waiting for the user's word on a card
that never holds a turn - one waiting in a project at a time

Revision ID: 0142
Revises: 0141
"""
import sqlalchemy as sa
from alembic import op

revision = "0142"
# (Written on the k-bilgi-67 branch: re-chained after main's newest at its merge.)
down_revision = "0141"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notes_offers",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("project_id", sa.String(32), sa.ForeignKey("projects.id"), nullable=False),
        # (By id alone: a deleted chat leaves the project's offer, pointing nowhere.)
        sa.Column("conversation_id", sa.String(32), nullable=True),
        sa.Column("run_id", sa.String(32), nullable=True),
        sa.Column("items", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_notes_offers_project_id", "notes_offers", ["project_id"])
    op.create_index("ix_notes_offers_conversation_id", "notes_offers", ["conversation_id"])
    op.create_index("uq_notes_offers_waiting", "notes_offers", ["project_id"], unique=True,
                    sqlite_where=sa.text("status = 'waiting'"))


def downgrade() -> None:
    op.drop_index("uq_notes_offers_waiting", "notes_offers")
    op.drop_index("ix_notes_offers_conversation_id", "notes_offers")
    op.drop_index("ix_notes_offers_project_id", "notes_offers")
    op.drop_table("notes_offers")
