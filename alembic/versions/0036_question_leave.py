"""a question says whether it is KOLONİ's own: leave asked for a tool

Revision ID: 0036
Revises: 0035
"""
import sqlalchemy as sa
from alembic import op

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A question from before this is shown as an agent's own, as it was then.
    with op.batch_alter_table("questions") as batch:
        batch.add_column(sa.Column(
            "leave", sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("questions") as batch:
        batch.drop_column("leave")
