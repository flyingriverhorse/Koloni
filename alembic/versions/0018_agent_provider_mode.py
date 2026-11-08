"""how an agent's provider ran when the agent was opened

Revision ID: 0018
Revises: 0017
"""
import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Empty for the agents there already are: how their provider ran then is not on
    # record, and it is not guessed from how the provider is set now.
    with op.batch_alter_table("agents") as batch:
        batch.add_column(sa.Column("provider_mode", sa.String(length=8), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("agents") as batch:
        batch.drop_column("provider_mode")
