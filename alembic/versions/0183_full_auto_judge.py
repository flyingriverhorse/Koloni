"""Full auto's judge (0.1.9): at Full auto a small model looks at each command the list does not
stop first - a project's switch of it, on (in the projects there are too); the user's Judge model,
none chosen (the Fast tier's first); and the lines the user said on its card not to ask about
again in a project.

Going back, all three go.

Revision ID: 0183
Revises: 0182
"""

import sqlalchemy as sa
from alembic import op

revision = "0183"
# (Written on the k-judge-1 branch: re-chained after main's newest at its merge.)
down_revision = "0182"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.add_column(
            sa.Column("full_auto_judge", sa.Boolean(), nullable=False, server_default=sa.true())
        )
    with op.batch_alter_table("user_preferences") as batch:
        batch.add_column(sa.Column("judge_provider_id", sa.String(32), nullable=True))
        batch.add_column(sa.Column("judge_model_id", sa.String(200), nullable=True))
    op.create_table(
        "judge_allowed",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("project_id", sa.String(32), nullable=False),
        sa.Column("command", sa.Text(), nullable=False),
        sa.Column("cwd", sa.Text(), nullable=False),
        sa.Column("program_sha", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("project_id", "command", "cwd", "program_sha"),
    )
    op.create_index("ix_judge_allowed_project_id", "judge_allowed", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_judge_allowed_project_id", table_name="judge_allowed")
    op.drop_table("judge_allowed")
    with op.batch_alter_table("user_preferences") as batch:
        batch.drop_column("judge_model_id")
        batch.drop_column("judge_provider_id")
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("full_auto_judge")
