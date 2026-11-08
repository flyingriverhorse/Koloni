"""observe_reports on a project, and on an agent what the Observer's model said of its
report, why it said nothing, and who it was (slice 33b)

Revision ID: 0049
Revises: 0048
"""
import sqlalchemy as sa
from alembic import op

revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column(
            "observe_reports", sa.Boolean(), nullable=False, server_default=sa.false()))
    with op.batch_alter_table("agents") as batch:
        batch.add_column(sa.Column("observation", sa.Text(), nullable=True))
        batch.add_column(sa.Column("observation_note", sa.Text(), nullable=True))
        batch.add_column(sa.Column("observed_by", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("agents") as batch:
        batch.drop_column("observed_by")
        batch.drop_column("observation_note")
        batch.drop_column("observation")
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("observe_reports")
