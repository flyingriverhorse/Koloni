"""Native agy asks KOLONİ before every tool it uses (slice 89e): it works in a home of
KOLONİ's whose PreToolUse hook hands each tool call to KOLONİ, which answers it as it answers
Claude Code's and Codex's requests (`AgentRunner._approve`). A hook agy did not load, or one
that cannot reach KOLONİ, stops the tool or the run: native agy never works unasked.

Against tests/fake_agy_cli.py, which runs the hook as agy 1.3.3 was measured to."""

import json
import os
import shutil
import time
from pathlib import Path

import pytest

from app.config import load_settings
from app.main import create_app
from app.model_agy import AgyClient, asked_as
from tests.fakes import ScriptedModel
from tests.keyed import TestClient
from tests.test_agent_writes import wait_status
from tests.test_agy_agent import FAKE, SKIP
from tests.test_claude_native import NOBODY, ORIGIN, nothing_was_asked, unattended
from tests.test_codex_app_server_scenarios import card_for, hello, watched
from tests.test_native_agent import start

DOOR = "koloni-door.json"  # next to hooks.json: where the hook finds KOLONİ
UNASKED = "ran without KOLONİ being asked"
UNSURE = "not known whether it ran"
UNKNOWN_YET = "KOLONİ does not know what this agy tool does yet"

# (elsewhere the hook's path is quoted on its line)
WINDOWS_CMD = pytest.mark.skipif(os.name != "nt",
                                 reason="the .cmd wrapper and short names are Windows'")


@pytest.fixture
def hooked_app(settings_env, tmp_path, monkeypatch):
    # The user's own home, with a hook of theirs: read, it would let every tool through.
    real = tmp_path / "real-home"
    (real / ".gemini" / "config").mkdir(parents=True)
    (real / ".gemini" / "config" / "hooks.json").write_text(json.dumps({"theirs": {
        "PreToolUse": [{"matcher": "*", "hooks": [
            {"type": "command", "command": 'echo {"decision": "allow"}'}]}]}}), encoding="utf-8")
    monkeypatch.setenv("USERPROFILE", str(real))
    monkeypatch.setenv("HOME", str(real))
    opened = []
    record, plan = tmp_path / "record.json", tmp_path / "plan.json"

    def write_plan(script, **more):
        plan.write_text(json.dumps({"record": str(record), "script": script, **more}),
                        encoding="utf-8")

    def make(script, timeout=30, homes=None, **more):
        write_plan(script, **more)
        cli = AgyClient(None, "gemini-asked", timeout=timeout, reads=False, launcher=FAKE,
                        env={"FAKE_AGY_PLAN": str(plan)})
        cli.homes = homes or make.homes
        app = create_app(load_settings(settings_env), model=ScriptedModel([]),
                         clients={"agy": cli})
        client = TestClient(app, base_url="http://127.0.0.1:8790")
        client.__enter__()
        opened.append(client)
        made = client.post("/api/providers", json={
            "name": "agy", "kind": "agy_cli", "mode": "native", "default_model": "gemini-asked"})
        assert made.status_code == 201, made.text
        return client, made.json()

    make.real = real
    make.homes = tmp_path / "runtime" / "agy-home"
    make.record = lambda: json.loads(record.read_text(encoding="utf-8"))
    make.ran = record.exists
    yield make
    for client in opened:
        client.__exit__(None, None, None)


def decisions(hooked_app):
    """What the hook told agy, one for each tool, in order."""
    return [json.loads(ran["out"])["decision"] for ran in hooked_app.record()["hooks"]]


def run_command(line, **more):
    return {"tool": "run_command", "parameters": {"CommandLine": line}, **more}


def write_file(path, content, **more):
    return {"tool": "write_file", "parameters": {"Path": path, "Content": content,
                                                "Overwrite": True},
            "touches": {path: content}, **more}


# --- 1. Ask: a command is a card --------------------------------------------------------------


def test_at_ask_agys_command_is_a_card_and_runs_once_approved(hooked_app, wait_run, project_dir):
    client, provider = hooked_app([
        run_command("python made.py", output="made\n", touches={"made.txt": "x"}),
        {"say": "Done."}])
    cid, run_id = start(client, project_dir, provider, mode="ask")
    asked = wait_status(client, cid, "waiting_approval")["commands"][0]
    assert (asked["status"], asked["command"], asked["origin"]) == (
        "proposed", "python made.py", "cli")
    assert not (project_dir / "made.txt").exists()  # nothing ran before the yes
    assert client.post(f"/api/commands/{asked['id']}/approve", json={}).status_code == 200
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert decisions(hooked_app) == ["allow"]
    (done,) = snap["commands"]  # one record: the card is the command
    assert (done["status"], done["output"]) == ("exited", "made\n")
    assert (project_dir / "made.txt").exists()
    assert SKIP in hooked_app.record()["argv"]  # the hook is the gate, not agy's own prompt


