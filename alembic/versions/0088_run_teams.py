"""each turn keeps its chat teams' rows as it left them (B-107)

Revision ID: 0088
Revises: 0087
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0088"
down_revision = "0087"
branch_labels = None
depends_on = None

# What of a row's state the canvas reads (app.schemas.ChatTeamState); the rest is its recipe's run.
SHOWN = ("run_id", "team", "recipe", "status", "why", "steps", "agents", "ended_ready", "passes")


def upgrade() -> None:
    with op.batch_alter_table("runs") as batch:
        batch.add_column(sa.Column("teams", sa.JSON(), nullable=True))
    # A row remembers the last turn it ran in: that turn keeps it as it is now (app.schemas.ChatTeamOut). An earlier
    # turn's is not on record any more.
    conn = op.get_bind()
    kept: dict[str, list[dict]] = {}
    rows = conn.execute(sa.text(
        "SELECT team_id, recipe_id, picked_by, why, state FROM conversation_teams "
        "WHERE state IS NOT NULL ORDER BY conversation_id, position")).fetchall()
    for team_id, recipe_id, picked_by, why, state in rows:
        state = json.loads(state) if isinstance(state, str) else state
        if state and state.get("run_id"):
            kept.setdefault(state["run_id"], []).append({
                "team_id": team_id, "recipe_id": recipe_id, "picked_by": picked_by, "why": why,
                "state": {key: state[key] for key in SHOWN if key in state}})
    for run_id, teams in kept.items():
        conn.execute(sa.text("UPDATE runs SET teams = :teams WHERE id = :id"),
                     {"teams": json.dumps(teams), "id": run_id})


def downgrade() -> None:
    with op.batch_alter_table("runs") as batch:
        batch.drop_column("teams")
