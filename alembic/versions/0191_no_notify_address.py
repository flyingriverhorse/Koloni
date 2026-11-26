"""The notification address goes (0.1.10, the user's 26 Nov: Slack / Discord cut): a project's
web hook address and the form it was posted in are dropped - the address is a secret, so it is not
left behind unused. The desktop notification stays. A day's summary whose time was set with only
the address to send it to has nowhere to go: its time is emptied.

Going back, the two columns come back empty (no address, "slack"); the summary's time does not.

Revision ID: 0191
Revises: 0187
"""

import sqlalchemy as sa
from alembic import op

revision = "0191"
# (Written on the k-kes-slack branch on 0187: re-chained after main's newest at its merge.)
down_revision = "0187"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE projects SET day_note_at = NULL WHERE day_note_at IS NOT NULL AND NOT notify_desktop"
    )
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("notify_format")
        batch.drop_column("notify_url")


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column("notify_url", sa.Text(), nullable=True))
        batch.add_column(
            sa.Column("notify_format", sa.String(length=8), server_default="slack", nullable=False)
        )
