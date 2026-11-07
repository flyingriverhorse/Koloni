"""an agent: what was counted of its own tool calls (the same call failing the same way, or
a reading call returning the same, N times), and when it last took a step or a tool did
anything for it

Revision ID: 0042
Revises: 0041
"""
import sqlalchemy as sa
from alembic import op

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nothing was counted of what ran before this, and nobody noted its last event: unknown.
    with op.batch_alter_table("agents") as batch:
        batch.add_column(sa.Column("sign", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("last_event_at", sa.DateTime(), nullable=True))
        # Which failed agents KOLONİ itself stopped: not known of any before this.
        batch.add_column(sa.Column(
            "stopped_by_koloni", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("agents") as batch:
        batch.drop_column("stopped_by_koloni")
        batch.drop_column("last_event_at")
        batch.drop_column("sign")
