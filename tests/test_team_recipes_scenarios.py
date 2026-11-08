"""K-takim-duzen: each ready team's own default recipe, run with the fake model - its steps in
order, by the right roles, a loop's round where it has one - and drawn only of the team's roles
and the shared ones; the Data, ML and Ops roles sit in Build, the Data scientist in Plan; the
"learned" experts' step opens only an expert that has learned, and is passed with none."""

import pytest

from app import knowledge, koloni, recipe_run
from app.agent import AgentRunner
from app.db.models import Team
from app.recipes import problems
from app.schemas import RecipeGraph, WhoRole
from tests.test_chat_flow import text
from tests.test_chat_teams_scenarios import teams_of
from tests.test_claim_scenarios import write
from tests.test_parallel import until
from tests.test_recipe_run_scenarios import FOUND, NONE, asked, by_call, row, strip
from tests.test_spawn import begin, call, spawn, step

# K-takim-duzen's: the team, its new default, and the roles any recipe may call.
DEFAULTS = {"ML": "Model change", "DataOps": "Pipeline change", "DevOps": "Infra change",
            "Docs": "Docs", "Research": "Research", "Product": "Spec", "Data": "Analysis",
            "Maintenance": "Upkeep"}
SHARED = {"Reviewer", "Lead", "Planner"}


def learned(root, topic, record=True):
    """The expert of `topic` as having learned in the project: its guide, and - unless not
    `record` (a guide file a project came with) - what its learning wrote of it."""
    where = knowledge.folder_of({"topic": topic})
    koloni.write(str(root), f"{where}/{knowledge.GUIDE}", "## Tracking")
    if record:
        koloni.write(str(root), f"{where}/{knowledge.LEARNED}", '{"learned_at": "2026-10-28"}')


def recipes(client):
    every = {r["id"]: r for r in client.get("/api/recipes").json()["recipes"]}
    return {team: every[found["default_recipe_id"]] for team, found in teams_of(client).items()
            if team in DEFAULTS}


def test_each_new_default_is_its_teams_and_calls_only_its_roles_and_the_shared_ones(make_client):
    client, _model = make_client({})
    teams = teams_of(client)
    with client.app.state.session_factory() as session:
        for team, recipe in recipes(client).items():
            assert recipe["name"] == DEFAULTS[team]
            drawn = RecipeGraph.model_validate(recipe["graph"])
            called = {s.who.role for s in drawn.steps if isinstance(s.who, WhoRole)}
            assert called - set(teams[team]["roles"]) <= SHARED, (team, called)
            assert problems(session, drawn, client.app.state.providers) == [], team
            assert (recipe_run.conditions(drawn), recipe_run.own_checks(drawn)) == ([], []), team
            # (B-173: an "at once" part opens two roles at most.)
            assert all(len(recipe_run.steps_of(drawn, g.id)) <= 2 for g in drawn.groups), team


def test_the_new_teams_roles_sit_in_their_stages(make_client):
    client, _model = make_client({})
    names = {r["id"]: r["name"] for r in client.get("/api/roles").json()}
    teams = teams_of(client)

    def stages(team):
        return {s["name"]: sorted(names[i] for i in s["roles"]) for s in teams[team]["stages"]}

    assert stages("ML") == {
        "Plan": ["Data scientist", "Databricks expert", "MLflow expert"],
        "Build": ["ML engineer", "MLOps engineer"], "Check": ["Model evaluator", "Tester"],
        "Write & keep up": []}
    assert stages("DataOps") == {"Plan": [], "Build": ["Data engineer", "Database engineer"],
                                 "Check": ["Data analyst", "Tester"], "Write & keep up": []}
    assert teams["DevOps"]["lead"]["name"] == "DevOps lead" and "Ops" not in teams


def test_the_learned_experts_step_opens_only_an_expert_that_learned(make_client, project_dir):
    client, _model = make_client({})
    graph = RecipeGraph.model_validate(recipes(client)["ML"]["graph"])
    experts = next(s for s in graph.steps if s.id == "experts")
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    with client.app.state.session_factory() as session:
        ml = session.get_one(Team, teams_of(client)["ML"]["id"])
        slots = AgentRunner._slots_of(session, ml, str(project_dir), cid)
        assert slots(experts) == []  # (none learned: the step is passed - no Learn of its own)
        learned(project_dir, "MLflow", record=False)
        assert slots(experts) == []  # (a guide file the project came with: not learned here)
        learned(project_dir, "MLflow")
        assert slots(experts) == [("MLflow expert",)]
        state = recipe_run.begin(graph, "r", "Model change", lambda one: [] if one.id == "experts"
                                 else [(one.who.role,)] if isinstance(one.who, WhoRole) else [])
        recipe_run.opened(state, "a1", "Data scientist")["ok"] = True
        assert recipe_run.advance(state) == (
            "Next: Build it - open ML engineer. Skipped, no expert has learned yet: Experts review the plan.")
        assert state["unmet"] == {"experts": "no expert has learned yet"}


