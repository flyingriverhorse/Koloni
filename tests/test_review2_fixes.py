"""Regression tests for defects found in the slice 2 whole-branch review."""

import asyncio
import json
import sys
import time

import httpx2
import pytest

from app.commands import is_allowed, matches, suggest_prefix
from app.executors import docker
from app.executors.docker import DockerCommand
from app.executors.host import HostExecutor
from app.model_client import ModelUnavailable, OpenAICompatClient, StepResult, ToolCallRequest
from tests.fakes import Script, ScriptedExecutor
from tests.test_agent_writes import wait_status
from tests.test_chat_flow import start, start_in_mode, text
from tests.test_host_executor import alive, py, run

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell behaviour")


def cmd(command="pytest -q", id="k1", **extra):
    args = json.dumps({"command": command, **extra})
    return StepResult("", [ToolCallRequest(id, "run_command", args)], 1, 1)


# C1 / I5 — a rule covers plain commands only, and no rule is offered for "run anything"


@pytest.mark.parametrize("command", [
    "pytest (Remove-Item -Recurse .)",
    "pytest @(Remove-Item x)",
    "pytest & rm -rf .",
    "pytest {Remove-Item x}",
    "pytest $env:X",
    "pytest %TEMP%",
    "pytest #x",
    "pytest !x",
    "pytest *",
    "pytest ~",
    "pytest\tx",
])
def test_a_rule_never_covers_a_command_with_shell_syntax(command):
    assert matches(command, "pytest") is False
    assert suggest_prefix(command) == ""


@pytest.mark.parametrize("command, rule", [
    ('pytest -k "a or b" tests/x.py', "pytest"),
    ("git commit -m 'fix: thing' --no-verify", "git commit"),
    ("python -m pytest tests\\unit -q", "python -m pytest"),
    ("npm run build -- --mode=prod,x+y", "npm run build"),
])
def test_plain_commands_with_quotes_paths_and_flags_are_covered(command, rule):
    assert matches(command, rule) is True
    assert is_allowed(command, [rule]) is True


@pytest.mark.parametrize("command, prefix", [
    ("& 'C:\\x\\python.exe' -m pytest", ""),  # the call operator itself is not a rule
    ("python test.py", "python test.py"),
    ("python -c \"print(1)\"", ""),  # an interpreter with inline code: never remembered
    ("python", ""),
    (".venv/Scripts/python -m pytest -q", ".venv/Scripts/python -m pytest"),
    ("C:\\Python312\\python.exe -m unittest", "C:\\Python312\\python.exe -m unittest"),
    ("py -m pytest", "py -m pytest"),
    ("node build.js --watch", "node build.js"),
    ("git -c core.pager=x log", ""),  # options before the subcommand
    ("cmd /c dir", ""),  # shells run anything
    ("powershell -Command ls", ""),
    ("bash -c ls", ""),
    ("uv run pytest -q", "uv run pytest"),
    ("uv run", ""),
    ("npx vitest run", "npx vitest"),
    ("npm run build", "npm run build"),
    ("npm test", "npm test"),
])
def test_suggested_rules_are_never_broader_than_one_program_and_task(command, prefix):
    assert suggest_prefix(command) == prefix


def test_always_run_on_a_command_that_cannot_be_remembered_adds_no_rule(
        make_client, wait_run, project_dir):
    executor = ScriptedExecutor([Script(["ok"])])
    client, _ = make_client([cmd("pytest; echo done"), text("done")], executor=executor)
    cid, run_id = start(client, project_dir)
    command = wait_status(client, cid, "waiting_approval")["commands"][0]
    assert command["suggested_prefix"] == ""
    client.post(f"/api/commands/{command['id']}/approve", json={"remember": True})
    snap = wait_run(client, cid, run_id)
    assert snap["allowed_commands"] == [] and snap["commands"][0]["status"] == "exited"


# C2 — every path ends the command's record


def test_a_second_stop_during_a_slow_kill_still_closes_the_command(
        make_client, wait_run, project_dir, gate):
    executor = ScriptedExecutor([Script(["working\n"], hold=gate, kill_seconds=0.6)])
    client, _ = make_client([cmd()], executor=executor)
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    for _ in range(200):
        if executor.started:
            break
        time.sleep(0.01)
    client.post(f"/api/runs/{run_id}/cancel")
    time.sleep(0.1)
    client.post(f"/api/runs/{run_id}/cancel")  # an impatient double click
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "cancelled"
    assert snap["commands"][0]["status"] == "killed"
    assert client.app.state.runner.commands.live_outputs(cid) == {}


