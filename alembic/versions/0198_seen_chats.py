"""When the user last looked at a chat (0.1.11, herdr's "done, not seen")

- `conversations.seen_at`: when its page last had it on screen - opened, or looked at as a turn
  of it ended. A chat whose last turn ended after it shows "done · not seen" (Chats, Now).
  Every chat there is now counts as seen: nothing of before is said unseen.

Going back drops the column.

Revision ID: 0198
Revises: 0197
"""

import sqlalchemy as sa
from alembic import op

revision = "0198"
# (Written on the k-herdr branch: re-chained after main's newest at its merge.)
down_revision = "0197"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("conversations") as batch:
        batch.add_column(sa.Column("seen_at", sa.DateTime(), nullable=True))
    op.execute("UPDATE conversations SET seen_at = CURRENT_TIMESTAMP")


def downgrade() -> None:
    with op.batch_alter_table("conversations") as batch:
        batch.drop_column("seen_at")
