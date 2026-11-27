"""D1 (0.1.11): an API Orchestrator opens a sub-agent in the background - `spawn_agent(background:
true)` - goes on at once, and wakes at each one's end, its report a note; a CLI Orchestrator's
spawn_agent always went on so (K-paralel-spawn) and still waits for all at its end."""

import json
from types import SimpleNamespace

import pytest

from app.agent.spawn_mixin import SPAWN_STARTED
from tests.conftest import Gate
from tests.fakes import Script
from tests.test_agent_commands import cmd
from tests.test_chat_flow import text
from tests.test_judge_scenarios import begin as judged_begin
from tests.test_judge_scenarios import judging  # noqa: F401  (a fixture)
from tests.test_parallel import now_snap, statuses, until
from tests.test_spawn import begin, call, role_id, step

ORIGIN = {"Origin": "http://127.0.0.1:8790"}


def bg(role, task, id):
    return call("spawn_agent", {"role": role, "task": task, "background": True}, id)


def tool_result(messages, call_id):
    return next(m["content"] for m in messages if m.get("tool_call_id") == call_id)


def said_in(messages, words):
    return sum(words in str(m["content"]) for m in messages)


def test_a_background_spawn_is_answered_started_and_its_report_comes_as_a_note(
    make_client, wait_run, project_dir
):
    a = Gate()
    client, model = make_client(
        {
            "Lead": [step(bg("Coder", "do A", "s1")), text("asked"), text("read")],
            "Coder": [a.step(text("A done"))],
        }
    )
    cid, run_id = begin(client, project_dir, mode="full_auto")
    snap = until(client, cid, lambda s: statuses(s) == {"Lead": "waiting", "Coder": "running"})
    assert snap["runs"][0]["status"] == "running"
    # It went on at once: its next step read "started", while the Coder still worked.
    assert tool_result(model.calls_of["Lead"][1], "s1") == SPAWN_STARTED.format(name="Coder")
    a.release()
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    last = model.calls_of["Lead"][-1]
    # Its report once - as the Coder's note, its words as data - and the call still says started.
    assert said_in(last, "A done") == 1
    assert any("Message from Coder (" in str(m["content"]) for m in last)
    assert tool_result(last, "s1") == SPAWN_STARTED.format(name="Coder")
    assert len(model.calls_of["Lead"]) == 3
    assert [m["content"] for m in snap["messages"] if m["role"] == "assistant"][-1] == "read"


def test_each_childs_end_wakes_the_lead_once(make_client, wait_run, project_dir):
    a, b = Gate(), Gate()
    client, model = make_client(
        {
            "Lead": [
                step(bg("Coder", "do A", "s1"), bg("Tester", "do B", "s2")),
                text("both asked"),
                text("B is back"),
                text("A is back"),
            ],
            "Coder": [a.step(text("A done"))],
            "Tester": [b.step(text("B done"))],
        }
    )
    cid, run_id = begin(client, project_dir, mode="full_auto")
    a.wait_partial()
    b.wait_partial()
    until(client, cid, lambda s: statuses(s)["Lead"] == "waiting")
    assert len(model.calls_of["Lead"]) == 2
    b.release()
    until(client, cid, lambda s: statuses(s)["Tester"] == "completed")
    # One step for the Tester's end, then it waits again: the Coder still works.
    snap = until(
        client, cid, lambda s: len(model.calls_of["Lead"]) == 3 and statuses(s)["Lead"] == "waiting"
    )
    assert statuses(snap)["Coder"] == "running" and snap["runs"][0]["status"] == "running"
    assert said_in(model.calls_of["Lead"][2], "B done") == 1
    assert said_in(model.calls_of["Lead"][2], "A done") == 0
    a.release()
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert len(model.calls_of["Lead"]) == 4
    assert said_in(model.calls_of["Lead"][3], "A done") == 1


