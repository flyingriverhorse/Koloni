"""22b: the user's own preferences, one text for every project; and a memory record's tier
can be "preference" - a line the summariser suggests for them, waiting for the user

Revision ID: 0118
Revises: 0117
"""
import sqlalchemy as sa
from alembic import op

revision = "0118"
down_revision = "0117"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_preferences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("changed_at", sa.DateTime(), nullable=True),
    )
    with op.batch_alter_table("memories") as batch:
        batch.alter_column("tier", existing_type=sa.String(8), type_=sa.String(12))


def downgrade() -> None:
    with op.batch_alter_table("memories") as batch:
        batch.alter_column("tier", existing_type=sa.String(12), type_=sa.String(8))
    op.drop_table("user_preferences")
