"""K-tarayici-disari A3: a site the agents' browsers open (`allowed_web` kind "page") is kept on
its project, not on the chat that allowed it: it no longer goes with that chat, and Project
settings adds one with no chat at all

Revision ID: 0133
Revises: 0132
"""
import sqlalchemy as sa
from alembic import op

revision = "0133"
# (Written on the k-tarayici-a3 branch: re-chained after main's newest at its merge.)
down_revision = "0132"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("allowed_web") as batch:
        batch.alter_column("conversation_id", existing_type=sa.String(length=32), nullable=True)
        batch.add_column(sa.Column("project_id", sa.String(length=32), nullable=True))
        batch.create_foreign_key("fk_allowed_web_project_id", "projects", ["project_id"], ["id"])
        batch.create_index("ix_allowed_web_project_id", ["project_id"], unique=False)
    # A chat's site goes to its project; one site allowed in two of its chats is one rule,
    # marked Ask first if either was.
    op.execute("UPDATE allowed_web SET project_id = (SELECT c.project_id FROM conversations c "
               "WHERE c.id = allowed_web.conversation_id) WHERE kind = 'page'")
    op.execute("UPDATE allowed_web SET ask_first = 1 WHERE project_id IS NOT NULL AND EXISTS ("
               "SELECT 1 FROM allowed_web o WHERE o.project_id = allowed_web.project_id "
               "AND o.kind = 'page' AND o.host = allowed_web.host AND o.ask_first)")
    op.execute("DELETE FROM allowed_web WHERE project_id IS NOT NULL AND rowid > ("
               "SELECT min(o.rowid) FROM allowed_web o WHERE o.project_id = allowed_web.project_id "
               "AND o.kind = 'page' AND o.host = allowed_web.host)")
    op.execute("UPDATE allowed_web SET conversation_id = NULL WHERE project_id IS NOT NULL")
    with op.batch_alter_table("allowed_web") as batch:
        batch.create_unique_constraint("uq_allowed_web_project", ["project_id", "kind", "host"])


def downgrade() -> None:
    # A project's site goes back on one chat of it - into the chat's own rule for it, if it has
    # one (a chat moved in since), marked Ask first if either was; one of a project with no
    # chat goes.
    first = "(SELECT min(c.id) FROM conversations c WHERE c.project_id = p.project_id)"
    op.execute("UPDATE allowed_web SET ask_first = 1 WHERE EXISTS (SELECT 1 FROM allowed_web p "
               "WHERE p.conversation_id IS NULL AND p.ask_first AND p.kind = allowed_web.kind "
               f"AND p.host = allowed_web.host AND allowed_web.conversation_id = {first})")
    op.execute("DELETE FROM allowed_web WHERE id IN (SELECT p.id FROM allowed_web p "
               "JOIN allowed_web o ON o.kind = p.kind AND o.host = p.host "
               f"WHERE p.conversation_id IS NULL AND o.conversation_id = {first})")
    op.execute("UPDATE allowed_web SET conversation_id = (SELECT min(c.id) FROM conversations c "
               "WHERE c.project_id = allowed_web.project_id) WHERE conversation_id IS NULL")
    op.execute("DELETE FROM allowed_web WHERE conversation_id IS NULL")
    with op.batch_alter_table("allowed_web") as batch:
        batch.drop_constraint("uq_allowed_web_project", type_="unique")
        batch.drop_index("ix_allowed_web_project_id")
        batch.drop_constraint("fk_allowed_web_project_id", type_="foreignkey")
        batch.drop_column("project_id")
        batch.alter_column("conversation_id", existing_type=sa.String(length=32), nullable=False)
