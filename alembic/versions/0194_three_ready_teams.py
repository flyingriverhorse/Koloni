"""Three ready teams (0.1.10, the user's call: Web app, Quality and Docs - the eleven were more
than a chat picks from): the other eight KOLONİ made - Backend / API, Data, DevOps, Research,
Product, Maintenance, ML and DataOps - go, with their stages, their lead and the rows the Lead
picked them in. Their roles stay.

Only a team as it came goes. One the user changed stays as theirs: renamed (no longer the ready
one, as 0093 and 0103 tell it), its members not the ready ones (a role taken out - one of 0103's
experts too - or one of the user's put in), its stages not Plan, Build, Check and Write & keep up
one after another, a role moved to another stage than its kind's, its lead switched off or not
left to the Lead's pick, its recipe not its ready one, or its lead role saved since it was made. So does one the user uses: picked in a chat (Manual), kept for a
project's new chats, or named by a recipe's step. A chat the Lead had picked one for keeps its
other rows; with none left it works as a deleted team's chat does (`delete_team`): the Lead
picks again where it decides, and any role may open in Manual.

shortcut: what names a gone team elsewhere is not followed: a night while you're away planned
with one runs without it (its chat gets the evening's teams, or none); a folder's own recipe
(.koloni/recipes) whose step names one is refused when it runs, as naming no team here; and the
state of a recipe run on a Lead's row that goes is lost with the row. Look for them if a user is
seen to miss one.

Going back, the eight do not come back: put back the copy KOLONİ made of the database before
this upgrade (runtime/data/backups/).

Revision ID: 0194
Revises: 0192
"""

import json
import re

import sqlalchemy as sa
from alembic import op

revision = "0194"
# (Written on 0190; chained after 0.1.10's 0192 at merge.)
down_revision = "0192"
branch_labels = None
depends_on = None

# The eight as `app.roles.READY_TEAMS` held them, with the recipe each was given (0093, 0103).
GONE = {
    "Backend / API": (
        (
            "Coder",
            "Architect",
            "Database engineer",
            "Tester",
            "Reviewer",
            "Security reviewer",
            "Performance engineer",
        ),
        "Bugfix",
    ),
    "Data": (("Data analyst", "Database engineer", "Researcher", "Reviewer"), "Analysis"),
    "DevOps": (
        ("DevOps", "Security reviewer", "Dependency keeper", "Performance engineer"),
        "Infra change",
    ),
    "Research": (("Researcher", "Summarizer", "Spec writer"), "Research"),
    "Product": (("Hive keeper", "Scout", "Spec writer"), "Spec"),
    "Maintenance": (("Refactorer", "Dependency keeper", "Debugger", "Tester"), "Upkeep"),
    "ML": (
        ("Data scientist", "ML engineer", "Model evaluator", "MLOps engineer", "Tester"),
        "Model change",
    ),
    "DataOps": (
        ("Data engineer", "Database engineer", "Data analyst", "Tester"),
        "Pipeline change",
    ),
}
# 0103's two experts of ML: roles of the user's kind, in the team as it came.
EXPERTS = {"ML": {"MLflow expert", "Databricks expert"}}
# The stage each of their roles sits in as KOLONİ placed it (`app.roles.place_in_stages`: the one
# of its kind, a Data, ML or Ops role's Build, the Data scientist's Plan), or before 0103 moved
# its kind (Build; the Dependency keeper's Write & keep up). None: not placed yet.
PLAN, BUILD, CHECK, WRITE = "Plan", "Build", "Check", "Write & keep up"
PLACED = {
    **dict.fromkeys(
        ("Architect", "Hive keeper", "Researcher", "Scout", "MLflow expert", "Databricks expert"),
        {PLAN},
    ),
    **dict.fromkeys(
        (
            "Coder",
            "Data engineer",
            "Database engineer",
            "Debugger",
            "DevOps",
            "ML engineer",
            "MLOps engineer",
            "Refactorer",
        ),
        {BUILD},
    ),
    **dict.fromkeys(
        (
            "Data analyst",
            "Model evaluator",
            "Performance engineer",
            "Reviewer",
            "Security reviewer",
            "Tester",
        ),
        {CHECK},
    ),
    **dict.fromkeys(("Spec writer", "Summarizer"), {WRITE}),
    "Data scientist": {PLAN, BUILD},
    "Dependency keeper": {BUILD, WRITE},
}
STAGES = [PLAN, BUILD, CHECK, WRITE]
# As `app.roles._BUILT_IN`: a built-in role named so beside the user's own of its name.
BUILT_IN = re.compile(r" \(built-in(?: \d+)?\)$")
STOCK = "name = :team AND created_at = (SELECT MIN(created_at) FROM teams)"


