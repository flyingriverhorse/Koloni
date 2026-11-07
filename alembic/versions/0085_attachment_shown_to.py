"""attachments get shown_to: for each agent, what became of a picture or video for its
model - shown, or not and why - for the file's card (slice 85c)

Revision ID: 0085
Revises: 0084
"""
import sqlalchemy as sa
from alembic import op

revision = "0085"
down_revision = "0084"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("attachments") as batch:
        batch.add_column(sa.Column("shown_to", sa.JSON(), server_default="{}", nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("attachments") as batch:
        batch.drop_column("shown_to")
