"""a role: which providers may be picked for it, and how far one agent of it may go; an agent: why its model was picked

Revision ID: 0032
Revises: 0031
"""
import sqlalchemy as sa
from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A role from before this: every provider of the team guide may be picked, no limit.
    with op.batch_alter_table("roles") as batch:
        batch.add_column(sa.Column("pick_from", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("max_steps", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("max_tokens", sa.Integer(), nullable=True))
    # Nobody said why an earlier pick was made.
    with op.batch_alter_table("agents") as batch:
        batch.add_column(sa.Column("chosen_why", sa.String(300), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("agents") as batch:
        batch.drop_column("chosen_why")
    with op.batch_alter_table("roles") as batch:
        batch.drop_column("max_tokens")
        batch.drop_column("max_steps")
        batch.drop_column("pick_from")
