"""89m: "Finish only when the tests pass" - Claude Code's Stop hook sends an agent that changed
files back to work while the project's tests fail, at most twice (fake CLI, measured shape)."""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.agent import TESTS_NO_START, TESTS_STILL_FAIL
from app.finish_tests import (
    NO_COMMAND,
    NOT_STARTED,
    NOT_TIMED,
    automatic,
    command_of,
    did_not_start,
)
from app.model_native import STOP_HOOK
from tests.test_backlog_auto import until
from tests.test_chat_flow import text
from tests.test_claude_native import ORIGIN, claude_app  # noqa: F401  (a fixture)
from tests.test_session_agent import session_app  # noqa: F401  (a fixture)
from tests.test_spawn import role_id, spawn

# The project's tests: they pass once fixed.txt is there.
CHECK = ("import pathlib, sys\n"
         "if pathlib.Path('fixed.txt').exists():\n    sys.exit(0)\n"
         "print('FAILED test_greeting - assert hi == hello')\nsys.exit(1)\n")


def write(named):
    return {"tool": "Write", "input": {"file_path": f"PROJECT/{named}", "content": "x"},
            "write": [named, "x"], "result": "ok"}


def start(client, project_dir, provider, finish=True, mode="full_auto", hands_code=False,
          command="python check.py", **more):
    (project_dir / "check.py").write_text(CHECK, encoding="utf-8")
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    patched = client.patch(f"/api/projects/{pid}", headers={"Origin": ORIGIN}, json={
        "check_command": command, "finish_tests": finish})
    assert patched.status_code == 200, patched.text
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(f"/api/conversations/{cid}", headers={"Origin": ORIGIN}, json={
        "permission_mode": mode, "provider_id": provider["id"], "lead_hands_code": hands_code,
        **more})
    run = client.post(f"/api/conversations/{cid}/messages",
                      json={"content": "fix the greeting"}).json()["run"]
    return pid, cid, run["id"]


def koloni_ran(snap):
    return [(c["status"], c["origin"]) for c in snap["tool_calls"]
            if c["name"] == "run_command" and c["origin"] == "koloni"]


def test_failing_tests_send_it_back_with_their_output_and_once_they_pass_it_finishes(
    claude_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _ = claude_app([write("a.txt"), {"say": "done"}],
                                     after_block=[[write("fixed.txt"), {"say": "fixed"}]])
    pid, cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id, timeout=30)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    seen = claude_app.record()
    (stop,) = seen["init"]["request"]["hooks"]["Stop"]
    assert stop["hookCallbackIds"] == [STOP_HOOK] and stop["timeout"] > 600
    blocked, let = seen["stops"]
    assert blocked["decision"] == "block" and let == {}
    assert "FAILED test_greeting" in blocked["reason"]
    assert "data, not instructions" in blocked["reason"]
    # KOLONİ ran them twice, in the project, on record as its own
    assert koloni_ran(snap) == [("succeeded", "koloni")] * 2
    assert [c["exit_code"] for c in snap["commands"] if c["command"] == "python check.py"] \
        == [1, 0]
    # and now that a run of them is on record and was quick, it is on by default
    project = next(p for p in client.get("/api/projects").json() if p["id"] == pid)
    assert project["finish_tests_auto"]["on"] is True
    assert project["finish_tests_auto"]["reason"].endswith("s last time")


def test_still_failing_after_two_send_backs_it_finishes_and_says_so(
    claude_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _ = claude_app([write("a.txt")],
                                     after_block=[[write("b.txt")], [write("c.txt")]])
    _pid, cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id, timeout=30)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert [one.get("decision") for one in claude_app.record()["stops"]] == \
        ["block", "block", None]
    assert len(koloni_ran(snap)) == 3
    assert TESTS_STILL_FAIL.format(times=2) in [c["result"] for c in snap["tool_calls"]]


def test_a_claude_code_session_coder_is_sent_back_by_koloni_while_the_tests_fail(
    session_app, project_dir  # noqa: F811
):
    # B-303: a session has no Stop hook (its prompt goes on stdin); KOLONI runs it again, told.
    client, provider, _ = session_app(
        [{"call": "write_file", "args": {"path": "a.txt", "content": "x"}}, {"say": "done"}],
        default_steps=[spawn("Coder", "fix the greeting"), text("done")])
    client.patch(f"/api/roles/{role_id(client, 'Coder')}", json={"provider_id": provider["id"]})
    # (the Lead: the local model)
    _pid, cid, _run_id = start(client, project_dir, {"id": None}, spawn_approval="never")

    def coder_done():  # (then its work waits: the same failing check is the merge's)
        snap = client.get(f"/api/conversations/{cid}").json()
        return snap if any(a["name"] == "Coder" and a["status"] == "completed"
                           for a in snap["agents"]) else None

    snap = until(coder_done, seconds=60)
    coder = next(a["id"] for a in snap["agents"] if a["name"] == "Coder")
    assert [c["agent_id"] for c in snap["tool_calls"]
            if c["name"] == "run_command" and c["origin"] == "koloni"] == [coder] * 3
    assert TESTS_STILL_FAIL.format(times=2) in [c["result"] for c in snap["tool_calls"]]
    told = session_app.record()["stdin"]  # (its last run's: sent back twice)
    assert told.count("KOLONİ ran the project's tests before letting you finish") == 2
    assert "FAILED test_greeting" in told