def test_at_ask_a_rejected_command_is_denied_and_never_runs(hooked_app, wait_run, project_dir):
    client, provider = hooked_app([
        run_command("python made.py", touches={"made.txt": "x"}), {"say": "Left it."}])
    cid, run_id = start(client, project_dir, provider, mode="ask")
    asked = wait_status(client, cid, "waiting_approval")["commands"][0]
    assert client.post(f"/api/commands/{asked['id']}/reject").status_code == 200
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed"  # a no carries the turn on
    assert decisions(hooked_app) == ["deny"]
    assert not (project_dir / "made.txt").exists()
    assert [c["status"] for c in snap["commands"]] == ["rejected"]
    assert [(t["name"], t["status"]) for t in snap["tool_calls"]] == [("run_command", "denied")]


def test_at_full_auto_a_command_is_judged_in_the_folder_it_runs_in(
    hooked_app, wait_run, project_dir
):
    # denetim-010 #18: the line names no `.github`, its Cwd does - a workflow written there.
    (project_dir / ".github" / "workflows").mkdir(parents=True)
    line = "echo on > ci.yml"
    client, provider = hooked_app([
        run_command(line, parameters={"CommandLine": line,
                                      "Cwd": str(project_dir / ".github" / "workflows")}),
        {"say": "Left it."}])
    cid, run_id = start(client, project_dir, provider, mode="full_auto")
    asked = card_for(client, cid, line)
    assert asked["cwd"] == ".github/workflows"
    assert client.post(f"/api/commands/{asked['id']}/reject").status_code == 200
    wait_run(client, cid, run_id)
    assert decisions(hooked_app) == ["deny"]


def test_a_card_left_open_longer_than_the_silence_limit_does_not_end_agy(
    hooked_app, wait_run, project_dir
):
    client, provider = hooked_app([run_command("python made.py"), {"say": "ok"}], timeout=2)
    cid, run_id = start(client, project_dir, provider, mode="ask")
    asked = wait_status(client, cid, "waiting_approval")["commands"][0]
    time.sleep(5)  # the user is thinking: agy waits on its hook, and says nothing
    client.post(f"/api/commands/{asked['id']}/approve", json={})
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]


def test_at_ask_reading_in_the_project_is_not_asked_and_a_listing_outside_is(
    hooked_app, wait_run, project_dir, tmp_path
):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    client, provider = hooked_app([
        {"tool": "read_file", "parameters": {"Path": str(project_dir / "hello.py")},
         "output": "print('hi')"},
        {"tool": "list_directory", "parameters": {"DirectoryPath": str(project_dir)}},
        {"tool": "list_directory", "parameters": {"DirectoryPath": str(elsewhere)}},
        {"say": "Looked."}])
    cid, run_id = start(client, project_dir, provider, mode="ask")
    snap = wait_status(client, cid, "waiting_approval")
    (pending,) = [t for t in snap["tool_calls"] if t["status"] == "pending"]
    assert json.loads(pending["arguments"]) == {"path": str(elsewhere)}
    assert client.post(f"/api/tool-calls/{pending['id']}/reject",
                       headers={"Origin": ORIGIN}).status_code == 200
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert decisions(hooked_app) == ["allow", "allow", "deny"]


# --- 2. Full auto: only what is asked at every level is a card ---------------------------------


def test_at_full_auto_an_ordinary_command_and_write_pass_unasked(
    hooked_app, wait_run, project_dir
):
    client, provider = hooked_app([
        run_command("python hello.py", output="hi\n"), write_file("notes.txt", "x\n"),
        {"say": "ok"}])
    statuses = watched(client)
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert decisions(hooked_app) == ["allow", "allow"]
    nothing_was_asked(snap, statuses)
    assert [c["status"] for c in snap["commands"]] == ["exited"]
    assert [(f["path"], f["status"]) for f in snap["file_changes"]] == [("notes.txt", "applied")]
    assert not [t for t in snap["tool_calls"] if UNASKED in (t["result"] or "")]


