"""model providers; a model choice per conversation and role; the model each agent ran on

Revision ID: 0005
Revises: 0004
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "providers",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=True),
        sa.Column("api_key", sa.Text(), nullable=True),
        sa.Column("default_model", sa.String(length=200), nullable=True),
        sa.Column("executable", sa.Text(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    for table in ("conversations", "roles"):
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("provider_id", sa.String(length=32), nullable=True))
            batch.add_column(sa.Column("model_id", sa.String(length=200), nullable=True))
    with op.batch_alter_table("agents") as batch:
        batch.add_column(sa.Column("provider_name", sa.String(length=60), nullable=True))
        batch.add_column(sa.Column("model_id", sa.String(length=200), nullable=True))
    # Until now every agent of a turn ran on the turn's one model. Which provider
    # that was is not on record, so the name stays empty.
    op.execute(
        "UPDATE agents SET model_id = "
        "(SELECT runs.model_id FROM runs WHERE runs.id = agents.run_id)"
    )


def downgrade() -> None:
    with op.batch_alter_table("agents") as batch:
        batch.drop_column("model_id")
        batch.drop_column("provider_name")
    for table in ("roles", "conversations"):
        with op.batch_alter_table(table) as batch:
            batch.drop_column("model_id")
            batch.drop_column("provider_id")
    op.drop_table("providers")
