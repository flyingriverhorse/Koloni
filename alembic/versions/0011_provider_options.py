"""settings a kind of provider has beyond the common ones (Copilot's own model server)

Revision ID: 0011
Revises: 0010
"""
import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("providers") as batch:
        batch.add_column(sa.Column("options", sa.JSON(), nullable=True))


def downgrade() -> None:
    # A Copilot provider cannot be run by the code this goes back to.
    op.execute("UPDATE conversations SET provider_id = NULL, model_id = NULL WHERE provider_id "
               "IN (SELECT id FROM providers WHERE kind = 'copilot_cli')")
    op.execute("UPDATE roles SET provider_id = NULL, model_id = NULL WHERE provider_id "
               "IN (SELECT id FROM providers WHERE kind = 'copilot_cli')")
    op.execute("DELETE FROM providers WHERE kind = 'copilot_cli'")
    with op.batch_alter_table("providers") as batch:
        batch.drop_column("options")
