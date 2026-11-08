"""27 / 93-C3: the Claude Code session an agent's last native turn left, to be resumed with only
what is new (`agents.cli_session`)

Revision ID: 0139
Revises: 0138
"""
import sqlalchemy as sa
from alembic import op

revision = "0139"
# (Written on the k-cli-resume branch: re-chained after main's newest at its merge.)
down_revision = "0138"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agents") as batch:
        batch.add_column(sa.Column("cli_session", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("agents") as batch:
        batch.drop_column("cli_session")
