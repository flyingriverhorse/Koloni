"""Task 8 (0.1.11): the API Orchestrator's run_command in the background - answered at once, run
as its own call runs it (list, judge, cards), read with command_output, stopped with stop_command
or the turn's Stop, held to the chat's spawn_max_parallel; at its end KOLONİ's note wakes it and
its call's result is what it printed."""

import asyncio
import json
from types import SimpleNamespace

from sqlalchemy import select

from app.agent.words import COMMAND_ENDED, COMMAND_LATER
from app.db.models import ToolCall
from app.model_client import StepResult, ToolCallRequest
from tests.conftest import Gate
from tests.fakes import Script, ScriptedExecutor
from tests.test_background_spawn import said_in, tool_result
from tests.test_chat_flow import text
from tests.test_parallel import statuses, until
from tests.test_spawn import begin, call, step

ORIGIN = {"Origin": "http://127.0.0.1:8790"}


def later(command, id="k1"):
    return step(call("run_command", {"command": command, "background": True}, id))


def row_id(client, provider_id="k1"):
    with client.app.state.session_factory() as session:
        return session.scalar(select(ToolCall.id).where(ToolCall.provider_call_id == provider_id))


def executor_started(client):
    """Whether a command runs and has printed something."""
    return any(said for _cid, said in client.app.state.runner.commands._live.values())


def on(client, tool, id="k1", **more):
    """A step that calls `tool` on the background command `id` started - its id read as it runs."""

    async def asked(on_delta):
        while not executor_started(client):  # (once it runs: a stand-in starts at once)
            await asyncio.sleep(0.01)
        given = json.dumps({"id": row_id(client, id), **more})
        return StepResult("", [ToolCallRequest(f"{tool}-{id}", tool, given)], 1, 1)

    return asked


def test_a_background_command_answers_at_once_and_its_end_wakes_the_orchestrator(
    make_client, wait_run, project_dir
):
    gate = Gate()
    executor = ScriptedExecutor([Script(["building...\n", "built\n"], hold=gate)])
    client, model = make_client(
        {"Lead": [later("make build"), text("started it"), text("read it")]}, executor=executor
    )
    cid, run_id = begin(client, project_dir, mode="full_auto")
    snap = until(client, cid, lambda s: statuses(s) == {"Lead": "waiting"} and s["commands"])
    assert snap["commands"][0]["status"] == "running" and snap["runs"][0]["status"] == "running"
    call_id = row_id(client)
    assert tool_result(model.calls_of["Lead"][1], "k1") == COMMAND_LATER.format(id=call_id)
    gate.release()
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    last = model.calls_of["Lead"][-1]
    assert len(model.calls_of["Lead"]) == 3
    assert said_in(last, COMMAND_ENDED.format(id=call_id, status="succeeded")) == 1
    assert "built" in tool_result(last, "k1")  # its call's result is what it printed
    assert snap["commands"][0]["status"] == "exited"


def test_command_output_reads_it_while_it_runs_and_stop_command_stops_it(
    make_client, wait_run, project_dir
):
    gate = Gate()
    executor = ScriptedExecutor([Script(["first line\n"], hold=gate)])
    client, model = make_client({"Lead": []}, executor=executor)
    model.by_agent["Lead"] += [  # (its steps name the command by the id it was given)
        later("make serve"),
        step(call("list_dir", {}, "l1")),  # (it goes on)
        on(client, "command_output"),
        on(client, "stop_command"),
        text("stopped it"),
        text("read its end"),
    ]
    cid, run_id = begin(client, project_dir, mode="full_auto")
    snap = wait_run(client, cid, run_id)
    gate.release()
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    read = tool_result(model.calls_of["Lead"][3], "command_output-k1")
    assert "runs in the background" in read and "first line" in read
    stopped = tool_result(model.calls_of["Lead"][4], "stop_command-k1")
    assert stopped == f"Command {row_id(client)} is stopped."
    assert executor.killed
    assert snap["commands"][0]["status"] in ("killed", "interrupted")


def test_the_turns_stop_kills_a_background_command(make_client, wait_run, project_dir):
    gate = Gate()
    executor = ScriptedExecutor([Script(["working\n"], hold=gate)])
    client, model = make_client(
        {"Lead": [later("make long"), text("started it"), text("never")]}, executor=executor
    )
    cid, run_id = begin(client, project_dir, mode="full_auto")
    until(client, cid, lambda s: statuses(s) == {"Lead": "waiting"} and s["commands"])
    assert client.post(f"/api/runs/{run_id}/cancel").status_code == 202
    snap = wait_run(client, cid, run_id)
    gate.release()
    assert snap["runs"][0]["status"] == "cancelled"
    assert executor.killed and snap["commands"][0]["status"] in ("killed", "interrupted")
    assert len(model.calls_of["Lead"]) == 2  # no step after the Stop


def test_background_commands_are_held_to_the_chats_ceiling(make_client, wait_run, project_dir):
    gate = Gate()
    executor = ScriptedExecutor([Script(["a\n"], hold=gate), Script(["b\n"])])
    client, model = make_client(
        {"Lead": [later("make a", "k1"), later("make b", "k2"), text("one runs"), text("ended")]},
        executor=executor,
    )
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_max_parallel=1)
    until(client, cid, lambda s: len(model.calls_of["Lead"]) >= 3)
    refused = tool_result(model.calls_of["Lead"][2], "k2")
    assert refused.startswith("error: 1 of your commands run in the background already")
    assert row_id(client, "k1") in refused  # (the one at work named)
    gate.release()
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert [one[0] for one in executor.started] == ["make a"]


def test_its_card_waits_while_the_orchestrator_goes_on_and_a_no_is_its_note(
    make_client, wait_run, project_dir
):
    executor = ScriptedExecutor([Script(["x\n"])])
    client, model = make_client(
        {"Lead": [later("make deploy"), text("asked for it"), text("heard the no")]},
        executor=executor,
    )
    cid, run_id = begin(client, project_dir, mode="ask")
    snap = until(client, cid, lambda s: [c["status"] for c in s["commands"]] == ["proposed"])
    until(client, cid, lambda s: len(model.calls_of["Lead"]) >= 2)  # it went on meanwhile
    (asked,) = snap["commands"]
    assert client.post(f"/api/commands/{asked['id']}/reject", headers=ORIGIN).status_code == 200
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert executor.started == []
    assert said_in(model.calls_of["Lead"][-1], "ended (denied)") == 1


def test_background_is_offered_to_the_api_orchestrator_at_its_own_work_only(
    make_client, wait_run, project_dir
):
    client, model = make_client({"Lead": [text("hi")]})
    cid, run_id = begin(client, project_dir, mode="full_auto")
    wait_run(client, cid, run_id)
    run = next(t for t in model.tool_args[0] if t["function"]["name"] == "run_command")
    assert "background" in run["function"]["parameters"]["properties"]
    runner = client.app.state.runner
    asked = SimpleNamespace(name="run_command")
    lead = SimpleNamespace(
        depth=0,
        answering=False,
        discussion=False,
        model=SimpleNamespace(),
        run_id=run_id,
        tools=("run_command",),
        agent_id="x",
        role="Lead",
    )
    assert runner._command_offered_later(lead, asked, {"background": True})
    assert not runner._command_offered_later(
        lead, asked, {"background": True, "keep_running": True}
    )
    for no in (
        {"depth": 1},
        {"answering": True},
        {"model": SimpleNamespace(native=True)},
        {"tools": ()},
    ):
        assert not runner._command_offered_later(
            SimpleNamespace(**{**vars(lead), **no}), asked, {"background": True}
        )
