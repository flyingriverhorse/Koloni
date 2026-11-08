"""own commands: the user's own slash commands, for one project or every project (slice 53)

Revision ID: 0053
Revises: 0052
"""
import sqlalchemy as sa
from alembic import op

revision = "0053"
down_revision = "0052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "own_commands",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("project_id", sa.String(length=32), nullable=True),
        sa.Column("name", sa.String(length=40), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("template", sa.Text(), nullable=False),
        sa.Column("role", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("own_commands") as batch:
        batch.create_index(batch.f("ix_own_commands_project_id"), ["project_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("own_commands") as batch:
        batch.drop_index(batch.f("ix_own_commands_project_id"))
    op.drop_table("own_commands")
