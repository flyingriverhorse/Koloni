"""Slice 33a's acceptance set: the track record and the signs of being stuck. Written before
the code.

Nothing here is a score. The record is what was measured of the agents that ran, by role and
model, and what is not on record is unknown. A sign is a count: the same call failing the same
way, or a reading call returning the same, since anything last changed. The agent is told, the
one who opened it is told, the user sees it - and where somebody is watching nothing is stopped
for it. Only in a turn nobody watches does the fifth time end the agent's work.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.schemas import AgentOut

if "sign" not in AgentOut.model_fields:  # written before the code
    pytest.skip("slice 33a is not built yet", allow_module_level=True)

from app.model_client import ModelUnavailable, StepResult  # noqa: E402
from tests.fakes import Script, ScriptedExecutor  # noqa: E402
from tests.test_agent_commands import cmd  # noqa: E402
from tests.test_agent_writes import write  # noqa: E402
from tests.test_chat_flow import text  # noqa: E402
from tests.test_spawn import begin, call, step  # noqa: E402
from tests.test_trigger_scenarios import finished, run_now, setup, trigger  # noqa: E402

SAME_FAILURE = "failed {n} times with the same arguments and the same error"
SAME_RESULT = "returned the same result {n} times with the same arguments"


def miss(id, path="missing.txt"):
    return step(call("read_file", {"path": path}, id))


def look(id, path="hello.py"):
    return step(call("read_file", {"path": path}, id))


def spawn(id, role="Coder"):
    return step(call("spawn_agent", {"role": role, "task": "look into it"}, id))


def told(model, name="Lead"):
    """What each of an agent's tool calls returned, as its model was last given them."""
    return [m["content"] for m in model.calls_of[name][-1] if m["role"] == "tool"]


def agent(snap, role="Lead"):
    return next(a for a in snap["agents"] if a["role_name"] == role)


def watched(make_client, wait_run, project_dir, steps, **more):
    """One turn somebody is watching, with nothing asked on the way: (model, snapshot)."""
    client, model = make_client(steps, **more)
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    return model, wait_run(client, cid, run_id)


# --- signs of being stuck ----------------------------------------------------------------------


def test_the_third_time_a_call_fails_the_same_way_the_agent_is_told_and_it_shows(
    make_client, wait_run, project_dir
):
    # (a sub-agent: B-413's loop guard asks about the Orchestrator at the fifth)
    model, snap = watched(make_client, wait_run, project_dir, {
        "Lead": [spawn("s1"), text("done")],
        "Coder": [*(miss(str(n)) for n in range(6)), text("I give up.")]})
    # somebody is watching: nothing is stopped for it, however often
    assert snap["runs"][0]["status"] == "completed" and len(model.calls_of["Coder"]) == 7
    first, second, third, *_more, sixth = told(model, "Coder")
    assert "times" not in first and "times" not in second
    # what the call returned is there as it was, and after it what was counted - a fact
    assert third.startswith("error: 'missing.txt' does not exist")
    assert SAME_FAILURE.format(n=3) in third and SAME_FAILURE.format(n=6) in sixth
    sign = agent(snap, "Coder")["sign"]
    assert (sign["kind"], sign["count"]) == ("same_failure", 6)
    assert SAME_FAILURE.format(n=6) in sign["text"]


def test_a_command_that_fails_the_same_way_counts_whatever_the_clock_said(
    make_client, wait_run, project_dir
):
    said = ["12:00:01 FAILED test_x in 0.31s (pid 4411)\n",
            "12:00:09 FAILED test_x in 0.29s (pid 4532)\n",
            "12:01:44 FAILED test_x in 0.30s (pid 4610)\n"]
    model, snap = watched(
        make_client, wait_run, project_dir,
        {"Lead": [*(cmd("pytest -q", id=f"k{n}") for n in range(3)), text("Still red.")]},
        executor=ScriptedExecutor([Script([out], exit_code=1) for out in said]))
    assert SAME_FAILURE.format(n=3) in told(model)[2]
    assert agent(snap)["sign"]["kind"] == "same_failure"


