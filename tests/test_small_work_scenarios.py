"""Tarif maliyeti T2 (the user's decision 4, 23 Nov): under Orchestrator decides, a small change -
a few lines in one or two files - needs no team: the Orchestrator makes it with one agent (or
itself, where the project lets it write), says in one line why no team, and KOLONİ's end checks
run all the same. `pick_teams` lists each recipe with how many agents its run opens, so a pick
weighs the cost - one whose stored drawing no longer reads is left out, failing no turn. A recipe
left at a step is no small change: an answer that leaves it stands with no check of half its work
(its own end checks it). A fake model and a scripted executor; KOLONİ's review and its ask for a
test are on in this module (conftest), so a turn ends as in the app."""

import pytest

from app.tools import pick_schema
from tests.fakes import ScriptedExecutor
from tests.test_chat_flow import text
from tests.test_chat_teams_scenarios import teams_of
from tests.test_claim_scenarios import write
from tests.test_proof_end_scenarios import guess, texts
from tests.test_recipe_proof_scenarios import FAILED, PASSED, PYTEST
from tests.test_recipe_run_scenarios import made, own_test, row
from tests.test_recipes_scenarios import graph
from tests.test_recipes_scenarios import step as part
from tests.test_spawn import begin, spawn, step

SMALL = "A small change - a few lines in one or two files - needs no team"
NO_TEAM = "No team: a two-line change in one file."


def picks(tools):
    (pick,) = [t["function"] for t in tools if t["function"]["name"] == "pick_teams"]
    return pick


def test_pick_teams_says_a_small_change_needs_no_team_and_counts_each_recipes_agents():
    class Team:
        name = "Web app"

    class Counted:
        def __init__(self, least, most):
            self.least, self.most = least, most

    said = pick_schema(
        [(Team, ["Coder"])],
        [("Feature", Counted(6, 16)), ("Spec", Counted(2, 2)), ("One", Counted(1, 1)), ("X", None)],
    )["function"]
    assert SMALL in said["description"]
    # (Projects default to "delegates": the Orchestrator writes no file itself there.)
    assert "make it with one agent (or yourself, where you may write files)" in said["description"]
    assert said["description"].endswith("- Feature: 6-16 agents\n- Spec: 2 agents\n- One: 1 agent")
    recipe = said["parameters"]["properties"]["teams"]["items"]["properties"]["recipe"]
    assert recipe["enum"] == ["Feature", "Spec", "One", "X"]  # (one not counted is a recipe too)


def small_turn(make_client, project_dir, executor, *after):
    """Under Orchestrator decides at Full auto, a Coder makes a two-line change with no team
    and no test; the Lead's answers: done, its why no team, then `after`."""
    client, model = make_client(
        {
            "Lead": [
                spawn("Coder", "make greet say Hello", "c1"),
                text("done"),
                text(NO_TEAM),
                *after,
            ],
            "Coder": [step(write("greet.py", "def greet():\n    return 'Hello'\n")), text("done")],
        },
        executor=executor,
    )
    cid, run_id = begin(
        client, project_dir, mode="full_auto", spawn_approval="never", teams_mode="lead"
    )
    return client, model, cid, run_id


def said(calls):
    return [str(one[-1]["content"])[:100] for one in calls]


@pytest.mark.no_po  # (the Assistant PO's request would be one more call)
def test_a_small_change_under_orchestrator_decides_picks_no_team_and_is_checked(
    make_client, wait_run, project_dir, monkeypatch
):
    # Why no team, then KOLONİ's checks - before the fix they never ran after that line: "Tests
    # not run: the turn ended before KOLONİ's check" - then its ask for a test, answered in a line.
    guess(monkeypatch, PYTEST)
    no_test = "No test: greet's text is all it changes."
    client, model, cid, run_id = small_turn(
        make_client, project_dir, ScriptedExecutor([PASSED]), text(no_test)
    )
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    # (Told so, with the ready recipes' counts - the migrated ones: Feature's is T1's to keep.)
    told = picks(model.tool_args[0])["description"]
    assert SMALL in told and "- Feature: 6-16 agents" in told, told
    calls = model.calls_of["Lead"]
    assert len(calls) == 4, said(calls)
    assert "say in one line why no team works on it" in calls[2][-1]["content"], said(calls)
    assert "greet.py changed and no test did" in calls[3][-1]["content"], said(calls)
    assert snap["conversation"]["teams"] == []
    assert [a["role_name"] for a in snap["agents"] if a["depth"] == 1] == ["Coder"]
    answers = [m["content"] for m in snap["messages"] if m["role"] == "assistant" and m["content"]]
    assert answers[-2:] == [NO_TEAM, no_test], answers
    rows = texts(snap)
    assert f"Tests passed: {PYTEST} (guessed) - 4 passed" in rows, rows
    assert any(one.startswith("No review: a small change") for one in rows), rows


