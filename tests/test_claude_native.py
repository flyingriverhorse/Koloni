"""Claude Code working natively: its own tools, with KOLONİ answering its permission prompts."""

import json
import sys
import time
from pathlib import Path

import pytest

from app.config import load_settings
from app.main import create_app
from app.model_native import ClaudeNativeClient
from app.model_session import ClaudeSessionClient
from tests.fakes import ScriptedModel
from tests.keyed import TestClient
from tests.test_agent_writes import wait_status
from tests.test_chat_flow import text
from tests.test_spawn import call, role_id, spawn, step

FAKE = [sys.executable, str(Path(__file__).with_name("fake_claude_native_cli.py"))]

WRITE = {"tool": "Write", "input": {"file_path": "PROJECT/hello.py",
                                                  "content": "print('hello')\n"},
         "write": ["hello.py", "print('hello')\n"], "result": "File updated"}
BASH = {"tool": "Bash", "input": {"command": "pytest -q"}, "result": "2 passed"}
# Its tools never given (slice 89b): they act later, elsewhere, or ask the user themselves.
NEVER = {"EnterWorktree", "ExitWorktree", "CronCreate", "CronDelete", "ScheduleWakeup",
         "RemoteTrigger", "PushNotification", "AskUserQuestion", "Workflow",
         "DesignSync", "SendMessage", "ListAgents"}


@pytest.fixture
def claude_app(settings_env, tmp_path, project_dir):
    opened = []
    record, plan = tmp_path / "record.json", tmp_path / "plan.json"

    def make(script, default_steps=(), timeout=30, own_setup=False, **more):
        # paths the CLI names are absolute, as the real one's are
        script = json.loads(json.dumps(script).replace("PROJECT", project_dir.as_posix()))
        plan.write_text(json.dumps({"record": str(record), "script": script, **more}),
                        encoding="utf-8")
        cli = ClaudeNativeClient(launcher=FAKE, timeout=timeout, own_setup=own_setup,
                                 env={"FAKE_CLI_PLAN": str(plan)})
        default = ScriptedModel(
            default_steps if isinstance(default_steps, dict) else list(default_steps),
            model_id="big-model")
        app = create_app(load_settings(settings_env), model=default, clients={"Claude": cli})
        client = TestClient(app, base_url="http://127.0.0.1:8790")
        client.__enter__()
        opened.append(client)
        provider = client.post("/api/providers", json={
            "name": "Claude", "kind": "claude_cli", "mode": "native",
            "for_agents": True})  # (B-385: its own sub-agents and roles inside run on it)
        assert provider.status_code == 201, provider.text
        return client, provider.json(), default

    make.record = lambda: json.loads(record.read_text(encoding="utf-8"))
    make.ran = record.exists
    yield make
    for client in opened:
        client.__exit__(None, None, None)


def start(client, project_dir, provider, mode):
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(f"/api/conversations/{cid}", json={  # (a scripted Lead writes: 48 off)
        "permission_mode": mode, "provider_id": provider["id"] if provider else None,
        "lead_hands_code": False},
        headers={"Origin": "http://127.0.0.1:8790"})  # a level is raised from the app's own page
    run = client.post(f"/api/conversations/{cid}/messages",
                      json={"content": "fix the greeting"}).json()["run"]
    return cid, run["id"]


def hello(project_dir):
    return (project_dir / "hello.py").read_text(encoding="utf-8")


# --- it asks before it changes things ----------------------------------------------


def test_claude_code_asks_before_it_writes_and_the_user_approves(
    claude_app, wait_run, project_dir
):
    client, provider, _ = claude_app([{"say": "I will fix it."}, WRITE, {"say": "Fixed."}],
                                     model="claude-sonnet-5-5")
    cid, run_id = start(client, project_dir, provider, "ask")
    snap = wait_status(client, cid, "waiting_approval")
    change = snap["file_changes"][0]
    assert (change["status"], change["path"], change["origin"]) == ("proposed", "hello.py", "cli")
    assert "-print('hi')" in change["diff"] and "+print('hello')" in change["diff"]
    assert hello(project_dir) == "print('hi')\n"  # nothing has been written yet
    assert client.post(f"/api/file-changes/{change['id']}/approve").status_code == 200
    snap = wait_run(client, cid, run_id)

    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert hello(project_dir) == "print('hello')\n"  # written by Claude Code itself
    # one change on record, the one that was approved - not a second one found afterwards
    assert [(c["status"], c["origin"]) for c in snap["file_changes"]] == [("applied", "cli")]
    assert [(t["name"], t["status"], t["origin"]) for t in snap["tool_calls"]] == [
        ("edit_file", "succeeded", "cli")]
    seen = claude_app.record()
    # what was approved is what runs: the input goes back untouched
    assert seen["asked"] == [{"behavior": "allow", "updatedInput": {
        "file_path": f"{project_dir.as_posix()}/hello.py", "content": "print('hello')\n"}}]
    argv = seen["argv"]
    # asked over its own control protocol (slice 89b), not through a tool of KOLONİ's
    assert argv[argv.index("--permission-prompt-tool") + 1] == "stdio"
    assert argv[argv.index("--permission-mode") + 1] == "default"
    assert "--tools" not in argv  # its own tools
    # but not the user's own setup, unless the provider says so
    assert argv[argv.index("--setting-sources") + 1] == "project,local"
    assert argv.count("--strict-mcp-config") == 1
    assert seen["cwd"] == str(project_dir)
    assert "approve" not in seen["tools"] and "spawn_agent" in seen["tools"]
    lead = snap["agents"][0]
    assert (lead["provider_name"], lead["model_id"]) == ("Claude", "claude-sonnet-5-5")
    assert [m["content"] for m in snap["messages"] if m["role"] == "assistant"
            and m["content"]] == ["I will fix it.", "Fixed."]
    # its own price is never taken: a plan's tokens have none, and it prices a local model too
    assert [row["cost"] for row in client.get("/api/usage").json()["by_model"]] == [None]


def test_a_command_that_reads_another_runs_bridge_file_waits_at_full_auto(
    claude_app, wait_run, project_dir
):
    # B-304: with that key it would call KOLONİ's tools as that run's agent.
    line = "Get-Content $env:TEMP\\koloni-cli-other\\bridge.json"
    client, provider, _ = claude_app([
        {"tool": "Bash", "input": {"command": line}, "result": "{}"}, {"say": "Left it."}])
    cid, run_id = start(client, project_dir, provider, "full_auto")
    asked = wait_status(client, cid, "waiting_approval")["commands"][0]
    assert (asked["status"], asked["command"]) == ("proposed", line)
    assert client.post(f"/api/commands/{asked['id']}/reject", json={}).status_code == 200
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert [c["status"] for c in snap["commands"]] == ["rejected"]


def test_a_rejected_write_is_not_made_and_claude_code_is_told(
    claude_app, wait_run, project_dir
):
    client, provider, _ = claude_app([WRITE, {"say": "I left it alone."}])
    cid, run_id = start(client, project_dir, provider, "ask")
    change = wait_status(client, cid, "waiting_approval")["file_changes"][0]
    assert client.post(f"/api/file-changes/{change['id']}/reject").status_code == 200
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert hello(project_dir) == "print('hi')\n"
    assert [c["status"] for c in snap["file_changes"]] == ["rejected"]
    assert [(t["name"], t["status"]) for t in snap["tool_calls"]] == [("edit_file", "denied")]
    verdict = claude_app.record()["asked"][0]
    assert verdict["behavior"] == "deny" and "declined" in verdict["message"]


def test_a_command_of_its_own_waits_for_approval_and_is_recorded(
    claude_app, wait_run, project_dir
):
    client, provider, _ = claude_app([BASH, {"say": "Tests pass."}])
    cid, run_id = start(client, project_dir, provider, "ask")
    asked = wait_status(client, cid, "waiting_approval")["commands"][0]
    assert (asked["status"], asked["command"], asked["origin"]) == ("proposed", "pytest -q", "cli")
    assert client.post(f"/api/commands/{asked['id']}/approve", json={}).status_code == 200
    snap = wait_run(client, cid, run_id)
    done = snap["commands"][0]
    assert (done["status"], done["output"]) == ("exited", "2 passed")
    assert done["exit_code"] is None  # Claude Code does not say; nothing is made up
    assert len(snap["commands"]) == 1
    assert [(t["name"], t["status"]) for t in snap["tool_calls"]] == [("run_command", "succeeded")]