def _named_by_recipes(bind) -> set[str]:
    """The teams a recipe's step names, casefolded (`app.recipes`: a step's who is a role or a
    team by its name)."""
    named: set[str] = set()

    def walk(part) -> None:
        if isinstance(part, dict):
            if isinstance(part.get("team"), str):
                named.add(part["team"].casefold())
            for value in part.values():
                walk(value)
        elif isinstance(part, list):
            for value in part:
                walk(value)

    for (graph,) in bind.execute(sa.text("SELECT graph FROM recipes")):
        try:
            walk(json.loads(graph) if isinstance(graph, str) else graph)
        except ValueError:
            continue  # (one that is no JSON names nothing KOLONİ can read)
    return named


def _as_it_came(bind, team: str, found, builtin_names: set[str], own_names: set[str]) -> bool:
    """Whether the ready team `found` is as KOLONİ made it: its members and where they sit,
    its stages, lead and recipe. `builtin_names` and `own_names`: the built-in roles there are,
    and the user's."""
    team_id, lead_id, lead_on, may_pick, recipe_id = found
    ready, recipe = GONE[team]
    members = [
        (BUILT_IN.sub("", name) if builtin else name, builtin, stage)
        for name, builtin, stage in bind.execute(
            sa.text(
                "SELECT r.name, r.builtin, s.name FROM role_teams rt "
                "JOIN roles r ON r.id = rt.role_id "
                "LEFT JOIN team_stages s ON s.id = rt.stage_id WHERE rt.team_id = :id"
            ),
            {"id": team_id},
        )
    ]
    names = {name for name, _builtin, _stage in members}
    experts = EXPERTS.get(team, set())
    theirs = any(
        not (name in ready if builtin else name in experts) for name, builtin, _stage in members
    )
    moved = any(
        stage is not None and stage not in PLACED.get(name, ()) for name, _b, stage in members
    )
    # (A ready role not made yet - an older install, or a new one before its first start - is
    # no role taken out: `seed_builtin_roles` adds it to the ready teams still there.)
    taken_out = ((set(ready) & builtin_names) | (experts & own_names)) - names
    stages = bind.execute(
        sa.text("SELECT name, together FROM team_stages WHERE team_id = :id ORDER BY position"),
        {"id": team_id},
    ).fetchall()
    own_recipe = bind.execute(
        sa.text("SELECT 1 FROM recipes WHERE id = :id AND name = :name AND ready"),
        {"id": recipe_id, "name": recipe},
    ).first()
    # (None: a team with no lead role on record - none the user could have taken away.)
    lead = (
        bind.execute(
            sa.text("SELECT name FROM roles WHERE id = :id AND updated_at = created_at"),
            {"id": lead_id},
        ).first()
        if lead_id is not None
        else (f"{team} lead",)
    )
    return (
        not theirs
        and not moved
        and not taken_out
        and [name for name, _ in stages] == STAGES
        and not any(together for _, together in stages)
        and bool(lead_on)
        and bool(may_pick)
        and own_recipe is not None
        and lead is not None
        and lead[0] == f"{team} lead"
    )


def upgrade() -> None:
    bind = op.get_bind()
    builtin_names = {
        BUILT_IN.sub("", name)
        for (name,) in bind.execute(sa.text("SELECT name FROM roles WHERE builtin"))
    }
    own_names = {
        name for (name,) in bind.execute(sa.text("SELECT name FROM roles WHERE NOT builtin"))
    }
    kept_for_projects = {
        row.get("team_id")
        for (rows,) in bind.execute(sa.text("SELECT teams FROM projects"))
        for row in (json.loads(rows) if isinstance(rows, str) else rows or [])
        if isinstance(row, dict)
    }
    by_recipes = _named_by_recipes(bind)
    for team in GONE:
        found = bind.execute(
            sa.text(
                "SELECT id, lead_role_id, lead_on, lead_may_pick, default_recipe_id FROM teams "
                f"WHERE {STOCK}"
            ),
            {"team": team},
        ).first()
        if found is None:
            continue  # (deleted or renamed by the user, or never made here)
        team_id, lead_id = found[0], found[1]
        # (A Manual chat's row too where the Lead picked it: going to Manual keeps the Lead's
        # picks as the user's to change.)
        picked = bind.execute(
            sa.text(
                "SELECT 1 FROM conversation_teams ct JOIN conversations c "
                "ON c.id = ct.conversation_id WHERE ct.team_id = :id "
                "AND (ct.picked_by = 'user' OR c.teams_mode = 'manual') LIMIT 1"
            ),
            {"id": team_id},
        ).first()
        if (
            picked is not None
            or team_id in kept_for_projects
            or team.casefold() in by_recipes
            or not _as_it_came(bind, team, found, builtin_names, own_names)
        ):
            continue
        for table in ("conversation_teams", "role_teams", "team_stages"):
            bind.execute(sa.text(f"DELETE FROM {table} WHERE team_id = :id"), {"id": team_id})
        bind.execute(sa.text("DELETE FROM teams WHERE id = :id"), {"id": team_id})
        if lead_id is not None:
            bind.execute(sa.text("DELETE FROM role_teams WHERE role_id = :id"), {"id": lead_id})
            bind.execute(sa.text("DELETE FROM roles WHERE id = :id"), {"id": lead_id})


def downgrade() -> None:
    # (What went is not made again: see the module's note.)
    pass
