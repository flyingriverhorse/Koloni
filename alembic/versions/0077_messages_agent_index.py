"""messages get an index on agent_id: the track record counts each agent's steps by it (K-33a)

Revision ID: 0077
Revises: 0076
"""
from alembic import op

revision = "0077"
down_revision = "0076"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("messages") as batch:
        batch.create_index(batch.f("ix_messages_agent_id"), ["agent_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("messages") as batch:
        batch.drop_index(batch.f("ix_messages_agent_id"))
