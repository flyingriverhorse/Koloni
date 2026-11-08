"""file claims: the agent and the file an agent is waiting for

Revision ID: 0022
Revises: 0021
"""
import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Empty for every agent there already is: none of them is waiting for a file.
    with op.batch_alter_table("agents") as batch:
        batch.add_column(sa.Column("waiting_for", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("agents") as batch:
        batch.drop_column("waiting_for")
