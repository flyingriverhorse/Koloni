"""run_command through the agent loop, with a scripted executor."""

import asyncio
import json
import re
import time
from types import SimpleNamespace

import pytest

from app import agent
from app.agent import recover_interrupted
from app.command_runner import PATCH_REJECTED, WRITE_REJECTED, CommandRunner
from app.db.models import Agent, Command, Conversation, Message, Project, Run, ToolCall
from app.db.session import make_engine, make_session_factory, upgrade_db
from app.model_client import StepResult, ToolCallRequest
from tests.fakes import Script, ScriptedExecutor
from tests.test_agent_writes import wait_status
from tests.test_chat_flow import start, start_in_mode, text


def cmd(command="pytest -q", id="k1", **extra):
    args = json.dumps({"command": command, **extra})
    return StepResult("", [ToolCallRequest(id, "run_command", args)], 1, 1)


def approve(client, command_id, remember=False):
    return client.post(f"/api/commands/{command_id}/approve", json={"remember": remember})


def test_ask_level_waits_then_runs_once(make_client, wait_run, project_dir):
    executor = ScriptedExecutor([Script(["2 passed\n"], exit_code=0)])
    client, model = make_client([cmd(), text("They pass.")], executor=executor)
    cid, run_id = start(client, project_dir, "run the tests")
    snap = wait_status(client, cid, "waiting_approval")
    command = snap["commands"][0]
    assert (command["status"], command["command"], command["cwd"]) == ("proposed", "pytest -q", ".")
    assert (command["location"], command["suggested_prefix"]) == ("host", "pytest")
    assert command["timeout_seconds"] == 120 and executor.started == []

    assert approve(client, command["id"]).json()["status"] in ("running", "exited")
    snap = wait_run(client, cid, run_id)
    done = snap["commands"][0]
    assert (done["status"], done["exit_code"], done["output"]) == ("exited", 0, "2 passed\n")
    assert done["started_at"] and done["ended_at"]
    assert snap["tool_calls"][0]["status"] == "succeeded"
    result = model.calls[1][-1]["content"]
    assert result.startswith("exit code 0 (") and result.endswith("2 passed\n")
    assert snap["allowed_commands"] == []
    assert executor.started == [("pytest -q", str(project_dir.resolve()))]
    assert snap["runs"][0]["status"] == "completed"


def test_always_run_adds_the_rule_and_skips_the_next_ask(make_client, wait_run, project_dir):
    executor = ScriptedExecutor([Script(["a"]), Script(["b"]), Script(["c"])])
    client, _ = make_client([
        cmd("pytest -q", "k1"), cmd("pytest -q tests", "k2"), cmd("pytest; rm x", "k3"),
        text("done")], executor=executor)
    cid, run_id = start(client, project_dir)
    first = wait_status(client, cid, "waiting_approval")["commands"][0]
    approve(client, first["id"], remember=True)

    # the second pytest runs without a question; the chained one asks again
    snap = wait_status(client, cid, "waiting_approval")
    assert [c["status"] for c in snap["commands"]] == ["exited", "exited", "proposed"]
    assert [r["prefix"] for r in snap["allowed_commands"]] == ["pytest"]
    approve(client, snap["commands"][2]["id"])
    wait_run(client, cid, run_id)
    assert len(executor.started) == 3


def test_reject_tells_the_model_it_was_the_users_decision(make_client, wait_run, project_dir):
    executor = ScriptedExecutor([])
    client, model = make_client([cmd("rm -rf build"), text("Understood.")], executor=executor)
    cid, run_id = start(client, project_dir)
    command = wait_status(client, cid, "waiting_approval")["commands"][0]
    assert client.post(f"/api/commands/{command['id']}/reject").json()["status"] == "rejected"
    snap = wait_run(client, cid, run_id)
    assert snap["commands"][0]["status"] == "rejected"
    assert snap["tool_calls"][0]["status"] == "denied"
    said = model.calls[1][-1]["content"]
    assert "not a tool error" in said
    # B-321: a no to this command, not to the task - Codex gave the whole task up at "stop"
    assert "carry on with the rest of the task" in said.lower() and "stop" not in said.lower()
    assert executor.started == []


