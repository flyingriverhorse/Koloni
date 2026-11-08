"""spoken: what a message asked of the lead's answer to be said aloud, on the turn, and the
line the lead wrote to be said, on its message (slice 32a)

Revision ID: 0046
Revises: 0045
"""
import sqlalchemy as sa
from alembic import op

revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("runs") as batch:
        batch.add_column(sa.Column("spoken", sa.JSON(), nullable=True))
    with op.batch_alter_table("messages") as batch:
        batch.add_column(sa.Column("spoken", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("messages") as batch:
        batch.drop_column("spoken")
    with op.batch_alter_table("runs") as batch:
        batch.drop_column("spoken")
