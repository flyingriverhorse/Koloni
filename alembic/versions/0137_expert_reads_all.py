"""an expert reads everything under its sources (K-uzman-derin)

Its money limit says how much of it is written into the guide; `max_pages` is only a safety cap
now. An expert kept with the old default (20) gets the new one (500), so that Learn again reads
on past the 20 pages it stopped at.

Revision ID: 0137
Revises: 0136
"""
from alembic import op

revision = "0137"
# (Written on the k-uzman-derin branch: re-chained after main's newest at its merge.)
down_revision = "0136"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE roles SET knowledge = json_set(knowledge, '$.max_pages', 500) "
               "WHERE knowledge IS NOT NULL AND json_extract(knowledge, '$.max_pages') = 20")


def downgrade() -> None:
    op.execute("UPDATE roles SET knowledge = json_set(knowledge, '$.max_pages', 20) "
               "WHERE knowledge IS NOT NULL AND json_extract(knowledge, '$.max_pages') = 500")
    # (The old schema took at most 200.)
    op.execute("UPDATE roles SET knowledge = json_set(knowledge, '$.max_pages', 200) "
               "WHERE knowledge IS NOT NULL AND json_extract(knowledge, '$.max_pages') > 200")
