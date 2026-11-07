"""an agent and a request of KOLONİ's own: what of the tokens sent was read again from the provider's cache and written to it; a price: for a million tokens read from the cache and a million written to it

Revision ID: 0041
Revises: 0040
"""
import sqlalchemy as sa
from alembic import op

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nobody said any of it of what ran before this, and no price from before has one
    # for the cache: all of it is unknown, not a zero.
    for table in ("agents", "own_requests"):
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("cache_read_tokens", sa.Integer(), nullable=True))
            batch.add_column(sa.Column("cache_write_tokens", sa.Integer(), nullable=True))
    with op.batch_alter_table("prices") as batch:
        batch.add_column(sa.Column("cache_read", sa.Float(), nullable=True))
        batch.add_column(sa.Column("cache_write", sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("prices") as batch:
        batch.drop_column("cache_write")
        batch.drop_column("cache_read")
    for table in ("own_requests", "agents"):
        with op.batch_alter_table(table) as batch:
            batch.drop_column("cache_write_tokens")
            batch.drop_column("cache_read_tokens")