def test_at_full_auto_a_command_that_reads_a_secret_is_a_card(hooked_app, wait_run, project_dir):
    (project_dir / ".env").write_text("TOKEN=x\n", encoding="utf-8")
    client, provider = hooked_app([run_command("type .env", output="TOKEN=x\n"), {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)
    asked = wait_status(client, cid, "waiting_approval")["commands"][0]
    assert (asked["command"], asked["status"]) == ("type .env", "proposed")
    client.post(f"/api/commands/{asked['id']}/reject")
    wait_run(client, cid, run_id)
    assert decisions(hooked_app) == ["deny"]


def test_at_full_auto_reading_the_env_file_is_a_card(hooked_app, wait_run, project_dir):
    (project_dir / ".env").write_text("TOKEN=agy-secret\n", encoding="utf-8")
    client, provider = hooked_app([
        {"tool": "read_file", "parameters": {"Path": str(project_dir / ".env")},
         "output": "TOKEN=agy-secret"}, {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_status(client, cid, "waiting_approval")
    (pending,) = [t for t in snap["tool_calls"] if t["status"] == "pending"]
    assert ".env" in pending["arguments"]
    client.post(f"/api/tool-calls/{pending['id']}/reject", headers={"Origin": ORIGIN})
    snap = wait_run(client, cid, run_id)
    assert decisions(hooked_app) == ["deny"]
    assert "agy-secret" not in json.dumps(snap["tool_calls"])


def test_at_full_auto_a_write_to_a_workflow_is_a_card(hooked_app, wait_run, project_dir):
    client, provider = hooked_app([
        write_file(".github/workflows/x.yml", "on: push\n"), {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_status(client, cid, "waiting_approval")
    (card,) = [c for c in snap["file_changes"] if c["status"] == "proposed"]
    assert card["path"] == ".github/workflows/x.yml" and "+on: push" in card["diff"]
    assert not (project_dir / ".github").exists()
    client.post(f"/api/file-changes/{card['id']}/approve")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert decisions(hooked_app) == ["allow"]
    assert (project_dir / ".github" / "workflows" / "x.yml").read_text(encoding="utf-8") == (
        "on: push\n")
    assert [(c["path"], c["status"]) for c in snap["file_changes"]] == [
        (".github/workflows/x.yml", "applied")]


def test_a_tool_koloni_does_not_know_that_names_a_path_is_judged_as_a_change_of_it(
    hooked_app, wait_run, project_dir
):
    client, provider = hooked_app([
        {"tool": "move", "parameters": {"SourcePath": "hello.py",
                                        "TargetPath": ".github/workflows/x.yml"}},
        {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)  # at Full auto
    snap = wait_status(client, cid, "waiting_approval")  # a workflow: asked at every level
    assert hooked_app.record()["hooks"][0].get("out") is None  # the hook waits for the user
    (question,) = snap["questions"]
    assert "TargetPath" in question["question"]  # the card shows all it was given
    client.post(f"/api/questions/{question['id']}/answer", json={"answer": "Deny"},
                headers={"Origin": ORIGIN})
    snap = wait_run(client, cid, run_id)
    assert hello(project_dir) == "print('hi')\n" and not (project_dir / ".github").exists()
    assert decisions(hooked_app) == ["deny"]
    # denied by KOLONİ, and on record so - not as a step nobody knows the end of
    assert not [t for t in snap["tool_calls"] if UNSURE in (t["result"] or "")]


def test_a_tool_koloni_does_not_know_is_a_card_in_words_even_at_full_auto(
    hooked_app, wait_run, project_dir
):
    client, provider = hooked_app([
        {"tool": "search_web", "parameters": {"query": "koloni"}}, {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)  # at Full auto
    (question,) = wait_status(client, cid, "waiting_approval")["questions"]
    assert "search_web" in question["question"]
    client.post(f"/api/questions/{question['id']}/answer", json={"answer": "Deny"},
                headers={"Origin": ORIGIN})
    wait_run(client, cid, run_id)
    assert decisions(hooked_app) == ["deny"]


def test_a_kolonis_tool_it_was_not_offered_is_refused_by_its_hook_even_at_full_auto(
    hooked_app, wait_run, project_dir
):
    # (B-310: named as KOLONİ's own, but not among this run's: refused whichever server has it)
    from app.model_agy import NOT_OFFERED

    client, provider = hooked_app([{"koloni": "not_offered", "args": {"x": 1}}, {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)  # at Full auto
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert decisions(hooked_app) == ["deny"] and hooked_app.record()["results"] == []
    told = [(t["name"], t["status"], t["result"]) for t in snap["tool_calls"]]
    # (and, as for any step its hook refused, its start is put down as interrupted: R101)
    assert told[0] == ("agy__mcp__koloni__not_offered", "denied", NOT_OFFERED), told


def test_a_kolonis_tool_it_was_not_offered_is_refused_through_its_wrapper_too(
    hooked_app, wait_run, project_dir
):
    from app.model_agy import NOT_OFFERED

    client, provider = hooked_app([
        {"koloni": "not_offered", "args": {"x": 1}, "wrapped": True}, {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)  # at Full auto
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert decisions(hooked_app) == ["deny"] and hooked_app.record()["results"] == []
    told = [(t["name"], t["status"], t["result"]) for t in snap["tool_calls"]]
    assert ("agy__mcp__koloni__not_offered", "denied", NOT_OFFERED) in told, told


def test_agy_reads_its_own_definitions_of_kolonis_tools_and_nothing_else_of_kolonis_runtime(
    hooked_app, wait_run, project_dir, monkeypatch
):
    # B-318: 1.4.x reads <tool>.json before it calls a tool of KOLONİ's; its home is in
    # KOLONİ's runtime, never opened otherwise - its config, settings, another run's home.
    monkeypatch.setenv("KOLONI_RUNTIME_ROOT", str(hooked_app.homes.parent))
    other = hooked_app.homes / "agy-other" / ".gemini" / "antigravity-cli" / "mcp" / "koloni"
    other.mkdir(parents=True)
    (other / "spawn_agent.json").write_text("{}", encoding="utf-8")
    defined = "{home}/.gemini/antigravity-cli/mcp/koloni"

    def view(path):
        return {"tool": "view_file", "parameters": {"AbsolutePath": path}}

    client, provider = hooked_app([
        view(f"{defined}/spawn_agent.json"), view("{home}/.gemini/config/mcp_config.json"),
        view(f"{defined}/../../settings.json"), view(str(other / "spawn_agent.json")),
        {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)  # at Full auto
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert "spawn_agent" in hooked_app.record()["tools"]
    said = [json.loads(ran["out"]) for ran in hooked_app.record()["hooks"]]
    assert [one["decision"] for one in said] == ["allow", "deny", "deny", "deny"], said
    assert all("KOLONİ's own record" in one["reason"] for one in said[1:]), said


@pytest.mark.parametrize(("tool", "given"), [
    ("call_mcp_tool", {"ServerName": "other", "ToolName": "spawn_agent", "Arguments": {}}),
    # (a path it names is no change of that file: another server's tool may do anything)
    ("call_mcp_tool", {"ServerName": "other", "ToolName": "x", "FilePath": "hello.py"}),
    ("list_resources", {"ServerName": "other", "FilePath": "hello.py"}),
    # (a key more leaves it wrapped: the server it really goes to is not known)
    ("call_mcp_tool", {"ServerName": "koloni", "ServerId": "evil", "ToolName": "spawn_agent"}),
])
def test_agys_wrapper_to_another_server_is_a_card_in_words_even_at_full_auto(
    hooked_app, wait_run, project_dir, tool, given
):
    client, provider = hooked_app([{"tool": tool, "parameters": given}, {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)  # at Full auto
    (question,) = wait_status(client, cid, "waiting_approval")["questions"]
    assert tool in question["question"]
    client.post(f"/api/questions/{question['id']}/answer", json={"answer": "Deny"},
                headers={"Origin": ORIGIN})
    wait_run(client, cid, run_id)
    assert decisions(hooked_app) == ["deny"] and hooked_app.record()["results"] == []


def test_another_servers_wrapper_allowed_on_a_card_that_never_ends_is_on_record_as_interrupted(
    hooked_app, wait_run, project_dir
):
    client, provider = hooked_app([{"tool": "call_mcp_tool", "never_ends": True, "parameters": {
        "ServerName": "other", "ToolName": "x"}}, {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)  # at Full auto
    (question,) = wait_status(client, cid, "waiting_approval")["questions"]
    client.post(f"/api/questions/{question['id']}/answer", json={"answer": "Allow"},
                headers={"Origin": ORIGIN})
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert decisions(hooked_app) == ["allow"]
    told = [(t["name"], t["status"]) for t in snap["tool_calls"]]
    assert [name for name, status in told if status == "interrupted"] == [
        "agy__call_mcp_tool"], told


def test_a_step_its_hook_is_asked_about_again_is_judged_as_it_was_asked_last(
    hooked_app, wait_run, project_dir
):
    # (first told of as KOLONİ's tool through the wrapper, then as a command at the same step)
    wrapped = ["call_mcp_tool", {"ServerName": "koloni", "ToolName": "spawn_agent",
                                 "Arguments": {}}]
    client, provider = hooked_app([
        run_command("python made.py", output="made\n", touches={"made.txt": "x"},
                    hook_first=wrapped), {"say": "Done."}])
    cid, run_id = start(client, project_dir, provider)  # at Full auto
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert decisions(hooked_app) == ["allow", "allow"]
    assert [(c["command"], c["status"]) for c in snap["commands"]] == [
        ("python made.py", "exited")]


@pytest.mark.parametrize("tool", ["invoke_subagent", "browser_subagent", "run_workflow"])
def test_an_agy_tool_that_runs_code_or_starts_agents_is_refused_until_measured(
    hooked_app, wait_run, project_dir, tool
):
    client, provider = hooked_app([{"tool": tool, "parameters": {"Task": "x"}}, {"say": "ok"}])
    statuses = watched(client)
    cid, run_id = start(client, project_dir, provider)  # at Full auto
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    (said,) = [json.loads(ran["out"]) for ran in hooked_app.record()["hooks"]]
    assert said == {"decision": "deny", "reason": UNKNOWN_YET}
    nothing_was_asked(snap, statuses)


# --- 3. A turn nobody is watching -------------------------------------------------------------


def test_native_agy_is_not_started_in_a_turn_nobody_is_watching(hooked_app, wait_run, project_dir):
    client, provider = hooked_app([run_command("pytest -q"), {"say": "done"}])
    _snap, run, _statuses = unattended(
        client, project_dir, provider, "full_auto", wait_run, first_line=True,
        commands=["pytest -q"])
    assert not hooked_app.ran()


def test_unattended_agy_is_denied_what_its_trigger_does_not_allow_and_nobody_is_asked(
    hooked_app, wait_run, project_dir
):
    client, provider = hooked_app([
        run_command("pytest -q", output="ok\n"),
        run_command("pytest -q && echo x", touches={"ran.txt": "x"}),
        write_file("hello.py", "changed\n"), {"say": "done"}])
    # (The first line - no CLI with tools of its own starts unwatched - is switched off.)
    snap, run, statuses = unattended(
        client, project_dir, provider, "full_auto", wait_run, commands=["pytest -q"])
    assert run["status"] == "completed", run
    assert decisions(hooked_app) == ["allow", "deny", "deny"]
    assert hello(project_dir) == "print('hi')\n" and not (project_dir / "ran.txt").exists()
    assert [(t["name"], t["status"]) for t in snap["tool_calls"]] == [
        ("run_command", "succeeded"), ("run_command", "denied"), ("edit_file", "denied")]
    assert all(NOBODY in t["result"] for t in snap["tool_calls"][1:])
    nothing_was_asked(snap, statuses)


def test_unattended_a_tool_koloni_does_not_know_is_refused_and_nobody_is_asked(
    hooked_app, wait_run, project_dir
):
    client, provider = hooked_app([
        {"tool": "search_web", "parameters": {"query": "koloni"}}, {"say": "done"}])
    snap, run, statuses = unattended(
        client, project_dir, provider, "full_auto", wait_run, commands=["pytest -q"])
    assert run["status"] == "completed", run
    assert decisions(hooked_app) == ["deny"]
    nothing_was_asked(snap, statuses)


# --- 4. A hook that cannot be trusted ---------------------------------------------------------


@pytest.mark.parametrize("loaded", [0, 2])  # none, or one of the project's besides KOLONİ's
def test_an_agy_that_loaded_other_than_kolonis_one_hook_is_stopped_before_it_is_given_the_task(
    hooked_app, wait_run, project_dir, loaded
):
    client, provider = hooked_app(
        [run_command("python made.py", touches={"made.txt": "x"}), {"say": "done"}],
        hooks_loaded=loaded)
    cid, run_id = start(client, project_dir, provider)
    run = wait_run(client, cid, run_id)["runs"][0]
    assert run["status"] == "failed" and "hook" in run["error"], run
    assert not (project_dir / "made.txt").exists()
    assert hooked_app.record()["stdin"] in (None, "")  # never told what to do


def test_a_write_to_agys_project_hooks_is_a_card_at_full_auto(hooked_app, wait_run, project_dir):
    client, provider = hooked_app([
        write_file(".agents/hooks.json", "{}"), {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_status(client, cid, "waiting_approval")
    (card,) = [c for c in snap["file_changes"] if c["status"] == "proposed"]
    assert card["path"] == ".agents/hooks.json"
    client.post(f"/api/file-changes/{card['id']}/reject")
    wait_run(client, cid, run_id)
    assert decisions(hooked_app) == ["deny"] and not (project_dir / ".agents").exists()


def test_a_tool_that_ran_without_its_hook_is_marked_and_ends_the_run(
    hooked_app, wait_run, project_dir
):
    client, provider = hooked_app([
        run_command("python made.py", touches={"made.txt": "x"}, unhooked=True),
        {"say": "done"}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    run = snap["runs"][0]
    assert run["status"] == "failed" and UNASKED in run["error"], run
    (ran,) = [t for t in snap["tool_calls"] if t["name"] == "run_command"]
    assert UNASKED in ran["result"]


def test_a_hook_that_cannot_reach_koloni_blocks_the_tool(hooked_app, wait_run, project_dir):
    client, provider = hooked_app([
        run_command("python made.py", touches={"made.txt": "x"}, remove=DOOR),
        {"say": "done"}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "failed"  # (agy itself ends its turn: measured)
    assert not (project_dir / "made.txt").exists()
    (ran,) = hooked_app.record()["hooks"]
    assert ran["code"] != 0 and json.loads(ran["out"])["decision"] == "deny"


# --- 5. KOLONİ's home, and nothing of the door anywhere but in it -----------------------------


def test_the_home_is_kolonis_and_is_cleaned_up(hooked_app, wait_run, project_dir):
    client, provider = hooked_app([run_command("python hello.py"), {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    seen = hooked_app.record()
    home = Path(seen["env"]["USERPROFILE"])
    assert seen["env"]["HOME"] == str(home) and home.parent == hooked_app.homes
    assert list(hooked_app.homes.iterdir()) == []  # gone after the run
    # the user's own home: neither read for its hooks nor written to
    assert not (hooked_app.real / ".gemini" / "antigravity-cli").exists()
    hooks = json.loads(seen["config"]["hooks.json"])
    ((group,),) = [one["PreToolUse"] for one in hooks.values()]
    (hook,) = group["hooks"]
    assert group["matcher"] == "*" and hook["timeout"] >= 1800
    assert len(seen["hooks"]) == 1 and seen["hooks"][0]["command"] == hook["command"]


def test_no_key_or_port_is_on_a_command_line_or_in_the_environment(
    hooked_app, wait_run, project_dir
):
    client, provider = hooked_app([run_command("python hello.py"), {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)
    assert wait_run(client, cid, run_id)["runs"][0]["status"] == "completed"
    seen = hooked_app.record()
    door = json.loads(seen["config"][DOOR])
    key, port = door["key"], str(door["port"])
    lines = [*seen["argv"], *(ran["command"] for ran in seen["hooks"])]
    assert key not in json.dumps([lines, seen["env"], seen["stdin"]])
    assert port not in [word for line in lines for word in line.split()]
    assert port not in seen["env"].values()


@WINDOWS_CMD
def test_a_path_with_a_space_goes_through_a_cmd_wrapper(
    hooked_app, wait_run, project_dir, tmp_path, monkeypatch
):
    import app.agy_hook

    spaced = tmp_path / "with space" / "agy_hook.py"
    spaced.parent.mkdir()
    shutil.copy(app.agy_hook.__file__, spaced)
    monkeypatch.setattr(app.agy_hook, "__file__", str(spaced))
    client, provider = hooked_app([
        run_command("python made.py", touches={"made.txt": "x"}), {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    seen = hooked_app.record()
    (ran,) = seen["hooks"]
    assert ran["command"].endswith(".cmd") and " " not in ran["command"]
    (wrapper,) = [text for name, text in seen["config"].items() if name.endswith(".cmd")]
    assert f'"{spaced}"' in wrapper
    assert json.loads(ran["out"])["decision"] == "allow"
    assert (project_dir / "made.txt").exists()


@WINDOWS_CMD
@pytest.mark.parametrize("folder", ["a b", "Masaüstü"])  # (OneDrive's Desktop on Turkish Windows)
def test_a_home_whose_path_has_a_space_or_a_letter_beyond_ascii_works(
    hooked_app, wait_run, project_dir, tmp_path, folder
):
    homes = tmp_path / folder / "agy-home"
    client, provider = hooked_app([
        run_command("python made.py", touches={"made.txt": "x"}), {"say": "ok"}], homes=homes)
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    (ran,) = hooked_app.record()["hooks"]
    # the hook is started from the folder of hooks.json: no path of the home on its line
    assert ran["command"] == r".\koloni-hook.cmd" and json.loads(ran["out"])["decision"] == "allow"
    assert (project_dir / "made.txt").exists() and list(homes.iterdir()) == []


@WINDOWS_CMD
def test_a_hook_script_whose_path_has_a_letter_beyond_ascii_is_started_by_its_short_name(
    hooked_app, wait_run, project_dir, tmp_path, monkeypatch
):
    import app.agy_hook

    placed = tmp_path / "Masaüstü" / "agy_hook.py"
    placed.parent.mkdir()
    shutil.copy(app.agy_hook.__file__, placed)
    monkeypatch.setattr(app.agy_hook, "__file__", str(placed))
    client, provider = hooked_app([
        run_command("python made.py", touches={"made.txt": "x"}), {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    (wrapper,) = [text for name, text in hooked_app.record()["config"].items()
                  if name.endswith(".cmd")]
    assert wrapper.isascii() and "Masaüstü" not in wrapper  # its 8.3 name: MASAST~1
    assert (project_dir / "made.txt").exists()


def test_the_users_own_gemini_and_antigravity_settings_do_not_reach_native_agy(
    hooked_app, wait_run, project_dir, monkeypatch
):
    monkeypatch.setenv("GEMINI_API_KEY", "the-users-own")
    monkeypatch.setenv("ANTIGRAVITY_CONFIG_DIR", "C:/elsewhere")
    client, provider = hooked_app([{"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)
    assert wait_run(client, cid, run_id)["runs"][0]["status"] == "completed"
    env = hooked_app.record()["env"]
    assert [name for name in env if name.upper().startswith(("GEMINI_", "ANTIGRAVITY_"))] == []


def test_a_home_left_behind_by_an_earlier_process_is_removed_at_start(settings_env, tmp_path):
    left = tmp_path / "runtime" / "agy-home" / "agy-left1234"
    (left / ".gemini" / "config").mkdir(parents=True)
    (left / ".gemini" / "config" / DOOR).write_text("{}", encoding="utf-8")
    create_app(load_settings(settings_env))
    assert not left.exists()


# --- 6. How each of agy's tools is asked about ------------------------------------------------


def test_how_each_of_agys_tools_is_asked_about():
    assert asked_as("run_command", {"CommandLine": "pytest -q", "Cwd": "sub"}) == [
        ("Bash", {"command": "pytest -q", "cwd": "sub"})]
    # one that asks to run outside its sandbox has that for a reason: a card at every level
    for bypass in (True, "true"):
        assert asked_as("run_command", {"CommandLine": "pytest -q", "BypassSandbox": bypass}) == [
            ("Bash", {"command": "pytest -q", "reason": "it asks to run outside its sandbox"})]
    assert asked_as("run_command", {"CommandLine": "pytest -q", "BypassSandbox": False}) == [
        ("Bash", {"command": "pytest -q"})]
    # input to a command at work is judged as a command; its output is only read
    assert asked_as("send_command_input", {"CommandId": "c1", "Input": "rm -rf build\n"}) == [
        ("Bash", {"command": "rm -rf build\n"})]
    assert asked_as("command_status", {"CommandId": "c1"}) == []
    # the files a search is held to go with it
    assert asked_as("grep_search", {"SearchPath": "src", "Query": "x", "Includes": ["*.py"]}) == [
        ("Grep", {"path": "src", "glob": ["*.py"]})]
    # argument names in any case and joined any way - but "Profile" is no file
    for named in ("absolutePath", "absolute_path", "ABSOLUTE_PATH"):
        assert asked_as("view_file", {named: "a.py", "Profile": "p"}) == [
            ("Read", {"file_path": "a.py"})], named
    # a whole-file write that names two files: each is asked about
    assert asked_as("write_file", {"Path": "a.txt", "TargetFile": "b.txt", "Content": "x"}) == [
        ("Write", {"file_path": "a.txt", "content": "x"}),
        ("Write", {"file_path": "b.txt", "content": "x"})]
    # a change of each file a tool KOLONİ does not know names, with all it was given
    moved = {"SourcePath": "a.py", "TargetPath": "b.py"}
    assert asked_as("move", moved) == [("Edit", {**moved, "file_path": "a.py"}),
                                       ("Edit", {**moved, "file_path": "b.py"})]


def test_what_koloni_cannot_judge_of_agys_tools_is_refused_or_asked_in_words():
    for refused in (asked_as("run_command", {}), asked_as("send_command_input", {}),
                    asked_as("view_file", {}), asked_as("write_file", {"Content": "x"}),
                    asked_as("invoke_subagent", {"Task": "x"})):
        assert isinstance(refused, str), refused
    assert asked_as("invoke_subagent", {}) == UNKNOWN_YET
    # a look whose path is not found, and a tool with no path at all: asked in words
    for tool, args in (("list_dir", {"Where": "x"}), ("search_web", {"query": "x"})):
        ((name, given),) = asked_as(tool, args)
        assert name == tool and given["reason"] and all(given[k] == v for k, v in args.items())


def test_a_listing_is_harmless_only_of_kolonis_server_and_another_servers_tool_is_asked():
    # B-318: a listing of KOLONİ's server changes nothing; of another, of none named, or with
    # more than a server, it is asked - as is a wrapped call left wrapped, whatever path it names
    assert asked_as("list_resources", {"ServerName": "koloni"}) == []
    for tool, args in (("list_resources", {"ServerName": "other"}), ("list_resources", {}),
                       ("list_tools", {"ServerName": "koloni", "Cursor": "x"}),
                       ("list_resources", {"ServerName": "other", "FilePath": "hello.py"}),
                       ("call_mcp_tool", {"ServerName": "other", "ToolName": "x",
                                          "FilePath": "hello.py"})):
        ((name, given),) = asked_as(tool, args)
        assert name == tool and given["reason"], (tool, args)


def test_agys_wrapper_is_kolonis_tool_only_when_it_names_kolonis_server_and_one_tool():
    from app.model_agy import unwrapped

    assert unwrapped("call_mcp_tool", {"ServerName": "koloni", "ToolName": "read_backlog",
                                       "Arguments": {}}) == "mcp__koloni__read_backlog"
    assert unwrapped("call_mcp_tool", {"server_name": "koloni", "tool_name": "x"}) == \
        "mcp__koloni__x"
    for args in ({"ServerName": "other", "ToolName": "read_backlog"}, {"ServerName": "koloni"},
                 {"ServerName": "koloni", "ToolName": "a", "Name": "b"},
                 {"ServerName": "koloni", "ToolName": ["read_backlog"]},
                 {"ServerName": "koloni", "Server": "koloni", "ToolName": "read_backlog"},
                 # (a key more - another way of naming the server, say - leaves it wrapped)
                 {"ServerName": "koloni", "ServerId": "evil", "ToolName": "read_backlog"},
                 {"ServerName": "koloni", "ToolName": "read_backlog", "Arguments": {},
                  "Args": {}}):
        assert unwrapped("call_mcp_tool", args) == "call_mcp_tool", args
    assert unwrapped("view_file", {"ServerName": "koloni", "ToolName": "x"}) == "view_file"


def test_only_a_definition_with_one_link_in_this_runs_own_folder_is_its_own(tmp_path):
    from app.model_agy import own_definition

    home = tmp_path / "agy-1"
    (home / ".gemini" / "config").mkdir(parents=True)
    defined = home / ".gemini" / "antigravity-cli" / "mcp" / "koloni"
    defined.mkdir(parents=True)
    (defined / "spawn_agent.json").write_text("{}", encoding="utf-8")
    key = home / ".gemini" / "config" / "bridge.json"
    key.write_text('{"key": "k"}', encoding="utf-8")
    os.link(key, defined / "read_backlog.json")  # (a hard link to the bridge's key)
    offered = {"spawn_agent", "read_backlog"}
    assert own_definition(str(defined / "spawn_agent.json"), home, offered)
    assert not own_definition(str(defined / "read_backlog.json"), home, offered)
    assert not own_definition(str(defined / "spawn_agent.json"), home, {"read_backlog"})
    assert not own_definition("spawn_agent.json", home, offered)  # (relative: never resolved)


def test_natively_a_wrapper_is_kolonis_only_as_its_hook_judged_it():
    # (its stream's parameters say koloni, but its hook let it through as no tool of KOLONİ's)
    from app.model_agy import _Bridged, _Hooked

    bridged, hooked = _Bridged(frozenset({"read_backlog"})), _Hooked()
    hooked.steps["agy_3"] = True
    translate = AgyClient(None, "m", reads=False)._translator(hooked, bridged)
    given = {"ServerName": "koloni", "ToolName": "read_backlog"}
    (started,) = translate(wrapper_step("ACTIVE", given))  # (told: nothing judged it KOLONİ's)
    told = translate(wrapper_step("DONE", given))
    assert [one["item"]["tool"] for one in told] == ["call_mcp_tool"] and bridged.reported == 0
    assert started["item"]["id"] == told[0]["item"]["id"]
    # as its hook judged it: KOLONİ's, counted, and on record where KOLONİ ran it
    bridged.served, hooked.kolonis["agy_4"] = 1, "mcp__koloni__read_backlog"
    assert translate(wrapper_step("DONE", {}, 4)) == [] and bridged.reported == 1
    # its start told before its hook ran is settled with no record of its own
    (started,) = translate(wrapper_step("ACTIVE", {}, 5))
    bridged.served, hooked.kolonis["agy_5"] = 2, "mcp__koloni__read_backlog"
    assert translate(wrapper_step("DONE", {}, 5)) == [{"type": "item.completed", "item": {
        "type": "mcp_tool_call", "id": started["item"]["id"], "server": "agy",
        "settled": True}}]
    # another tool at a step its hook once judged a wrapper is itself, never dropped
    hooked.kolonis["agy_6"] = "mcp__koloni__read_backlog"
    bridged.served += 1
    told = translate(tool_step("DONE", "view_file", {"AbsolutePath": "a.py"}, 6))
    assert [one["item"]["tool"] for one in told] == ["view_file"] and bridged.reported == 2
    # reading only, one whose stream names no parameters is agy's own and not counted
    bridged = _Bridged(frozenset({"read_backlog"}))
    told = AgyClient(None, "m")._translator(None, bridged)(wrapper_step("DONE", {}))
    assert [one["item"]["tool"] for one in told] == ["call_mcp_tool"] and bridged.reported == 0


def tool_step(state, name, given, index):
    return {"event": "step_update", "step_update": {
        "step_index": index, "state": state, "step_type": "tool", "tool_name": name,
        "tool_info": {"name": name, "parameters": given, "output": "x"}}}


def wrapper_step(state, given, index=3):
    return {"event": "step_update", "step_update": {
        "step_index": index, "state": state, "step_type": "tool", "tool_name": "call_mcp_tool",
        "tool_info": {"name": "call_mcp_tool", "parameters": given, "output": "x"}}}
