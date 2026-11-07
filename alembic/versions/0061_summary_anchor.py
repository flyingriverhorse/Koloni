"""summary_anchor: how many of an agent's answers its summary stands for, so that the
lead of a later turn goes on from it - and from what the user corrected in it (slice 59d).
Numbered after main's newest; renumbered at merge if another slice took 0060.

Revision ID: 0061
Revises: 0060
"""
import sqlalchemy as sa
from alembic import op

revision = "0061"
down_revision = "0060"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agents") as batch:
        batch.add_column(sa.Column("summary_anchor", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("agents") as batch:
        batch.drop_column("summary_anchor")
