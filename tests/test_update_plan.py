"""Task 5 (0.1.11): update_plan - the API Orchestrator's plan shown to the user as its own words
(`agent.live`, as a CLI's plan is): each step masked and cut, at most 30, gone with the turn;
offered to the Orchestrator of an API model only, never to its agents."""

import time

from app.tools_at_work import PLAN_SHOWN
from tests.conftest import Gate, scaled
from tests.test_background_spawn import tool_result
from tests.test_chat_flow import text
from tests.test_claim_scenarios import setup
from tests.test_spawn import call, step

SECRET = "sk-ant-api03-" + "y" * 40


def names(tools):
    return [t["function"]["name"] for t in tools or []]


def watched(client):
    """The live events the bus sends, as they are sent."""
    sent, emit = [], client.app.state.bus.emit_transient

    def watch(conversation_id, kind, payload):
        if kind == "agent.live":
            sent.append(payload)
        return emit(conversation_id, kind, payload)

    client.app.state.bus.emit_transient = watch
    return sent


def test_the_orchestrators_plan_is_shown_masked_cut_and_gone_with_the_turn(
    make_client, wait_run, project_dir
):
    held = Gate()
    steps = [
        {"step": f"Step {n}", "status": "completed" if n < 2 else "pending"} for n in range(31)
    ]
    steps[1] = {"step": f"Read the key {SECRET} " + "x" * 300, "status": "completed"}
    steps[2] = {"step": "Build it", "status": "inProgress"}
    steps[3] = {"step": "Re​ad‮ it", "status": "pending"}  # (nothing unseen kept)
    client, model, cid, run_id = setup(
        make_client,
        project_dir,
        {
            "Lead": [
                step(call("update_plan", {"steps": steps}, "p1")),
                held.step(text("done")),
            ],
        },
    )
    sent = watched(client)
    held.wait_partial()
    deadline = time.monotonic() + scaled(5)
    while not sent and time.monotonic() < deadline:
        time.sleep(0.05)
    late = client.get(f"/api/conversations/{cid}/events", params={"once": True}).text
    assert tool_result(model.calls_of["Lead"][1], "p1") == PLAN_SHOWN.format(k=3, m=30)
    (shown,) = sent
    plan = shown["plan"]
    assert len(plan) == 30  # (31 asked)
    assert plan[0] == {"step": "Step 0", "status": "completed"}
    assert SECRET not in plan[1]["step"] and "***" in plan[1]["step"]
    assert len(plan[1]["step"]) == 200
    assert plan[2] == {"step": "Build it", "status": "inProgress"}
    assert plan[3] == {"step": "Read it", "status": "pending"}
    assert "event: agent.live" in late and "Build it" in late  # (a page opened late sees it)
    held.release()
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    lead = next(a for a in snap["agents"] if a["depth"] == 0)
    assert sent[-1] == {"agent_id": lead["id"], "context": None, "plan": None}  # gone at the end
    assert (
        "agent.live"
        not in client.get(f"/api/conversations/{cid}/events", params={"once": True}).text
    )


def test_update_plan_is_the_api_orchestrators_alone(make_client, wait_run, project_dir):
    client, model, cid, run_id = setup(
        make_client,
        project_dir,
        {
            "Lead": [
                step(call("spawn_agent", {"role": "Coder", "task": "look"}, "s1")),
                step(call("update_plan", {"steps": []}, "p0")),
                text("x"),
            ],
            "Coder": [
                step(call("update_plan", {"steps": [{"step": "a", "status": "pending"}]}, "p1")),
                text("done"),
            ],
        },
    )
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert "only the Orchestrator at its own work" in tool_result(model.calls_of["Coder"][1], "p1")
    assert "steps:" in tool_result(model.calls_of["Lead"][2], "p0")  # (an empty plan: refused)
    offered = [names(tools) for tools in model.tool_args]
    assert sum("update_plan" in one for one in offered) == len(model.calls_of["Lead"])
