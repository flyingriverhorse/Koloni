"""what a decision on a memory record was, and when the user's rules last changed

Revision ID: 0017
Revises: 0016
"""
import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Both stay empty for what was decided before: who and when is on record there, what
    # the decision was is not, and it is not guessed.
    with op.batch_alter_table("memories") as batch:
        batch.add_column(sa.Column("decided_how", sa.String(length=12), nullable=True))
    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column("rules_changed_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("rules_changed_at")
    with op.batch_alter_table("memories") as batch:
        batch.drop_column("decided_how")
