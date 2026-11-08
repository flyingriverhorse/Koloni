"""teams, roles and recipes put in order (K-takim-duzen): three more categories - Data, ML and
Ops - after Build; the ready ML and DataOps teams, the MLflow and Databricks experts in ML; the
ready Ops team named DevOps; eight ready recipes, each the default of its ready team

A built-in role is moved to its new category only where it is still in its old one. A team is
made only where its name and its lead's are free; the ready Ops is renamed only where it still
is the ready one, by that name, and DevOps is free. A team gets its default only where it is
the ready one and has none: a recipe the user chose is kept, a team the user made or renamed is
left as it is. The experts are the user's own roles from here on: deleted, they do not come
back. Their members join the new teams as they are added (`app.roles.seed_builtin_roles`), and
take their stages there (`place_in_stages`).

Going back puts the categories, the name and the defaults back, and takes away the recipes
nothing names, ML and DataOps, and the experts still as they were made.
shortcut: going back, a chat's row of ML or DataOps goes with its team, and a project's default
teams still name it, as a note of it does (deleting a team on its card clears the project's);
clear those too if a downgrade is ever used for more than tests.

Revision ID: 0103
Revises: 0102
"""
import json
import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0103"
down_revision = "0102"
branch_labels = None
depends_on = None

# As they were when this was written (app.roles): a migration does not follow later code.
# (Ops olive: brown is what a kind with no category is drawn in.)
CATEGORIES = (("data", "Data", "teal"), ("ml", "ML", "rose"), ("ops", "Ops", "olive"))
# The built-in roles a new category takes, each from the category it was in.
MOVED = {"Database engineer": ("build", "data"), "Data engineer": ("build", "data"),
         "ML engineer": ("build", "ml"), "Data scientist": ("build", "ml"),
         "DevOps": ("build", "ops"), "MLOps engineer": ("build", "ops"),
         "Dependency keeper": ("write", "ops")}
# Their members that were built-in roles before this; the new ones join as they are added.
TEAMS = {"ML": ("Tester",), "DataOps": ("Database engineer", "Data analyst", "Tester")}
STAGES = ("Plan", "Build", "Check", "Write & keep up")
LEAD_DESCRIPTION = "Runs its team's stages when the team works beside another team."
LEAD_INSTRUCTIONS = ("Run your team's stages in order with the recipe you were given; hand "
                     "findings to the right role; report to the Lead.")
LEAD_TOOLS = ["list_dir", "read_file", "search", "spawn_agent", "ask_user", "message_agent",
              "open_room", "discuss", "post_note", "read_notes", "remember", "recall"]
EXPERT_TOOLS = ["list_dir", "read_file", "search", "message_agent", "post_note", "read_notes",
                "recall"]


def _knows(topic, source):
    return {"topic": topic, "sources": [source], "max_pages": 20, "max_usd": 0.5,
            "learn_with": None, "removed": [], "weekly": False, "search_answering": False}


# Not learned: learning reads the web, only when the user presses Learn.
EXPERTS = {"MLflow expert": _knows("MLflow", "https://mlflow.org/docs/latest/"),
           "Databricks expert": _knows("Databricks", "https://docs.databricks.com/aws/en/")}
# Its instructions (the user's: "for now AWS, but when we say otherwise it should understand the
# difference"); the MLflow expert has none.
INSTRUCTIONS = {"Databricks expert": (
    "Databricks' docs differ by cloud (AWS, Azure, GCP). Work from AWS, your guide's, unless told "
    "otherwise. When the user or the task names Azure or GCP, say what differs there and point to "
    "that cloud's docs (https://learn.microsoft.com/azure/databricks/ or "
    "https://docs.databricks.com/gcp/en/) instead of assuming AWS.")}


def _step(id, name, role, **more):
    return {"id": id, "name": name, "who": {"role": role}, "done_when": "done",
            "if_fails": "ask", "ask_me": False, "group": None, **more}


def _review(id, name, role, **more):
    return _step(id, name, role, done_when="no_findings", **more)


def _graph(steps, way, then="in", groups=(), loops=()):
    return {"version": 1, "steps": steps,
            "groups": [{"id": id, "name": "All at once, wait for all"} for id in groups],
            "ends": [{"id": "end", "then": then}],
            "arrows": [{"from": a, "to": b}
                       for a, b in zip(("start", *way), (*way, "end"), strict=True)],
            "loops": [{"from": a, "to": b, "rounds": n} for a, b, n in loops]}