def test_a_step_on_a_problem_with_nobody_to_fill_it_says_so_not_no_problem():
    drawn = RecipeGraph.model_validate({
        "steps": [{"id": "test", "name": "Run the tests", "who": {"role": "Tester"},
                   "done_when": "no_findings"},
                  {"id": "experts", "name": "Ask the experts", "who": {"experts": "learned"},
                   "when": "problem"}],
        "ends": [{"id": "end"}], "arrows": [{"from": a, "to": b} for a, b in (
            ("start", "test"), ("test", "experts"), ("experts", "end"))]})
    state = recipe_run.begin(drawn, "r", "R", lambda one: [] if one.id == "experts" else [("Tester",)])
    recipe_run.opened(state, "a1", "Tester").update(ok=True, found=True)
    recipe_run.advance(state)
    assert state["unmet"] == {"experts": "no expert has learned yet"}


def test_the_lead_that_picks_ml_is_told_its_experts_step_is_skipped(make_client, wait_run,
                                                                      project_dir):
    client, _model = make_client({"Lead": [
        step(call("pick_teams", {"teams": [{"team": "ML", "why": "a model change"}]}, "p")),
        text("done")]})
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never",
                        teams_mode="lead")
    snap = wait_run(client, cid, run_id)
    (picked,) = [t["result"] for t in snap["tool_calls"] if t["name"] == "pick_teams"]
    assert ("ML by Model change: Plan the experiment (Data scientist) → Experts review the plan "
            "skipped: no expert has learned yet → Build it (ML engineer)") in picked


# --- each recipe with the fake model --------------------------------------------------------------


def both(one, two, at):
    return step(call("spawn_agent", {"role": one, "task": "check it"}, f"{at}1"),
                call("spawn_agent", {"role": two, "task": "check it"}, f"{at}2"))


def fix(role, by, at):
    return step(call("spawn_agent", {"role": role, "task": "fix it", "findings_from": by}, at))


def ran(make_client, project_dir, team, lead, said, ready=True):
    """The team's chat run by its default recipe, as far as Ready for you (an "in" end) or its
    end (a report); the snapshot."""
    client, _model = make_client({"Lead": [*lead, text("all done")], **said})
    cid, _run_id = begin(client, project_dir, mode="auto_edit", spawn_approval="never",
                         teams_mode="manual",
                         teams=[{"team_id": teams_of(client)[team]["id"], "recipe_id": None}])
    snap = until(client, cid, (lambda s: asked(s) and "Ready for you" in asked(s)["question"])
                 if ready else (lambda s: row(s)["status"] == "done"), timeout=10)
    assert not [c for c in by_call(snap) if c[0] == "failed"], by_call(snap)
    assert row(snap)["recipe"] == DEFAULTS[team]
    return snap


def opened(snap):
    return [a["role_name"] for a in snap["agents"] if a["depth"] == 1]


def in_waves(names, *sizes):
    """`names` cut into waves of these sizes, each sorted: agents opened at once can share a
    timestamp, and their order is then their ids' (seen on a CI runner)."""
    at, waves = 0, []
    for size in sizes:
        waves.append(sorted(names[at:at + size]))
        at += size
    return waves + [names[at:]]


def test_model_change_plans_has_the_learned_expert_review_builds_checks_twice_and_reviews(
    make_client, project_dir
):
    learned(project_dir, "MLflow")
    snap = ran(make_client, project_dir, "ML", [
        spawn("Data scientist", "plan it", "p"), spawn("MLflow expert", "review the plan", "x"),
        spawn("ML engineer", "build it", "b"), both("Tester", "Model evaluator", "c"),
        fix("ML engineer", "Model evaluator", "f"), both("Tester", "Model evaluator", "d"),
        spawn("Reviewer", "review it", "r")], {
        "Data scientist": [text("Hypothesis: a smaller learning rate; metric: AUC.")],
        "MLflow expert": [text(NONE)], "ML engineer": [step(write("made.txt", "x")), text("built")],
        "Tester": [text(NONE)], "Model evaluator": [text(FOUND)], "ML engineer 2": [text("fixed")],
        "Tester 2": [text(NONE)], "Model evaluator 2": [text(NONE)], "Reviewer": [text(NONE)]})
    assert opened(snap) == ["Data scientist", "MLflow expert", "ML engineer", "Tester",
                            "Model evaluator", "ML engineer", "Tester", "Model evaluator", "Reviewer"]
    # (R116: the checks that sent it back ran again - the loop's round is theirs too)
    assert strip(row(snap)) == [("plan", "done", 0), ("experts", "done", 0), ("build", "done", 1),
                                ("checks", "done", 1), ("review", "done", 0), ("end", "now", 0)]


