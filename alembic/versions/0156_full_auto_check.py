"""a project's check of a harmful-looking command at Full auto, and what it said of a command
(K-yargıç)

K-yargıç: at Full auto, before a command that deletes or sends something off this machine waits
for the user, the first model of the Fast tier may be asked whether a line the user wrote names
it. Projects get `full_auto_check`, "ask" for every one (as before: the check is off until the
user turns it on); commands get `judged`, what the check said of one (null: not checked).
Going back drops both.

Revision ID: 0156
Revises: 0155
"""

import sqlalchemy as sa
from alembic import op

revision = "0156"
# (Written on the k-yargic branch: re-chained after main's newest at its merge.)
down_revision = "0155"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.add_column(
            sa.Column("full_auto_check", sa.String(length=5), nullable=False, server_default="ask")
        )
    with op.batch_alter_table("commands") as batch:
        batch.add_column(sa.Column("judged", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("commands") as batch:
        batch.drop_column("judged")
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("full_auto_check")
