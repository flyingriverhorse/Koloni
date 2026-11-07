"""a project: the command that checks a sub-agent's work before it is taken, and whether what is taken may be committed; a merge: how its check went, and the commit offered for it

Revision ID: 0037
Revises: 0036
"""
import sqlalchemy as sa
from alembic import op

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A project from before this has no check, and nothing of it is offered for a commit:
    # the user has said neither. A merge from before this was not checked.
    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column("check_command", sa.String(length=500), nullable=True))
        batch.add_column(sa.Column(
            "git_commit", sa.Boolean(), server_default=sa.false(), nullable=False))
    with op.batch_alter_table("merges") as batch:
        batch.add_column(sa.Column("check_state", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("commit_state", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("merges") as batch:
        batch.drop_column("commit_state")
        batch.drop_column("check_state")
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("git_commit")
        batch.drop_column("check_command")
