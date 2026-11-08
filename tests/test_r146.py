"""K-r146: REA's R146 - once a recipe has ended in a turn, the Orchestrator may open an agent
outside it for a small follow-up (a finding the recipe left)."""

from tests.test_chat_flow import text
from tests.test_chat_teams_scenarios import teams_of
from tests.test_claim_scenarios import write
from tests.test_parallel import until
from tests.test_recipe_checks_scenarios import build_review_ship
from tests.test_recipe_run_scenarios import FOUND, READY, answer, asked, by_call, manual, row
from tests.test_spawn import call, spawn, step

SCRIPTS = {
    "Coder": [step(write("greet.py", "print('Helo')\n")), text("built")],
    "Coder 2": [text("still Helo")],
    "Coder 3": [step(write("greet.py", "print('Hello')\n")), text("fixed")],
    "Reviewer": [text(FOUND)], "Reviewer 2": [text(FOUND)],
}
RECIPE = [spawn("Coder", "build", "c1"), spawn("Reviewer", "review", "r1"),
          step(call("spawn_agent", {"role": "Coder", "task": "fix", "findings_from": "Reviewer"}, "c2")),
          spawn("Reviewer", "review", "r2")]


def ends_with_findings(client, project_dir, lead):
    client, _model = client({"Lead": [*RECIPE, *lead, text("done")], **SCRIPTS})
    cid, run_id = manual(client, project_dir, (teams_of(client)["Web app"], build_review_ship(client)))
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"])
    return client, cid, run_id, asked(snap)


def test_after_take_in_the_lead_opens_a_coder_outside_the_ended_recipe(make_client, wait_run, project_dir):
    # R146 (live): "the recipe has ended and Coder is not offered in this step" - Ask for changes
    # was the only way to a one-line finding.
    client, cid, run_id, card = ends_with_findings(
        make_client, project_dir, [spawn("Coder", "fix the finding left in greet.py", "c3")])
    answer(client, card, "Take in")
    snap = wait_run(client, cid, run_id)
    assert row(snap)["status"] == "in"
    status, said = by_call(snap)[-1]
    assert status == "succeeded" and "not in the project" not in said
    # (its work went in as any agent's: no kept copy beside a recipe)
    assert (project_dir / "greet.py").read_text() == "print('Hello')\n"
    assert [m["status"] for m in snap["merges"]] == ["applied", "applied"]


def test_fix_the_findings_takes_the_work_in_and_tells_the_lead_to_open_a_coder(
        make_client, wait_run, project_dir):
    client, cid, run_id, card = ends_with_findings(make_client, project_dir, [step(call(
        "spawn_agent", {"role": "Coder", "task": "fix them", "findings_from": "Reviewer 2"}, "c3"))])
    assert card["options"] == ["Take in", "Fix the findings", "Ask for changes"]
    answer(client, card, "Fix the findings")
    snap = wait_run(client, cid, run_id)
    assert row(snap)["status"] == "in"
    told = by_call(snap)[-2][1]
    assert "The user took the work in." in told
    assert "open Coder now with spawn_agent and findings_from Reviewer 2" in told
    assert by_call(snap)[-1][0] == "succeeded"
    assert "Findings Reviewer 2 handed on" in {a["name"]: a["task"] for a in snap["agents"]}["Coder 3"]
    assert (project_dir / "greet.py").read_text() == "print('Hello')\n"


def test_a_running_recipe_still_refuses_a_role_its_step_does_not_name(make_client, wait_run, project_dir):
    # (Only an ended recipe lets one in: while it runs, its step is the door, as before.)
    client, _model = make_client({"Lead": [spawn("Reviewer", "review first", "r0"), *RECIPE, text("done")],
                                  **SCRIPTS})
    cid, run_id = manual(client, project_dir, (teams_of(client)["Web app"], build_review_ship(client)))
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"])
    assert "the Reviewer role is not one of its roles now" in by_call(snap)[0][1]
    answer(client, asked(snap), "Take in")
    wait_run(client, cid, run_id)