def test_background_children_obey_the_chats_limits(make_client, wait_run, project_dir):
    a, b = Gate(), Gate()
    client, model = make_client(
        {
            "Lead": [
                step(bg("Coder", "do A", "s1"), bg("Tester", "do B", "s2")),
                step(bg("Reviewer", "do C", "s3")),
                text("asked"),
                text("one back"),
                text("both back"),
            ],
            "Coder": [a.step(text("A done"))],
            "Tester": [b.step(text("B done"))],
        }
    )
    cid, run_id = begin(
        client, project_dir, mode="full_auto", spawn_max_parallel=1, spawn_max_agents=2
    )
    a.wait_partial()
    # One at once (the chat's setting): the Tester waits for a place, the Lead goes on.
    snap = until(client, cid, lambda s: statuses(s).get("Tester") == "queued")
    assert statuses(snap)["Coder"] == "running"
    # A third is over the turn's two: refused as a spawn that waits is.
    until(client, cid, lambda s: len(model.calls_of["Lead"]) >= 3)
    over = tool_result(model.calls_of["Lead"][2], "s3")
    assert over.startswith("error: ") and "2" in over, over
    a.release()
    b.wait_partial()
    b.release()
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert statuses(snap) == {"Lead": "completed", "Coder": "completed", "Tester": "completed"}
    slots = client.app.state.runner._slots.get(run_id)
    assert slots is None or slots._value == 1


def test_lead_steps_count_to_its_role_limit(make_client, wait_run, project_dir):
    gates = [Gate(), Gate(), Gate()]
    client, model = make_client(
        {
            "Lead": [
                step(*(bg(role, "work", f"s{n}") for n, role in enumerate(("Coder", "Tester"))))
            ]
            + [step(bg("Researcher", "look", "s9")), text("asked")]
            + [text(f"read {n}") for n in range(5)],
            "Coder": [gates[0].step(text("A done"))],
            "Tester": [gates[1].step(text("B done"))],
            "Researcher": [gates[2].step(text("C done"))],
        }
    )
    assert (
        client.patch(
            f"/api/roles/{role_id(client, 'Lead')}", json={"max_steps": 4}, headers=ORIGIN
        ).status_code
        == 200
    )
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_max_parallel=3)
    for gate in gates:
        gate.wait_partial()
    until(client, cid, lambda s: statuses(s)["Lead"] == "waiting")
    gates[0].release()
    until(client, cid, lambda s: len(model.calls_of["Lead"]) == 4)  # its last step
    gates[1].release()
    gates[2].release()
    snap = wait_run(client, cid, run_id)
    lead = next(x for x in snap["agents"] if x["name"] == "Lead")
    assert lead["error"] == "stopped at its role's limit of 4 steps", lead["error"]
    assert len(model.calls_of["Lead"]) == 4  # no step past its limit, each end a step
    # Its children were waited for: none was cut by the turn's end.
    assert {statuses(snap)[n] for n in ("Coder", "Tester", "Researcher")} == {"completed"}


def test_stop_ends_background_children_and_no_lead_step_follows(make_client, wait_run, project_dir):
    a = Gate()
    client, model = make_client(
        {
            "Lead": [step(bg("Coder", "do A", "s1")), text("asked"), text("never")],
            "Coder": [a.step(text("A done"))],
        }
    )
    cid, run_id = begin(client, project_dir, mode="full_auto")
    until(client, cid, lambda s: statuses(s) == {"Lead": "waiting", "Coder": "running"})
    assert client.post(f"/api/runs/{run_id}/cancel").status_code == 202
    snap = wait_run(client, cid, run_id)
    a.release()
    assert snap["runs"][0]["status"] == "cancelled"
    assert statuses(snap) == {"Lead": "cancelled", "Coder": "cancelled"}
    assert len(model.calls_of["Lead"]) == 2
    slots = client.app.state.runner._slots.get(run_id)
    assert slots is None or slots._value == 2


def test_a_background_childs_card_reaches_the_user(make_client, wait_run, project_dir):
    client, model = make_client(
        {
            "Lead": [step(bg("Coder", "run the tests", "s1")), text("asked"), text("read")],
            "Coder": [cmd("pytest -q"), text("ran them")],
        }
    )
    cid, run_id = begin(client, project_dir, mode="ask", spawn_approval="never")
    snap = until(client, cid, lambda s: [c["status"] for c in s["commands"]] == ["proposed"])
    # The Lead went on and waits; the Coder's command waits on the user's card meanwhile.
    snap = until(client, cid, lambda s: statuses(s)["Lead"] == "waiting")
    assert statuses(snap)["Coder"] == "waiting"
    (asked,) = snap["commands"]
    assert client.post(f"/api/commands/{asked['id']}/reject", headers=ORIGIN).status_code == 200
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert said_in(model.calls_of["Lead"][-1], "ran them") == 1