def test_a_rejected_command_does_not_run(claude_app, wait_run, project_dir):
    client, provider, _ = claude_app([{**BASH, "write": ["ran.txt", "x"]}, {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider, "ask")
    asked = wait_status(client, cid, "waiting_approval")["commands"][0]
    assert client.post(f"/api/commands/{asked['id']}/reject").status_code == 200
    snap = wait_run(client, cid, run_id)
    assert not (project_dir / "ran.txt").exists()
    assert [c["status"] for c in snap["commands"]] == ["rejected"]
    assert [(t["name"], t["status"]) for t in snap["tool_calls"]] == [("run_command", "denied")]
    assert claude_app.record()["asked"][0]["behavior"] == "deny"


# --- the permission level decides ----------------------------------------------------


def test_auto_edit_lets_it_write_and_still_asks_about_commands(
    claude_app, wait_run, project_dir
):
    client, provider, _ = claude_app([WRITE, BASH, {"say": "done"}])
    cid, run_id = start(client, project_dir, provider, "auto_edit")
    snap = wait_status(client, cid, "waiting_approval")
    assert hello(project_dir) == "print('hello')\n"  # written without a card
    assert [(c["status"], c["origin"]) for c in snap["file_changes"]] == [("applied", "cli")]
    asked = snap["commands"][0]
    assert asked["status"] == "proposed"
    client.post(f"/api/commands/{asked['id']}/approve", json={})
    assert wait_run(client, cid, run_id)["runs"][0]["status"] == "completed"


def test_full_auto_asks_nothing(claude_app, wait_run, project_dir):
    client, provider, _ = claude_app([WRITE, BASH, {"say": "done"}])
    cid, run_id = start(client, project_dir, provider, "full_auto")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert [c["status"] for c in snap["file_changes"]] == ["applied"]
    assert [(c["status"], c["output"]) for c in snap["commands"]] == [("exited", "2 passed")]
    assert [v["behavior"] for v in claude_app.record()["asked"]] == ["allow", "allow"]


def test_what_it_reads_and_runs_is_asked_of_koloni_and_recorded(
    claude_app, wait_run, project_dir
):
    # (Slice 89b: every tool reaches KOLONİ through its hook - a read and a harmless
    # command too, which Claude Code did without asking before.)
    client, provider, _ = claude_app([
        {"tool": "Read", "input": {"file_path": "PROJECT/hello.py"}, "result": "1\tprint('hi')"},
        {"tool": "Bash", "input": {"command": "echo hi"}, "result": "hi"},
        {"tool": "Bash", "input": {"command": "false"}, "error": "exit 1"},
        {"say": "Looked."}])
    cid, run_id = start(client, project_dir, provider, "full_auto")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert [(t["name"], t["status"], t["origin"]) for t in snap["tool_calls"]] == [
        ("claude__Read", "succeeded", "cli"),
        ("run_command", "succeeded", "cli"), ("run_command", "failed", "cli")]
    assert [(c["command"], c["status"], c["output"]) for c in snap["commands"]] == [
        ("echo hi", "exited", "hi"), ("false", "exited", "exit 1")]
    assert [v["behavior"] for v in claude_app.record()["asked"]] == ["allow"] * 3


def test_a_write_outside_the_project_asks_at_every_level(
    claude_app, wait_run, project_dir, tmp_path
):
    outside = (tmp_path / "elsewhere" / "x.txt").as_posix()
    client, provider, _ = claude_app([
        {"tool": "Write", "input": {"file_path": outside, "content": "x"},
         "write": [outside, "x"]},
        {"say": "done"}])
    cid, run_id = start(client, project_dir, provider, "full_auto")
    snap = wait_status(client, cid, "waiting_approval")
    # (slice 41: KOLONİ's own card for a path outside the project, as for its own tools)
    (asked,) = [t for t in snap["tool_calls"] if t["status"] == "pending"]
    assert asked["name"] == "edit_file" and outside in asked["arguments"]
    client.post(f"/api/tool-calls/{asked['id']}/reject", headers={"Origin": ORIGIN})
    snap = wait_run(client, cid, run_id)
    assert not Path(outside).exists()
    assert claude_app.record()["asked"][0]["behavior"] == "deny"
    assert snap["file_changes"] == []


def test_a_tool_koloni_cannot_show_as_a_diff_is_asked_about_in_words(
    claude_app, wait_run, project_dir
):
    turned = chr(0x202e)                                 # turns the text after it round
    client, provider, _ = claude_app([
        {"tool": "WebFetch", "input": {"url": f"https://example.com/{turned}txt.exe"},
         "result": "<html>"},
        {"say": "Fetched."}])
    cid, run_id = start(client, project_dir, provider, "ask")
    question = wait_status(client, cid, "waiting_approval")["questions"][0]
    assert "WebFetch" in question["question"] and "example.com" in question["question"]
    # KOLONİ's own question, and said to be: not one the agent put to the user
    assert question["leave"] is True and question["options"] == ["Allow", "Deny"]
    # ...so what does not show in the CLI's words is written out in it, not left to act
    assert turned not in question["question"]
    assert turned.encode("unicode_escape").decode() + "txt.exe" in question["question"]
    client.post(f"/api/questions/{question['id']}/answer", json={"answer": "Allow"}, headers={"Origin": ORIGIN})
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert [(t["name"], t["status"]) for t in snap["tool_calls"]] == [
        ("claude__WebFetch", "succeeded")]
    assert claude_app.record()["asked"][0]["behavior"] == "allow"


# --- roles, other agents, stopping ------------------------------------------------------


def test_a_read_only_role_keeps_its_limits_natively(claude_app, wait_run, project_dir):
    client, provider, default = claude_app(
        [WRITE, BASH, {"say": "I may only read."}],
        default_steps=[spawn("Reviewer", "Review hello.py"), text("ok")])
    client.patch(f"/api/roles/{role_id(client, 'Reviewer')}", json={"provider_id": provider["id"]})
    cid, run_id = start(client, project_dir, None, "full_auto")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert hello(project_dir) == "print('hi')\n"
    argv = claude_app.record()["argv"]
    withheld = argv[argv.index("--disallowedTools") + 1]
    assert {"Write", "Edit", "Bash"} <= set(withheld.split(","))
    # and were it to ask all the same, the answer is no
    verdicts = claude_app.record()["asked"]
    assert [v["behavior"] for v in verdicts] == ["deny", "deny"]
    assert "Reviewer role" in verdicts[0]["message"]
    assert snap["file_changes"] == [] and snap["commands"] == []


def test_claude_code_reaches_other_agents_through_koloni(claude_app, wait_run, project_dir):
    client, provider, default = claude_app(
        [{"koloni": "spawn_agent", "args": {"role": "Reviewer", "task": "Review hello.py"}},
         {"say": "Reviewed."}],
        default_steps=[text("Looks fine.")])
    local = client.get("/api/providers").json()[0]
    client.patch(f"/api/roles/{role_id(client, 'Reviewer')}", json={"provider_id": local["id"]})
    cid, run_id = start(client, project_dir, provider, "ask")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert [a["provider_name"] for a in snap["agents"]] == ["Claude", "Local"]
    assert snap["agents"][1]["report"] == "Looks fine."
    assert [(t["name"], t["origin"]) for t in snap["tool_calls"]] == [("spawn_agent", "koloni")]


def test_stop_while_claude_code_waits_for_approval(claude_app, wait_run, project_dir):
    client, provider, _ = claude_app([WRITE, {"hang": True}])
    cid, run_id = start(client, project_dir, provider, "ask")
    wait_status(client, cid, "waiting_approval")
    client.post(f"/api/runs/{run_id}/cancel")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "cancelled"
    assert [c["status"] for c in snap["file_changes"]] == ["rejected"]
    assert hello(project_dir) == "print('hi')\n"


def test_the_level_can_change_while_claude_code_works_but_not_under_codex(
    claude_app, wait_run, project_dir
):
    client, provider, _ = claude_app([WRITE, {"say": "done"}])
    cid, run_id = start(client, project_dir, provider, "ask")
    change = wait_status(client, cid, "waiting_approval")["file_changes"][0]
    # it asks, so nothing is lost by lowering or raising the level under it
    assert client.patch(f"/api/conversations/{cid}", json={"permission_mode": "auto_edit"},
                        headers={"Origin": "http://127.0.0.1:8790"}).status_code == 200
    client.post(f"/api/file-changes/{change['id']}/approve")
    assert wait_run(client, cid, run_id)["runs"][0]["status"] == "completed"


def test_in_a_discussion_claude_code_speaks_with_its_own_tools_off():
    native = ClaudeNativeClient("claude-path", "opus", timeout=30)
    talker = native.talker()
    assert isinstance(talker, ClaudeSessionClient)
    assert (talker._executable, talker._model) == ("claude-path", "opus")



# --- review fixes ---------------------------------------------------------------------


def test_a_read_only_role_cannot_write_or_run_through_any_other_tool(
    claude_app, wait_run, project_dir
):
    # Claude Code has tools KOLONİ has never heard of: the user's own MCP servers, its
    # sub-agents. A role that may only read gets none of them at any permission level.
    client, provider, default = claude_app(
        [{"tool": "mcp__filesystem__write_file", "input": {"path": "hello.py"},
          "write": ["hello.py", "broken"]},
         {"tool": "mcp__shell__run", "input": {"command": "x"},
          "write": ["ran.txt", "x"]},
         {"tool": "Agent", "input": {"prompt": "write things"},
          "write": ["sub.txt", "x"]},
         {"tool": "Grep", "input": {"pattern": "hi"}, "result": "hello.py:1"},
         {"say": "I may only read."}],
        default_steps=[spawn("Reviewer", "Review hello.py"), text("ok")])
    client.patch(f"/api/roles/{role_id(client, 'Reviewer')}", json={"provider_id": provider["id"]})
    cid, run_id = start(client, project_dir, None, "full_auto")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert hello(project_dir) == "print('hi')\n"
    assert not (project_dir / "ran.txt").exists() and not (project_dir / "sub.txt").exists()
    verdicts = [v["behavior"] for v in claude_app.record()["asked"]]
    assert verdicts == ["deny", "deny", "deny", "allow"]
    assert "Reviewer role" in claude_app.record()["asked"][0]["message"]


def test_nobody_but_claude_codes_own_permission_flow_gets_leave(
    claude_app, wait_run, project_dir
):
    # The model calls the approve tool itself, as if to give itself leave.
    made_up = {"tool_name": "Bash", "input": {"command": "rm -rf everything"},
               "tool_use_id": "toolu_made_up"}
    client, provider, _ = claude_app([
        {"koloni": "approve", "args": made_up},
        {"koloni": "approve", "args": {"tool_name": "Write", "input": {
            "file_path": "PROJECT/hello.py", "content": "x"}}},
        {"say": "done"}])
    cid, run_id = start(client, project_dir, provider, "full_auto")
    snap = wait_run(client, cid, run_id, timeout=15)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    # (Since slice 89b leave is asked over its control protocol: no such tool is offered,
    # and its hook lets through only those that are.)
    seen = claude_app.record()
    assert [h["hookSpecificOutput"]["permissionDecision"] for h in seen["hooks"]] == [
        "ask", "ask"]
    assert seen["results"] == []
    # and nothing is put on record as if a command or a change had been asked for
    assert snap["commands"] == [] and snap["file_changes"] == [] and snap["questions"] == []
    assert snap["tool_calls"] == []


def test_what_was_approved_and_never_reported_is_settled_when_the_run_ends(
    claude_app, wait_run, project_dir
):
    client, provider, _ = claude_app([
        {**WRITE, "silent": True},                       # written, but its result never comes
        {**BASH, "silent": True},
        {"say": "done"}])
    cid, run_id = start(client, project_dir, provider, "full_auto")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert hello(project_dir) == "print('hello')\n"
    assert [c["status"] for c in snap["commands"]] == ["interrupted"]
    assert not [t for t in snap["tool_calls"] if t["status"] in ("pending", "running")]


def test_stop_after_approval_leaves_one_true_record_of_the_write(
    claude_app, wait_run, project_dir
):
    client, provider, _ = claude_app([{**WRITE, "pause": 30}])
    cid, run_id = start(client, project_dir, provider, "ask")
    change = wait_status(client, cid, "waiting_approval")["file_changes"][0]
    client.post(f"/api/file-changes/{change['id']}/approve")
    for _ in range(300):  # the CLI has written the file and is still busy
        if hello(project_dir) == "print('hello')\n":
            break
        time.sleep(0.02)
    client.post(f"/api/runs/{run_id}/cancel")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "cancelled"
    assert [(c["status"], c["path"]) for c in snap["file_changes"]] == [("applied", "hello.py")]


def test_a_write_that_claude_code_is_slow_to_make_is_approved_at_once_and_never_rejected(
    claude_app, wait_run, project_dir
):
    """The yes is on record when it is given, though no place was waited for: the CLI
    makes the change itself, and here never does. Stop does not turn the yes into a no."""
    slow = {key: value for key, value in WRITE.items() if key != "write"}
    client, provider, _ = claude_app([{**slow, "pause": 30}])
    cid, run_id = start(client, project_dir, provider, "ask")
    change = wait_status(client, cid, "waiting_approval")["file_changes"][0]
    began = time.monotonic()
    said = client.post(f"/api/file-changes/{change['id']}/approve")
    assert said.status_code == 200 and said.json()["status"] == "approved"
    assert time.monotonic() - began < 2
    client.post(f"/api/runs/{run_id}/cancel")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "cancelled"
    assert [c["status"] for c in snap["file_changes"]] == ["failed"]
    assert [t["result"] for t in snap["tool_calls"]] == [
        "error: it was approved, and the CLI never made the change"]
    assert hello(project_dir) == "print('hi')\n"


def test_claude_codes_own_settings_are_never_changed_without_asking(
    claude_app, wait_run, project_dir
):
    grant = {"tool": "Write", "input": {
        "file_path": "PROJECT/.claude/settings.local.json",
        "content": '{"permissions": {"allow": ["Bash"]}}'},
        "write": [".claude/settings.local.json", "{}"]}
    client, provider, _ = claude_app([grant, {"say": "done"}])
    cid, run_id = start(client, project_dir, provider, "full_auto")
    question = wait_status(client, cid, "waiting_approval")["questions"][0]
    assert "its own settings" in question["question"]
    assert ".claude/settings.local.json" in question["question"]
    client.post(f"/api/questions/{question['id']}/answer", json={"answer": "Deny"}, headers={"Origin": ORIGIN})
    wait_run(client, cid, run_id)
    assert not (project_dir / ".claude" / "settings.local.json").exists()


@pytest.mark.parametrize("named", [".CLAUDE/settings.json", ".claude./settings.json"])
def test_claude_codes_own_settings_are_asked_about_by_any_name_windows_opens(
    claude_app, wait_run, project_dir, named
):
    """With no `.claude` yet, `resolve()` keeps the name as written: on NTFS these are
    still the folder Claude Code reads its settings from."""
    grant = {"tool": "Write", "input": {
        "file_path": f"PROJECT/{named}", "content": '{"permissions": {"allow": ["Bash"]}}'},
        "write": [named, "{}"]}
    client, provider, _ = claude_app([grant, {"say": "done"}])
    cid, run_id = start(client, project_dir, provider, "full_auto")
    question = wait_status(client, cid, "waiting_approval")["questions"][0]
    assert "its own settings" in question["question"]
    client.post(f"/api/questions/{question['id']}/answer", json={"answer": "Deny"}, headers={"Origin": ORIGIN})
    wait_run(client, cid, run_id)
    assert not (project_dir / ".claude").exists()


# What tells later turns what they may do, or runs by itself (`NOT_WRITTEN_UNATTENDED`).
STANDING = [".git/hooks/pre-commit", ".github/workflows/ci.yml",
            "sub/.claude/settings.json", ".koloni/settings.json"]
# K-fullauto-sorma 2: an instruction file alone is asked below Full auto, not at it.
INSTRUCTIONS = ["CLAUDE.md", "sub/AGENTS.md"]


def standing_write(named):
    return {"tool": "Write", "input": {"file_path": f"PROJECT/{named}",
            "content": "x"}, "write": [named, "x"]}


@pytest.mark.parametrize("named", INSTRUCTIONS)
def test_claude_codes_write_of_an_instruction_file_is_not_asked_at_full_auto(
    claude_app, wait_run, project_dir, named
):
    client, provider, _ = claude_app([standing_write(named), {"say": "done"}])
    cid, run_id = start(client, project_dir, provider, "full_auto")
    snap = wait_run(client, cid, run_id)
    assert [v["behavior"] for v in claude_app.record()["asked"]] == ["allow"]
    assert (project_dir / named).read_text(encoding="utf-8") == "x" and snap["questions"] == []


@pytest.mark.parametrize("named, mode", [*((one, "full_auto") for one in STANDING),
                                         *((one, "auto_edit") for one in INSTRUCTIONS)])
def test_claude_codes_write_of_a_file_that_stands_over_later_turns_is_asked_at_full_auto(
    claude_app, wait_run, project_dir, named, mode
):
    """As for KOLONİ's own write tools: at every level, at any depth (K-claude-yazma)."""
    client, provider, _ = claude_app([standing_write(named), {"say": "done"}])
    cid, run_id = start(client, project_dir, provider, mode)
    snap = wait_status(client, cid, "waiting_approval")
    proposed = [c for c in snap["file_changes"] if c["status"] == "proposed"]
    if proposed:
        client.post(f"/api/file-changes/{proposed[0]['id']}/reject")
    else:
        client.post(f"/api/questions/{snap['questions'][0]['id']}/answer",
                    json={"answer": "Deny"}, headers={"Origin": ORIGIN})
    wait_run(client, cid, run_id)
    assert [v["behavior"] for v in claude_app.record()["asked"]] == ["deny"]
    assert not (project_dir / named).exists()


def test_an_edit_of_a_file_with_windows_line_endings_still_shows_its_diff(
    claude_app, wait_run, project_dir
):
    (project_dir / "two.py").write_bytes(b"a = 1\r\nb = 2\r\nc = 3\r\n")
    edit = {"tool": "Edit", "input": {
        "file_path": "PROJECT/two.py", "old_string": "a = 1\nb = 2", "new_string": "a = 10\nb = 20"},
        "write": ["two.py", "a = 10\r\nb = 20\r\nc = 3\r\n"]}
    client, provider, _ = claude_app([edit, {"say": "done"}])
    cid, run_id = start(client, project_dir, provider, "ask")
    snap = wait_status(client, cid, "waiting_approval")
    assert snap["questions"] == []  # a real diff, not a question in words
    change = snap["file_changes"][0]
    assert "-a = 1" in change["diff"] and "+a = 10" in change["diff"] and "+b = 20" in change["diff"]
    client.post(f"/api/file-changes/{change['id']}/approve")
    wait_run(client, cid, run_id)


def test_kolonis_own_tools_need_no_leave_and_its_sub_agents_words_are_not_its_own(
    claude_app, wait_run, project_dir
):
    client, provider, _ = claude_app([
        {"say": "Main agent speaking."},
        {"say": "A sub-agent of Claude Code speaking.", "parent": "toolu_sub"},
        {"say": "Done."}])
    cid, run_id = start(client, project_dir, provider, "ask")
    snap = wait_run(client, cid, run_id)
    assert [m["content"] for m in snap["messages"] if m["role"] == "assistant"
            and m["content"]] == ["Main agent speaking.\n\nDone."]
    argv = claude_app.record()["argv"]
    allowed = set(argv[argv.index("--allowedTools") + 1].split(","))
    assert "mcp__koloni__spawn_agent" in allowed and "mcp__koloni__ask_user" in allowed
    assert "mcp__koloni__approve" not in allowed  # that one it may only be asked through


def test_a_request_without_an_id_or_for_kolonis_own_tool_is_answered_safely(
    claude_app, wait_run, project_dir
):
    client, provider, _ = claude_app([
        {"tool": "Write", "no_id": True,
         "input": {"file_path": "PROJECT/hello.py", "content": "x"}, "write": ["hello.py", "x"]},
        {"tool": "mcp__koloni__approve", "input": {"tool_name": "Bash"}},
        {"tool": "mcp__koloni__spawn_agent", "input": {"role": "Reviewer"}},
        {"say": "done"}])
    cid, run_id = start(client, project_dir, provider, "full_auto")
    snap = wait_run(client, cid, run_id)
    # The hook lets through only the tools of KOLONİ's it offered; a write it cannot tie to
    # a tool use is refused. (No approve is offered: its tool server refuses that call.)
    seen = claude_app.record()
    assert [h["hookSpecificOutput"]["permissionDecision"] for h in seen["hooks"]] == [
        "ask", "ask", "allow"]
    assert [v["behavior"] for v in seen["asked"]] == ["deny", "allow"]
    assert hello(project_dir) == "print('hi')\n"
    assert snap["file_changes"] == [] and snap["commands"] == []


def test_a_command_without_an_exit_code_says_so_plainly(claude_app, wait_run, project_dir):
    client, provider, _ = claude_app([BASH, {"say": "done"}])
    cid, run_id = start(client, project_dir, provider, "full_auto")
    snap = wait_run(client, cid, run_id)
    assert snap["tool_calls"][0]["result"].startswith("no exit code reported\n2 passed")


# --- its own sub-agents ---------------------------------------------------------------

# Claude Code's own sub-agent is its Agent tool. Measured (6 Oct 2026): every event of it
# names that tool use; a task_started system event names the tool use and says whether it
# works in the background; a task_notification names it again, with its status and its
# report as "summary". In the background the tool returns at once ("launched"); in the
# foreground it returns after the notification, with the report wrapped in a note.
AGENT = {"tool": "Agent", "id": "toolu_sub", "result": "Async agent launched.",
         "input": {"description": "Look around", "subagent_type": "Explore",
                   "prompt": "Read hello.py and say what it prints"}}
NOTIFIED = {"system": {"subtype": "task_notification", "tool_use_id": "toolu_sub",
                       "status": "completed", "summary": "It prints hi."}}
SUB = {"parent": "toolu_sub"}


def calls_by_name(snap):
    return {call["name"]: call for call in snap["tool_calls"]}


def test_its_own_sub_agent_is_one_tool_call_and_what_it_does_hangs_off_it(
    claude_app, wait_run, project_dir
):
    client, provider, _ = claude_app([
        {"say": "I will ask a helper."},
        AGENT,
        {"system": {"subtype": "task_started", "tool_use_id": "toolu_sub"}},
        {"tool": "Read", "input": {"file_path": "PROJECT/hello.py"}, "result": "print('hi')",
         **SUB},
        {"tool": "Bash", "input": {"command": "echo hi"}, "result": "hi", **SUB},
        {**WRITE, **SUB},
        {"say": "Not there yet.", **SUB},
        {"say": "It prints hi.", **SUB},
        NOTIFIED,
        {"tool": "Grep", "input": {"pattern": "hi"}, "result": "hello.py:1"},
        {"say": "Done."}])
    cid, run_id = start(client, project_dir, provider, "full_auto")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    calls = calls_by_name(snap)
    sub = calls["claude__Agent"]
    # not an agent of KOLONİ's: a tool call of the one agent there is
    assert len(snap["agents"]) == 1
    assert (sub["status"], sub["origin"], sub["parent_call_id"]) == ("succeeded", "cli", None)
    assert json.loads(sub["arguments"])["description"] == "Look around"
    assert sub["result"] == "It prints hi."  # its last words
    inner = {name: call["parent_call_id"] for name, call in calls.items()}
    assert inner == {"claude__Agent": None, "claude__Read": sub["id"], "run_command": sub["id"],
                     "edit_file": sub["id"], "claude__Grep": None}
    # its command and its change are the agent's records; whose they were is on their call
    assert snap["commands"][0]["tool_call_id"] == calls["run_command"]["id"]
    assert snap["file_changes"][0]["tool_call_id"] == calls["edit_file"]["id"]
    said = [m["content"] for m in snap["messages"] if m["role"] == "assistant" and m["content"]]
    assert said == ["I will ask a helper.", "Done."]


def test_a_sub_agent_that_works_in_the_foreground_ends_with_its_tools_result(
    claude_app, wait_run, project_dir
):
    client, provider, _ = claude_app([
        {**AGENT, "open": True},
        {"tool": "Read", "input": {"file_path": "PROJECT/hello.py"}, "result": "x", **SUB},
        {"say": "It prints hi.", **SUB},
        {"result_for": "toolu_sub", "result": "It prints hi."},
        {"say": "Done."}])
    cid, run_id = start(client, project_dir, provider, "full_auto")
    snap = wait_run(client, cid, run_id)
    calls = calls_by_name(snap)
    sub = calls["claude__Agent"]
    assert (sub["status"], sub["result"]) == ("succeeded", "It prints hi.")
    assert calls["claude__Read"]["parent_call_id"] == sub["id"]
    assert len(snap["tool_calls"]) == 2


def test_the_task_shown_before_the_launch_returns_does_not_end_the_sub_agent(
    claude_app, wait_run, project_dir
):
    client, provider, _ = claude_app([
        {**AGENT, "open": True},
        {"task": "Read hello.py and say what it prints", **SUB},
        {"result_for": "toolu_sub", "result": "Async agent launched."},
        {"say": "It prints hi.", **SUB},
        NOTIFIED,
        {"say": "Done."}])
    cid, run_id = start(client, project_dir, provider, "full_auto")
    sub = calls_by_name(wait_run(client, cid, run_id))["claude__Agent"]
    assert (sub["status"], sub["result"]) == ("succeeded", "It prints hi.")


def test_what_a_sub_agent_does_after_it_was_said_to_be_done_is_still_its_own(
    claude_app, wait_run, project_dir
):
    client, provider, _ = claude_app([
        {**AGENT, "open": True},
        {"say": "Starting.", **SUB},
        {"result_for": "toolu_sub", "result": "It prints hi."},
        {"tool": "Read", "input": {"file_path": "PROJECT/hello.py"}, "result": "x", **SUB},
        {"say": "Done."}])
    cid, run_id = start(client, project_dir, provider, "full_auto")
    calls = calls_by_name(wait_run(client, cid, run_id))
    assert calls["claude__Read"]["parent_call_id"] == calls["claude__Agent"]["id"]


def test_a_sub_agent_that_fails_or_is_stopped_says_so(claude_app, wait_run, project_dir):
    failed = {"system": {**NOTIFIED["system"], "status": "failed", "summary": "It broke."}}
    client, provider, _ = claude_app([AGENT, failed, {"say": "Done."}])
    cid, run_id = start(client, project_dir, provider, "full_auto")
    sub = calls_by_name(wait_run(client, cid, run_id))["claude__Agent"]
    # it said nothing itself: what the CLI says of it is all there is
    assert (sub["status"], sub["result"]) == ("failed", "It broke.")


def test_what_a_sub_agent_asks_leave_for_is_recorded_under_it(claude_app, wait_run, project_dir):
    client, provider, _ = claude_app([
        {**AGENT},
        {**BASH, **SUB},
        {"say": "Tests pass.", **SUB},
        {"system": {**NOTIFIED["system"], "summary": "Tests pass."}},
        {"say": "Done."}])
    cid, run_id = start(client, project_dir, provider, "ask")
    # leave for the sub-agent itself is asked in words; nothing runs before the answer
    snap = wait_status(client, cid, "waiting_approval")
    question = snap["questions"][0]
    assert "Agent" in question["question"]
    client.post(f"/api/questions/{question['id']}/answer", json={"answer": "Allow"}, headers={"Origin": ORIGIN})
    for _ in range(300):
        snap = client.get(f"/api/conversations/{cid}").json()
        if snap["commands"]:
            break
        time.sleep(0.02)
    calls = calls_by_name(snap)
    # the command waits for the user, and already says whose it is
    assert snap["commands"][0]["status"] == "proposed"
    assert calls["run_command"]["parent_call_id"] == calls["claude__Agent"]["id"]
    assert calls["claude__Agent"]["status"] == "running"
    client.post(f"/api/commands/{snap['commands'][0]['id']}/approve", json={})
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    # one record for the sub-agent: the one leave was asked for
    assert [(c["name"], c["status"]) for c in snap["tool_calls"]] == [
        ("claude__Agent", "succeeded"), ("run_command", "succeeded")]
    assert calls_by_name(snap)["claude__Agent"]["result"] == "Tests pass."


def test_a_sub_agent_still_at_work_does_not_stay_running_after_stop(
    claude_app, wait_run, project_dir
):
    client, provider, _ = claude_app([AGENT, {"say": "Looking.", **SUB}, {"hang": True}])
    cid, run_id = start(client, project_dir, provider, "full_auto")
    for _ in range(500):
        snap = client.get(f"/api/conversations/{cid}").json()
        if snap["tool_calls"]:
            break
        time.sleep(0.02)
    assert [(c["name"], c["status"]) for c in snap["tool_calls"]] == [("claude__Agent", "running")]
    client.post(f"/api/runs/{run_id}/cancel")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "cancelled"
    assert [(c["name"], c["status"]) for c in snap["tool_calls"]] == [
        ("claude__Agent", "interrupted")]


def test_a_sub_agent_never_reported_done_is_not_called_done_when_the_run_ends(
    claude_app, wait_run, project_dir
):
    client, provider, _ = claude_app([
        AGENT,
        {"tool": "Read", "input": {"file_path": "PROJECT/hello.py"}, "result": "x", **SUB},
        {"say": "Done."}])
    cid, run_id = start(client, project_dir, provider, "full_auto")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert [(c["name"], c["status"]) for c in snap["tool_calls"]] == [
        ("claude__Agent", "interrupted"), ("claude__Read", "succeeded")]


def test_a_sub_agent_that_was_refused_is_no_sub_agent(claude_app, wait_run, project_dir):
    client, provider, _ = claude_app([{**AGENT}, {"say": "Done."}])
    cid, run_id = start(client, project_dir, provider, "ask")
    question = wait_status(client, cid, "waiting_approval")["questions"][0]
    client.post(f"/api/questions/{question['id']}/answer", json={"answer": "Deny"}, headers={"Origin": ORIGIN})
    snap = wait_run(client, cid, run_id)
    assert [(c["name"], c["status"]) for c in snap["tool_calls"]] == [("claude__Agent", "denied")]


def started(use_id="toolu_sub", background=False):
    return {"system": {"subtype": "task_started", "tool_use_id": use_id,
                       "is_backgrounded": background}}


def test_in_the_foreground_as_measured_it_is_one_call_with_its_report(
    claude_app, wait_run, project_dir
):
    client, provider, _ = claude_app([
        {**AGENT, "open": True},
        started(),
        {"task": "Read hello.py and say what it prints", **SUB},
        {"tool": "Read", "input": {"file_path": "PROJECT/hello.py"}, "result": "x", **SUB},
        NOTIFIED,
        {"result_for": "toolu_sub", "result": "[Subagent hand-back] ... It prints hi."},
        {"say": "Done."}])
    cid, run_id = start(client, project_dir, provider, "full_auto")
    snap = wait_run(client, cid, run_id)
    assert [(c["name"], c["status"], c["result"]) for c in snap["tool_calls"]
            if c["name"] == "claude__Agent"] == [("claude__Agent", "succeeded", "It prints hi.")]
    assert len(snap["tool_calls"]) == 2


def test_a_silent_sub_agent_in_the_foreground_ends_with_its_tools_result(
    claude_app, wait_run, project_dir
):
    client, provider, _ = claude_app([
        {**AGENT, "open": True}, started(),
        {"result_for": "toolu_sub", "result": "It prints hi."}, {"say": "Done."}])
    cid, run_id = start(client, project_dir, provider, "full_auto")
    sub = calls_by_name(wait_run(client, cid, run_id))["claude__Agent"]
    assert (sub["status"], sub["result"]) == ("succeeded", "It prints hi.")


def test_one_in_the_background_heard_before_its_launch_returned_is_not_ended_by_it(
    claude_app, wait_run, project_dir
):
    client, provider, _ = claude_app([
        {**AGENT, "open": True}, started(background=True),
        {"say": "Starting.", **SUB},
        {"result_for": "toolu_sub", "result": "Async agent launched."},
        {"tool": "Read", "input": {"file_path": "PROJECT/hello.py"}, "result": "x", **SUB},
        NOTIFIED, {"say": "Done."}])
    cid, run_id = start(client, project_dir, provider, "full_auto")
    calls = calls_by_name(wait_run(client, cid, run_id))
    assert (calls["claude__Agent"]["status"], calls["claude__Agent"]["result"]) == (
        "succeeded", "It prints hi.")
    assert calls["claude__Read"]["parent_call_id"] == calls["claude__Agent"]["id"]


def test_a_notice_that_names_no_sub_agent_ends_none(claude_app, wait_run, project_dir):
    other = {"system": {"subtype": "task_notification", "status": "completed",
                        "summary": "the build finished"}}
    client, provider, _ = claude_app([AGENT, {"say": "Looking.", **SUB}, other, {"say": "Done."}])
    cid, run_id = start(client, project_dir, provider, "full_auto")
    sub = calls_by_name(wait_run(client, cid, run_id))["claude__Agent"]
    assert sub["status"] == "interrupted" and "build" not in (sub["result"] or "")


def test_an_ending_koloni_does_not_know_is_not_called_a_success(
    claude_app, wait_run, project_dir
):
    killed = {"system": {**NOTIFIED["system"], "status": "killed", "summary": "It was killed."}}
    client, provider, _ = claude_app([AGENT, {"say": "Looking.", **SUB}, killed, {"say": "Done."}])
    cid, run_id = start(client, project_dir, provider, "full_auto")
    sub = calls_by_name(wait_run(client, cid, run_id))["claude__Agent"]
    assert (sub["status"], sub["result"]) == ("interrupted", "It was killed.")


def test_two_sub_agents_at_once_each_keep_their_own_work_and_ending(
    claude_app, wait_run, project_dir
):
    second = {**AGENT, "id": "toolu_two",
              "input": {**AGENT["input"], "description": "Second look"}}
    two = {"parent": "toolu_two"}
    client, provider, _ = claude_app([
        AGENT, second, started(background=True), started("toolu_two", background=True),
        {"tool": "Glob", "input": {"pattern": "*.py"}, "result": "hello.py", **two},
        {"tool": "Read", "input": {"file_path": "PROJECT/hello.py"}, "result": "x", **SUB},
        {"system": {**NOTIFIED["system"], "tool_use_id": "toolu_two", "summary": "One file."}},
        {"tool": "Grep", "input": {"pattern": "hi"}, "result": "hello.py:1", **SUB},
        NOTIFIED, {"say": "Done."}])
    cid, run_id = start(client, project_dir, provider, "full_auto")
    snap = wait_run(client, cid, run_id)
    subs = {json.loads(c["arguments"])["description"]: c for c in snap["tool_calls"]
            if c["name"] == "claude__Agent"}
    assert {k: (c["status"], c["result"]) for k, c in subs.items()} == {
        "Look around": ("succeeded", "It prints hi."), "Second look": ("succeeded", "One file.")}
    under = {c["name"]: c["parent_call_id"] for c in snap["tool_calls"]
             if c["name"] != "claude__Agent"}
    assert under == {"claude__Glob": subs["Second look"]["id"],
                     "claude__Read": subs["Look around"]["id"],
                     "claude__Grep": subs["Look around"]["id"]}


def test_a_sub_agent_opened_by_a_sub_agent_hangs_off_that_sub_agent(
    claude_app, wait_run, project_dir
):
    inner = {**AGENT, "id": "toolu_in", "input": {**AGENT["input"], "description": "Dig deeper"},
             **SUB}
    deep = {"parent": "toolu_in"}
    client, provider, _ = claude_app([
        AGENT, started(background=True),
        inner, started("toolu_in", background=True),
        {"tool": "Read", "input": {"file_path": "PROJECT/hello.py"}, "result": "x", **deep},
        {"system": {**NOTIFIED["system"], "tool_use_id": "toolu_in", "summary": "Deep enough."}},
        {"tool": "Grep", "input": {"pattern": "hi"}, "result": "hello.py:1", **SUB},
        NOTIFIED, {"say": "Done."}])
    cid, run_id = start(client, project_dir, provider, "full_auto")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    subs = {json.loads(c["arguments"])["description"]: c for c in snap["tool_calls"]
            if c["name"] == "claude__Agent"}
    outer, within = subs["Look around"], subs["Dig deeper"]
    # the canvas draws one box inside the other from exactly this
    assert (outer["parent_call_id"], within["parent_call_id"]) == (None, outer["id"])
    assert {k: (c["status"], c["result"]) for k, c in subs.items()} == {
        "Look around": ("succeeded", "It prints hi."), "Dig deeper": ("succeeded", "Deep enough.")}
    under = {c["name"]: c["parent_call_id"] for c in snap["tool_calls"]
             if c["name"] != "claude__Agent"}
    assert under == {"claude__Read": within["id"], "claude__Grep": outer["id"]}


# Measured on 2.1.311 (27 Oct 2026, B-136): its sub-agent is launched in the background, the
# turn that launched it ends with a first result, and after the notification it takes another
# turn on the report, which ends with a second.
LAUNCHED = [{**AGENT, "open": True}, started(background=True),
            {"result_for": "toolu_sub", "result": "Async agent launched."}]
FIRST = {"emit": {"type": "result", "subtype": "success", "is_error": False, "result": "",
                  "usage": {"input_tokens": 200, "output_tokens": 10}}}


def test_a_result_while_its_sub_agent_works_in_the_background_does_not_end_the_turn(
    claude_app, wait_run, project_dir
):
    client, provider, _ = claude_app([
        *LAUNCHED, {"say": "It is at work."}, FIRST,
        {"tool": "Read", "input": {"file_path": "PROJECT/hello.py"}, "result": "x", **SUB},
        NOTIFIED, {"say": "It prints hi."}])
    cid, run_id = start(client, project_dir, provider, "full_auto")
    snap = wait_run(client, cid, run_id)
    run = snap["runs"][0]
    assert run["status"] == "completed", run["error"]
    said = [m["content"] for m in snap["messages"] if m["role"] == "assistant" and m["content"]]
    assert said[-1].endswith("It prints hi.")
    calls = calls_by_name(snap)
    assert calls["claude__Agent"]["status"] == "succeeded"
    assert calls["claude__Read"]["parent_call_id"] == calls["claude__Agent"]["id"]
    # both turns: 200, then 400 and 100 read from its cache; 10, then 30
    assert (run["input_tokens"], run["output_tokens"]) == (700, 40)


@pytest.mark.parametrize("launched", [LAUNCHED, [AGENT, started(background=True)]],
                         ids=["said-before-its-launch-returned", "said-after"])
def test_its_sub_agent_at_work_in_the_background_is_not_silence(
    claude_app, wait_run, project_dir, launched
):
    client, provider, _ = claude_app(
        [*launched, FIRST, {"sleep": 7}, NOTIFIED, {"say": "It prints hi."}], timeout=5)
    cid, run_id = start(client, project_dir, provider, "full_auto")
    run = wait_run(client, cid, run_id, timeout=20)["runs"][0]
    assert run["status"] == "completed", run["error"]


def test_it_ending_while_its_sub_agent_works_in_the_background_is_said_to_cut_it_off(
    claude_app, wait_run, project_dir
):
    # (The stand-in ends after its last result: the sub-agent was never said to be done.)
    client, provider, _ = claude_app([*LAUNCHED, {"say": "It is at work."}])
    cid, run_id = start(client, project_dir, provider, "full_auto")
    # (its own process, started and ended: 1.4 s alone, past 5 s on a busy machine)
    run = wait_run(client, cid, run_id, timeout=20)["runs"][0]
    assert run["status"] == "failed"
    assert "background" in run["error"] and "cut off" in run["error"]


# --- in a turn nobody is watching (slice 18a) -------------------------------------------

ORIGIN = "http://127.0.0.1:8790"
NOBODY = "nobody is here to ask"
LEVELS = ["ask", "auto_edit", "full_auto"]
RAN = {**BASH, "write": ["ran.txt", "x"]}  # a command that leaves a mark when it really runs


def unattended(client, project_dir, provider, level, wait_run, first_line=False, **permissions):
    """Start a trigger's turn on Claude Code in a conversation at `level`; returns the
    snapshot when it is over, the run, and every status the run was ever given.

    Claude Code with its own tools is not started in a turn nobody is watching at all
    (`first_line`: the test of that). The tests below are of the second line, should the
    first ever give way - what it asks leave for is answered by the trigger's own leave,
    and nothing waits - so they switch the first line off."""
    client.headers["Origin"] = ORIGIN
    if not first_line:
        client.app.state.runner._cannot_be_held = lambda model, provider=None: False
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    body = {"name": "watch", "kind": "schedule", "conversation_id": cid,
            "message": "look the project over", "config": {"every_minutes": 60}}
    if permissions:
        # A trigger's commands are rules of its conversation's allow list, by their ids.
        rules = [
            client.post(f"/api/conversations/{cid}/allowed-commands",
                        json={"prefix": line}).json()["id"]
            for line in permissions.pop("commands", [])
        ]
        body["permissions"] = {"write": False, "agents": 0, **permissions, "commands": rules}
    made = client.post(f"/api/projects/{pid}/triggers", json=body)
    assert made.status_code == 201, made.text
    # (After: a trigger is not made on a CLI with its own tools, K-tetik-native-uyari. Claude
    # Code is the Lead that writes here: K-48 refuses one that hands code on.)
    assert client.patch(f"/api/conversations/{cid}", json={
        "permission_mode": level, "provider_id": provider["id"],
        "lead_hands_code": False}).status_code == 200
    statuses, emit = [], client.app.state.bus.emit

    def watched(conversation_id, run_id, kind, payload):
        if kind.startswith("run."):
            statuses.append(payload["status"])
        return emit(conversation_id, run_id, kind, payload)

    client.app.state.bus.emit = watched
    run_id = client.post(f"/api/triggers/{made.json()['id']}/run").json()["run_id"]
    snap = wait_run(client, cid, run_id, timeout=20)
    run = next(r for r in snap["runs"] if r["id"] == run_id)
    assert run["unattended"] is True
    return snap, run, statuses


def nothing_was_asked(snap, statuses):
    assert "waiting_approval" not in statuses, statuses
    assert snap["questions"] == []
    assert not [c for c in snap["commands"] if c["status"] in ("proposed", "rejected")]
    assert not [f for f in snap["file_changes"] if f["status"] in ("proposed", "rejected")]
    assert not [t for t in snap["tool_calls"] if t["status"] in ("pending", "running")]


@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize("below", [False, True])
def test_claude_code_with_its_own_tools_is_not_started_in_a_turn_nobody_is_watching(
    claude_app, wait_run, project_dir, level, below
):
    """It asks KOLONİ before it writes or runs - when it chooses to: it reads wherever it
    likes, has web tools and sub-agents of its own, and the user's own settings can allow
    things beforehand. With nobody watching it cannot be held, so it is refused before it
    starts: as the lead the turn fails, as a sub-agent's provider it is not opened."""
    client, provider, default = claude_app([WRITE, RAN, {"say": "done"}])
    if below:
        default.steps[:] = [
            step(call("spawn_agent", {"role": "Coder", "task": "change things"}, "s")),
            text("could not")]
        client.patch(f"/api/roles/{role_id(client, 'Coder')}",
                     json={"provider_id": provider["id"]})
        provider = client.get("/api/providers").json()[0]
    snap, run, statuses = unattended(
        client, project_dir, provider, level, wait_run, first_line=True,
        write=True, commands=["pytest -q"], agents=4)
    assert not claude_app.ran()
    assert hello(project_dir) == "print('hi')\n" and not (project_dir / "ran.txt").exists()
    assert snap["file_changes"] == [] and snap["commands"] == []
    if below:
        assert run["status"] == "completed", run
        ((name, status, said),) = [
            (t["name"], t["status"], t["result"]) for t in snap["tool_calls"]]
        assert (name, status) == ("spawn_agent", "denied"), said
        assert "its own tools" in said and NOBODY in said
        assert len(snap["agents"]) == 1
    else:
        assert run["status"] == "failed", run
        assert "its own tools" in run["error"] and NOBODY in run["error"]
        assert snap["tool_calls"] == []
    nothing_was_asked(snap, statuses)


@pytest.mark.parametrize("level", LEVELS)
def test_unattended_claude_code_changes_and_runs_nothing_its_trigger_does_not_allow(
    claude_app, wait_run, project_dir, level
):
    client, provider, _ = claude_app([WRITE, RAN, {"say": "I could only read."}])
    snap, run, statuses = unattended(client, project_dir, provider, level, wait_run)
    assert run["status"] == "completed", run
    assert hello(project_dir) == "print('hi')\n"
    assert not (project_dir / "ran.txt").exists()
    verdicts = claude_app.record()["asked"]
    assert [v["behavior"] for v in verdicts] == ["deny", "deny"]
    assert all(NOBODY in v["message"] for v in verdicts), verdicts
    # refused before anything was put on record as a change or a command to decide
    assert snap["file_changes"] == [] and snap["commands"] == []
    assert [(t["name"], t["status"]) for t in snap["tool_calls"]] == [
        ("edit_file", "denied"), ("run_command", "denied")]
    assert all(NOBODY in t["result"] for t in snap["tool_calls"])
    nothing_was_asked(snap, statuses)


@pytest.mark.parametrize("level", LEVELS)
def test_unattended_claude_code_does_what_its_trigger_allows_without_asking(
    claude_app, wait_run, project_dir, level
):
    other = {"tool": "Bash", "input": {"command": "pytest -q && echo x"},
             "write": ["ran.txt", "x"]}
    client, provider, _ = claude_app([WRITE, BASH, other, {"say": "done"}])
    snap, run, statuses = unattended(
        client, project_dir, provider, level, wait_run, write=True, commands=["pytest -q"])
    assert run["status"] == "completed", run
    verdicts = claude_app.record()["asked"]
    assert [v["behavior"] for v in verdicts] == ["allow", "allow", "deny"]
    assert NOBODY in verdicts[2]["message"]
    assert hello(project_dir) == "print('hello')\n"
    assert not (project_dir / "ran.txt").exists()
    assert [(c["status"], c["origin"]) for c in snap["file_changes"]] == [("applied", "cli")]
    assert [(c["command"], c["status"]) for c in snap["commands"]] == [("pytest -q", "exited")]
    assert [(t["name"], t["status"]) for t in snap["tool_calls"]] == [
        ("edit_file", "succeeded"), ("run_command", "succeeded"), ("run_command", "denied")]
    nothing_was_asked(snap, statuses)


@pytest.mark.parametrize("level", LEVELS)
def test_unattended_claude_code_is_refused_whatever_would_be_asked_about_in_words(
    claude_app, wait_run, project_dir, level, tmp_path
):
    # The trigger allows all a trigger can allow: none of the first five is among it.
    outside = (tmp_path / "elsewhere" / "x.txt").as_posix()
    client, provider, _ = claude_app([
        {"tool": "WebFetch", "input": {"url": "https://example.com"},
         "write": ["fetched.txt", "x"]},
        {"tool": "Write", "input": {
            "file_path": "PROJECT/.claude/settings.local.json",
            "content": '{"permissions": {"allow": ["Bash"]}}'},
         "write": [".claude/settings.local.json", "{}"]},
        {"tool": "Write", "input": {"file_path": outside, "content": "x"},
         "write": [outside, "x"]},
        {**AGENT, "id": "toolu_asked", "write": ["sub.txt", "x"]},
        {"tool": "mcp__shell__run", "input": {"command": "pytest -q"},
         "write": ["ran.txt", "x"]},
        {"tool": "NotebookEdit", "input": {"notebook_path": "PROJECT/n.ipynb"},
         "result": "edited"},
        {"tool": "Grep", "input": {"pattern": "hi"}, "result": "hello.py:1"},
        {"say": "done"}])
    snap, run, statuses = unattended(
        client, project_dir, provider, level, wait_run,
        write=True, commands=["pytest -q"], agents=4)
    assert run["status"] == "completed", run
    verdicts = claude_app.record()["asked"]
    # a notebook inside the project is a file, which this trigger lets it change; a look
    # is a look
    assert [v["behavior"] for v in verdicts] == [
        "deny", "deny", "deny", "deny", "deny", "allow", "allow"], verdicts
    assert all(NOBODY in v["message"] for v in verdicts[:5]), verdicts
    for left in ("fetched.txt", ".claude/settings.local.json", "sub.txt", "ran.txt"):
        assert not (project_dir / left).exists(), left
    assert not Path(outside).exists()
    assert snap["commands"] == []
    denied = [t["name"] for t in snap["tool_calls"] if t["status"] == "denied"]
    # (the write outside the project: refused as KOLONİ's own tools' would be - slice 41)
    assert denied == ["claude__WebFetch", "claude__Write", "edit_file", "claude__Agent",
                      "claude__mcp__shell__run"]
    nothing_was_asked(snap, statuses)


@pytest.mark.parametrize("named", STANDING)
def test_unattended_claude_code_never_writes_a_file_that_stands_over_later_turns(
    claude_app, wait_run, project_dir, named
):
    """The second line (the first does not start it at all): its trigger lets it change
    files, not one such - as for KOLONİ's own write tools."""
    client, provider, _ = claude_app([standing_write(named), {"say": "done"}])
    snap, run, statuses = unattended(
        client, project_dir, provider, "full_auto", wait_run, write=True)
    assert run["status"] == "completed", run
    verdicts = claude_app.record()["asked"]
    assert [v["behavior"] for v in verdicts] == ["deny"]
    assert NOBODY in verdicts[0]["message"]
    assert not (project_dir / named).exists()
    assert snap["file_changes"] == []
    nothing_was_asked(snap, statuses)


@pytest.mark.parametrize("level", ["ask", "full_auto"])
def test_what_claude_codes_own_sub_agent_asks_for_goes_through_the_same_gate(
    claude_app, wait_run, project_dir, level
):
    # A sub-agent Claude Code opened without asking (past its hook, should it ever).
    client, provider, _ = claude_app([
        {**AGENT, "unhooked": True}, {**WRITE, **SUB}, {**RAN, **SUB}, NOTIFIED,
        {"say": "done"}])
    snap, run, statuses = unattended(client, project_dir, provider, level, wait_run)
    assert run["status"] == "completed", run
    assert [v["behavior"] for v in claude_app.record()["asked"]] == ["deny", "deny"]
    assert hello(project_dir) == "print('hi')\n" and not (project_dir / "ran.txt").exists()
    assert snap["file_changes"] == [] and snap["commands"] == []
    nothing_was_asked(snap, statuses)


def test_unattended_claude_code_is_not_given_the_tools_its_trigger_does_not_allow(
    claude_app, wait_run, project_dir
):
    """Claude Code does not ask about what its own settings already allow: what the
    trigger does not allow is taken away before it starts, where no setting gives it back."""
    client, provider, _ = claude_app([{"say": "looked"}])
    unattended(client, project_dir, provider, "full_auto", wait_run)
    argv = claude_app.record()["argv"]
    withheld = set(argv[argv.index("--disallowedTools") + 1].split(","))
    assert {"Write", "Edit", "MultiEdit", "NotebookEdit", "Bash", "PowerShell"} <= withheld
    # nor what KOLONİ could only ask about in words, were it asked: its tools that reach
    # out, and the MCP servers of the user's own settings
    assert {"WebFetch", "WebSearch"} <= withheld
    assert argv.count("--strict-mcp-config") == 1


def test_unattended_claude_code_keeps_the_tools_its_trigger_allows(
    claude_app, wait_run, project_dir
):
    client, provider, _ = claude_app([{"say": "looked"}])
    unattended(client, project_dir, provider, "ask", wait_run, write=True,
               commands=["pytest -q"])
    argv = claude_app.record()["argv"]
    assert set(argv[argv.index("--disallowedTools") + 1].split(",")) == {
        "WebFetch", "WebSearch", *NEVER}
    assert argv.count("--strict-mcp-config") == 1


def test_a_turn_the_user_started_is_given_its_tools_as_before(
    claude_app, wait_run, project_dir
):
    client, provider, _ = claude_app([{"say": "looked"}])
    cid, run_id = start(client, project_dir, provider, "ask")
    wait_run(client, cid, run_id)
    argv = claude_app.record()["argv"]
    # (but for those never given: slice 89b)
    assert set(argv[argv.index("--disallowedTools") + 1].split(",")) == NEVER


# --- the user's own Claude Code setup: only where the provider says so ------------------


def test_native_claude_code_starts_without_the_users_own_setup_unless_the_provider_says_so(
    tmp_path,
):
    bridge = tmp_path / "bridge.json"
    isolated = ClaudeNativeClient(launcher=["x"])._native_arguments(tmp_path, bridge)
    assert isolated[isolated.index("--setting-sources") + 1] == "project,local"
    assert isolated.count("--strict-mcp-config") == 1
    assert "--mcp-config" in isolated  # KOLONİ's own server is still given
    # a turn nobody is watching asks for the same thing: it is said once
    unasked = ClaudeNativeClient(launcher=["x"])._native_arguments(
        tmp_path, bridge, ("unasked",))
    assert unasked.count("--strict-mcp-config") == 1 and "--setting-sources" in unasked
    # with the user's own setup: as it was started before there was a choice
    own = ClaudeNativeClient(launcher=["x"], own_setup=True)
    argv = own._native_arguments(tmp_path, bridge)
    assert "--setting-sources" not in argv and "--strict-mcp-config" not in argv
    assert argv == [a for a in isolated
                    if a not in ("--setting-sources", "project,local", "--strict-mcp-config",
                                 "--disable-slash-commands", "--settings",
                                 '{"disableAllHooks": true}')]
    unasked = own._native_arguments(tmp_path, bridge, ("unasked",))
    assert unasked.count("--strict-mcp-config") == 1 and "--setting-sources" not in unasked


def test_own_setup_is_a_setting_of_claude_code_only_and_reaches_its_native_client(settings):
    from app.db.models import Provider
    from app.providers import Providers, check_options

    assert check_options("claude_cli", {"own_setup": True}, False) == {"own_setup": True}
    for off in (None, {}, {"own_setup": False}, {"own_setup": None}):
        assert check_options("claude_cli", off, False) is None
    for bad in ("yes", 1, 0, [True]):
        with pytest.raises(ValueError, match="own_setup is true or false"):
            check_options("claude_cli", {"own_setup": bad}, False)
    with pytest.raises(ValueError, match="unknown setting"):
        check_options("claude_cli", {"own_setup": True, "offline": True}, False)
    for kind in ("openai_compat", "codex_cli", "qoder_cli", "agy_cli", "anthropic",
                 "copilot_cli"):
        with pytest.raises(ValueError):
            check_options(kind, {"own_setup": True}, False)

    def built(options):
        row = Provider(id="p", name="Claude", kind="claude_cli", mode="native", options=options)
        return Providers(settings)._build(row, None)

    assert built({"own_setup": True})._own_setup is True
    assert built(None)._own_setup is False


def test_claude_code_natively_is_told_to_answer_in_the_users_language_after_its_own_sub_agents():
    # (Live, B-136's run: a Turkish question got its last answer in English, after its background
    # sub-agent's English report - the session Lead is told the user's language in its instructions.)
    from app.model_native import CLAUDE_RULES
    assert "in the\nlanguage of the last user message of the conversation, even after a sub-agent" in CLAUDE_RULES
    # K-r152: and once - not a report again at each sub-agent's report (five in one live turn)
    assert "say briefly, once, what you did" in CLAUDE_RULES


def test_a_failed_command_of_its_own_says_its_exit_code(claude_app, wait_run, project_dir):
    # (Live, B-136's run: a PowerShell command of Claude Code's said "no exit code reported".)
    failing = {"tool": "PowerShell", "input": {"command": "pytest -q"}, "error": "Exit code 1\n1 failed"}
    client, provider, _ = claude_app([failing, {"say": "it fails"}])
    cid, run_id = start(client, project_dir, provider, "full_auto")
    snap = wait_run(client, cid, run_id)
    assert [c["exit_code"] for c in snap["commands"]] == [1]
    (ran,) = [t for t in snap["tool_calls"] if t["name"] == "run_command"]
    assert ran["result"].startswith("exit code 1")


# --- 89k: another model in the middle of a chat --------------------------------------------


def test_a_model_picked_between_turns_runs_the_next_turn_with_the_whole_chat(
    settings_env, tmp_path, project_dir, wait_run, monkeypatch
):
    # No CLI session outlives a turn (`--no-session-persistence`): the next turn is a new
    # Claude Code on the model picked now, given the chat so far as every turn is.
    from app.providers import Providers

    record, plan = tmp_path / "record.json", tmp_path / "plan.json"
    plan.write_text(json.dumps({"record": str(record), "script": [{"say": "Done."}]}),
                    encoding="utf-8")
    monkeypatch.setattr(Providers, "_build", lambda self, provider, model_id: ClaudeNativeClient(
        model=model_id, launcher=FAKE, timeout=30, env={"FAKE_CLI_PLAN": str(plan)}))
    with TestClient(create_app(load_settings(settings_env)),
                    base_url="http://127.0.0.1:8790") as client:
        provider = client.post("/api/providers", json={
            "name": "Claude", "kind": "claude_cli", "mode": "native"}).json()
        cid, run_id = start(client, project_dir, provider, "full_auto")
        wait_run(client, cid, run_id, timeout=30)
        assert client.patch(f"/api/conversations/{cid}", json={
            "provider_id": provider["id"], "model_id": "claude-sonnet-5-5"}).status_code == 200
        run_id = client.post(f"/api/conversations/{cid}/messages",
                             json={"content": "now the tests"}).json()["run"]["id"]
        snap = wait_run(client, cid, run_id, timeout=30)
    assert snap["runs"][-1]["status"] == "completed", snap["runs"][-1]["error"]
    seen = json.loads(record.read_text(encoding="utf-8"))
    argv = seen["argv"]
    assert argv[argv.index("--model") + 1] == "claude-sonnet-5-5"
    assert "fix the greeting" in seen["stdin"] and "now the tests" in seen["stdin"]


# --- 89g: a role run inside Claude Code, as a sub-agent of its own ---------------------------

CHECKER = {"name": "Checker", "description": "Looks over the code", "instructions": "Check it.",
           "tools": ["read_file", "search", "list_dir", "ask_user"], "inside_cli": True}
# The version measured to name a role's tool use to the hook (`INSIDE_FROM`).
MEASURED = "2.1.311"


def agents_given(argv):
    return json.loads(argv[argv.index("--agents") + 1]) if "--agents" in argv else None


def offered(claude_app):
    return sorted(agents_given(claude_app.record()["argv"]) or [])


def turn(client, project_dir, provider, wait_run, cid=None, **conversation):
    """A watched turn on Claude Code at Full auto, in a new conversation or `cid`; its id."""
    if cid is None:
        pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
        cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    assert client.patch(f"/api/conversations/{cid}", json={
        "permission_mode": "full_auto", "provider_id": provider["id"], "lead_hands_code": False,
        **conversation}, headers={"Origin": ORIGIN}).status_code == 200
    run_id = client.post(f"/api/conversations/{cid}/messages",
                         json={"content": "fix the greeting"}).json()["run"]["id"]
    run = next(r for r in wait_run(client, cid, run_id)["runs"] if r["id"] == run_id)
    assert run["status"] == "completed", run["error"]
    return cid


def test_a_role_is_offered_inside_claude_code_only_when_the_user_says_so(
    claude_app, wait_run, project_dir
):
    client, provider, _ = claude_app([{"say": "Done."}], version=MEASURED)
    made = client.post("/api/roles", json={**CHECKER, "inside_cli": False},
                       headers={"Origin": ORIGIN})
    assert made.status_code == 201 and made.json()["inside_cli"] is False
    cid = turn(client, project_dir, provider, wait_run)
    assert offered(claude_app) == []  # off by default
    assert client.patch(f"/api/roles/{made.json()['id']}", json={"inside_cli": True},
                        headers={"Origin": ORIGIN}).json()["inside_cli"] is True
    turn(client, project_dir, provider, wait_run, cid)
    # its line, its instructions and its tools as Claude Code's own - nothing else, no model
    # (it has none of its own), and none of KOLONİ's tools
    given = agents_given(claude_app.record()["argv"])["koloni-checker"]
    assert sorted(given.pop("tools")) == ["Glob", "Grep", "LS", "NotebookRead", "Read"]
    assert given == {"description": "Looks over the code", "prompt": "Check it."}


def test_a_role_the_lead_may_not_open_is_not_offered_inside_it(claude_app, wait_run, project_dir):
    client, provider, _ = claude_app([{"say": "Done."}], version=MEASURED)
    made = client.post("/api/roles", json={**CHECKER, "enabled": False},
                       headers={"Origin": ORIGIN}).json()
    cid = turn(client, project_dir, provider, wait_run)
    assert offered(claude_app) == []
    client.patch(f"/api/roles/{made['id']}", json={"enabled": True}, headers={"Origin": ORIGIN})
    turn(client, project_dir, provider, wait_run, cid)
    assert offered(claude_app) == ["koloni-checker"]  # the same, once it may be opened


def test_no_role_is_offered_inside_where_every_sub_agent_is_asked_about_first(
    claude_app, wait_run, project_dir
):
    client, provider, _ = claude_app([{"say": "Done."}], version=MEASURED)
    client.post("/api/roles", json=CHECKER, headers={"Origin": ORIGIN})
    cid = turn(client, project_dir, provider, wait_run, spawn_approval="always")
    assert offered(claude_app) == []
    turn(client, project_dir, provider, wait_run, cid, spawn_approval="auto")
    assert offered(claude_app) == ["koloni-checker"]


def test_no_role_is_offered_inside_past_the_depth_limit(claude_app, wait_run, project_dir):
    # A sub-agent on Claude Code that may open others, at the deepest level allowed.
    client, provider, _ = claude_app(
        [{"say": "Done."}], version=MEASURED,
        default_steps=[spawn("Boss", "x"), text("ok"), spawn("Boss", "x", "s2"), text("ok")])
    client.post("/api/roles", json={
        "name": "Boss", "provider_id": provider["id"], "tools": [
            "read_file", "list_dir", "search", "write_file", "edit_file", "run_command",
            "spawn_agent"]}, headers={"Origin": ORIGIN})
    client.post("/api/roles", json=CHECKER, headers={"Origin": ORIGIN})
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    for depth, given in ((1, []), (2, ["koloni-checker"])):
        client.patch(f"/api/conversations/{cid}", json={
            "permission_mode": "full_auto", "spawn_max_depth": depth},
            headers={"Origin": ORIGIN})
        run_id = client.post(f"/api/conversations/{cid}/messages",
                             json={"content": "fix it"}).json()["run"]["id"]
        snap = wait_run(client, cid, run_id)
        boss = snap["agents"][-1]
        assert (boss["role_name"], boss["status"]) == ("Boss", "completed"), boss
        assert offered(claude_app) == given


def test_no_role_is_offered_inside_a_turn_nobody_watches(claude_app, wait_run, project_dir):
    client, provider, _ = claude_app([{"say": "Done."}], version=MEASURED)
    client.post("/api/roles", json=CHECKER, headers={"Origin": ORIGIN})
    unattended(client, project_dir, provider, "full_auto", wait_run)
    assert offered(claude_app) == []
    turn(client, project_dir, provider, wait_run)
    assert offered(claude_app) == ["koloni-checker"]


def test_no_role_is_offered_inside_a_job_done_while_the_user_is_away(
    claude_app, wait_run, project_dir, monkeypatch
):
    client, provider, _ = claude_app([{"say": "Done."}], version=MEASURED)
    client.post("/api/roles", json=CHECKER, headers={"Origin": ORIGIN})
    runner = client.app.state.runner
    inside = runner._inside_roles

    def at_night(ctx, *args):  # its turn taken for a night's job (`_away_jobs`)
        runner._away_jobs[ctx.run_id] = ctx.agent_id
        try:
            return inside(ctx, *args)
        finally:
            runner._away_jobs.pop(ctx.run_id, None)

    monkeypatch.setattr(runner, "_inside_roles", at_night)
    turn(client, project_dir, provider, wait_run)
    assert offered(claude_app) == []
    monkeypatch.setattr(runner, "_inside_roles", inside)
    turn(client, project_dir, provider, wait_run)
    assert offered(claude_app) == ["koloni-checker"]


def test_a_lead_that_hands_code_on_offers_no_role_inside_that_would_change_things(
    claude_app, wait_run, project_dir
):
    client, provider, _ = claude_app([{"say": "Done."}], version=MEASURED)
    client.post("/api/roles", json=CHECKER, headers={"Origin": ORIGIN})
    client.post("/api/roles", json={**CHECKER, "name": "Fixer", "tools": [
        "read_file", "run_command"]}, headers={"Origin": ORIGIN})
    cid = turn(client, project_dir, provider, wait_run, lead_hands_code=True)
    # its commands would write in the Lead's folder, past any diff
    assert offered(claude_app) == ["koloni-checker"]
    turn(client, project_dir, provider, wait_run, cid, lead_hands_code=False)
    assert offered(claude_app) == ["koloni-checker", "koloni-fixer"]


def test_an_older_claude_code_is_offered_no_role_and_that_is_said(
    claude_app, wait_run, project_dir
):
    # (One not measured to name a role's tool use to the hook would hold it to its Lead's rights.)
    client, provider, _ = claude_app([{"say": "Done."}], version="2.1.310")
    client.post("/api/roles", json=CHECKER, headers={"Origin": ORIGIN})
    cid = turn(client, project_dir, provider, wait_run)
    assert offered(claude_app) == []
    snap = client.get(f"/api/conversations/{cid}").json()
    (note,) = [t for t in snap["tool_calls"] if t["name"] == "claude__agents"]
    assert note["result"] == "not offered inside Claude Code: Claude Code is older than 2.1.311"


def test_a_role_inside_claude_code_is_shown_and_held_to_its_own_tools(
    claude_app, wait_run, project_dir
):
    inside = {"parent": "toolu_sub", "agent_type": "koloni-checker"}
    client, provider, _ = claude_app([
        {**AGENT, "input": {**AGENT["input"], "subagent_type": "koloni-checker"}},
        {"system": {"subtype": "task_started", "tool_use_id": "toolu_sub"}},
        {"tool": "Read", "input": {"file_path": "PROJECT/hello.py"}, "result": "x", **inside},
        {**RAN, **inside},  # a tool its role does not have
        NOTIFIED,
        {"say": "Done."}], version=MEASURED)
    client.post("/api/roles", json=CHECKER, headers={"Origin": ORIGIN})
    cid, run_id = start(client, project_dir, provider, "full_auto")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert len(snap["agents"]) == 1  # not an agent of KOLONİ's
    calls = calls_by_name(snap)
    sub = calls["claude__Agent"]
    assert json.loads(sub["arguments"])["koloni_role"] == "Checker"
    assert (calls["claude__Read"]["status"], calls["claude__Read"]["parent_call_id"]) == (
        "succeeded", sub["id"])
    refused = calls["claude__Bash"]
    assert (refused["status"], refused["parent_call_id"]) == ("denied", sub["id"])
    assert refused["result"] == ("Checker (inside Claude Code) may not use Bash: its role does "
                                 "not give it that tool")
    assert not (project_dir / "ran.txt").exists() and snap["commands"] == []
    seen = claude_app.record()
    assert [v["behavior"] for v in seen["asked"]] == ["allow", "allow", "deny"]
    assert "may not use Bash" in seen["asked"][-1]["message"]


def test_a_sub_agent_named_as_no_role_koloni_offered_may_use_nothing(
    claude_app, wait_run, project_dir
):
    # (a project's own .claude/agents could name one so)
    ghost = {"parent": "toolu_sub", "agent_type": "koloni-ghost"}
    client, provider, _ = claude_app([
        {**AGENT, "input": {**AGENT["input"], "subagent_type": "koloni-ghost"}},
        {"tool": "Read", "input": {"file_path": "PROJECT/hello.py"}, "result": "x", **ghost},
        {"koloni": "spawn_agent", "args": {"role": "Coder", "task": "x"}, **ghost},
        NOTIFIED, {"say": "Done."}], version=MEASURED)
    client.post("/api/roles", json=CHECKER, headers={"Origin": ORIGIN})
    cid, run_id = start(client, project_dir, provider, "full_auto")
    snap = wait_run(client, cid, run_id)
    assert len(snap["agents"]) == 1
    seen = claude_app.record()
    assert seen["results"] == []
    assert [v["behavior"] for v in seen["asked"]] == ["allow", "deny", "deny"]
    assert "koloni-ghost (inside Claude Code) may not use Read" in seen["asked"][1]["message"]
    assert "may not use mcp__koloni__spawn_agent" in seen["asked"][2]["message"]


def test_a_role_the_model_writes_into_its_own_sub_agent_is_not_kept(
    claude_app, wait_run, project_dir
):
    client, provider, _ = claude_app([
        {**AGENT, "input": {**AGENT["input"], "koloni_role": "Admin"}},
        NOTIFIED, {"say": "Done."}], version=MEASURED)
    cid, run_id = start(client, project_dir, provider, "full_auto")
    sub = calls_by_name(wait_run(client, cid, run_id))["claude__Agent"]
    assert "koloni_role" not in json.loads(sub["arguments"])


def test_a_roles_tools_as_claude_codes_own_and_its_name_there():
    from app.model_native import claude_tools, inside_name
    assert claude_tools(["read_file", "write_file", "run_command", "web_search", "spawn_agent"],
                        ("run", "search")) == ["Read", "NotebookRead", "Write"]
    assert claude_tools(["spawn_agent", "ask_user"]) == []  # (such a role is not offered)
    assert inside_name("UI designer") == "koloni-ui-designer"
    assert inside_name("Çevirmen 2") == "koloni-evirmen-2" and inside_name("Тест") == "koloni-role"


def test_a_role_inside_claude_code_cannot_use_kolonis_tools_which_are_its_leads(
    claude_app, wait_run, project_dir
):
    client, provider, _ = claude_app([
        {**AGENT, "input": {**AGENT["input"], "subagent_type": "koloni-checker"}},
        {"koloni": "spawn_agent", "args": {"role": "Coder", "task": "x"},
         "parent": "toolu_sub", "agent_type": "koloni-checker"},
        NOTIFIED, {"say": "Done."}], version=MEASURED)
    client.post("/api/roles", json=CHECKER, headers={"Origin": ORIGIN})
    cid, run_id = start(client, project_dir, provider, "full_auto")
    snap = wait_run(client, cid, run_id)
    assert len(snap["agents"]) == 1  # nothing was opened
    seen = claude_app.record()
    hooks = [h["hookSpecificOutput"]["permissionDecision"] for h in seen["hooks"]]
    assert hooks == ["ask", "ask"]  # its Lead's would be "allow"
    assert seen["results"] == [] and "may not use mcp__koloni__spawn_agent" in (
        seen["asked"][-1]["message"])


@pytest.mark.skipif(sys.platform != "win32", reason="Windows' command line has a limit")
def test_roles_that_do_not_fit_its_command_line_are_not_offered_and_that_is_said(
    claude_app, wait_run, project_dir
):
    client, provider, _ = claude_app([{"say": "Done."}], version=MEASURED)
    client.post("/api/roles", json={**CHECKER, "instructions": "x" * 40_000},
                headers={"Origin": ORIGIN})
    cid, run_id = start(client, project_dir, provider, "full_auto")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert agents_given(claude_app.record()["argv"]) is None
    (note,) = [t for t in snap["tool_calls"] if t["name"] == "claude__agents"]
    assert note["status"] == "failed" and "not offered inside Claude Code" in note["result"]
    assert json.loads(note["arguments"]) == {"roles": ["Checker"]}


def test_a_role_inside_claude_code_runs_on_its_own_model_on_its_leads_provider(
    claude_app, wait_run, project_dir
):
    client, provider, _ = claude_app([{"say": "Done."}], version=MEASURED)
    client.post("/api/roles", json={**CHECKER, "provider_id": provider["id"],
                                    "model_id": "claude-haiku-5"}, headers={"Origin": ORIGIN})
    turn(client, project_dir, provider, wait_run)
    assert agents_given(claude_app.record()["argv"])["koloni-checker"]["model"] == "claude-haiku-5"
