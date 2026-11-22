"""The project's last green state (kanıtlı bitiş S7, decision 14b)

`projects.tests_green`: by "<folder> <command>", what the last whole suite KOLONİ ran that passed
counted ({"ran", "skipped", "at"}): a later run with fewer tests, or more skipped ones, is said.
Every project starts with none. Going back drops it.

Revision ID: 0166
Revises: 0165
"""
import sqlalchemy as sa
from alembic import op

revision = "0166"
# (Written on the k-kanit-temel branch: re-chained after main's newest at its merge.)
down_revision = "0165"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column("tests_green", sa.JSON(), nullable=False, server_default="{}"))


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("tests_green")