@pytest.mark.parametrize("patch", ["git apply --whitespace=fix fix.diff",
                                   "$patch = @'\n*** Begin Patch\n'@\napply_patch $patch"])
def test_a_patch_command_refused_says_to_change_the_file_with_the_file_tools(
        make_client, wait_run, project_dir, patch):
    # B-389 (R187, live): refused, the agent gave its change up instead of using edit_file.
    client, model = make_client([cmd(patch), text("Understood.")], executor=ScriptedExecutor([]))
    cid, run_id = start(client, project_dir)
    command = wait_status(client, cid, "waiting_approval")["commands"][0]
    client.post(f"/api/commands/{command['id']}/reject")
    wait_run(client, cid, run_id)
    said = model.calls[1][-1]["content"]
    assert said == PATCH_REJECTED and "make it with edit_file / write_file" in said
    # (Not "theirs to refuse": at Auto-edit and Full auto a file change is not asked.)
    assert "refuse" not in said


@pytest.mark.parametrize(("command", "patch"), [
    ("cat x.diff | apply_patch", True), ("  apply_patch <<'EOF'", True),
    ("echo hi; apply_patch $p", True), ("git am 0001.patch", True),
    ("grep -rn apply_patch app", False), ("git apply --check x.diff", False),
    ("pytest -q", False)])
def test_only_a_command_that_applies_a_patch_is_told_of_the_file_tools(command, patch):
    from app.command_runner import REJECTED, rejected
    assert rejected(command) == (PATCH_REJECTED if patch else REJECTED)


@pytest.mark.parametrize(("command", "writes"), [
    ("[System.IO.File]::WriteAllText('a.py', $text)", True),
    ("$t = [IO.File]::ReadAllText('a.py'); [IO.File]::AppendAllLines('a.py', $l)", True),
    ("Set-Content -Path a.py -Value $t", True), ("$t | Out-File a.py", True),
    ("add-content a.py 'x'", True), ("New-Item b.py -ItemType File -Value 'x = 1'", True),
    ("echo hi > out.txt", True), ("echo hi >>log.txt", True),
    ("[IO.File]::ReadAllText('a.py')", False), ("pytest -q 2>&1", False),
    ("git status >$null", False), ("dir > NUL", False), ("New-Item -ItemType Directory b", False),
    ("$x | Out-Null", False), ("Get-Content a.py | % { $_ -replace 'a', 'b' }", False),
    ("rm -rf build > log.txt", False)])  # (refused for its delete: not told it was the write)
def test_a_refused_command_that_writes_a_file_is_told_of_the_file_tools(command, writes):
    # B-393 (R188, live): refused a patch, Copilot's Coder wrote the file with PowerShell, refused
    # again - and again; only the wording changes, not whether it is asked.
    from app.command_runner import REJECTED, WRITE_REJECTED, rejected
    assert rejected(command) == (WRITE_REJECTED if writes else REJECTED)
    assert ("make it with edit_file / write_file" in rejected(command)) is writes


def test_a_long_line_of_new_item_without_a_value_is_judged_at_once():
    # (review: one pattern over it took seconds, on the event loop)
    import time

    from app.command_runner import REJECTED, rejected
    began = time.perf_counter()
    assert rejected("new-item " * 22_000) == REJECTED   # ~200 KB, no -Value
    assert time.perf_counter() - began < 0.5


@pytest.mark.parametrize("refusal", [
    agent.REJECTED, agent.OUTSIDE_REJECTED, agent.WEB_REJECTED, agent.NO_COMMANDS,
    agent.NO_CHANGES, agent.ONLY_READS, agent.CHANGE_REJECTED, agent.LEAVE_REJECTED,
    agent.READ_ONLY_WRITE, PATCH_REJECTED, WRITE_REJECTED])
