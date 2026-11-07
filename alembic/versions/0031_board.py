"""a project's and a provider's limit on agents at work; a conversation's lane and the changes outside it

Revision ID: 0031
Revises: 0030
"""
import sqlalchemy as sa
from alembic import op

revision = "0031"
# After slice 25a's 0030: the two were built side by side and joined here.
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column("max_agents", sa.Integer(), nullable=True))
    with op.batch_alter_table("providers") as batch:
        batch.add_column(sa.Column("max_running", sa.Integer(), nullable=True))
    with op.batch_alter_table("conversations") as batch:
        batch.add_column(sa.Column("lane", sa.Text(), nullable=True))
    # A change from before there were lanes was outside none.
    with op.batch_alter_table("file_changes") as batch:
        batch.add_column(sa.Column(
            "outside_lane", sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("file_changes") as batch:
        batch.drop_column("outside_lane")
    with op.batch_alter_table("conversations") as batch:
        batch.drop_column("lane")
    with op.batch_alter_table("providers") as batch:
        batch.drop_column("max_running")
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("max_agents")
