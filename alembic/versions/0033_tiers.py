"""a role: the tier of model it asks for; a conversation: its lead's model by how hard the message is

Revision ID: 0033
Revises: 0032
"""
import sqlalchemy as sa
from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A role from before this asks for no tier. (The tier of a model is a key in its
    # provider's list, which is JSON; the new built-in roles are added at start, where
    # every built-in role that is missing is: `app.roles.seed_builtin_roles`.)
    with op.batch_alter_table("roles") as batch:
        batch.add_column(sa.Column("tier", sa.String(10), nullable=True))
    with op.batch_alter_table("conversations") as batch:
        batch.add_column(sa.Column(
            "lead_auto", sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("conversations") as batch:
        batch.drop_column("lead_auto")
    with op.batch_alter_table("roles") as batch:
        batch.drop_column("tier")
