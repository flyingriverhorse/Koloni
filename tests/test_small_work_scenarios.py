"""Tarif maliyeti T2 (the user's decision 4, 23 Nov): under Orchestrator decides, a small change -
a few lines in one or two files - needs no team: the Orchestrator makes it itself or with one
agent, says in one line why no team, and KOLONİ's end checks run all the same. `pick_teams` lists
each recipe with how many agents its run opens, so a pick weighs the cost. A fake model and a
scripted executor."""

import pytest

from app.tools import pick_schema
from tests.fakes import ScriptedExecutor
from tests.test_chat_flow import text
from tests.test_claim_scenarios import write
from tests.test_proof_end_scenarios import guess, texts
from tests.test_recipe_proof_scenarios import PASSED, PYTEST
from tests.test_spawn import begin, spawn, step

SMALL = "A small change - a few lines in one or two files - needs no team"


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
        [(Team, ["Coder"])], [("Feature", Counted(6, 16)), ("Spec", Counted(2, 2)), ("X", None)]
    )["function"]
    assert SMALL in said["description"]
    assert said["description"].endswith("- Feature: 6-16 agents\n- Spec: 2 agents")
    recipe = said["parameters"]["properties"]["teams"]["items"]["properties"]["recipe"]
    assert recipe["enum"] == ["Feature", "Spec", "X"]  # (one not counted is still a recipe)


@pytest.mark.no_po  # (the Assistant PO's request would be one more call)
def test_a_small_change_under_orchestrator_decides_picks_no_team_and_is_checked(
    make_client, wait_run, project_dir, monkeypatch
):
    guess(monkeypatch, PYTEST)
    client, model = make_client(
        {
            "Lead": [
                spawn("Coder", "make greet say Hello", "c1"),
                text("done"),
                text("No team: a two-line change in one file."),
            ],
            "Coder": [step(write("greet.py", "def greet():\n    return 'Hello'\n")), text("done")],
        },
        executor=ScriptedExecutor([PASSED]),
    )
    cid, run_id = begin(
        client, project_dir, mode="full_auto", spawn_approval="never", teams_mode="lead"
    )
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    # (Told so, with the ready recipes' counts - the migrated ones: Feature's is T1's to keep.)
    told = picks(model.tool_args[0])["description"]
    assert SMALL in told and "- Feature: 6-16 agents" in told, told
    calls = model.calls_of["Lead"]
    assert len(calls) == 3 and "say in one line why no team works on it" in calls[2][-1]["content"]
    assert snap["conversation"]["teams"] == []
    assert [a["role_name"] for a in snap["agents"] if a["depth"] == 1] == ["Coder"]
    answers = [m["content"] for m in snap["messages"] if m["role"] == "assistant" and m["content"]]
    assert answers[-1] == "No team: a two-line change in one file.", answers
    assert f"Tests passed: {PYTEST} (guessed) - 4 passed" in texts(snap), texts(snap)
