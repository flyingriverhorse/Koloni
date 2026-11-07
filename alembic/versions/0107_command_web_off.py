"""a command asked because web is off says so, and its card offers no rule (K-web-komut)

Revision ID: 0107
Revises: 0106
"""
import sqlalchemy as sa
from alembic import op

revision = "0107"
down_revision = "0106"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("commands") as batch:
        batch.add_column(sa.Column("web_off", sa.Boolean(), nullable=False,
                                   server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("commands") as batch:
        batch.drop_column("web_off")
