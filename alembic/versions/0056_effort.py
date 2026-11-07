"""effort: a reasoning level per role, its most, the Lead's per conversation, and the level
an agent's steps were sent (slice 59a)

Revision ID: 0056
Revises: 0055
"""
import sqlalchemy as sa
from alembic import op

revision = "0056"
down_revision = "0055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # None everywhere: the model's own, as before.
    with op.batch_alter_table("roles") as batch:
        batch.add_column(sa.Column("effort", sa.String(length=8), nullable=True))
        batch.add_column(sa.Column("max_effort", sa.String(length=8), nullable=True))
    with op.batch_alter_table("conversations") as batch:
        batch.add_column(sa.Column("lead_effort", sa.String(length=8), nullable=True))
    with op.batch_alter_table("agents") as batch:
        batch.add_column(sa.Column("effort", sa.String(length=8), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("agents") as batch:
        batch.drop_column("effort")
    with op.batch_alter_table("conversations") as batch:
        batch.drop_column("lead_effort")
    with op.batch_alter_table("roles") as batch:
        batch.drop_column("max_effort")
        batch.drop_column("effort")
