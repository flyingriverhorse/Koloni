"""how a CLI provider is run: one session per agent, or one run per step

Revision ID: 0006
Revises: 0005
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("providers") as batch:
        batch.add_column(sa.Column("mode", sa.String(length=8), nullable=True))
    # Claude Code moves to a session; Codex stays step by step (its own patch tool
    # cannot be switched off in a session).
    op.execute("UPDATE providers SET mode = 'session' WHERE kind = 'claude_cli'")
    op.execute("UPDATE providers SET mode = 'step' WHERE kind = 'codex_cli'")


def downgrade() -> None:
    with op.batch_alter_table("providers") as batch:
        batch.drop_column("mode")
