"""K-devam-butce: the steps a stopped agent gets on top when it is told to go on with none
left (the project's setting), and what each agent was given so

Revision ID: 0117
Revises: 0116
"""
import sqlalchemy as sa
from alembic import op

revision = "0117"
down_revision = "0116"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column(
            "continue_steps", sa.Integer(), nullable=False, server_default="25"))
    with op.batch_alter_table("agents") as batch:
        batch.add_column(sa.Column(
            "steps_given", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    with op.batch_alter_table("agents") as batch:
        batch.drop_column("steps_given")
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("continue_steps")
