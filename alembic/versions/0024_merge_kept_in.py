"""working copies: where a copy that was kept is on disk

Revision ID: 0024
Revises: 0023
"""
import sqlalchemy as sa
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Empty for every merge there already is: what it says of a kept folder is in its notes.
    with op.batch_alter_table("merges") as batch:
        batch.add_column(sa.Column("kept_in", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("merges") as batch:
        batch.drop_column("kept_in")
