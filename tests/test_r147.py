"""K-r147: REA's R147 - the Orchestrator's steps for the recipe it runs."""

from dataclasses import replace

from app.agent.words import STEPS_STOP
from tests.test_chat_flow import text
from tests.test_chat_teams_scenarios import teams_of
from tests.test_claim_scenarios import write
from tests.test_lead_decides import says
from tests.test_parallel import until
from tests.test_recipe_run_scenarios import READY, answer, asked, manual, one_step, row
from tests.test_spawn import call, spawn, step


def test_the_lead_running_its_recipe_has_its_steps_and_more_for_each_ask_for_changes(
        make_client, wait_run, project_dir):
    # A one-team chat: the Lead (depth 0) runs the recipe itself. 3 + 4 for the one-step recipe
    # holds its first round (6 steps), and 3 + 4 x 2 once sent back its second (10 steps).
    looks = lambda at: [step(call("list_dir", {"path": "."}, f"{at}{n}")) for n in range(3)]  # noqa: E731
    client, _model = make_client({
        "Lead": [*looks("a"), step(call("list_dir", {"path": "."}, "a3")), spawn("Coder", "build", "c1"),
                 *looks("b"), spawn("Coder", "build again", "c2"), text("all done")],
        # (K-r146: a recipe that changed nothing asks nobody to take it in - so each writes)
        "Coder": [step(write("a.py", "a\n")), text("built")],
        "Coder 2": [step(write("a.py", "b\n", id="w2")), text("built again")],
    })
    runner = client.app.state.runner
    runner.settings = replace(runner.settings, max_steps=3)
    cid, run_id = manual(client, project_dir, (teams_of(client)["Web app"], one_step(client, "Just build", "Coder")))
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"])
    answer(client, asked(snap), "Ask for changes")
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"] and len(
        [a for a in s["agents"] if a["name"].startswith("Coder")]) == 2)
    answer(client, asked(snap), "Take in")
    snap = wait_run(client, cid, run_id)
    lead = next(a for a in snap["agents"] if a["depth"] == 0)
    assert lead["status"] == "completed", lead["error"]
    assert row(snap)["status"] == "in"


def test_an_agent_reopened_after_a_stop_at_its_step_limit_is_said_to_have_stopped_there(
        make_client, wait_run, project_dir):
    # R148 (live): the Lead opened such a lead again three times, the same task each time.
    from tests.test_topic_scenarios import FIRST, GO_ON, SECOND, SPAWN_CODER, calls_of, setup, turn

    looks = [step(call("list_dir", {"path": "."}, f"r{n}")) for n in range(3)]
    client, _model, _pid, cid = setup(make_client, project_dir, {
        # (B-397: at Full auto the Lead answers the Coder's step-limit card - here, Stop here)
        "Lead": [SPAWN_CODER, says(STEPS_STOP, "a smaller task next time"), text("it stopped"),
                 GO_ON, text("done")],
        "Coder": [*looks, text("smaller part done")]})
    runner = client.app.state.runner
    runner.settings = replace(runner.settings, max_steps=2)
    snap, first = turn(client, wait_run, cid, FIRST)
    assert next(a for a in snap["agents"] if a["name"] == "Coder")["error"] == "step_limit"
    snap, second = turn(client, wait_run, cid, SECOND)
    ((_status, said),) = calls_of(snap, second["id"], "message_agent")
    assert said.startswith("Coder failed last time at its step limit (2 steps) - give it a smaller "
                           "task or more steps, rather than the same task again.")