def test_recovery_closes_a_running_command_even_under_a_finished_run(tmp_path):
    from app.agent import recover_interrupted
    from app.db.models import Agent, Command, Conversation, Message, Project, Run, ToolCall
    from app.db.session import make_engine, make_session_factory, upgrade_db

    db = tmp_path / "r.db"
    upgrade_db(db)
    factory = make_session_factory(make_engine(db))
    with factory() as s:
        s.add(Project(id="p", name="p", root_path=str(tmp_path)))
        s.flush()
        s.add(Conversation(id="c", project_id="p"))
        s.flush()
        s.add(Run(id="r", conversation_id="c", status="cancelled"))
        s.flush()
        s.add(Agent(id="a", run_id="r", role_name="Lead", tools=[]))
        s.flush()
        s.add(Message(id="m", conversation_id="c", run_id="r", role="assistant"))
        s.flush()
        s.add(ToolCall(id="t", run_id="r", agent_id="a", message_id="m", seq=1, provider_call_id="t",
                       name="run_command", arguments="{}", status="interrupted"))
        s.flush()
        s.add(Command(id="k", run_id="r", agent_id="a", tool_call_id="t", command="x", cwd=".",
                      location="host", status="running", timeout_seconds=120))
        s.commit()
    recover_interrupted(factory)
    with factory() as s:
        assert s.get(Command, "k").status == "interrupted"


# I3 — the reason a command did not start is on its record


def test_the_reason_a_command_did_not_start_is_kept_with_it(make_client, wait_run, project_dir):
    reason = "the image python:3.12 is not on this machine; run: docker pull python:3.12"
    executor = ScriptedExecutor([Script(start_error=reason)])
    client, _ = make_client([cmd(), text("cannot")], executor=executor)
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    command = wait_run(client, cid, run_id)["commands"][0]
    assert command["status"] == "failed_to_start" and reason in command["output"]


# C3 — a child that outlives its shell


def detached_child(folder) -> str:
    """A command that starts a 60 s child, prints its pid and returns at once.

    The child does not hold the command's output pipe, so the shell really exits.
    """
    (folder / "sleep60.py").write_text("import time; time.sleep(60)", encoding="utf-8")
    if sys.platform == "win32":
        return (
            f"(Start-Process -FilePath '{sys.executable}' -ArgumentList 'sleep60.py' "
            "-PassThru -WindowStyle Hidden).Id"
        )
    return f"'{sys.executable}' sleep60.py >/dev/null 2>&1 & echo $!"


