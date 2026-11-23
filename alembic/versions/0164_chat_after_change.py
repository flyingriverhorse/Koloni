"""Check after a change for one chat (kanıtlı bitiş S10, plan decision 17)

`conversations.after_change`: null - the project's After a change, as before; "off" - this chat's
changes are not checked; "on" - they are (Check it where the project's is Nothing). Every chat
starts on null. Going back drops it.

Revision ID: 0164
Revises: 0163
"""
import sqlalchemy as sa
from alembic import op

revision = "0164"
# (Written on the k-kanit-sohbet branch: re-chained after main's newest at its merge.)
down_revision = "0163"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("conversations") as batch:
        batch.add_column(sa.Column("after_change", sa.String(3), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("conversations") as batch:
        batch.drop_column("after_change")