# As they were when this was written (`app.schemas.RecipeGraph`, version 1). An "at once" group
# opens two roles at most (B-173). A review right after the work sends what it finds back to it,
# at most 2 rounds - but a report's (Analysis), and a review after the checks: what it finds, the
# user sees. The experts' review of the plan sends it back once.
READY = {
    "Model change": _graph(
        [_step("plan", "Plan the experiment", "Data scientist"),
         {**_review("experts", "Experts review the plan", None), "who": {"experts": "learned"}},
         _step("build", "Build it", "ML engineer"),
         _review("tests", "Run the tests", "Tester", group="checks"),
         _review("metrics", "Compare the metrics", "Model evaluator", group="checks"),
         _review("review", "Review it", "Reviewer")],
        ("plan", "experts", "build", "checks", "review"), groups=("checks",),
        loops=(("experts", "plan", 1), ("checks", "build", 2))),
    "Pipeline change": _graph(
        [_step("build", "Change the pipeline", "Data engineer"),
         _review("tests", "Run the tests", "Tester", group="checks"),
         _review("quality", "Check the data quality", "Data analyst", group="checks"),
         _review("review", "Review it", "Reviewer")],
        ("build", "checks", "review"), groups=("checks",), loops=(("checks", "build", 2),)),
    "Infra change": _graph(
        [_step("build", "Change the infrastructure", "DevOps"),
         _review("security", "Security review", "Security reviewer", group="reviews"),
         _review("speed", "Performance review", "Performance engineer", group="reviews"),
         _review("review", "Review it", "Reviewer")],
        ("build", "reviews", "review"), groups=("reviews",), loops=(("reviews", "build", 2),)),
    "Docs": _graph(
        [_step("write", "Write the docs", "Docs writer"), _review("review", "Review it", "Reviewer")],
        ("write", "review"), loops=(("review", "write", 2),)),
    "Research": _graph(
        [_step("research", "Find it out", "Researcher"),
         _step("summary", "Sum it up", "Summarizer")],
        ("research", "summary"), then="report"),
    "Spec": _graph(
        [_step("tasks", "Break it into tasks", "Product owner"),
         _step("spec", "Write the spec", "Spec writer")],
        ("tasks", "spec"), then="report"),
    "Analysis": _graph(
        [_step("analyse", "Analyse the data", "Data analyst"),
         _review("review", "Review the analysis", "Reviewer")],
        ("analyse", "review"), then="report"),
    # As Quality check's (0102): only if the tests fail, the Debugger, then the tests again.
    "Upkeep": _graph(
        [_step("update", "Update the dependencies", "Dependency keeper"),
         _review("test", "Run the tests", "Tester"),
         _step("fix", "Find and fix the cause", "Debugger", when="problem")],
        ("update", "test", "fix"), loops=(("fix", "test", 2),)),
}
DEFAULTS = {"ML": "Model change", "DataOps": "Pipeline change", "Ops": "Infra change",
            "Docs": "Docs", "Research": "Research", "Product": "Spec", "Data": "Analysis",
            "Maintenance": "Upkeep"}
RECIPE = "(SELECT id FROM recipes WHERE name = :recipe AND ready = 1)"
# As 0093's: the ready teams are the first ever made - ML and DataOps are given their time, so
# they are told apart from the user's teams the same way.
FIRST = "(SELECT MIN(created_at) FROM teams)"
STOCK = f"name = :team AND created_at = {FIRST}"


def _free(bind, table, name) -> bool:
    return bind.execute(sa.text(f"SELECT 1 FROM {table} WHERE lower(name) = lower(:name)"),
                        {"name": name}).first() is None


