"""how a team's finished branch reaches the user's (K-dal-takim D2)

`projects.finish_way`: "merge" here, or "pull_request" - pushed, a pull request opened, never
merged by KOLONİ. None: not chosen yet.

Revision ID: 0136
Revises: 0135
"""
import sqlalchemy as sa
from alembic import op

revision = "0136"
# (Written on the k-dal-takim-2 branch: re-chained after main's newest at its merge.)
down_revision = "0135"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column("finish_way", sa.String(20), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("finish_way")
