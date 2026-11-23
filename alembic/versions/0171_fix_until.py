"""Fix rounds: Until it passes (k-canli-016, the user's decision)

`projects.fix_rounds` may be null: until it passes - failing tests and blocking findings go back
while each round makes progress, at most 20, within the turn's token limit and the project's
budget. It is the default: a project still at the old default 2 moves to it; any other number
it was set to is kept. Going back: until it passes is 2 again.

Revision ID: 0171
Revises: 0169
"""
import sqlalchemy as sa
from alembic import op

revision = "0171"
# (Written on the k-canli-016 branch: re-chained after main's newest at its merge.)
down_revision = "0169"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.alter_column("fix_rounds", existing_type=sa.Integer(), nullable=True,
                           server_default=None)
    op.execute("UPDATE projects SET fix_rounds = NULL WHERE fix_rounds = 2")


def downgrade() -> None:
    op.execute("UPDATE projects SET fix_rounds = 2 WHERE fix_rounds IS NULL")
    with op.batch_alter_table("projects") as batch:
        batch.alter_column("fix_rounds", existing_type=sa.Integer(), nullable=False,
                           server_default="2")