def test_a_refusal_forbids_that_action_only_and_says_to_carry_on(refusal):
    # B-321: each says not to do it some other way, and (but the one that names the tools to
    # write with instead) to carry on with the rest of the task
    assert re.search(r"another way|any other way|anything that does the same|any tool|"
                     r"anything else", refusal), refusal
    assert (agent.CARRY_ON in refusal) is (refusal is not agent.READ_ONLY_WRITE), refusal
    assert "stop" not in refusal.lower(), refusal


def test_auto_edit_level_still_asks_for_commands(make_client, project_dir):
    client, _ = make_client([cmd()], executor=ScriptedExecutor([Script([])]))
    cid, _run_id = start_in_mode(client, project_dir, "auto_edit")
    assert wait_status(client, cid, "waiting_approval")["commands"][0]["status"] == "proposed"


def test_full_auto_runs_without_asking(make_client, wait_run, project_dir):
    executor = ScriptedExecutor([Script(["ok"])])
    client, _ = make_client([cmd(), text("done")], executor=executor)
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    snap = wait_run(client, cid, run_id)
    assert snap["commands"][0]["status"] == "exited"
    with client.stream("GET", f"/api/conversations/{cid}/events?after=0&once=1") as r:
        assert "waiting_approval" not in r.read().decode()


def test_nonzero_exit_is_a_result_not_a_failure(make_client, wait_run, project_dir):
    executor = ScriptedExecutor([Script(["1 failed\n"], exit_code=1)])
    client, model = make_client([cmd(), text("One test fails.")], executor=executor)
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    snap = wait_run(client, cid, run_id)
    assert (snap["commands"][0]["status"], snap["commands"][0]["exit_code"]) == ("exited", 1)
    assert snap["tool_calls"][0]["status"] == "succeeded"
    assert model.calls[1][-1]["content"].startswith("exit code 1 (")
    assert snap["runs"][0]["status"] == "completed"


def test_timeout_kills_and_reports(make_client, wait_run, project_dir, gate):
    executor = ScriptedExecutor([Script(["started\n"], hold=gate)])
    client, model = make_client(
        [cmd(timeout_seconds=1), text("It hung.")], executor=executor)
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    snap = wait_run(client, cid, run_id, timeout=10)
    command = snap["commands"][0]
    assert command["status"] == "timed_out" and command["exit_code"] is None
    assert executor.killed == [command["id"]]
    assert snap["tool_calls"][0]["status"] == "failed"
    result = model.calls[1][-1]["content"]
    assert "timed out after 1 seconds" in result and "started" in result


def test_stop_kills_the_running_command(make_client, wait_run, project_dir, gate):
    executor = ScriptedExecutor([Script(["working\n"], hold=gate)])
    client, _ = make_client([cmd()], executor=executor)
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    for _ in range(200):
        if executor.started:
            break
        time.sleep(0.01)
    client.post(f"/api/runs/{run_id}/cancel")
    snap = wait_run(client, cid, run_id)
    command = snap["commands"][0]
    assert snap["runs"][0]["status"] == "cancelled"
    assert command["status"] == "killed" and command["output"] == "working\n"
    assert executor.killed == [command["id"]]


def test_start_error_is_reported_and_nothing_runs(make_client, wait_run, project_dir):
    executor = ScriptedExecutor([Script(start_error="Docker is not available: daemon not running")])
    client, model = make_client([cmd(), text("I cannot run it.")], executor=executor)
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    snap = wait_run(client, cid, run_id)
    assert snap["commands"][0]["status"] == "failed_to_start"
    assert snap["tool_calls"][0]["status"] == "failed"
    assert "Docker is not available" in model.calls[1][-1]["content"]
    assert executor.started == []


def test_output_is_capped_at_one_mebibyte(make_client, wait_run, project_dir):
    chunk = "x" * (600 * 1024)
    executor = ScriptedExecutor([Script([chunk, chunk, chunk], exit_code=0)])
    client, model = make_client([cmd(), text("big")], executor=executor)
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    command = wait_run(client, cid, run_id)["commands"][0]
    assert command["status"] == "exited" and command["output_truncated"] is True
    assert len(command["output"]) <= 1024 * 1024 + 200
    assert command["output"].endswith("[output truncated: more than 1 MiB]")
    assert "characters omitted" in model.calls[1][-1]["content"]


