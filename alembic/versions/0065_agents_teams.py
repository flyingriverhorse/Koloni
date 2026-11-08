"""agents and teams: a role's kind of work, on / off and tier range, teams of roles, a
conversation's team, the tier an agent ran at (slice 81b)

Built-in roles lose the fixed tier they came with, where it is still that one: the Lead
picks a tier for each job now. A tier the user gave one is kept.

Revision ID: 0065
Revises: 0064
"""
import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0065"
down_revision = "0064"
branch_labels = None
depends_on = None

# As they were when this was written (app.roles): a migration does not follow later code.
OLD_TIERS = {
    "Planner": "strongest", "Coder": "strongest", "Tester": "balanced", "Reviewer": "strongest",
    "Researcher": "balanced", "Debugger": "strongest", "Architect": "strongest",
    "Security reviewer": "strongest", "Docs writer": "fast", "Refactorer": "balanced",
    "UI designer": "balanced", "Data analyst": "balanced", "DevOps": "balanced",
    "Spec writer": "strongest", "Performance engineer": "balanced",
    "Database engineer": "balanced", "Dependency keeper": "balanced", "Translator": "fast",
    "Summarizer": "fast", "Product owner": "strongest", "Assistant product owner": "balanced",
    "Observer": "balanced",
}
KINDS = {
    "plan": ("Lead", "Planner", "Architect", "Researcher", "Product owner",
             "Assistant product owner"),
    "check": ("Tester", "Reviewer", "Security reviewer", "Performance engineer",
              "Data analyst", "Observer"),
    "write": ("Docs writer", "Spec writer", "Translator", "Summarizer", "Dependency keeper"),
}
# Slice 62's ready teams.
TEAMS = {
    "Web app": ("Coder", "UI designer", "Tester", "Reviewer", "Debugger", "Refactorer"),
    "Backend / API": ("Coder", "Architect", "Database engineer", "Tester", "Reviewer",
                      "Security reviewer", "Performance engineer"),
    "Data": ("Data analyst", "Database engineer", "Researcher", "Reviewer"),
    "Docs": ("Docs writer", "Spec writer", "Translator", "Summarizer"),
    "Ops": ("DevOps", "Security reviewer", "Dependency keeper", "Performance engineer"),
    "Quality": ("Tester", "Reviewer", "Security reviewer", "Debugger"),
    "Research": ("Researcher", "Summarizer", "Spec writer"),
    "Product": ("Product owner", "Assistant product owner", "Spec writer"),
    "Maintenance": ("Refactorer", "Dependency keeper", "Debugger", "Tester"),
}


def upgrade() -> None:
    with op.batch_alter_table("roles") as batch:
        # (Room for "conversation": the rule that runs on the conversation's model.)
        batch.alter_column("tier", type_=sa.String(length=16), existing_type=sa.String(length=10))
        batch.add_column(sa.Column("tier_min", sa.String(length=10), nullable=True))
        batch.add_column(sa.Column("tier_max", sa.String(length=10), nullable=True))
        batch.add_column(sa.Column(
            "kind", sa.String(length=40), server_default="build", nullable=False))
        batch.add_column(sa.Column(
            "enabled", sa.Boolean(), server_default=sa.true(), nullable=False))
    with op.batch_alter_table("conversations") as batch:
        batch.add_column(sa.Column("team_id", sa.String(length=32), nullable=True))
    with op.batch_alter_table("agents") as batch:
        batch.add_column(sa.Column("tier", sa.String(length=10), nullable=True))
    with op.batch_alter_table("runs") as batch:
        batch.add_column(sa.Column(
            "by_user", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.create_table(
        "teams",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "role_teams",
        sa.Column("role_id", sa.String(length=32), nullable=False),
        sa.Column("team_id", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("role_id", "team_id"),
    )

    bind = op.get_bind()
    for name, tier in OLD_TIERS.items():
        bind.execute(sa.text(
            "UPDATE roles SET tier = NULL WHERE builtin AND name = :name AND tier = :tier"
        ), {"name": name, "tier": tier})
    for kind, names in KINDS.items():
        for name in names:
            bind.execute(sa.text("UPDATE roles SET kind = :kind WHERE builtin AND name = :name"),
                         {"kind": kind, "name": name})
    # The ready teams, once: a fresh database has no roles yet, and its built-in ones join
    # these as they are added (`app.roles.seed_builtin_roles`).
    made = datetime.now(UTC).replace(tzinfo=None).isoformat(" ", "microseconds")
    for team, names in TEAMS.items():
        team_id = uuid.uuid4().hex
        bind.execute(sa.text("INSERT INTO teams (id, name, created_at) VALUES (:id, :name, :at)"),
                     {"id": team_id, "name": team, "at": made})
        for name in names:
            bind.execute(sa.text(
                "INSERT INTO role_teams (role_id, team_id) "
                "SELECT id, :team FROM roles WHERE builtin AND name = :name"
            ), {"team": team_id, "name": name})


def downgrade() -> None:
    op.drop_table("role_teams")
    op.drop_table("teams")
    with op.batch_alter_table("runs") as batch:
        batch.drop_column("by_user")
    with op.batch_alter_table("agents") as batch:
        batch.drop_column("tier")
    with op.batch_alter_table("conversations") as batch:
        batch.drop_column("team_id")
    with op.batch_alter_table("roles") as batch:
        batch.drop_column("enabled")
        batch.drop_column("kind")
        batch.drop_column("tier_max")
        batch.drop_column("tier_min")
        batch.alter_column("tier", type_=sa.String(length=10), existing_type=sa.String(length=16))
