"""where a CLI ran a command of its own is not known: a command's folder may be empty

Revision ID: 0015
Revises: 0014
"""
import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("commands") as batch:
        batch.alter_column("cwd", existing_type=sa.Text(), nullable=True)
    # Until now "." was written for these too, though KOLONİ never knew it.
    op.execute("UPDATE commands SET cwd = NULL WHERE origin = 'cli'")


def downgrade() -> None:
    op.execute("UPDATE commands SET cwd = '.' WHERE cwd IS NULL")
    with op.batch_alter_table("commands") as batch:
        batch.alter_column("cwd", existing_type=sa.Text(), nullable=False)