def test_bad_arguments_are_tool_errors(make_client, wait_run, project_dir):
    calls = [
        ToolCallRequest("a", "run_command", json.dumps({"command": "   "})),
        # (a drive's root: never opened - another folder outside is asked about)
        ToolCallRequest("b", "run_command", json.dumps({"command": "ls", "cwd": "../" * 40})),
        ToolCallRequest("c", "run_command", json.dumps({"command": "ls", "cwd": "nope"})),
        ToolCallRequest("d", "run_command", json.dumps({"command": "ls", "timeout_seconds": 0})),
        ToolCallRequest("e", "run_command", json.dumps({"command": "ls", "timeout_seconds": 9999})),
        ToolCallRequest("f", "run_command", json.dumps({})),
    ]
    client, _ = make_client(
        [StepResult("", calls, 1, 1), text("ok")], executor=ScriptedExecutor([]))
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    snap = wait_run(client, cid, run_id)
    results = [t["result"] for t in snap["tool_calls"]]
    assert "command is empty" in results[0]
    assert "never opened" in results[1]
    assert "is not a folder" in results[2]
    assert "timeout_seconds must be between 1 and 600" in results[3]
    assert "timeout_seconds must be between 1 and 600" in results[4]
    assert "missing required argument: command" in results[5]
    assert all(t["status"] == "failed" for t in snap["tool_calls"]) and snap["commands"] == []


def test_a_command_runs_in_the_requested_subfolder(make_client, wait_run, project_dir):
    (project_dir / "pkg").mkdir()
    executor = ScriptedExecutor([Script(["ok"])])
    client, _ = make_client([cmd("ls", cwd="pkg"), text("done")], executor=executor)
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    snap = wait_run(client, cid, run_id)
    assert snap["commands"][0]["cwd"] == "pkg"
    assert executor.started == [("ls", str((project_dir / "pkg").resolve()))]


def test_pending_command_keeps_its_recorded_location_and_still_needs_the_decision(
        make_client, wait_run, project_dir):
    executor = ScriptedExecutor([Script(["ok"])])
    client, _ = make_client([cmd(), text("done")], executor=executor)
    cid, run_id = start(client, project_dir)
    command = wait_status(client, cid, "waiting_approval")["commands"][0]
    pid = client.get("/api/projects").json()[0]["id"]
    client.patch(f"/api/projects/{pid}", json={"exec_location": "docker", "docker_image": "alpine"})
    assert client.patch(f"/api/conversations/{cid}", json={"permission_mode": "full_auto"},
                        headers={"Origin": "http://127.0.0.1:8790"}).status_code == 200
    time.sleep(0.2)
    still = client.get(f"/api/conversations/{cid}").json()
    assert still["commands"][0]["status"] == "proposed" and executor.started == []

    approve(client, command["id"])
    snap = wait_run(client, cid, run_id)
    assert snap["commands"][0]["location"] == "host"
    assert executor.locations == ["host"]


def test_removing_a_rule_makes_the_command_ask_again(make_client, wait_run, project_dir):
    executor = ScriptedExecutor([Script(["a"]), Script(["b"])])
    client, _ = make_client([cmd(), text("one"), cmd(id="k2"), text("two")], executor=executor)
    cid, run_id = start(client, project_dir)
    first = wait_status(client, cid, "waiting_approval")["commands"][0]
    approve(client, first["id"], remember=True)
    snap = wait_run(client, cid, run_id)
    rule = snap["allowed_commands"][0]

    assert client.delete(f"/api/allowed-commands/{rule['id']}").status_code == 204
    assert client.delete(f"/api/allowed-commands/{rule['id']}").status_code == 404
    client.post(f"/api/conversations/{cid}/messages", json={"content": "again"})
    snap = wait_status(client, cid, "waiting_approval")
    assert snap["allowed_commands"] == [] and snap["commands"][1]["status"] == "proposed"


