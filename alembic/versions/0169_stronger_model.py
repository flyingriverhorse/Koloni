"""Then a stronger model (kanıtlı bitiş S11, decisions 18, 19)

`projects.stronger_model`: where a turn's fix rounds are spent and a test still fails (or a
blocking finding stands), KOLONİ hands the fix to the next stronger tier on the Models page - on
in every project, as decision 18 has it; off, the work waits after the first model's rounds.
Going back drops it.

Revision ID: 0169
Revises: 0170
"""
import sqlalchemy as sa
from alembic import op

revision = "0169"
# (Written on the k-kanit-yukselt branch: re-chained after main's newest at its merge.)
down_revision = "0170"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column("stronger_model", sa.Boolean(), nullable=False,
                                   server_default=sa.true()))


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("stronger_model")