def _categories(bind) -> None:
    """Data, ML and Ops after Build, each numbered where the user has a category by its name."""
    after = bind.execute(sa.text("SELECT position FROM categories WHERE key = 'build'")).scalar()
    after = 1 if after is None else after
    new = [one for one in CATEGORIES if bind.execute(sa.text(
        "SELECT 1 FROM categories WHERE key = :key"), {"key": one[0]}).first() is None]
    bind.execute(sa.text("UPDATE categories SET position = position + :n WHERE position > :at"),
                 {"n": len(new), "at": after})
    names = {name.casefold() for (name,) in bind.execute(sa.text("SELECT name FROM categories"))}
    for at, (key, name, colour) in enumerate(new, start=after + 1):
        shown, n = name, 1
        while shown.casefold() in names:
            n += 1
            shown = f"{name} {n}"
        names.add(shown.casefold())
        bind.execute(sa.text("INSERT INTO categories (key, name, colour, position) "
                             "VALUES (:k, :n, :c, :at)"), {"k": key, "n": shown, "c": colour, "at": at})
    for role, (was, now) in MOVED.items():
        bind.execute(sa.text("UPDATE roles SET kind = :now WHERE builtin AND name = :name "
                             "AND kind = :was"), {"now": now, "was": was, "name": role})


def _team(bind, team, made, first) -> str | None:
    """A ready team as `app.api.teams.create_team` makes one, with the built-in roles that are
    there already; its id, or None where its name or its lead's is taken."""
    if not _free(bind, "teams", team) or not _free(bind, "roles", f"{team} lead"):
        return None
    team_id, lead = uuid.uuid4().hex, uuid.uuid4().hex
    bind.execute(sa.text(
        "INSERT INTO roles (id, name, description, instructions, tools, builtin, "
        "created_by_agent, tier, kind, enabled, mcp, skills, created_at, updated_at) "
        "VALUES (:id, :name, :says, :does, :tools, 0, 0, 'conversation', 'lead', 1, '[]', '[]', "
        ":at, :at)"
    ), {"id": lead, "name": f"{team} lead", "says": LEAD_DESCRIPTION, "does": LEAD_INSTRUCTIONS,
        "tools": json.dumps(LEAD_TOOLS), "at": made})
    bind.execute(sa.text(
        "INSERT INTO teams (id, name, created_at, lead_role_id, lead_on, lead_may_pick) "
        "VALUES (:id, :name, :at, :lead, 1, 1)"), {"id": team_id, "name": team, "at": first,
                                                    "lead": lead})
    for at, name in enumerate(STAGES):
        bind.execute(sa.text("INSERT INTO team_stages (id, team_id, name, position, together) "
                             "VALUES (:id, :team, :name, :at, 0)"),
                     {"id": uuid.uuid4().hex, "team": team_id, "name": name, "at": at})
    for name in TEAMS[team]:
        bind.execute(sa.text("INSERT INTO role_teams (role_id, team_id) "
                             "SELECT id, :team FROM roles WHERE builtin AND name = :name"),
                     {"team": team_id, "name": name})
    return team_id


def _experts(bind, made, ml) -> None:
    """The two experts, where neither their name nor their topic's folder is another role's."""
    topics = {(json.loads(known) if isinstance(known, str) else known).get("topic", "").casefold()
              for (known,) in bind.execute(sa.text(
                  "SELECT knowledge FROM roles WHERE knowledge IS NOT NULL"))}
    for name, known in EXPERTS.items():
        if not _free(bind, "roles", name) or known["topic"].casefold() in topics:
            continue
        role = uuid.uuid4().hex
        bind.execute(sa.text(
            "INSERT INTO roles (id, name, description, instructions, tools, builtin, "
            "created_by_agent, kind, enabled, mcp, skills, knowledge, created_at, updated_at) "
            "VALUES (:id, :name, :says, :does, :tools, 0, 0, 'plan', 1, '[]', '[]', :knows, :at, "
            ":at)"
        ), {"id": role, "name": name, "tools": json.dumps(EXPERT_TOOLS), "at": made,
            "does": INSTRUCTIONS.get(name, ""),
            "says": f"Knows {known['topic']}: answers from its sources, advises and reads only.",
            "knows": json.dumps(known)})
        if ml is not None:
            bind.execute(sa.text("INSERT INTO role_teams (role_id, team_id) VALUES (:r, :t)"),
                         {"r": role, "t": ml})