def test_snapshot_and_sync_carry_live_output(make_client, project_dir, gate):
    executor = ScriptedExecutor([Script(["first line\n"], hold=gate)])
    client, _ = make_client([cmd()], executor=executor)
    cid, _run_id = start_in_mode(client, project_dir, "full_auto")
    snap = {}
    for _ in range(200):
        snap = client.get(f"/api/conversations/{cid}").json()
        if snap["commands"] and snap["commands"][0]["output"]:
            break
        time.sleep(0.01)
    command = snap["commands"][0]
    assert (command["status"], command["output"]) == ("running", "first line\n")
    url = f"/api/conversations/{cid}/events?after={snap['last_event_id']}&once=1"
    with client.stream("GET", url) as r:
        frames = [f for f in r.read().decode().split("\n\n") if f.startswith("event: command.sync")]
    assert len(frames) == 1
    assert json.loads(frames[0].split("data: ", 1)[1]) == {
        "command_id": command["id"], "output": "first line\n"}


def test_approving_twice_or_after_the_run_ended_is_409(make_client, wait_run, project_dir):
    client, _ = make_client([cmd(), text("done")], executor=ScriptedExecutor([Script(["ok"])]))
    cid, run_id = start(client, project_dir)
    command = wait_status(client, cid, "waiting_approval")["commands"][0]
    assert approve(client, command["id"]).status_code == 200
    wait_run(client, cid, run_id)
    again = approve(client, command["id"])
    assert again.status_code == 409 and "no longer waiting" in again.json()["detail"]
    assert client.post("/api/commands/nope/reject").status_code == 404


def test_cancel_while_a_command_waits_rejects_it(make_client, wait_run, project_dir):
    executor = ScriptedExecutor([])
    client, _ = make_client([cmd()], executor=executor)
    cid, run_id = start(client, project_dir)
    wait_status(client, cid, "waiting_approval")
    client.post(f"/api/runs/{run_id}/cancel")
    snap = wait_run(client, cid, run_id)
    assert snap["commands"][0]["status"] == "rejected" and executor.started == []


def test_the_model_is_told_where_and_in_which_shell_commands_run(
        make_client, wait_run, project_dir):
    client, model = make_client([text("hi")], executor=ScriptedExecutor([]))
    cid, run_id = start(client, project_dir)
    wait_run(client, cid, run_id)
    system = model.calls[0][0]["content"]
    assert "run_command" in system and "on this machine" in system
    assert "run_command" in [t["function"]["name"] for t in model.tool_args[0]]


def test_recovery_settles_commands(tmp_path):
    db = tmp_path / "r.db"
    upgrade_db(db)
    factory = make_session_factory(make_engine(db))
    with factory() as s:
        s.add(Project(id="p", name="p", root_path=str(tmp_path)))
        s.flush()
        s.add(Conversation(id="c", project_id="p"))
        s.flush()
        s.add(Run(id="r", conversation_id="c", status="running"))
        s.flush()
        s.add(Agent(id="a", run_id="r", role_name="Lead", tools=[]))
        s.flush()
        s.add(Message(id="m", conversation_id="c", run_id="r", role="assistant"))
        s.flush()
        for cid, status in (("k1", "proposed"), ("k2", "running"), ("k3", "exited")):
            s.add(ToolCall(id=f"t{cid}", run_id="r", agent_id="a", message_id="m", seq=1, provider_call_id=cid,
                           name="run_command", arguments="{}", status="running"))
            s.flush()
            s.add(Command(id=cid, run_id="r", agent_id="a", tool_call_id=f"t{cid}", command="x", cwd=".",
                          location="host", status=status, timeout_seconds=120))
        s.commit()
    recover_interrupted(factory)
    with factory() as s:
        assert {c.id: c.status for c in s.query(Command)} == {
            "k1": "rejected", "k2": "interrupted", "k3": "exited"}
        assert s.get(Command, "k2").ended_at is not None


