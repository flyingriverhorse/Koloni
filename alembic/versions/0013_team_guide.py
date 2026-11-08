"""the team guide: which providers agents may choose, with the user's note and models

Revision ID: 0013
Revises: 0012
"""
import sqlalchemy as sa
from alembic import op

from app.config import is_local

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("providers") as batch:
        batch.add_column(sa.Column(
            "for_agents", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("note", sa.String(length=300), nullable=True))
        batch.add_column(sa.Column("models", sa.JSON(), nullable=True))
        batch.add_column(sa.Column(
            "only_listed", sa.Boolean(), nullable=False, server_default=sa.false()))
    with op.batch_alter_table("agents") as batch:
        batch.add_column(sa.Column("model_from", sa.String(length=16), nullable=True))
        batch.add_column(sa.Column(
            "chosen", sa.Boolean(), nullable=False, server_default=sa.false()))
    # Only a model server on this machine starts out ticked: anything else may cost
    # money, and letting agents choose it is the user's to decide.
    connection = op.get_bind()
    servers = connection.execute(
        sa.text("SELECT id, base_url FROM providers WHERE kind = 'openai_compat'")
    ).all()
    for provider_id, base_url in servers:
        if is_local(base_url):
            connection.execute(
                sa.text("UPDATE providers SET for_agents = 1 WHERE id = :id"),
                {"id": provider_id},
            )


def downgrade() -> None:
    with op.batch_alter_table("agents") as batch:
        batch.drop_column("chosen")
        batch.drop_column("model_from")
    with op.batch_alter_table("providers") as batch:
        batch.drop_column("only_listed")
        batch.drop_column("models")
        batch.drop_column("note")
        batch.drop_column("for_agents")
