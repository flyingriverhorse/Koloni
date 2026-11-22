"""a project's After a change (kanıtlı bitiş, S1)

After a turn that changed code KOLONİ runs the project's tests once and says under the answer
what was checked: "check" (Check it), "tests" (Tests only) or "nothing" (Nothing). It takes over
89m's "Finish only when the tests pass": a project that had turned that off gets Nothing - its
choice, said in Settings while `finish_tests` stays as it was - every other one Check it. The old
column is kept (not dropped in 0.1.6). Going back drops the new one.

Revision ID: 0162
Revises: 0161
"""
import sqlalchemy as sa
from alembic import op

revision = "0162"
# (Written on the k-kanit-son branch: re-chained after main's newest at its merge.)
down_revision = "0161"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column("after_change", sa.String(7), nullable=False,
                                   server_default="check"))
    op.execute("UPDATE projects SET after_change = 'nothing' WHERE finish_tests = 0")


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("after_change")
