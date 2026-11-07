"""effort_note: why an agent's model steps went without the level it was given - its
service refused it (slice 59c).

Revision ID: 0059
Revises: 0058
"""
import sqlalchemy as sa
from alembic import op

revision = "0059"
down_revision = "0058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agents") as batch:
        batch.add_column(sa.Column("effort_note", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("agents") as batch:
        batch.drop_column("effort_note")