@pytest.mark.parametrize("why, steps, scripts", [
    ("other commands, each failing", [
        cmd("pytest -q tests/a.py", id="k1"), cmd("pytest -q tests/b.py", id="k2"),
        cmd("ruff check .", id="k3")], ["1 failed\n"] * 3),
    ("the same command failing another way each time", [
        cmd("pytest -q", id="k1"), cmd("pytest -q", id="k2"), cmd("pytest -q", id="k3")],
     ["FAILED test_x\n", "FAILED test_y\n", "FAILED test_z\n"]),
    ("other arguments", [miss("a", "one.txt"), miss("b", "two.txt"), miss("c", "three.txt")], []),
    ("a change that landed in between", [
        miss("a"), miss("b"), write("notes.txt", "a note\n", id="w"), miss("c"), miss("d")], []),
])
def test_what_is_not_a_sign(make_client, wait_run, project_dir, why, steps, scripts):
    model, snap = watched(
        make_client, wait_run, project_dir, {"Lead": [*steps, text("done")]},
        executor=ScriptedExecutor([Script([out], exit_code=1) for out in scripts]))
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert agent(snap)["sign"] is None, why
    assert not any("times" in result for result in told(model)), why


def test_what_was_read_in_between_does_not_start_the_count_again(
    make_client, wait_run, project_dir
):
    # (two calls, back and forth: the one that fails is counted all the same)
    model, snap = watched(make_client, wait_run, project_dir, {
        "Lead": [miss("a"), look("b"), miss("c"), look("d"), miss("e"), text("done")]})
    results = told(model)
    assert SAME_FAILURE.format(n=3) in results[4]
    assert not any("times" in results[n] for n in (0, 1, 2, 3))
    assert (agent(snap)["sign"]["kind"], agent(snap)["sign"]["count"]) == ("same_failure", 3)


def test_the_third_time_a_reading_call_returns_the_same_the_agent_is_told(
    make_client, wait_run, project_dir
):
    model, snap = watched(make_client, wait_run, project_dir, {
        "Lead": [look("a"), look("b"), look("c"), text("It prints hi.")]})
    first, second, third = told(model)
    assert "times" not in first and "times" not in second
    assert "print('hi')" in third and SAME_RESULT.format(n=3) in third
    sign = agent(snap)["sign"]
    assert (sign["kind"], sign["count"]) == ("same_result", 3)


def test_the_one_who_opened_a_sub_agent_is_told_what_was_counted_of_it(
    make_client, wait_run, project_dir
):
    model, snap = watched(make_client, wait_run, project_dir, {
        "Lead": [spawn("s1"), text("It was not found.")],
        "Coder": [miss("a"), miss("b"), miss("c"), text("I could not find it.")]})
    (result,) = told(model)
    assert "I could not find it." in result and SAME_FAILURE.format(n=3) in result
    assert agent(snap, "Coder")["sign"]["count"] == 3
    assert agent(snap)["sign"] is None            # it is the sub-agent's, not the lead's


def test_in_a_turn_nobody_watches_the_fifth_time_ends_the_agents_work_and_says_why(
    make_client, wait_run, project_dir
):
    client, model, pid, cid = setup(make_client, project_dir, {
        "Lead": [*(miss(str(n)) for n in range(8)), text("never said")]})
    run_id = run_now(client, trigger(client, pid, cid)["id"])
    snap = finished(client, wait_run, cid, run_id)
    run = next(r for r in snap["runs"] if r["id"] == run_id)
    assert run["status"] == "failed" and SAME_FAILURE.format(n=5) in run["error"]
    assert len(model.calls_of["Lead"]) == 5        # no sixth step is taken
    assert agent(snap)["sign"]["count"] == 5


# --- the track record --------------------------------------------------------------------------


