"""Check by kind of work: which of KOLONİ's file checks a project runs (kanıtlı bitiş S5a)

`projects.check_kinds`: {kind: on} for "docs", "slides", "diagram", "data" (S5b adds "ui") - a kind
left out is on, so every project starts with all of them on ({}). Going back drops it.

Revision ID: 0167
Revises: 0166
"""
import sqlalchemy as sa
from alembic import op

revision = "0167"
down_revision = "0166"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column("check_kinds", sa.JSON(), nullable=False,
                                   server_default="{}"))


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("check_kinds")