@pytest.mark.parametrize(("team", "writer", "first", "second"), [
    ("DataOps", "Data engineer", "Tester", "Data analyst"),
    ("DevOps", "DevOps", "Security reviewer", "Performance engineer"),
])
def test_a_change_is_checked_by_two_at_once_fixed_once_and_reviewed(
    make_client, project_dir, team, writer, first, second
):
    snap = ran(make_client, project_dir, team, [
        spawn(writer, "change it", "b"), both(first, second, "c"), fix(writer, second, "f"),
        both(first, second, "d"), spawn("Reviewer", "review it", "r")], {
        writer: [step(write("made.txt", "x")), text("changed")], first: [text(NONE)], second: [text(FOUND)],
        f"{writer} 2": [text("fixed")], f"{first} 2": [text(NONE)], f"{second} 2": [text(NONE)],
        "Reviewer": [text(NONE)]})
    assert in_waves(opened(snap), 1, 2, 1, 2) == in_waves(
        [writer, first, second, writer, first, second, "Reviewer"], 1, 2, 1, 2)
    group = "checks" if team == "DataOps" else "reviews"
    assert strip(row(snap)) == [("build", "done", 1), (group, "done", 1), ("review", "done", 0),
                                ("end", "now", 0)]


def test_docs_are_written_reviewed_and_written_again_once(make_client, project_dir):
    snap = ran(make_client, project_dir, "Docs", [
        spawn("Docs writer", "write it", "w"), spawn("Reviewer", "review it", "r"),
        fix("Docs writer", "Reviewer", "f"), spawn("Reviewer", "review it again", "s")], {
        "Docs writer": [step(write("made.txt", "x")), text("written")], "Reviewer": [text(FOUND)],
        "Docs writer 2": [text("fixed")], "Reviewer 2": [text(NONE)]})
    assert opened(snap) == ["Docs writer", "Reviewer", "Docs writer", "Reviewer"]
    assert strip(row(snap)) == [("write", "done", 1), ("review", "done", 1), ("end", "now", 0)]


@pytest.mark.parametrize(("team", "first", "second", "ids"), [
    ("Research", "Researcher", "Summarizer", ("research", "summary")),
    ("Product", "Product owner", "Spec writer", ("tasks", "spec")),
    ("Data", "Data analyst", "Reviewer", ("analyse", "review")),
])
def test_two_steps_one_after_the_other_end_in_a_report(make_client, project_dir, team, first,
                                                       second, ids):
    snap = ran(make_client, project_dir, team, [spawn(first, "do it", "a"), spawn(second, "then", "b")],
               {first: [text("done it")], second: [text(NONE)]}, ready=False)
    assert opened(snap) == [first, second]
    assert strip(row(snap)) == [(ids[0], "done", 0), (ids[1], "done", 0), ("end", "done", 0)]


def test_upkeep_updates_tests_debugs_only_when_they_fail_and_tests_again(make_client, project_dir):
    snap = ran(make_client, project_dir, "Maintenance", [
        spawn("Dependency keeper", "update them", "u"), spawn("Tester", "run the tests", "t"),
        fix("Debugger", "Tester", "d"), spawn("Tester", "run them again", "s")], {
        "Dependency keeper": [step(write("made.txt", "x")), text("updated")], "Tester": [text(FOUND)],
        "Debugger": [text("fixed")], "Tester 2": [text(NONE)]})
    assert opened(snap) == ["Dependency keeper", "Tester", "Debugger", "Tester"]
    # B-177: the fix ran in round 1, then the tests passed: it shows done, not skipped.
    assert strip(row(snap)) == [("update", "done", 0), ("test", "done", 1), ("fix", "done", 1),
                                ("end", "now", 0)]


def test_a_report_recipe_whose_step_wrote_a_file_ends_at_take_in(make_client, wait_run, project_dir):
    # B-190 (live): the Spec writer could not write docs/api-spec.md; now it does, and a report
    # recipe's written file is the user's to take in - not a copy kept at the turn's end.
    from tests.test_claim_scenarios import write
    from tests.test_recipe_run_scenarios import answer

    client, _model = make_client({
        "Lead": [spawn("Product owner", "break it up", "a"),
                 spawn("Spec writer", "write docs/spec.md", "b"), text("all done")],
        "Product owner": [text("three tasks")],
        "Spec writer": [step(write("docs/spec.md", "# POST /predict\n")), text("written")]})
    cid, run_id = begin(client, project_dir, mode="auto_edit", spawn_approval="never",
                        teams_mode="manual",
                        teams=[{"team_id": teams_of(client)["Product"]["id"], "recipe_id": None}])
    snap = until(client, cid, lambda s: asked(s) and "Ready for you" in asked(s)["question"],
                 timeout=10)
    assert (row(snap)["recipe"], row(snap)["status"]) == ("Spec", "ready")
    assert not (project_dir / "docs" / "spec.md").exists()
    answer(client, asked(snap), "Take in")
    snap = wait_run(client, cid, run_id)
    assert (project_dir / "docs" / "spec.md").read_text(encoding="utf-8") == "# POST /predict\n"
    assert row(snap)["status"] == "in"
