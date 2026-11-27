"""D3 (0.1.11): one agent stopped - by the user from its box (`POST /api/agents/{id}/stop`) or by
the Orchestrator that opened it (`stop_agent`): its work so far kept for the user's Take in,
nothing of it in the project, its cards closed, the rest of the turn going on."""

from app.agent.words import STOP_DONE, USER_STOPPED, YOU_STOPPED
from app.db.models import Agent, ToolCall
from tests.conftest import Gate
from tests.test_agent_commands import cmd
from tests.test_background_spawn import bg, said_in, tool_result
from tests.test_chat_flow import text
from tests.test_claim_scenarios import agent, setup, write
from tests.test_parallel import statuses, until
from tests.test_spawn import call, step

ORIGIN = {"Origin": "http://127.0.0.1:8790"}


def stop(client, agent_id, headers=ORIGIN):
    return client.post(f"/api/agents/{agent_id}/stop", headers=headers)


def lines(snap):
    return [m["content"] for m in snap["messages"] if m["role"] == "koloni"]


def test_the_users_stop_ends_one_background_child_and_keeps_its_copy(
    make_client, wait_run, project_dir
):
    a, b = Gate(), Gate()
    client, model, cid, run_id = setup(
        make_client,
        project_dir,
        {
            "Lead": [
                step(bg("Coder", "do A", "s1"), bg("Tester", "do B", "s2")),
                text("asked"),
                text("Coder stopped"),
                text("all read"),
            ],
            "Coder": [step(write("a.txt", "A")), a.step(text("A done"))],
            "Tester": [b.step(text("B done"))],
        },
    )
    a.wait_partial()
    b.wait_partial()
    snap = until(client, cid, lambda s: statuses(s)["Lead"] == "waiting")
    assert stop(client, agent(snap, "Coder")["id"]).status_code == 204
    snap = until(client, cid, lambda s: statuses(s)["Coder"] == "cancelled")
    assert statuses(snap)["Tester"] == "running"  # the other goes on
    assert not (project_dir / "a.txt").exists()  # nothing reached the project
    assert agent(snap, "Coder")["error"] == "stopped by the user"
    # Its opener wakes for it and reads KOLONİ's word.
    until(client, cid, lambda s: len(model.calls_of["Lead"]) >= 3)
    assert said_in(model.calls_of["Lead"][2], USER_STOPPED.format(name="Coder")) == 1
    b.release()
    a.release()
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert statuses(snap)["Tester"] == "completed"
    (kept,) = snap["merges"]  # kept for Take in
    assert kept["status"] == "kept" and kept["kept_in"]
    assert [f["path"] for f in kept["files"]] == ["a.txt"]
    assert YOU_STOPPED.format(name="Coder") in lines(snap)
    assert len(model.calls_of["Coder"]) == 2  # no step after its Stop
    slots = client.app.state.runner._slots.get(run_id)
    assert slots is None or slots._value == 2


def test_a_waited_child_stops_and_its_card_closes(make_client, wait_run, project_dir):
    client, model, cid, run_id = setup(
        make_client,
        project_dir,
        {
            "Lead": [
                step(call("spawn_agent", {"role": "Coder", "task": "run the tests"}, "s1")),
                text("it was stopped"),
            ],
            "Coder": [cmd("pytest -q"), text("never")],
        },
        permission_mode="ask",
    )
    snap = until(client, cid, lambda s: [c["status"] for c in s["commands"]] == ["proposed"])
    assert stop(client, agent(snap, "Coder")["id"]).status_code == 204
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    (asked,) = snap["commands"]
    assert asked["status"] == "rejected" and statuses(snap)["Coder"] == "cancelled"
    assert not [c for c in snap["commands"] if c["status"] == "proposed"]
    assert snap["runs"][0]["status"] == "completed"
    # Its opener's call came back with it - no try-again advice for a Stop.
    told = tool_result(model.calls_of["Lead"][1], "s1")
    assert "Coder failed: stopped by the user" in told and "another model" not in told
    assert len(model.calls_of["Coder"]) == 1


def test_stop_from_another_origin_is_403(make_client, wait_run, project_dir):
    a = Gate()
    client, model, cid, run_id = setup(
        make_client,
        project_dir,
        {
            "Lead": [step(bg("Coder", "do A", "s1")), text("asked"), text("read")],
            "Coder": [a.step(text("A done"))],
        },
    )
    snap = until(client, cid, lambda s: statuses(s).get("Coder") == "running")
    coder = agent(snap, "Coder")["id"]
    assert stop(client, coder, headers={"Origin": "http://evil.example"}).status_code == 403
    assert client.post(f"/api/agents/{coder}/stop", headers={"Origin": ""}).status_code == 403
    assert stop(client, "nobody").status_code == 404
    a.release()
    snap = wait_run(client, cid, run_id)
    assert statuses(snap)["Coder"] == "completed"
    assert stop(client, coder).status_code == 409  # its work is over