@pytest.mark.judge
@pytest.mark.no_po
def test_a_background_childs_command_reaches_the_judge(judging, wait_run, project_dir):
    from tests.test_full_auto_judge import said

    client, _lead, judge, executor = judging(
        {
            "Lead": [step(bg("Coder", "make the CSV", "s1")), text("asked"), text("read")],
            "Coder": [cmd("python gen.py"), text("made it")],
        },
        [said("fine")],
        [Script([])],
    )
    _pid, cid, run_id = judged_begin(client, project_dir, "add a CSV export", check="ask")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    (ran,) = snap["commands"]
    assert ran["status"] == "exited" and executor.started[0][0] == "python gen.py"
    assert (ran["judged"]["kind"], ran["judged"]["verdict"]) == ("risk", "fine")
    assert len(judge.calls) == 1


def test_background_is_offered_to_an_api_lead_only(make_client, wait_run, project_dir):
    client, model = make_client(
        {
            "Lead": [step(bg("Coder", "do A", "s1")), text("asked"), text("read")],
            # A sub-agent asking for it: not its to ask - its spawn waits as ever.
            "Coder": [text("A done")],
        }
    )
    cid, run_id = begin(client, project_dir, mode="full_auto")
    wait_run(client, cid, run_id)

    def spawn_props(tools):
        spawn = next(t for t in tools if t["function"]["name"] == "spawn_agent")
        return spawn["function"]["parameters"]["properties"]

    lead_tools = model.tool_args[0]
    assert "background" in spawn_props(lead_tools)
    assert spawn_props(lead_tools)["background"]["description"].startswith(
        "Optional, true: the agent starts and you go on at once;"
    )
    runner = client.app.state.runner
    lead = SimpleNamespace(
        depth=0, answering=False, discussion=False, model=SimpleNamespace(), run_id=run_id
    )
    assert runner._background_offered(lead)
    for no in (
        replace_ns(lead, depth=1),
        replace_ns(lead, answering=True),
        replace_ns(lead, discussion=True),
        replace_ns(lead, model=SimpleNamespace(native=True)),
        replace_ns(lead, model=SimpleNamespace(session=True)),
    ):
        assert not runner._background_offered(no)
    asked = SimpleNamespace(name="spawn_agent", arguments=json.dumps({"background": True}))
    assert runner._background(lead, asked)
    assert not runner._background(replace_ns(lead, depth=1), asked)
    loose = SimpleNamespace(name="spawn_agent", arguments=json.dumps({"background": "yes"}))
    assert not runner._background(lead, loose)


def replace_ns(ns, **changed):
    return SimpleNamespace(**{**vars(ns), **changed})


def test_a_failed_lead_step_stops_its_background_children(make_client, wait_run, project_dir):
    from app.model_client import ModelUnavailable

    a = Gate()
    client, model = make_client(
        {
            "Lead": [
                step(bg("Coder", "do A", "s1")),
                ModelUnavailable("model server unreachable: refused"),
            ],
            "Coder": [a.step(text("A done"))],
        }
    )
    cid, run_id = begin(client, project_dir, mode="full_auto")
    snap = wait_run(client, cid, run_id)
    a.release()
    assert snap["runs"][0]["status"] == "failed"
    assert statuses(now_snap(client, cid))["Coder"] in ("cancelled", "failed")


def test_a_background_agent_over_before_its_opener_went_on_is_its_calls_answer(
    make_client, wait_run, project_dir
):
    # (One that never waits, as a stand-in can be: answered with its report, no note to wait for.)
    client, model = make_client(
        {"Lead": [step(bg("Coder", "do A", "s1")), text("read")], "Coder": [text("A done")]}
    )
    cid, run_id = begin(client, project_dir, mode="full_auto")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert "A done" in tool_result(model.calls_of["Lead"][1], "s1")
    assert len(model.calls_of["Lead"]) == 2