def worked(make_client, wait_run, project_dir):
    """A turn in which the lead wrote a file and opened three Coders: two finished, the
    third's model failed."""
    client, model = make_client({
        "Lead": [write("notes.txt", "a note\n", id="w"), spawn("s1"), spawn("s2"), spawn("s3"),
                 text("Two of three."),
                 text("And the second turn.")],
        "Coder": [look("a"), text("done")],
        "Coder 2": [text("done")],
        "Coder 3": [ModelUnavailable("the model server is down")],
    })
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    return client, model, cid, snap


def record(client, **asked):
    answer = client.get("/api/record", params=asked)
    assert answer.status_code == 200, answer.text
    return {row["role_name"]: row for row in answer.json()["rows"]}


def test_the_record_is_what_was_measured_by_role_and_model(make_client, wait_run, project_dir):
    client, _model, _cid, snap = worked(make_client, wait_run, project_dir)
    rows = record(client)
    lead, coder = rows["Lead"], rows["Coder"]
    assert (coder["agents"], coder["model_id"]) == (3, agent(snap, "Coder")["model_id"])
    assert coder["ended"] == {"done": 2, "failed": 1, "stopped_by_koloni": 0,
                              "stopped_by_user": 0, "interrupted": 0}
    assert (lead["agents"], lead["ended"]["done"]) == (1, 1)
    # an agent's steps, and what its model said it sent and wrote: the middle one of the row
    # (the lead: five steps that sent 1 + 5 + 5 + 5 + 5 and wrote 1 + 2 + 2 + 2 + 3)
    assert (lead["steps"], lead["input_tokens"], lead["output_tokens"]) == (5, 21, 10)
    assert lead["seconds"] is not None and lead["seconds"] >= 0
    # of the changes it made, how many were taken
    assert lead["changes"] == {"taken": 1, "rejected": 0}
    assert coder["changes"] == {"taken": 0, "rejected": 0}
    # another time is another record
    later = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    assert record(client, since=later) == {}


def test_what_no_model_reported_is_unknown_in_the_record_too(make_client, wait_run, project_dir):
    client, model = make_client({"Lead": [StepResult("hello", [], None, None)]})
    cid, run_id = begin(client, project_dir, mode="full_auto")
    wait_run(client, cid, run_id)
    lead = record(client)["Lead"]
    assert (lead["agents"], lead["steps"]) == (1, 1)
    assert lead["input_tokens"] is None and lead["output_tokens"] is None


def test_the_lead_is_given_the_record_as_it_stood_when_the_turn_began(
    make_client, wait_run, project_dir
):
    client, model, cid, _snap = worked(make_client, wait_run, project_dir)
    first_turn = [steps[0]["content"] for steps in model.calls_of["Lead"]]
    # nothing of it yet - and not in the middle of the turn either, when three had ended:
    # what a turn's steps begin with stays the same from its first step to its last
    assert len(first_turn) == 5 and len(set(first_turn)) == 1
    assert "ran in the last 30 days" not in first_turn[0]

    posted = client.post(f"/api/conversations/{cid}/messages", json={"content": "and now?"})
    wait_run(client, cid, posted.json()["run"]["id"])
    given = model.calls_of["Lead"][-1][0]["content"]
    # a fact and no more: who, on what, how many, how they ended
    line = next(line for line in given.splitlines() if "ran in the last 30 days" in line)
    assert "Coder on " in line and line.rstrip().endswith(
        "3 ran in the last 30 days - 2 done, 1 failed.")
    # one run says too little: the lead's own single turn is not among them
    assert given.count("ran in the last 30 days") == 1


def test_an_agent_says_when_it_last_did_anything(make_client, wait_run, project_dir):
    _model, snap = watched(make_client, wait_run, project_dir, {
        "Lead": [look("a"), text("done")]})
    lead = agent(snap)
    assert lead["last_event_at"] and lead["last_event_at"] >= lead["started_at"]