def test_stop_agent_only_its_own(make_client, wait_run, project_dir):
    gate = Gate()
    client, model, cid, run_id = setup(
        make_client,
        project_dir,
        {
            "Lead": [
                gate.step(
                    step(
                        call("stop_agent", {"name": "Reviewer"}, "x1"),
                        call("stop_agent", {"name": "Helper"}, "x2"),
                        call("stop_agent", {"name": "Writer"}, "x3"),
                        call("stop_agent", {"name": "Nobody"}, "x4"),
                    )
                ),
                text("done"),
            ]
        },
    )
    gate.wait_partial()
    now = client.get(f"/api/conversations/{cid}").json()
    lead, asked = now["agents"][0]["id"], now["messages"][0]["id"]
    with client.app.state.session_factory() as session:

        def opened(name, parent, provider_call_id, depth=1):
            made = ToolCall(
                run_id=run_id,
                agent_id=parent,
                message_id=asked,
                seq=0,
                provider_call_id=provider_call_id,
                name="spawn_agent",
                arguments="{}",
                status="running",
            )
            session.add(made)
            session.flush()
            one = Agent(
                run_id=run_id,
                role_name=name,
                name=name,
                tools=[],
                depth=depth,
                status="completed",
                parent_agent_id=parent,
                tool_call_id=made.id,
            )
            session.add(one)
            session.flush()
            return one.id

        opened("Reviewer", lead, "koloni_proof_review_1")  # KOLONİ's own look
        team_lead = opened("Team lead", lead, "c-t")
        opened("Helper", team_lead, "c-h", depth=2)  # a team lead's own
        opened("Writer", lead, "c-w")  # finished (all are: none holds the turn)
        session.commit()
    gate.release()
    snap = wait_run(client, cid, run_id)
    results = {c["provider_call_id"]: c["result"] for c in snap["tool_calls"]}
    assert results["x1"] == "error: Reviewer is not one you opened in this turn"
    assert results["x2"] == "error: Helper is not one you opened in this turn"
    assert results["x3"] == "error: Writer has finished"
    assert results["x4"] == "error: no agent named Nobody in this turn"


def test_the_orchestrators_stop_agent_stops_its_own(make_client, wait_run, project_dir):
    a, then = Gate(), Gate()
    client, model, cid, run_id = setup(
        make_client,
        project_dir,
        {
            "Lead": [
                step(bg("Coder", "do A", "s1")),
                then.step(step(call("stop_agent", {"name": "Coder"}, "x1"))),
                text("stopped it"),
            ],
            "Coder": [step(write("a.txt", "A")), a.step(text("A done"))],
        },
    )
    a.wait_partial()  # (it wrote a.txt in its copy)
    then.release()
    snap = wait_run(client, cid, run_id)
    a.release()
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert statuses(snap)["Coder"] == "cancelled"
    assert agent(snap, "Coder")["error"] == "stopped by the Orchestrator"
    stopped = next(c for c in snap["tool_calls"] if c["provider_call_id"] == "x1")
    assert stopped["result"] == STOP_DONE.format(name="Coder")
    assert not (project_dir / "a.txt").exists()
    (kept,) = snap["merges"]
    assert kept["status"] == "kept"
    # Not the user's: neither the chat's line nor KOLONİ's word to it.
    assert YOU_STOPPED.format(name="Coder") not in lines(snap)
    assert not any(USER_STOPPED.format(name="Coder") in m["content"] for m in snap["messages"])
    # Offered to the Orchestrator, not to its agents.
    names = [t["function"]["name"] for t in model.tool_args[0]]
    assert "stop_agent" in names


def test_the_turns_stop_still_stops_everything_after_one_stop(make_client, wait_run, project_dir):
    a, b = Gate(), Gate()
    client, model, cid, run_id = setup(
        make_client,
        project_dir,
        {
            "Lead": [
                step(bg("Coder", "do A", "s1"), bg("Coder", "do B", "s2")),
                text("asked"),
                text("never"),
            ],
            "Coder": [step(write("a.txt", "A")), a.step(text("A done"))],
            "Coder 2": [step(write("b.txt", "B")), b.step(text("B done"))],
        },
    )
    a.wait_partial()
    b.wait_partial()
    snap = until(client, cid, lambda s: statuses(s)["Lead"] == "waiting")
    assert stop(client, agent(snap, "Coder")["id"]).status_code == 204
    assert client.post(f"/api/runs/{run_id}/cancel").status_code == 202
    snap = wait_run(client, cid, run_id)
    a.release()
    b.release()
    assert snap["runs"][0]["status"] == "cancelled"
    assert statuses(snap) == {"Lead": "cancelled", "Coder": "cancelled", "Coder 2": "cancelled"}
    assert not (project_dir / "a.txt").exists() and not (project_dir / "b.txt").exists()
    # Each one's half work kept once, for Take in.
    kept = sorted(f["path"] for m in snap["merges"] for f in m["files"])
    assert kept == ["a.txt", "b.txt"], snap["merges"]


def test_tell_to_a_copilot_child_goes_to_the_orchestrator(make_client, wait_run, project_dir):
    a = Gate()
    client, model, cid, run_id = setup(
        make_client,
        project_dir,
        {
            "Lead": [
                step(call("spawn_agent", {"role": "Coder", "task": "do A"}, "s1")),
                text("read"),
            ],
            "Coder": [a.step(text("A done"))],
        },
    )
    snap = until(client, cid, lambda s: statuses(s).get("Coder") == "running")
    coder = agent(snap, "Coder")["id"]
    told = client.post(
        f"/api/agents/{coder}/tell", json={"words": "use blue", "to_lead": True}, headers=ORIGIN
    )
    assert told.status_code == 204
    a.release()
    snap = wait_run(client, cid, run_id)
    note = (
        "KOLONİ: the user's word to you about Coder, which can't hear messages while it works "
        "- their own word: "
    )
    assert said_in(model.calls_of["Lead"][-1], note) == 1
    assert said_in(model.calls_of["Coder"][-1], "use blue") == 0  # never the agent's