@pytest.mark.no_po
def test_after_the_why_no_team_the_check_runs_once(make_client, wait_run, project_dir, monkeypatch):
    # (Its failing tests go back to the Orchestrator; an answer to that with no call stands, as
    # it did before: the check is not run round again.)
    guess(monkeypatch, PYTEST)
    executor = ScriptedExecutor([FAILED, FAILED])  # (a second run would have its script)
    client, model, cid, run_id = small_turn(
        make_client, project_dir, executor, text("I leave the test as it is.")
    )
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert len(executor.started) == 1, executor.started
    calls = model.calls_of["Lead"]
    assert len(calls) == 4, said(calls)
    assert "1 failed" in str(calls[3][-1]["content"]), said(calls)
    assert f"Tests failed: {PYTEST} (guessed) - 1 failed, 3 passed" in texts(snap), texts(snap)


@pytest.mark.no_po
@pytest.mark.parametrize("then", [[], [spawn("Coder", "fix the failing test", "c2")]])
def test_a_recipe_left_at_a_step_is_not_checked_half_done(
    make_client, wait_run, project_dir, monkeypatch, then
):
    # Review of T2: an answer that leaves a recipe at its next step ("or say why it cannot run")
    # stands with no extra check - KOLONİ's fix round on half its work went to an Orchestrator its
    # step kept from fixing it (no Coder there), told the step again, then to a stronger model.
    # The row stops as it did, its work kept in its copy. (`then`: what the Lead would do next -
    # never asked.)
    guess(monkeypatch, PYTEST)
    executor = ScriptedExecutor([FAILED] * 4)
    client, model = make_client(
        {
            "Lead": [
                spawn("Coder", "build"),
                text("I stop here"),
                text("no tester"),
                *then,
                text("leave it"),
            ],
            "Coder": [step(write("a.py", "def f():\n    return 1\n")), text("built")],
        },
        executor=executor,
    )
    recipe = made(
        client,
        "Build then test",
        graph(
            [
                part("build", "Build it", {"role": "Coder"}),
                part("test", "Test it", {"role": "Tester"}),
            ],
            [("start", "build"), ("build", "test"), ("test", "end")],
        ),
    )
    own_test(client, project_dir)
    cid, run_id = begin(
        client,
        project_dir,
        mode="full_auto",
        spawn_approval="never",
        teams_mode="manual",
        teams=[{"team_id": teams_of(client)["Web app"]["id"], "recipe_id": recipe["id"]}],
    )
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    calls = model.calls_of["Lead"]
    assert len(calls) == 3 and "next step is Test it" in calls[2][-1]["content"], said(calls)
    assert executor.started == [] and texts(snap) == [
        "Tests not run: the turn ended before KOLONİ's check"
    ], texts(snap)
    assert (row(snap)["status"], row(snap)["why"]) == (
        "stopped",
        "rule broken: Test it was not done",
    ), row(snap)
    assert [one["status"] for one in snap["merges"]] == ["kept"], snap["merges"]


@pytest.mark.no_po
def test_a_stored_recipe_that_no_longer_reads_fails_no_turn(
    make_client, wait_run, project_dir, caplog
):
    # Review of T2: "internal error: 1 validation error for RecipeGraph" ended every Orchestrator
    # decides turn - it is left out of pick_teams, and said once in the log.
    from app.db.models import Recipe

    client, model = make_client([text("hello"), text("hello again")])
    with client.app.state.session_factory() as session:
        session.add(Recipe(name="Old one", graph={"version": 1, "steps": [], "gone": 1}))
        session.commit()
    for _turn in range(2):
        cid, run_id = begin(client, project_dir, teams_mode="lead")
        snap = wait_run(client, cid, run_id)
        assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    recipes = picks(model.tool_args[0])["parameters"]["properties"]["teams"]["items"]
    assert "Old one" not in recipes["properties"]["recipe"]["enum"]
    assert "Feature" in recipes["properties"]["recipe"]["enum"]
    assert caplog.text.count("'Old one' is not offered to pick_teams") == 1, caplog.text
