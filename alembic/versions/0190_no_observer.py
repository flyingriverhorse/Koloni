"""The Observer is gone (0.1.10, the user's 26 Nov: Checked, "No file changed" and the claim checks
already say what a sub-agent's record shows): the project's switch for it (`observe_reports`), what
it said on each agent (`observation`, `observation_note`, `observed_by`) and the built-in role. A
role of the user's own named "Observer" is theirs and stays. Going back, the columns come back as
0049 made them, empty; the built-in role comes back with 0.1.9 itself, which adds a built-in role
that is missing at its start (`seed_builtin_roles`).

Revision ID: 0190
Revises: 0187
"""

import sqlalchemy as sa
from alembic import op

revision = "0190"
# (Written on the k-observer-sil branch on 0187, 0.1.9's head; 0189 is k-tetik-sil's - the two
# are chained one after the other at their merge.)
down_revision = "0187"
branch_labels = None
depends_on = None

BUILT_IN = "SELECT id FROM roles WHERE builtin AND name = 'Observer'"


def upgrade() -> None:
    bind = op.get_bind()
    # (Never in a team - KOLONİ refused it one - but a link is let go of first all the same.)
    bind.execute(sa.text(f"DELETE FROM role_teams WHERE role_id IN ({BUILT_IN})"))
    bind.execute(sa.text(f"DELETE FROM roles WHERE id IN ({BUILT_IN})"))
    with op.batch_alter_table("agents") as batch:
        batch.drop_column("observed_by")
        batch.drop_column("observation_note")
        batch.drop_column("observation")
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("observe_reports")


def downgrade() -> None:
    # As 0049 made them.
    with op.batch_alter_table("projects") as batch:
        batch.add_column(
            sa.Column("observe_reports", sa.Boolean(), nullable=False, server_default=sa.false())
        )
    with op.batch_alter_table("agents") as batch:
        batch.add_column(sa.Column("observation", sa.Text(), nullable=True))
        batch.add_column(sa.Column("observation_note", sa.Text(), nullable=True))
        batch.add_column(sa.Column("observed_by", sa.JSON(), nullable=True))
