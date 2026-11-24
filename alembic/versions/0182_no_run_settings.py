"""Run the backlog, Runs by itself and Run settings go (0.1.8, To-do in a chat): a task runs in a
chat's queue, at that chat's level and on its model. The project's six columns of them go - a
backlog that ran by itself stops, its choices are not kept anywhere - and what a task's `flow`
held for Run the backlog ("queued"), its own branch ("branch"), a fix round due ("fix") and a
place in a queue ("place") is cleared. A task left "doing" is todo again: no turn of before says
which task it was (`Run.task_id` is new), so none would ever end it - nor start an unasked fix.

Going back, the columns come back with their defaults: off, Ask, no model chosen.

Revision ID: 0182
Revises: 0181
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "0182"
# (Written on the k-todo-sohbet branch: re-chained after main's newest at its merge.)
down_revision = "0181"
branch_labels = None
depends_on = None

GONE = ("queued", "branch", "fix", "place")


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE backlog_tasks SET status = 'todo' WHERE status = 'doing'"))
    for task_id, flow in conn.execute(
        sa.text("SELECT id, flow FROM backlog_tasks WHERE flow IS NOT NULL")
    ).fetchall():
        held = json.loads(flow) if isinstance(flow, str) else flow
        if not isinstance(held, dict) or not set(held) & set(GONE):
            continue
        kept = {key: value for key, value in held.items() if key not in GONE}
        conn.execute(
            sa.text("UPDATE backlog_tasks SET flow = :flow WHERE id = :id"),
            {"flow": json.dumps(kept) if kept else None, "id": task_id},
        )
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("backlog_lead_work")
        batch.drop_column("backlog_model_id")
        batch.drop_column("backlog_provider_id")
        batch.drop_column("backlog_mode")
        batch.drop_column("backlog_halt")
        batch.drop_column("backlog_auto")


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.add_column(
            sa.Column("backlog_auto", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch.add_column(sa.Column("backlog_halt", sa.Text(), nullable=True))
        batch.add_column(
            sa.Column("backlog_mode", sa.String(12), nullable=False, server_default="ask")
        )
        batch.add_column(sa.Column("backlog_provider_id", sa.String(32), nullable=True))
        batch.add_column(sa.Column("backlog_model_id", sa.String(200), nullable=True))
        batch.add_column(sa.Column("backlog_lead_work", sa.String(9), nullable=True))