def upgrade() -> None:
    bind = op.get_bind()
    made = datetime.now(UTC).replace(tzinfo=None).isoformat(" ", "microseconds")
    first = bind.execute(sa.text(f"SELECT {FIRST}")).scalar() or made
    _categories(bind)
    teams = {team: _team(bind, team, made, first) for team in TEAMS}
    _experts(bind, made, teams["ML"])
    for name, graph in READY.items():
        # (A recipe of the user's own by that name keeps it: the ready one is not added.)
        bind.execute(sa.text(
            "INSERT INTO recipes (id, name, ready, graph, created_at, updated_at) "
            "SELECT :id, :name, 1, :graph, :at, :at "
            "WHERE NOT EXISTS (SELECT 1 FROM recipes WHERE lower(name) = lower(:name))"
        ), {"id": uuid.uuid4().hex, "name": name, "graph": json.dumps(graph), "at": made})
    for team, recipe in DEFAULTS.items():
        bind.execute(sa.text(f"UPDATE teams SET default_recipe_id = {RECIPE} "
                             f"WHERE {STOCK} AND default_recipe_id IS NULL"),
                     {"team": team, "recipe": recipe})
    _rename(bind, "Ops", "DevOps")


def _rename(bind, was, now) -> None:
    """The ready team `was` and its lead named `now`, where both names are free."""
    if not _free(bind, "teams", now) or not _free(bind, "roles", f"{now} lead"):
        return
    lead = bind.execute(sa.text(f"SELECT lead_role_id FROM teams WHERE {STOCK}"),
                        {"team": was}).scalar()
    bind.execute(sa.text(f"UPDATE teams SET name = :now WHERE {STOCK}"), {"team": was, "now": now})
    bind.execute(sa.text("UPDATE roles SET name = :now WHERE id = :id AND name = :was"),
                 {"id": lead, "now": f"{now} lead", "was": f"{was} lead"})


def downgrade() -> None:
    bind = op.get_bind()
    _rename(bind, "DevOps", "Ops")
    # (A user who chose that very recipe for the team since loses it too: not told apart.)
    for team, recipe in DEFAULTS.items():
        bind.execute(sa.text(f"UPDATE teams SET default_recipe_id = NULL "
                             f"WHERE {STOCK} AND default_recipe_id = {RECIPE}"),
                     {"team": team, "recipe": recipe})
    for team in TEAMS:
        found = bind.execute(sa.text(f"SELECT id, lead_role_id FROM teams WHERE {STOCK}"),
                             {"team": team}).first()
        if found is not None:
            for table in ("conversation_teams", "role_teams", "team_stages"):
                bind.execute(sa.text(f"DELETE FROM {table} WHERE team_id = :id"), {"id": found[0]})
            bind.execute(sa.text("DELETE FROM teams WHERE id = :id"), {"id": found[0]})
            bind.execute(sa.text("DELETE FROM roles WHERE id = :id"), {"id": found[1]})
    for name, known in EXPERTS.items():
        for role, kept in bind.execute(sa.text(
                "SELECT id, knowledge FROM roles WHERE name = :name AND NOT builtin "
                "AND updated_at = created_at"), {"name": name}).fetchall():
            # (Never saved since, and its knowledge compared as data, as 0102 compares a drawing:
            # one the user changed - Learn's sources, a tool, a word - is theirs.)
            if (json.loads(kept) if isinstance(kept, str) else kept) == known:
                bind.execute(sa.text("DELETE FROM role_teams WHERE role_id = :id"), {"id": role})
                bind.execute(sa.text("DELETE FROM roles WHERE id = :id"), {"id": role})
    for name in READY:
        # (Gone only where nothing names it: no team's default, no chat's row.)
        bind.execute(sa.text(
            f"DELETE FROM recipes WHERE id IN {RECIPE} "
            "AND id NOT IN (SELECT default_recipe_id FROM teams "
            "WHERE default_recipe_id IS NOT NULL) "
            "AND id NOT IN (SELECT recipe_id FROM conversation_teams "
            "WHERE recipe_id IS NOT NULL)"), {"recipe": name})
    for role, (was, now) in MOVED.items():
        bind.execute(sa.text("UPDATE roles SET kind = :was WHERE builtin AND name = :name "
                             "AND kind = :now"), {"now": now, "was": was, "name": role})
    # (A role the user put in one of them goes to Build.)
    keys = ", ".join(f"'{key}'" for key, _name, _colour in CATEGORIES)
    op.execute(f"UPDATE roles SET kind = 'build' WHERE kind IN ({keys})")
    op.execute(f"DELETE FROM categories WHERE key IN ({keys})")
    # (Their places closed up, in the order they are in.)
    for at, (key,) in enumerate(bind.execute(sa.text(
            "SELECT key FROM categories ORDER BY position")).fetchall()):
        bind.execute(sa.text("UPDATE categories SET position = :at WHERE key = :key"),
                     {"at": at, "key": key})
