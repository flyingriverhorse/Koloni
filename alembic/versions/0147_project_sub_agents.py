"""Its chats' sub-agent settings are the project's (tek-ev, the user 6 Nov: Settings › Project),
and a discussion has no token limit by default

`projects.spawn_*`, `discussion_budget` and `room_*`: every chat of the project reads them, old
ones too (`models.settings_of`). A chat's own values stay as they are, unused. A new chat's
`discussion_budget` column has no server default (a kept 200000 stays, as 0146 did for a room's
tokens).

Each project is seeded from its chats' values (archived ones too), and from its own where it
had one before (when_away, away_minutes, lead_work; the new columns' defaults do not join), the
strictest winning, so that no chat gets a looser limit than it had; a value not known counts as
the strictest: spawn_approval always > auto > never; spawn_max_depth,
spawn_max_agents, spawn_max_parallel, room_posts, room_minutes the smallest; room_tokens the
smallest that is set and not the old default 400000, else none; discussion_budget the smallest
that is set and not the old default 200000, else none (the user: no limit unless someone set
one); when_away "waits" over "lead", away_minutes the largest; lead_work "delegates" over
"decides" over "itself". A project with no chats keeps the defaults.

Revision ID: 0147
Revises: 0146
"""
import sqlalchemy as sa
from alembic import op

revision = "0147"
# (Written on the k-settings branch: re-chained after main's newest at its merge.)
down_revision = "0146"
branch_labels = None
depends_on = None

COLUMNS = (
    ("spawn_approval", sa.String(8), "auto"),
    ("spawn_max_depth", sa.Integer(), "2"),
    ("spawn_max_agents", sa.Integer(), "6"),
    ("spawn_max_parallel", sa.Integer(), "2"),
)
LIMITS = (("discussion_budget", None), ("room_posts", "40"), ("room_tokens", None),
          ("room_minutes", "30"))
SEEDED = ("spawn_approval", "spawn_max_depth", "spawn_max_agents", "spawn_max_parallel",
          "room_posts", "room_minutes", "room_tokens", "discussion_budget", "when_away",
          "away_minutes", "lead_work")
# What a project had of its own before 0147 (0143 and before); the rest are new here.
OWN_BEFORE = ("when_away", "away_minutes", "lead_work")


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        for name, kind, default in COLUMNS:
            batch.add_column(sa.Column(name, kind, nullable=False, server_default=default))
        for name, default in LIMITS:
            batch.add_column(sa.Column(name, sa.Integer(), nullable=True,
                                       server_default=default))
    with op.batch_alter_table("conversations") as batch:
        batch.alter_column("discussion_budget", existing_type=sa.Integer(), server_default=None,
                           existing_nullable=True)
    _seed(op.get_bind())


def _strictest(project: dict, chats: list[dict]) -> dict:
    """What a project takes from its chats, and from itself where it had a value before: the
    strictest of each (the docstring). `chats` is never empty."""

    def of(name: str) -> list:
        rows = [project, *chats] if name in OWN_BEFORE else chats
        return [row[name] for row in rows if row[name] is not None]

    def stricter(name: str, loose_to_strict: list[str]) -> str:
        known = [v if v in loose_to_strict else loose_to_strict[-1] for v in of(name)]
        return max(known, key=loose_to_strict.index)

    def deliberate(name: str, old_default: int) -> int | None:
        return min((value for value in of(name) if value != old_default), default=None)

    return {
        "spawn_approval": stricter("spawn_approval", ["never", "auto", "always"]),
        **{name: min(of(name)) for name in (
            "spawn_max_depth", "spawn_max_agents", "spawn_max_parallel")},
        # (None when every one had no limit: the project has none either.)
        **{name: min(of(name), default=None) for name in ("room_posts", "room_minutes")},
        "room_tokens": deliberate("room_tokens", 400_000),
        "discussion_budget": deliberate("discussion_budget", 200_000),
        "when_away": stricter("when_away", ["lead", "waits"]),
        "away_minutes": max(of("away_minutes")),
        "lead_work": stricter("lead_work", ["itself", "decides", "delegates"]),
    }


def _seed(bind) -> None:
    names = ", ".join(SEEDED)
    for project in bind.execute(sa.text(f"SELECT id, {names} FROM projects")).mappings().all():
        # (Archived chats too: one taken out again follows the project, and leaving its stricter
        # values out would loosen it.)
        chats = bind.execute(sa.text(f"SELECT {names} FROM conversations WHERE project_id = :p"),
                             {"p": project["id"]}).mappings().all()
        if chats:
            seeded = _strictest(dict(project), [dict(chat) for chat in chats])
            bind.execute(sa.text("UPDATE projects SET " + ", ".join(
                f"{name} = :{name}" for name in SEEDED) + " WHERE id = :id"),
                {**seeded, "id": project["id"]})


def downgrade() -> None:
    # Each chat takes back what it followed, so that none goes looser than it was: its project's
    # values - in a chat its To-do list opened, the To-do page's lead_work where it has one.
    op.execute("UPDATE conversations SET " + ", ".join(
        f"{name} = (SELECT {name} FROM projects WHERE projects.id = conversations.project_id)"
        for name in SEEDED if name != "lead_work") + ", lead_work = (SELECT CASE WHEN "
        "projects.backlog_lead_work IS NOT NULL AND EXISTS (SELECT 1 FROM backlog_tasks WHERE "
        "backlog_tasks.conversation_id = conversations.id) THEN projects.backlog_lead_work "
        "ELSE projects.lead_work END FROM projects WHERE projects.id = conversations.project_id) "
        "WHERE project_id IS NOT NULL")
    with op.batch_alter_table("conversations") as batch:
        batch.alter_column("discussion_budget", existing_type=sa.Integer(),
                           server_default="200000", existing_nullable=True)
    with op.batch_alter_table("projects") as batch:
        for name, _default in reversed(LIMITS):
            batch.drop_column(name)
        for name, _kind, _default in reversed(COLUMNS):
            batch.drop_column(name)
