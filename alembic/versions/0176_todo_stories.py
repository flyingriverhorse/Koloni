"""To-do's goals and stories (0.1.8, To-do in a chat): a goal holds stories, a story holds tasks
and bugs; a task's kind; the task a turn works on and the story a topic is of (filled later).

A task kept from before is a task of no story. Going back drops the tables and the columns.

Revision ID: 0176
Revises: 0175
"""

import sqlalchemy as sa
from alembic import op

revision = "0176"
# (Written on the k-todo-story branch: re-chained after main's newest at its merge.)
down_revision = "0175"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "goals",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("project_id", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(length=8), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_goals_project_id", "goals", ["project_id"])
    op.create_table(
        "stories",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("project_id", sa.String(length=32), nullable=False),
        sa.Column("goal_id", sa.String(length=32), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("notes", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.String(length=8), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_stories_project_id", "stories", ["project_id"])
    op.create_index("ix_stories_goal_id", "stories", ["goal_id"])
    with op.batch_alter_table("backlog_tasks") as batch:
        batch.add_column(sa.Column("story_id", sa.String(length=32), nullable=True))
        batch.add_column(
            sa.Column("kind", sa.String(length=4), nullable=False, server_default="task")
        )
        batch.create_index("ix_backlog_tasks_story_id", ["story_id"])
    with op.batch_alter_table("runs") as batch:
        batch.add_column(sa.Column("task_id", sa.String(length=32), nullable=True))
        batch.create_index("ix_runs_task_id", ["task_id"])
    with op.batch_alter_table("topics") as batch:
        batch.add_column(sa.Column("story_id", sa.String(length=32), nullable=True))
        batch.create_index("ix_topics_story_id", ["story_id"])


def downgrade() -> None:
    with op.batch_alter_table("topics") as batch:
        batch.drop_index("ix_topics_story_id")
        batch.drop_column("story_id")
    with op.batch_alter_table("runs") as batch:
        batch.drop_index("ix_runs_task_id")
        batch.drop_column("task_id")
    with op.batch_alter_table("backlog_tasks") as batch:
        batch.drop_index("ix_backlog_tasks_story_id")
        batch.drop_column("kind")
        batch.drop_column("story_id")
    op.drop_index("ix_stories_goal_id", table_name="stories")
    op.drop_index("ix_stories_project_id", table_name="stories")
    op.drop_table("stories")
    op.drop_index("ix_goals_project_id", table_name="goals")
    op.drop_table("goals")