def test_a_clis_command_is_judged_in_the_folder_it_says_it_runs_in(tmp_path):
    # denetim-010 #18: `ask_for` judges a CLI's line with its cwd, as `run` does - `> settings.json`
    # in `.claude` writes Claude Code's settings: a card at Full auto, though the line names none.
    db = tmp_path / "r.db"
    upgrade_db(db)
    factory = make_session_factory(make_engine(db))
    with factory() as s:
        s.add(Project(id="p", name="p", root_path=str(tmp_path)))
        s.flush()
        s.add(Conversation(id="c", project_id="p", permission_mode="full_auto"))
        s.flush()
        s.add(Run(id="r", conversation_id="c", status="running"))
        s.flush()
        s.add(Agent(id="a", run_id="r", role_name="Lead", tools=[]))
        s.flush()
        s.add(Message(id="m", conversation_id="c", run_id="r", role="assistant"))
        s.flush()
        for n in (1, 2):
            s.add(ToolCall(id=f"t{n}", run_id="r", agent_id="a", message_id="m", seq=n,
                           provider_call_id=f"k{n}", name="run_command", arguments="{}",
                           status="running"))
        s.commit()
    runner = CommandRunner(factory, SimpleNamespace(emit=lambda *_: None), None, lambda **_: None)
    asked = []

    async def no(run_id, cid, agent_id, command_id, rule):
        asked.append(command_id)
        return "reject"

    runner._wait_for_decision = no
    line = "echo x > settings.json"
    assert asyncio.run(runner.ask_for("r", "c", "a", "t1", line, cwd="."))[0]
    assert not asyncio.run(runner.ask_for("r", "c", "a", "t2", line, cwd=".claude"))[0]
    assert len(asked) == 1


def test_a_real_command_runs_on_this_machine_through_the_agent(make_client, wait_run, project_dir):
    client, model = make_client([cmd("echo koloni-says-hi"), text("done")])  # real executor
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    snap = wait_run(client, cid, run_id, timeout=30)
    command = snap["commands"][0]
    assert (command["status"], command["exit_code"]) == ("exited", 0)
    assert "koloni-says-hi" in command["output"]
    assert "koloni-says-hi" in model.calls[1][-1]["content"]


def test_startup_stops_containers_of_commands_left_running(tmp_path, monkeypatch):
    from app.config import load_settings
    from app.main import create_app
    from tests.fakes import ScriptedModel
    from tests.keyed import TestClient

    settings = load_settings({"KOLONI_RUNTIME_ROOT": str(tmp_path / "rt")})
    upgrade_db(settings.db_path)
    factory = make_session_factory(make_engine(settings.db_path))
    with factory() as s:
        s.add(Project(id="p", name="p", root_path=str(tmp_path)))
        s.flush()
        s.add(Conversation(id="c", project_id="p"))
        s.flush()
        s.add(Run(id="r", conversation_id="c", status="running"))
        s.flush()
        s.add(Agent(id="a", run_id="r", role_name="Lead", tools=[]))
        s.flush()
        s.add(Message(id="m", conversation_id="c", run_id="r", role="assistant"))
        s.flush()
        for cid, location in (("kd", "docker"), ("kh", "host")):
            s.add(ToolCall(id=f"t{cid}", run_id="r", agent_id="a", message_id="m", seq=1, provider_call_id=cid,
                           name="run_command", arguments="{}", status="running"))
            s.flush()
            s.add(Command(id=cid, run_id="r", agent_id="a", tool_call_id=f"t{cid}", command="x", cwd=".",
                          location=location, status="running", timeout_seconds=120))
        s.commit()

    killed = []

    async def fake_kill(ids):
        killed.extend(ids)

    monkeypatch.setattr("app.main.kill_containers", fake_kill)
    with TestClient(create_app(settings, model=ScriptedModel([])), base_url="http://127.0.0.1:8790"):
        pass
    assert killed == ["kd"]
