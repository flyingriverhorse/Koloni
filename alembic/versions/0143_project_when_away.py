"""what a new chat in a project starts with while the user is away (K-cli-vekil)

`projects.when_away` and `projects.away_minutes`: copied into each new chat there
(`Conversation.when_away`, `away_minutes`).

Revision ID: 0143
Revises: 0142
"""
import sqlalchemy as sa
from alembic import op

revision = "0143"
# (Written on the k-cli-vekil branch: re-chained after main's newest at its merge.)
down_revision = "0142"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column("when_away", sa.String(5), nullable=False,
                                   server_default="waits"))
        batch.add_column(sa.Column("away_minutes", sa.Integer(), nullable=False,
                                   server_default="10"))


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("away_minutes")
        batch.drop_column("when_away")