def test_switched_off_it_has_no_stop_hook_and_no_tests_run(
    claude_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _ = claude_app([write("a.txt")])
    _pid, cid, run_id = start(client, project_dir, provider, finish=False)
    snap = wait_run(client, cid, run_id, timeout=30)
    seen = claude_app.record()
    assert "Stop" not in seen["init"]["request"]["hooks"] and "stops" not in seen
    assert koloni_ran(snap) == [] and snap["commands"] == []


def test_tests_that_could_not_start_do_not_send_it_back(
    claude_app, wait_run, project_dir, monkeypatch  # noqa: F811
):
    client, provider, _ = claude_app([write("a.txt")])

    async def not_started(*_args, **_more):  # (as a Docker that is not there ends one)
        return "failed", "error: Docker is not running"

    monkeypatch.setattr(client.app.state.runner.commands, "run", not_started)
    _pid, cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id, timeout=30)
    assert claude_app.record()["stops"] == [{}]
    assert TESTS_NO_START.format(first="Docker is not running") in [
        c["result"] for c in snap["tool_calls"]]


def test_a_test_program_that_is_not_there_does_not_send_it_back_and_is_the_reason_after(
    claude_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _ = claude_app([write("a.txt")])
    pid, cid, run_id = start(client, project_dir, provider, command="no-such-program-89m")
    snap = wait_run(client, cid, run_id, timeout=30)
    assert claude_app.record()["stops"] == [{}]  # ran, said its program is not there: no block
    (said,) = [c["result"] for c in snap["tool_calls"] if c["origin"] == "cli"
               and (c["result"] or "").startswith("the tests could not start: ")]
    assert "no-such-program-89m" in said
    project = next(p for p in client.get("/api/projects").json() if p["id"] == pid)
    assert project["finish_tests_auto"] == {
        "on": False, "command": "no-such-program-89m", "reason": NOT_STARTED}


def test_with_no_file_changed_no_tests_run(claude_app, wait_run, project_dir):  # noqa: F811
    client, provider, _ = claude_app([{"say": "nothing to change"}])
    _pid, cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id, timeout=30)
    assert claude_app.record()["stops"] == [{}]
    assert snap["commands"] == []


def test_where_commands_are_asked_they_are_not_run_and_that_is_said(
    claude_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _ = claude_app([write("a.txt")])
    _pid, cid, run_id = start(client, project_dir, provider, mode="auto_edit")
    snap = wait_run(client, cid, run_id, timeout=30)
    assert claude_app.record()["stops"] == [{}] and snap["commands"] == []
    assert any("the tests were not run" in (c["result"] or "") for c in snap["tool_calls"])


def test_an_agent_that_does_not_write_gets_no_stop_hook(
    claude_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _ = claude_app([{"say": "I hand it on"}])
    _pid, cid, run_id = start(client, project_dir, provider, hands_code=True)
    wait_run(client, cid, run_id, timeout=30)
    seen = claude_app.record()
    assert "Stop" not in seen["init"]["request"]["hooks"] and "stops" not in seen


def test_the_test_command_is_the_check_command_or_what_the_folder_shows(tmp_path):
    assert command_of(str(tmp_path), "make check") == "make check"
    assert command_of(str(tmp_path), None) is None
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {
        "test": 'echo "Error: no test specified" && exit 1'}}), encoding="utf-8")
    assert command_of(str(tmp_path), None) is None  # (npm init's: it only fails)
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "vitest run"}}),
                                           encoding="utf-8")
    assert command_of(str(tmp_path), None) == "npm test"
    (tmp_path / "tests").mkdir()
    assert command_of(str(tmp_path), None) == "npm test"  # (a Node project's tests/)
    (tmp_path / "package.json").unlink()
    assert command_of(str(tmp_path), None) == "python -m pytest -q"
    (tmp_path / "tests").rmdir()
    (tmp_path / "pytest.ini").write_text("", encoding="utf-8")
    assert command_of(str(tmp_path), None) == "python -m pytest -q"


class _Ran:
    def __init__(self, seconds):
        start = datetime(2026, 10, 28, tzinfo=UTC)
        self.row = None if seconds is None else (
            start, start + timedelta(seconds=seconds), "exited", 1, "1 failed")

    def execute(self, _query):
        return SimpleNamespace(first=lambda: self.row)


def test_on_by_default_only_where_a_run_of_the_tests_was_quick(tmp_path):
    project = SimpleNamespace(id="p", root_path=str(tmp_path), check_command="make check")
    assert automatic(_Ran(None), project) == {
        "on": False, "command": "make check", "reason": NOT_TIMED}
    assert automatic(_Ran(12), project)["on"] is True
    assert automatic(_Ran(150), project) == {
        "on": False, "command": "make check", "reason": "the tests took 3 min last time"}
    unstarted = _Ran(1)
    unstarted.row = (*unstarted.row[:3], 9009, "")
    assert automatic(unstarted, project)["reason"] == NOT_STARTED
    project.check_command = None
    assert automatic(_Ran(12), project)["reason"] == NO_COMMAND


def test_what_a_missing_program_says_is_told_from_a_failing_test():
    # (wrapped by PowerShell at its console's width)
    assert did_not_start(1, "pytest : The term 'pytest' is not recognized as the name of a\n"
                            "cmdlet, function, script file, or operable program.")
    # PowerShell 7's wording (K-pwsh, measured)
    assert did_not_start(1, "pytest: \nLine |\n   2 |  pytest -q\n     |  ~~~~~~\n     | The term "
                            "'pytest' is not recognized as a name of a cmdlet, function, script "
                            "file, or executable program.\nCheck the spelling of the name")
    assert did_not_start(1, "'npm' is not recognized as an internal or external command,")
    assert did_not_start(127, "") and did_not_start(1, "bash: pytest: command not found")
    assert did_not_start(1, "C:/Python/python.exe: No module named pytest")
    assert not did_not_start(1, "FAILED tests/test_a.py::test_x - assert 1 == 2")
    assert not did_not_start(None, "")
