"""a request KOLONİ itself makes of a model, on record under the model that was asked; a lead: who was asked how hard its message is

Revision ID: 0034
Revises: 0033
"""
import sqlalchemy as sa
from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nothing is made up for the turns before this: what their questions spent stays on
    # their leads' records, where it was counted then.
    op.create_table(
        "own_requests",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("run_id", sa.String(length=32), nullable=False),
        sa.Column("agent_id", sa.String(length=32), nullable=False),
        sa.Column("provider_name", sa.String(length=60), nullable=False),
        sa.Column("provider_mode", sa.String(length=8), nullable=True),
        sa.Column("model_id", sa.String(length=200), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("cut_short", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("own_requests") as batch:
        batch.create_index(batch.f("ix_own_requests_run_id"), ["run_id"], unique=False)
    with op.batch_alter_table("agents") as batch:
        batch.add_column(sa.Column("asked_how_hard", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("agents") as batch:
        batch.drop_column("asked_how_hard")
    op.drop_table("own_requests")
