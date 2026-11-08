"""plan_first on a conversation; on a run, whether it is a plan turn and the plan it wrote
(slice 49)

Revision ID: 0052
Revises: 0051
"""
import sqlalchemy as sa
from alembic import op

revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("conversations") as batch:
        batch.add_column(sa.Column(
            "plan_first", sa.Boolean(), nullable=False, server_default=sa.false()))
    with op.batch_alter_table("runs") as batch:
        batch.add_column(sa.Column(
            "plan_turn", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("plan", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("runs") as batch:
        batch.drop_column("plan")
        batch.drop_column("plan_turn")
    with op.batch_alter_table("conversations") as batch:
        batch.drop_column("plan_first")
