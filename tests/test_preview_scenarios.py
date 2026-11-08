"""Slice 42b's acceptance set, the backend's part: a command that keeps running, and the page it
serves shown beside the chat. Written before the code.

`run_command` with `keep_running: true` starts the command and answers at once - its id, the
last lines it printed, and the address it serves on, if it said one - while the command goes on.
Only an address on this machine is taken, and never KOLONİ's own port nor a model server's. It is
asked for as any command is (the card says it keeps running), at most three keep running in a
conversation, Stop ends one, and one left running when KOLONİ stopped is not taken for running.

Contract: `CommandOut.keep_running` (bool) and `CommandOut.preview_url` (str | None);
`POST /api/commands/{id}/stop` from the app's own page.
"""

import json
import time

import pytest

from app.schemas import CommandOut

if "keep_running" not in CommandOut.model_fields:
    pytest.skip("slice 42b is not built yet", allow_module_level=True)  # written before the code

from app.agent import recover_interrupted  # noqa: E402
from app.db.models import (  # noqa: E402
    Agent,
    Command,
    Conversation,
    Message,
    Project,
    Run,
    ToolCall,
)
from app.db.session import make_engine, make_session_factory, upgrade_db  # noqa: E402
from app.model_client import StepResult, ToolCallRequest  # noqa: E402
from tests.fakes import Script, ScriptedExecutor  # noqa: E402
from tests.test_agent_writes import wait_status  # noqa: E402
from tests.test_chat_flow import start, start_in_mode, text  # noqa: E402

ORIGIN = "http://127.0.0.1:8790"


def serve(command="npm run dev", id="k1"):
    args = json.dumps({"command": command, "keep_running": True})
    return StepResult("", [ToolCallRequest(id, "run_command", args)], 1, 1)


def commands(client, cid):
    return client.get(f"/api/conversations/{cid}").json()["commands"]


def until(check, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not (found := check()):
        assert time.monotonic() < deadline, "not in time"
        time.sleep(0.02)
    return found


def test_a_server_keeps_running_after_the_tool_answers_and_its_address_is_taken(
    make_client, wait_run, project_dir, gate
):
    executor = ScriptedExecutor(
        [Script(["  VITE ready\n  Local: http://localhost:5173/\n"], hold=gate)]
    )
    client, model = make_client([serve(), text("It is up.")], executor=executor)
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    snap = wait_run(client, cid, run_id)  # the turn ends; the server does not
    (command,) = snap["commands"]
    assert command["keep_running"] is True
    assert command["status"] == "running" and command["preview_url"] == "http://localhost:5173/"
    told = model.calls[1][-1]["content"]
    assert command["id"] in told and "http://localhost:5173/" in told and "VITE ready" in told
    assert executor.killed == []


def test_only_an_address_on_this_machine_is_taken_and_never_koloni_s_or_a_model_server_s(
    make_client, wait_run, project_dir, gate
):
    printed = [
        "http://example.com:3000/\n",  # not this machine
        "http://127.0.0.1:8790/\n",  # KOLONİ's own
        "http://127.0.0.1:9/\n",  # the model server's (KOLONI_MODEL_BASE_URL in the tests)
    ]
    executor = ScriptedExecutor([Script([line], hold=gate) for line in printed])
    client, _model = make_client(
        [serve(id=f"k{i}") for i in range(3)] + [text("done")], executor=executor
    )
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    snap = wait_run(client, cid, run_id)
    assert [c["preview_url"] for c in snap["commands"]] == [None, None, None]
    for c in snap["commands"]:
        client.post(f"/api/commands/{c['id']}/stop", headers={"Origin": ORIGIN})


def test_it_is_asked_for_and_the_card_says_it_keeps_running(make_client, project_dir, gate):
    executor = ScriptedExecutor([Script(["Local: http://127.0.0.1:3000\n"], hold=gate)])
    client, _model = make_client([serve(), text("up")], executor=executor)
    cid, _run_id = start(client, project_dir, "start the site")
    snap = wait_status(client, cid, "waiting_approval")
    (command,) = snap["commands"]
    assert (command["status"], command["keep_running"]) == ("proposed", True)
    assert executor.started == []


def test_stop_ends_it_with_what_it_started(make_client, wait_run, project_dir, gate):
    executor = ScriptedExecutor([Script(["Local: http://127.0.0.1:3000\n"], hold=gate)])
    client, _model = make_client([serve(), text("up")], executor=executor)
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    (command,) = wait_run(client, cid, run_id)["commands"]
    refused = client.post(f"/api/commands/{command['id']}/stop")  # says nothing of where it is from
    assert refused.status_code == 403
    stopped = client.post(f"/api/commands/{command['id']}/stop", headers={"Origin": ORIGIN})
    assert stopped.status_code == 200, stopped.text
    until(lambda: commands(client, cid)[0]["status"] == "killed")
    assert executor.killed == [command["id"]]


def test_no_more_than_three_keep_running_in_a_conversation(
    make_client, wait_run, project_dir, gate
):
    executor = ScriptedExecutor(
        [Script([f"Local: http://127.0.0.1:300{i}\n"], hold=gate) for i in range(3)]
    )
    client, model = make_client(
        [serve(id=f"k{i}") for i in range(4)] + [text("done")], executor=executor
    )
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    snap = wait_run(client, cid, run_id)
    assert len(executor.started) == 3
    assert [c["status"] for c in snap["commands"]].count("running") == 3
    assert "three" in model.calls[4][-1]["content"].lower() or "3" in model.calls[4][-1]["content"]
    for c in snap["commands"]:
        client.post(f"/api/commands/{c['id']}/stop", headers={"Origin": ORIGIN})


def test_one_left_running_when_koloni_stopped_is_not_taken_for_running(tmp_path):
    db = tmp_path / "r.db"
    upgrade_db(db)
    factory = make_session_factory(make_engine(db))
    with factory() as s:
        s.add(Project(id="p", name="p", root_path=str(tmp_path)))
        s.flush()
        s.add(Conversation(id="c", project_id="p"))
        s.flush()
        s.add(Run(id="r", conversation_id="c", status="completed"))
        s.flush()
        s.add(Agent(id="a", run_id="r", role_name="Lead", tools=[]))
        s.flush()
        s.add(Message(id="m", conversation_id="c", run_id="r", role="assistant"))
        s.flush()
        s.add(
            ToolCall(
                id="t",
                run_id="r",
                agent_id="a",
                message_id="m",
                seq=1,
                provider_call_id="k",
                name="run_command",
                arguments="{}",
                status="succeeded",
            )
        )
        s.flush()
        s.add(
            Command(
                id="k",
                run_id="r",
                agent_id="a",
                tool_call_id="t",
                command="npm run dev",
                cwd=".",
                location="host",
                status="running",
                timeout_seconds=120,
                keep_running=True,
                preview_url="http://localhost:5173/",
            )
        )
        s.commit()
    recover_interrupted(factory)
    with factory() as s:
        left = s.get(Command, "k")
        assert left.status != "running" and left.ended_at is not None
