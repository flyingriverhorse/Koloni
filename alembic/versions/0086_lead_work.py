"""lead_work: who changes the files, three ways (batch-18, K-devret)

0050's "Lead delegates the work" was on or off for each chat, and on in every new one. Now it
is "delegates", "decides" (the Lead makes a small change itself and hands bigger work on) or
"itself", and a folder says what its new chats start with.

Revision ID: 0086
Revises: 0085
"""
import sqlalchemy as sa
from alembic import op

revision = "0086"
down_revision = "0085"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("conversations") as batch:
        batch.add_column(sa.Column(
            "lead_work", sa.String(9), nullable=False, server_default="delegates"))
    op.execute("UPDATE conversations SET lead_work = 'itself' WHERE NOT lead_hands_code")
    with op.batch_alter_table("conversations") as batch:
        batch.drop_column("lead_hands_code")
    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column(
            "lead_work", sa.String(9), nullable=False, server_default="delegates"))


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("lead_work")
    with op.batch_alter_table("conversations") as batch:
        batch.add_column(sa.Column(
            "lead_hands_code", sa.Boolean(), nullable=False, server_default=sa.true()))
    # (Deciding has the Lead's write tools: back, it writes itself.)
    op.execute("UPDATE conversations SET lead_hands_code = (lead_work = 'delegates')")
    with op.batch_alter_table("conversations") as batch:
        batch.drop_column("lead_work")