def wait_dead(pid: int, seconds: float = 5) -> bool:
    deadline = time.monotonic() + seconds
    while alive(pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    return not alive(pid)


@pytest.mark.anyio
async def test_a_child_that_outlives_the_shell_can_still_be_killed(tmp_path):
    output, code = await run(detached_child(tmp_path), tmp_path)
    child = int(output.split()[-1])
    assert code == 0 and alive(child)  # the shell is gone, its child is not

    running = await HostExecutor().start("k2", detached_child(tmp_path), tmp_path)
    second = int("".join([chunk async for chunk in running]).split()[-1])
    assert await asyncio.wait_for(running.wait(), 15) == 0
    assert alive(second)
    await running.kill()
    assert await asyncio.to_thread(wait_dead, second)
    import subprocess
    subprocess.run(["taskkill", "/F", "/PID", str(child)] if sys.platform == "win32"
                   else ["kill", "-9", str(child)], capture_output=True)


def test_nothing_a_finished_command_started_is_left_running(make_client, wait_run, project_dir):
    client, _ = make_client([cmd(detached_child(project_dir)), text("done")])  # real executor
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    snap = wait_run(client, cid, run_id, timeout=40)
    command = snap["commands"][0]
    assert (command["status"], command["exit_code"]) == ("exited", 0)
    assert wait_dead(int(command["output"].split()[-1]))


def test_a_command_is_recorded_when_its_shell_exits_even_if_output_stays_open(
        make_client, wait_run, project_dir):
    # A background child can keep the output pipe open long after the shell is done.
    executor = ScriptedExecutor([Script(["started\n"], exit_code=0, linger=True)])
    client, _ = make_client([cmd(), text("done")], executor=executor)
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    started = time.monotonic()
    command = wait_run(client, cid, run_id, timeout=20)["commands"][0]
    assert (command["status"], command["exit_code"], command["output"]) == ("exited", 0, "started\n")
    assert time.monotonic() - started < 10  # the grace period, not the 120 s limit
    assert executor.closed == [command["id"]]


# I4 / I9 — what PowerShell reports


@windows_only
@pytest.mark.anyio
async def test_non_ascii_output_survives(tmp_path):
    (tmp_path / "şirket_ğüİ.txt").write_text("x", encoding="utf-8")
    output, _ = await run("Write-Output 'şğİöç'; Get-ChildItem -Name", tmp_path)
    assert "şğİöç" in output and "şirket_ğüİ.txt" in output
    output, _ = await run(py("print('çıktı ğüş')", tmp_path), tmp_path)
    assert "çıktı ğüş" in output


@windows_only
@pytest.mark.anyio
@pytest.mark.parametrize("command, expected", [
    ("cmd /c exit 0; Get-Item ./no-such-file", 1),  # the last statement failed
    ("cmd /c exit 3; Write-Output handled", 0),  # an earlier failure was handled
    ("cmd /c exit 3", 3),
    ("exit 7", 7),
    ("Write-Output ok", 0),
])
async def test_exit_code_reflects_the_last_statement(tmp_path, command, expected):
    _, code = await run(command, tmp_path)
    assert code == expected


# I1 / I2 — Docker edge cases


@pytest.mark.anyio
async def test_a_failed_docker_kill_falls_back_to_removing_the_container(monkeypatch):
    calls = []

    async def fake_exec(argv, timeout):
        calls.append(argv[1:3])
        return (1, "Error: No such container") if argv[1] == "kill" else (0, "")

    monkeypatch.setattr(docker, "_exec", fake_exec)

    class Process:
        pid, returncode, stdout = 4321, None, None

        def kill(self):
            calls.append(["client", "kill"])

    await DockerCommand(Process(), "koloni-k1").kill()
    assert ["kill", "koloni-k1"] in calls and ["rm", "-f"] in calls
    assert ["client", "kill"] in calls


def test_docker_exit_125_is_a_start_failure_with_its_reason():
    command = DockerCommand.__new__(DockerCommand)
    reason = command.start_failure(125, "docker: Error response from daemon: mounts denied.\n")
    assert "mounts denied" in reason
    assert command.start_failure(1, "tests failed") is None
    assert command.start_failure(0, "") is None


def test_a_start_failure_reported_after_exit_is_recorded_as_not_started(
        make_client, wait_run, project_dir):
    executor = ScriptedExecutor([
        Script(["docker: Error response from daemon: mounts denied\n"], exit_code=125,
               start_failure="Docker could not start the container: mounts denied")])
    client, model = make_client([cmd(), text("cannot")], executor=executor)
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    snap = wait_run(client, cid, run_id)
    assert snap["commands"][0]["status"] == "failed_to_start"
    assert snap["tool_calls"][0]["status"] == "failed"
    assert "mounts denied" in model.calls[1][-1]["content"]


# I6 — a model that is slow to start answering is not a stalled model


@pytest.mark.anyio
async def test_the_wait_for_the_first_token_has_its_own_longer_limit():
    class SlowStart(httpx2.AsyncByteStream):
        async def __aiter__(self):
            await asyncio.sleep(0.5)  # ingesting a long prompt
            yield b'data: {"choices": [{"delta": {"content": "ok"}}]}\n\n'
            yield b"data: [DONE]\n\n"

    def handler(request):
        return httpx2.Response(200, stream=SlowStart())

    async def on_delta(_):
        pass

    patient = OpenAICompatClient(
        "http://model/v1", transport=httpx2.MockTransport(handler),
        stall_seconds=0.2, first_token_seconds=5)
    assert (await patient.stream_step("m", [], None, on_delta)).content == "ok"

    impatient = OpenAICompatClient(
        "http://model/v1", transport=httpx2.MockTransport(handler),
        stall_seconds=5, first_token_seconds=0.2)
    with pytest.raises(ModelUnavailable, match="did not start answering within 0.2 seconds"):
        await impatient.stream_step("m", [], None, on_delta)


# I7 — events do not carry command output


def test_command_events_do_not_repeat_the_output(make_client, wait_run, project_dir):
    executor = ScriptedExecutor([Script(["x" * 5000])])
    client, _ = make_client([cmd(), text("done")], executor=executor)
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    snap = wait_run(client, cid, run_id)
    assert len(snap["commands"][0]["output"]) == 5000  # the record has it
    with client.stream("GET", f"/api/conversations/{cid}/events?after=0&once=1") as r:
        frames = r.read().decode().split("\n\n")
    updates = [json.loads(f.split("data: ", 1)[1]) for f in frames if "event: command.updated" in f]
    assert updates and updates[-1]["status"] == "exited"
    assert all("output" not in update for update in updates)


def test_the_reason_a_command_did_not_start_reaches_clients_that_are_already_connected(
        make_client, wait_run, project_dir):
    # Nothing streams for a command that never started, so its event must carry the reason.
    reason = "the image x is not on this machine; run: docker pull x"
    executor = ScriptedExecutor([Script(start_error=reason)])
    client, _ = make_client([cmd(), text("cannot")], executor=executor)
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    wait_run(client, cid, run_id)
    with client.stream("GET", f"/api/conversations/{cid}/events?after=0&once=1") as r:
        frames = r.read().decode().split("\n\n")
    updates = [json.loads(f.split("data: ", 1)[1]) for f in frames if "event: command.updated" in f]
    assert updates[-1]["status"] == "failed_to_start" and reason in updates[-1]["output"]
