"""when_away: while the user is away, the Lead answers what it safely can (K-vekil-karar)

A chat's choice - "waits" (everything waits for the user, as before) or "lead" - and after how
many minutes unanswered the Lead steps in; and on a question, the Lead's reason where it
answered it, and when the user looked at that (OK).

Revision ID: 0091
Revises: 0090
"""
import sqlalchemy as sa
from alembic import op

revision = "0091"
down_revision = "0090"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("conversations") as batch:
        batch.add_column(sa.Column("when_away", sa.String(5), nullable=False,
                                   server_default="waits"))
        batch.add_column(sa.Column("away_minutes", sa.Integer(), nullable=False,
                                   server_default="10"))
    with op.batch_alter_table("questions") as batch:
        batch.add_column(sa.Column("lead_why", sa.Text(), nullable=True))
        batch.add_column(sa.Column("seen_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("questions") as batch:
        batch.drop_column("seen_at")
        batch.drop_column("lead_why")
    with op.batch_alter_table("conversations") as batch:
        batch.drop_column("away_minutes")
        batch.drop_column("when_away")
