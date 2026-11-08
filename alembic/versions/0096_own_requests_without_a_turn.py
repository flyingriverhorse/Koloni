"""a request KOLONİ itself makes of a model with no turn (the day's words, a recipe's draft, a
role's guide) goes on record too: Usage's "KOLONİ itself" (K-56)

Revision ID: 0096
Revises: 0098
"""
import sqlalchemy as sa
from alembic import op

revision = "0096"
down_revision = "0098"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("own_requests") as batch:
        batch.alter_column("run_id", existing_type=sa.String(length=32), nullable=True)
        batch.alter_column("agent_id", existing_type=sa.String(length=32), nullable=True)
        batch.add_column(sa.Column("project_id", sa.String(length=32), nullable=True))
        batch.create_foreign_key(
            "fk_own_requests_project_id", "projects", ["project_id"], ["id"])


def downgrade() -> None:
    # What was asked with no turn has no place before this: it goes.
    op.execute("DELETE FROM own_requests WHERE run_id IS NULL OR agent_id IS NULL")
    with op.batch_alter_table("own_requests") as batch:
        batch.drop_constraint("fk_own_requests_project_id", type_="foreignkey")
        batch.drop_column("project_id")
        batch.alter_column("agent_id", existing_type=sa.String(length=32), nullable=False)
        batch.alter_column("run_id", existing_type=sa.String(length=32), nullable=False)
