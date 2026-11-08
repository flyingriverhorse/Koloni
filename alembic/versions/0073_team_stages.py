"""a team's own stages in order, the stage each of its roles sits in, and the team's lead card
(slice 63a)

Every team gets the four stages of today's kinds of work, each role in the one of its kind (the
first where its kind is its own), and a lead: a role of kind "lead" that goes with its team.

Revision ID: 0073
Revises: 0072
"""
import json
import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0073"
down_revision = "0072"
branch_labels = None
depends_on = None

# As they were when this was written (app.roles): a migration does not follow later code.
STAGES = (("plan", "Plan"), ("build", "Build"), ("check", "Check"), ("write", "Write & keep up"))
LEAD_DESCRIPTION = "Runs its team's stages when the team works beside another team."
LEAD_INSTRUCTIONS = ("Run your team's stages in order with the recipe you were given; hand "
                     "findings to the right role; report to the Lead.")
LEAD_TOOLS = ["list_dir", "read_file", "search", "spawn_agent", "ask_user", "message_agent",
              "post_note", "read_notes", "remember", "recall"]


def upgrade() -> None:
    op.create_table(
        "team_stages",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("team_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("together", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("role_teams") as batch:
        batch.add_column(sa.Column("stage_id", sa.String(length=32), nullable=True))
        batch.create_foreign_key(
            "fk_role_teams_stage_id", "team_stages", ["stage_id"], ["id"], ondelete="SET NULL")
    with op.batch_alter_table("teams") as batch:
        # (No foreign key: the team deletes its lead itself, `app.api.teams`.)
        batch.add_column(sa.Column("lead_role_id", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column(
            "lead_on", sa.Boolean(), server_default=sa.true(), nullable=False))
        batch.add_column(sa.Column(
            "lead_may_pick", sa.Boolean(), server_default=sa.true(), nullable=False))

    bind = op.get_bind()
    made = datetime.now(UTC).replace(tzinfo=None).isoformat(" ", "microseconds")
    taken = {name.casefold() for (name,) in bind.execute(sa.text("SELECT name FROM roles"))}
    for team_id, team in bind.execute(sa.text("SELECT id, name FROM teams")).fetchall():
        ids = {}
        for position, (kind, name) in enumerate(STAGES):
            ids[kind] = uuid.uuid4().hex
            bind.execute(sa.text(
                "INSERT INTO team_stages (id, team_id, name, position, together) "
                "VALUES (:id, :team, :name, :at, 0)"
            ), {"id": ids[kind], "team": team_id, "name": name, "at": position})
        for kind, stage in ids.items():
            bind.execute(sa.text(
                "UPDATE role_teams SET stage_id = :stage WHERE team_id = :team AND role_id IN "
                "(SELECT id FROM roles WHERE kind = :kind)"
            ), {"stage": stage, "team": team_id, "kind": kind})
        bind.execute(sa.text(
            "UPDATE role_teams SET stage_id = :stage WHERE team_id = :team AND stage_id IS NULL"
        ), {"stage": ids["plan"], "team": team_id})
        # Named after its team, within a role name's 60 characters; one taken gets a number.
        name, n = f"{team[:55]} lead", 1
        while name.casefold() in taken:
            n += 1
            ending = f" lead {n}"
            name = f"{team[:60 - len(ending)]}{ending}"
        taken.add(name.casefold())
        lead = uuid.uuid4().hex
        bind.execute(sa.text(
            "INSERT INTO roles (id, name, description, instructions, tools, builtin, "
            "created_by_agent, tier_min, kind, enabled, mcp, skills, created_at, updated_at) "
            "VALUES (:id, :name, :says, :does, :tools, 0, 0, 'balanced', 'lead', 1, '[]', '[]', "
            ":at, :at)"
        ), {"id": lead, "name": name, "says": LEAD_DESCRIPTION, "does": LEAD_INSTRUCTIONS,
            "tools": json.dumps(LEAD_TOOLS), "at": made})
        bind.execute(sa.text("UPDATE teams SET lead_role_id = :lead WHERE id = :team"),
                     {"lead": lead, "team": team_id})


def downgrade() -> None:
    op.execute("DELETE FROM roles WHERE id IN (SELECT lead_role_id FROM teams)")
    with op.batch_alter_table("teams") as batch:
        batch.drop_column("lead_may_pick")
        batch.drop_column("lead_on")
        batch.drop_column("lead_role_id")
    with op.batch_alter_table("role_teams") as batch:
        batch.drop_constraint("fk_role_teams_stage_id", type_="foreignkey")
        batch.drop_column("stage_id")
    op.drop_table("team_stages")
