"""the command that scores a candidate's work (K-evrim slice 1)

`projects.measure_command`: the last line of its output is a number from 0 to 100. None: nothing
is measured.

Revision ID: 0140
Revises: 0139
"""
import sqlalchemy as sa
from alembic import op

revision = "0140"
# (Written on the k-evrim-1 branch: re-chained after main's newest at its merge.)
down_revision = "0139"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column("measure_command", sa.String(500), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("measure_command")
