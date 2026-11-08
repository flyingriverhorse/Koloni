"""while the user is away: the night's runs of jobs, and each task's part in one (slice 106)

Revision ID: 0087
Revises: 0086
"""
import sqlalchemy as sa
from alembic import op

revision = "0087"
down_revision = "0086"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "away_runs",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("project_id", sa.String(length=32), nullable=False),
        sa.Column("conversation_id", sa.String(length=32), nullable=False),
        sa.Column("run_id", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("jobs", sa.JSON(), nullable=False),
        sa.Column("kept_out", sa.JSON(), nullable=False),
        sa.Column("until", sa.DateTime(), nullable=True),
        sa.Column("money", sa.Float(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("why", sa.Text(), nullable=True),
        sa.Column("seen_at", sa.DateTime(), nullable=True),
        sa.Column("tried", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_away_runs_project_id", "away_runs", ["project_id"])
    op.create_index("ix_away_runs_conversation_id", "away_runs", ["conversation_id"])
    with op.batch_alter_table("backlog_tasks") as batch:
        batch.add_column(sa.Column("away_run_id", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("away_state", sa.String(length=8), nullable=True))
        batch.add_column(sa.Column("away_why", sa.Text(), nullable=True))
        batch.create_index("ix_backlog_tasks_away_run_id", ["away_run_id"])


def downgrade() -> None:
    with op.batch_alter_table("backlog_tasks") as batch:
        batch.drop_index("ix_backlog_tasks_away_run_id")
        batch.drop_column("away_why")
        batch.drop_column("away_state")
        batch.drop_column("away_run_id")
    op.drop_index("ix_away_runs_conversation_id", table_name="away_runs")
    op.drop_index("ix_away_runs_project_id", table_name="away_runs")
    op.drop_table("away_runs")
