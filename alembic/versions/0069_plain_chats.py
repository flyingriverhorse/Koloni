"""a chat may have no folder (slice 86a); an "Always run" rule is its chat's in one folder

Revision ID: 0069
Revises: 0068
"""
import sqlalchemy as sa
from alembic import op

revision = "0069"
down_revision = "0068"
branch_labels = None
depends_on = None

FOLDER_OF_ITS_CHAT = (
    "(SELECT project_id FROM conversations WHERE conversations.id = "
    "allowed_commands.conversation_id)"
)


def upgrade() -> None:
    with op.batch_alter_table("conversations") as batch:
        batch.alter_column("project_id", existing_type=sa.String(32), nullable=True)
    with op.batch_alter_table("allowed_commands") as batch:
        batch.add_column(sa.Column("project_id", sa.String(32), nullable=True))
    # Every rule so far was made where its chat is now.
    op.execute(f"UPDATE allowed_commands SET project_id = {FOLDER_OF_ITS_CHAT}")
    op.execute("DELETE FROM allowed_commands WHERE project_id IS NULL")  # (no chat: no rule)
    with op.batch_alter_table("allowed_commands") as batch:
        batch.alter_column("project_id", existing_type=sa.String(32), nullable=False)
        batch.drop_constraint("uq_allowed_commands_prefix", type_="unique")
        batch.create_unique_constraint(
            "uq_allowed_commands_prefix", ["conversation_id", "project_id", "prefix"])


def downgrade() -> None:
    if op.get_bind().execute(
            sa.text("SELECT 1 FROM conversations WHERE project_id IS NULL LIMIT 1")).first():
        raise RuntimeError(
            "there are chats with no folder, which the schema before 0069 cannot hold: give "
            "each one a folder, or delete it, first")
    # Before, a chat's rules held wherever it was: only the ones of its folder now are kept.
    op.execute(f"DELETE FROM allowed_commands WHERE project_id IS NOT {FOLDER_OF_ITS_CHAT}")
    with op.batch_alter_table("allowed_commands") as batch:
        batch.drop_constraint("uq_allowed_commands_prefix", type_="unique")
        batch.create_unique_constraint(
            "uq_allowed_commands_prefix", ["conversation_id", "prefix"])
        batch.drop_column("project_id")
    with op.batch_alter_table("conversations") as batch:
        batch.alter_column("project_id", existing_type=sa.String(32), nullable=False)
