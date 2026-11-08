"""Native Claude Code over its stream-json control protocol (slice 89b): one PreToolUse hook
for every tool, so that each of its tools - its reads too - is KOLONİ's to decide
(`AgentRunner._approve`), once; a Claude Code whose hook is not taken never runs."""

import asyncio
import json
import time
from pathlib import Path

import pytest

from app import model_cli, model_native, raw
from app.agent import UNASKED_BY_CLI as NOTE
from app.model_client import ModelUnavailable
from app.model_native import ClaudeNativeClient
from app.workspace import SECRET_CARD
from tests.test_agent_writes import wait_status
from tests.test_attachment_agents import FAKE_CLAUDE, answered, nothing, plan, record
from tests.test_chat_flow import text
from tests.test_claude_native import (
    ORIGIN,
    claude_app,  # noqa: F401  (a fixture)
    hello,
    start,
)
from tests.test_codex_app_server_scenarios import steered, watched
from tests.test_secret_read_scenarios import SECRET
from tests.test_skill_scenarios import add, give
from tests.test_spawn import role_id, spawn

UNASKED = NOTE.format(who="Claude Code")
ACCOUNT = {"email": "someone@example.com", "organization": "acct-4711-not-for-koloni"}


def env(project_dir):
    (project_dir / ".env").write_text(SECRET + "\n", encoding="utf-8")


def read(named, tool="Read", **more):
    return {"tool": tool, "input": {"file_path": named} if tool == "Read" else
            {"pattern": "KEY", **more}, "result": "x"}


def write(named, content="x"):
    return {"tool": "Write", "input": {"file_path": f"PROJECT/{named}", "content": content},
            "write": [named, content]}


def decisions(claude_app):  # noqa: F811
    """What KOLONİ's hook said of each tool, in order."""
    return [one["hookSpecificOutput"]["permissionDecision"]
            for one in claude_app.record()["hooks"]]


def verdicts(claude_app):  # noqa: F811
    return [one["behavior"] for one in claude_app.record()["asked"]]


def pending(client, cid):
    snap = wait_status(client, cid, "waiting_approval")
    return snap, [t for t in snap["tool_calls"] if t["status"] == "pending"]


# --- 1. It is started with its hook, before it is given anything to do ----------------------


def test_it_is_started_over_the_control_protocol_with_one_hook_for_every_tool(
    claude_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _ = claude_app([{"say": "done"}])
    cid, run_id = start(client, project_dir, provider, "ask")
    assert wait_run(client, cid, run_id)["runs"][0]["status"] == "completed"
    seen = claude_app.record()
    argv = seen["argv"]
    assert argv[argv.index("--input-format") + 1] == "stream-json"
    assert argv[argv.index("--output-format") + 1] == "stream-json"
    assert argv[argv.index("--permission-prompt-tool") + 1] == "stdio"
    # no "ask Read" rule (the hook holds every read); the project's own hooks are off - a
    # cloned repo's .claude/settings.json hooks ran unasked (measured on 2.1.311)
    assert json.loads(argv[argv.index("--settings") + 1]) == {"disableAllHooks": True}
    # neither the user's own skills and commands (they showed in `initialize`)
    assert "--disable-slash-commands" in argv
    assert "--no-session-persistence" in argv and argv.count("--strict-mcp-config") == 1
    request = seen["init"]
    assert request["type"] == "control_request"
    assert request["request"]["subtype"] == "initialize"
    (matcher,) = request["request"]["hooks"]["PreToolUse"]
    assert matcher["matcher"] is None and len(matcher["hookCallbackIds"]) == 1
    # the prompt came after it, as a user message
    assert "fix the greeting" in seen["stdin"]
    # and no tool that gives leave is offered to the model any more
    assert "approve" not in seen["tools"] and "spawn_agent" in seen["tools"]


# --- 2. Full auto: a secret is a card, an ordinary read and write are not -------------------


def test_at_full_auto_a_read_of_a_secret_is_a_card_and_an_ordinary_read_is_not(
    claude_app, wait_run, project_dir  # noqa: F811
):
    env(project_dir)
    client, provider, _ = claude_app([read("PROJECT/hello.py"), read("PROJECT/.env"),
                                      {"say": "done"}])
    cid, run_id = start(client, project_dir, provider, "full_auto")
    _snap, (asked,) = pending(client, cid)
    assert asked["name"] == "read_file" and asked["why_asked"] == SECRET_CARD
    client.post(f"/api/tool-calls/{asked['id']}/reject", headers={"Origin": ORIGIN})
    wait_run(client, cid, run_id, timeout=20)
    # one decision for each: the hook hands it to can_use_tool, which KOLONİ answers
    assert decisions(claude_app) == ["ask", "ask"]
    assert verdicts(claude_app) == ["allow", "deny"]


def test_at_full_auto_a_grep_of_a_secret_is_a_card_by_its_path_or_its_glob(
    claude_app, wait_run, project_dir  # noqa: F811
):
    env(project_dir)
    client, provider, _ = claude_app([
        read(None, "Grep", path=".env"), read(None, "Grep", glob=".env"),
        read(None, "Grep", path="hello.py"), {"say": "done"}])
    cid, run_id = start(client, project_dir, provider, "full_auto")
    seen = set()
    for _ in range(2):
        _snap, cards = pending(client, cid)
        (asked,) = [one for one in cards if one["id"] not in seen]
        seen.add(asked["id"])
        assert asked["why_asked"] == SECRET_CARD
        client.post(f"/api/tool-calls/{asked['id']}/reject", headers={"Origin": ORIGIN})
    snap = wait_run(client, cid, run_id, timeout=20)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert verdicts(claude_app) == ["deny", "deny", "allow"]


@pytest.mark.parametrize("given", [
    {"glob": ".env*", "output_mode": "content"},  # (as measured on 2.1.310)
    {"glob": "*"}, {"glob": "{.env,a.py}"}, {"glob": "**/*"}, {"path": "."}, {},
])
def test_at_full_auto_a_grep_over_a_folder_with_a_secret_its_glob_could_match_is_a_card(
    claude_app, wait_run, project_dir, given  # noqa: F811
):
    env(project_dir)
    client, provider, _ = claude_app([read(None, "Grep", **given), {"say": "done"}])
    cid, run_id = start(client, project_dir, provider, "full_auto")
    _snap, (asked,) = pending(client, cid)
    assert asked["why_asked"] == SECRET_CARD and ".env" in asked["arguments"]
    client.post(f"/api/tool-calls/{asked['id']}/reject", headers={"Origin": ORIGIN})
    wait_run(client, cid, run_id, timeout=20)
    assert verdicts(claude_app) == ["deny"]


def test_a_grep_whose_glob_cannot_match_a_secret_is_no_card(
    claude_app, wait_run, project_dir  # noqa: F811
):
    env(project_dir)
    client, provider, _ = claude_app([read(None, "Grep", glob="*.py", path="."),
                                      {"say": "done"}])
    statuses = watched(client)
    cid, run_id = start(client, project_dir, provider, "full_auto")
    assert wait_run(client, cid, run_id)["runs"][0]["status"] == "completed"
    assert "waiting_approval" not in statuses and verdicts(claude_app) == ["allow"]


def test_at_full_auto_a_command_that_reads_a_secret_is_a_command_card(
    claude_app, wait_run, project_dir  # noqa: F811
):
    env(project_dir)
    client, provider, _ = claude_app([
        {"tool": "Bash", "input": {"command": "cat .env"}, "result": SECRET}, {"say": "done"}])
    cid, run_id = start(client, project_dir, provider, "full_auto")
    snap = wait_status(client, cid, "waiting_approval")
    (asked,) = snap["commands"]
    assert (asked["status"], asked["command"]) == ("proposed", "cat .env")
    client.post(f"/api/commands/{asked['id']}/reject")
    wait_run(client, cid, run_id)
    assert verdicts(claude_app) == ["deny"]


def test_at_full_auto_a_write_of_github_is_a_card_and_claude_md_or_an_ordinary_one_is_not(
    claude_app, wait_run, project_dir  # noqa: F811
):
    # (K-fullauto-sorma 2: an instruction file alone is written unasked at Full auto; a
    # workflow, which runs by itself, is a card there as before.)
    client, provider, _ = claude_app([
        write("CLAUDE.md"), write(".github/workflows/ci.yml"), write("notes.txt"),
        {"say": "done"}])
    cid, run_id = start(client, project_dir, provider, "full_auto")
    snap = wait_status(client, cid, "waiting_approval")
    (proposed,) = [c for c in snap["file_changes"] if c["status"] == "proposed"]
    assert proposed["path"] == ".github/workflows/ci.yml"
    client.post(f"/api/file-changes/{proposed['id']}/reject")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert verdicts(claude_app) == ["allow", "deny", "allow"]
    assert (project_dir / "CLAUDE.md").read_text(encoding="utf-8") == "x"
    assert not (project_dir / ".github").exists()
    assert (project_dir / "notes.txt").read_text(encoding="utf-8") == "x"


# --- 3. Ask: an ordinary write is a card - one ----------------------------------------------


def test_at_ask_an_ordinary_write_is_one_card_and_approved_it_is_written(
    claude_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _ = claude_app([write("hello.py", "print('hello')\n"), {"say": "done"}])
    cid, run_id = start(client, project_dir, provider, "ask")
    snap = wait_status(client, cid, "waiting_approval")
    (change,) = snap["file_changes"]
    assert snap["questions"] == []  # one card: the diff
    client.post(f"/api/file-changes/{change['id']}/approve")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert hello(project_dir) == "print('hello')\n"
    assert (decisions(claude_app), verdicts(claude_app)) == (["ask"], ["allow"])
    assert [c["status"] for c in snap["file_changes"]] == ["applied"]


def test_at_ask_a_rejected_write_is_denied_and_not_made(
    claude_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _ = claude_app([write("hello.py", "print('hello')\n"), {"say": "done"}])
    cid, run_id = start(client, project_dir, provider, "ask")
    (change,) = wait_status(client, cid, "waiting_approval")["file_changes"]
    client.post(f"/api/file-changes/{change['id']}/reject")
    snap = wait_run(client, cid, run_id)
    assert hello(project_dir) == "print('hi')\n"
    assert verdicts(claude_app) == ["deny"]
    assert [c["status"] for c in snap["file_changes"]] == ["rejected"]


def test_at_ask_an_ordinary_read_inside_the_project_is_no_card(
    claude_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _ = claude_app([
        read("PROJECT/hello.py"), read(None, "Grep", path="hello.py"),
        {"tool": "Glob", "input": {"pattern": "*.py"}, "result": "hello.py"}, {"say": "done"}])
    statuses = watched(client)
    cid, run_id = start(client, project_dir, provider, "ask")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert "waiting_approval" not in statuses
    assert verdicts(claude_app) == ["allow", "allow", "allow"]


def test_at_ask_reading_a_background_commands_output_is_no_card(
    claude_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _ = claude_app([
        {"tool": "BashOutput", "input": {"bash_id": "b1"}, "result": "still going"},
        {"tool": "KillShell", "input": {"shell_id": "b1"}, "result": "ended"}, {"say": "done"}])
    statuses = watched(client)
    cid, run_id = start(client, project_dir, provider, "ask")
    assert wait_run(client, cid, run_id)["runs"][0]["status"] == "completed"
    assert "waiting_approval" not in statuses
    assert verdicts(claude_app) == ["allow", "allow"]


# --- 4. KOLONİ's own tools, and one it does not know ----------------------------------------


def test_kolonis_own_tools_are_let_through_by_the_hook(
    claude_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _ = claude_app([
        {"koloni": "post_note", "args": {"text": "looked at hello.py"}}, {"say": "done"}])
    cid, run_id = start(client, project_dir, provider, "ask")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert decisions(claude_app) == ["allow"] and claude_app.record()["asked"] == []
    assert [t["name"] for t in snap["tool_calls"]] == ["post_note"]


def test_a_tool_koloni_does_not_know_is_a_card_and_denied_it_does_not_run(
    claude_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _ = claude_app([
        {"tool": "mcp__theirs__do", "input": {"what": "x"}, "write": ["did.txt", "x"]},
        {"say": "done"}])
    cid, run_id = start(client, project_dir, provider, "ask")
    question = wait_status(client, cid, "waiting_approval")["questions"][0]
    assert "mcp__theirs__do" in question["question"]
    client.post(f"/api/questions/{question['id']}/answer", json={"answer": "Deny"},
                headers={"Origin": ORIGIN})
    wait_run(client, cid, run_id)
    assert verdicts(claude_app) == ["deny"]
    assert not (project_dir / "did.txt").exists()


def test_its_monitor_tool_is_asked_about_as_a_command(
    claude_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _ = claude_app([
        {"tool": "Monitor", "input": {"command": "tail -f app.log", "description": "log"},
         "result": "line"}, {"say": "done"}])
    cid, run_id = start(client, project_dir, provider, "ask")
    (asked,) = wait_status(client, cid, "waiting_approval")["commands"]
    assert (asked["status"], asked["command"]) == ("proposed", "tail -f app.log")
    client.post(f"/api/commands/{asked['id']}/reject")
    wait_run(client, cid, run_id)
    assert verdicts(claude_app) == ["deny"]


def test_a_monitor_that_names_no_command_is_refused(
    claude_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _ = claude_app([
        {"tool": "Monitor", "input": {"ws": {"url": "wss://example.com"}}}, {"say": "done"}])
    cid, run_id = start(client, project_dir, provider, "full_auto")
    wait_run(client, cid, run_id)
    (verdict,) = claude_app.record()["asked"]
    assert verdict["behavior"] == "deny" and "names none" in verdict["message"]


def test_its_tools_that_act_later_or_elsewhere_are_never_given(
    claude_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _ = claude_app([{"say": "done"}])
    cid, run_id = start(client, project_dir, provider, "full_auto")
    wait_run(client, cid, run_id)
    argv = claude_app.record()["argv"]
    withheld = set(argv[argv.index("--disallowedTools") + 1].split(","))
    assert {"EnterWorktree", "ExitWorktree", "CronCreate", "CronDelete", "ScheduleWakeup",
            "RemoteTrigger", "PushNotification", "AskUserQuestion", "Workflow",
            "DesignSync", "SendMessage", "ListAgents"} <= withheld


def test_its_task_tool_is_one_of_its_sub_agents_as_agent_is(
    claude_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _ = claude_app([
        {"tool": "Task", "id": "toolu_sub", "result": "Async agent launched.",
         "input": {"description": "Look around", "prompt": "read hello.py"}},
        {"tool": "Read", "input": {"file_path": "PROJECT/hello.py"}, "result": "x",
         "parent": "toolu_sub"},
        {"system": {"subtype": "task_notification", "tool_use_id": "toolu_sub",
                    "status": "completed", "summary": "It prints hi."}},
        {"say": "Done."}])
    cid, run_id = start(client, project_dir, provider, "full_auto")
    snap = wait_run(client, cid, run_id)
    calls = {c["name"]: c for c in snap["tool_calls"]}
    sub = calls["claude__Task"]
    assert (sub["status"], sub["result"]) == ("succeeded", "It prints hi.")
    assert calls["claude__Read"]["parent_call_id"] == sub["id"]


def test_a_permission_prompt_koloni_cannot_tie_to_a_tool_use_is_denied(
    claude_app, wait_run, project_dir  # noqa: F811
):
    # (Measured: every prompt names its tool use. One that names none is not answered yes.)
    client, provider, _ = claude_app([{**write("hello.py"), "no_id": True}, {"say": "done"}])
    cid, run_id = start(client, project_dir, provider, "full_auto")
    snap = wait_run(client, cid, run_id)
    assert verdicts(claude_app) == ["deny"]
    assert hello(project_dir) == "print('hi')\n"
    assert snap["file_changes"] == []


# --- 5. Fail closed: no hook, no run --------------------------------------------------------


def test_a_claude_code_that_refuses_the_hook_is_stopped_with_its_version_and_never_prompted(
    claude_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _ = claude_app([write("hello.py"), {"say": "done"}], initialize="error")
    cid, run_id = start(client, project_dir, provider, "full_auto")
    run = wait_run(client, cid, run_id, timeout=15)["runs"][0]
    assert run["status"] == "failed"
    assert "2.1.310" in run["error"] and "could not be asked before it acts" in run["error"]
    assert "unknown hook event" in run["error"]
    assert claude_app.record()["stdin"] == ""  # it was never given the prompt
    assert hello(project_dir) == "print('hi')\n"


def test_a_claude_code_that_never_answers_initialize_is_stopped_soon(
    claude_app, wait_run, project_dir, monkeypatch  # noqa: F811
):
    monkeypatch.setattr(model_native, "START_SECONDS", 1)  # (not its 30 s of silence)
    client, provider, _ = claude_app([write("hello.py")], initialize="silent")
    cid, run_id = start(client, project_dir, provider, "full_auto")
    run = wait_run(client, cid, run_id, timeout=15)["runs"][0]
    assert run["status"] == "failed" and "could not be asked before it acts" in run["error"]
    assert "did not answer for 1 seconds" in run["error"]
    assert claude_app.record()["stdin"] == ""


def test_a_claude_code_that_answers_without_applying_the_hook_is_stopped(
    claude_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _ = claude_app([write("hello.py")], hooks_applied=False)
    cid, run_id = start(client, project_dir, provider, "full_auto")
    run = wait_run(client, cid, run_id, timeout=15)["runs"][0]
    assert run["status"] == "failed" and "could not be asked before it acts" in run["error"]
    assert "did not apply KOLONİ's hook" in run["error"]
    assert claude_app.record()["stdin"] == "" and hello(project_dir) == "print('hi')\n"


def test_a_claude_code_that_dies_before_it_answers_says_why(
    claude_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _ = claude_app([write("hello.py")], initialize="die")
    cid, run_id = start(client, project_dir, provider, "full_auto")
    run = wait_run(client, cid, run_id, timeout=15)["runs"][0]
    assert run["status"] == "failed" and "2.1.310" in run["error"]
    assert "cannot take hooks from its host" in run["error"]  # what it said, kept


# --- 5b. KOLONİ's own skills, as a plugin of its own (89o): only where it keeps the user's out


TIDY = "---\nname: tidy\ndescription: Keep it small.\nallowed-tools: Bash\n---\n\nWrite less.\n"
# Measured on 2.1.311: such a line runs as the skill loads, past the hook and can_use_tool.
BANG = "---\nname: bang\ndescription: Says bang.\n---\n\n!`echo BANG > bang.txt`\n"


def kept(client, tmp_path, text):
    """A skill of this text (and a file beside it) in KOLONİ's store."""
    folder = tmp_path / "skills-in" / text.split("name: ")[1].split("\n")[0]
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(text, encoding="utf-8")
    (folder / "ref.md").write_text("more\n", encoding="utf-8")
    add(client, folder)


@pytest.mark.parametrize(("version", "plugin"), [("2.1.310", False), ("2.1.311", True),
                                                  ("2.2.0", True), ("garbled", False)])
def test_the_roles_skills_go_as_koloni_s_plugin_from_2_1_311_and_load_without_a_card(
    claude_app, wait_run, project_dir, tmp_path, version, plugin  # noqa: F811
):
    client, provider, _ = claude_app([
        {"tool": "Skill", "input": {"skill": "koloni:tidy"}, "result": "Launching skill: tidy"},
        {**read("PLUGIN_DIR/skills/tidy/ref.md"), "result": "more"},
        {"say": "done"}] if plugin else [{"say": "done"}], version=version)
    kept(client, tmp_path, TIDY)
    kept(client, tmp_path, BANG)
    give(client, "Lead", "tidy", "bang")
    cid, run_id = start(client, project_dir, provider, "ask")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed"
    seen = claude_app.record()
    argv = seen["argv"]
    # before 2.1.311 (or not known) every command and skill is off, KOLONİ's too
    assert ("--disable-slash-commands" in argv) is not plugin
    assert ("--plugin-dir" in argv) is plugin
    # B-151: given as its own, a skill is only named in its instructions; one that runs a
    # command as it loads is not given at all - and that is said once. Else both are there.
    told = seen["stdin"]
    assert ("koloni:tidy" in told, "Write less." in told, "echo BANG" in told) == (
        (True, False, False) if plugin else (False, True, True))
    said = [(c["status"], c["result"]) for c in snap["tool_calls"] if c["name"] == "use_skill"]
    assert said == ([("denied", "skill bang was not given to Claude Code: it runs a command "
                      "when it loads")] if plugin else [])
    if plugin:
        # its own skill, and a file of it, only read what KOLONİ gave: no card
        assert verdicts(claude_app) == ["allow", "allow"]
        assert seen["plugin_json"]["name"] == "koloni"
        # a skill whose text would run as it loads is not given; the other's SKILL.md is
        # written afresh, with its name and description only
        assert seen["plugin"] == [".claude-plugin/plugin.json", "skills/tidy/SKILL.md",
                                  "skills/tidy/ref.md"]
        assert seen["skill_md"] == {
            "tidy": '---\nname: tidy\ndescription: "Keep it small."\n---\n\nWrite less.\n'}
        assert not Path(argv[argv.index("--plugin-dir") + 1]).exists()  # gone after the run


@pytest.mark.parametrize(("skill", "projects"), [
    (None, None), (BANG, None),
    # a cloned repo's own skills and commands, unprefixed, would load with KOLONİ's
    (TIDY, "commands/deploy.md"), (TIDY, "skills/cloned/SKILL.md")])
def test_a_run_with_no_skill_to_give_safely_keeps_every_command_off(
    claude_app, wait_run, project_dir, tmp_path, skill, projects  # noqa: F811
):
    client, provider, _ = claude_app([{"say": "done"}], version="2.1.311")
    if skill:
        kept(client, tmp_path, skill)
        give(client, "Lead", "bang" if skill == BANG else "tidy")
    if projects:
        (project_dir / ".claude" / projects).parent.mkdir(parents=True)
        (project_dir / ".claude" / projects).write_text("x", encoding="utf-8")
    cid, run_id = start(client, project_dir, provider, "ask")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed"
    argv = claude_app.record()["argv"]
    assert "--disable-slash-commands" in argv and "--plugin-dir" not in argv
    # B-151: a skill that runs a command as it loads is not in its instructions either
    assert "echo BANG" not in claude_app.record()["stdin"]
    assert [c["name"] for c in snap["tool_calls"]] == (["use_skill"] if skill == BANG else [])
    # (a project with skills of its own: given whole in the instructions, as before)
    assert ("Write less." in claude_app.record()["stdin"]) is bool(projects)


def test_only_a_file_inside_the_runs_plugin_is_read_without_a_card(tmp_path):
    plugin = tmp_path / "koloni-cli-x" / "plugin"
    (plugin / "skills" / "tidy").mkdir(parents=True)
    ours = {"koloni:tidy"}

    def given(tool, **told):
        return model_native.only_given(tool, told, ours, str(plugin))

    assert given("Read", file_path=str(plugin / "skills" / "tidy" / "ref.md"))
    assert given("Skill", skill="koloni:tidy") and not given("Skill", skill="koloni:other")
    # not the run's folder beside it (its MCP key is there), nor a relative path, nor a search
    assert not given("Read", file_path=str(plugin / "skills" / ".." / ".." / "bridge.json"))
    assert not given("Read", file_path="skills/tidy/ref.md")
    assert not given("Grep", path=str(plugin / "skills" / "tidy"), pattern="x")
    assert not model_native.only_given(
        "Read", {"file_path": str(plugin / "skills" / "tidy" / "ref.md")}, ours, None)


def test_its_version_is_asked_each_run(claude_app, wait_run, project_dir, tmp_path):  # noqa: F811
    client, provider, _ = claude_app([{"say": "done"}])  # 2.1.310
    kept(client, tmp_path, TIDY)
    give(client, "Lead", "tidy")
    cid, run_id = start(client, project_dir, provider, "ask")
    assert wait_run(client, cid, run_id)["runs"][0]["status"] == "completed"
    assert "--plugin-dir" not in claude_app.record()["argv"]
    plan = tmp_path / "plan.json"  # (claude_app's) - it is updated in between
    plan.write_text(json.dumps({**json.loads(plan.read_text(encoding="utf-8")),
                                "version": "2.1.311"}), encoding="utf-8")
    again = client.post(f"/api/conversations/{cid}/messages", json={"content": "again"})
    assert wait_run(client, cid, again.json()["run"]["id"])["runs"][-1]["status"] == "completed"
    assert "--plugin-dir" in claude_app.record()["argv"]


def test_the_users_own_setup_goes_as_it_is_without_koloni_s_plugin(
    claude_app, wait_run, project_dir, tmp_path  # noqa: F811
):
    client, provider, _ = claude_app([{"say": "done"}], version="2.1.311", own_setup=True)
    kept(client, tmp_path, TIDY)
    give(client, "Lead", "tidy")
    cid, run_id = start(client, project_dir, provider, "ask")
    assert wait_run(client, cid, run_id)["runs"][0]["status"] == "completed"
    argv = claude_app.record()["argv"]
    assert "--plugin-dir" not in argv and "--disable-slash-commands" not in argv


def test_a_read_only_role_loads_only_koloni_s_skills(
    claude_app, wait_run, project_dir, tmp_path  # noqa: F811
):
    client, provider, _ = claude_app([
        {"tool": "Skill", "input": {"skill": "koloni:tidy"}, "result": "Launching skill: tidy"},
        {"tool": "Skill", "input": {"skill": "review"}, "result": "Launching skill: review"},
        {"say": "Reviewed."}],
        default_steps=[spawn("Reviewer", "Review hello.py"), text("ok")], version="2.1.311")
    # (Without its Bash: a skill that needs a shell is never given to a role with none.)
    kept(client, tmp_path, TIDY.replace("allowed-tools: Bash\n", ""))
    give(client, "Reviewer", "tidy")
    client.patch(f"/api/roles/{role_id(client, 'Reviewer')}", json={"provider_id": provider["id"]})
    cid, run_id = start(client, project_dir, None, "full_auto")
    assert wait_run(client, cid, run_id)["runs"][0]["status"] == "completed"
    asked = claude_app.record()["asked"]
    assert [one["behavior"] for one in asked] == ["allow", "deny"]
    assert "Reviewer role" in asked[1]["message"]


@pytest.mark.parametrize(("commands", "own"), [
    ([{"name": "init"}, {"name": "anthropic-skills:docx"}], None),  # another plugin's
    ([{"name": "init"}, {"name": "mine"}], "HOME/skills/mine"),  # the user's own skill
    ([{"name": "init"}, {"name": "deploy"}], "HOME/commands/deploy.md"),  # and command
])
def test_a_claude_code_that_loads_commands_koloni_did_not_give_is_stopped_before_its_prompt(
    claude_app, wait_run, project_dir, tmp_path, commands, own  # noqa: F811
):
    if own:  # (the test's home: conftest)
        mine = Path(own.replace("HOME", str(tmp_path / "home" / ".claude")))
        mine.parent.mkdir(parents=True, exist_ok=True)
        (mine.mkdir() if not own.endswith(".md") else mine.write_text("x", encoding="utf-8"))
    client, provider, _ = claude_app([write("hello.py"), {"say": "done"}], version="2.1.311",
                                     commands=commands)
    kept(client, tmp_path, TIDY)
    give(client, "Lead", "tidy")
    cid, run_id = start(client, project_dir, provider, "full_auto")
    run = wait_run(client, cid, run_id, timeout=15)["runs"][0]
    assert run["status"] == "failed"
    assert f"loaded commands or skills KOLONİ did not give ({commands[1]['name']})" in run["error"]
    assert claude_app.record()["stdin"] == "" and hello(project_dir) == "print('hi')\n"
    # its next run has its commands off again, as before 2.1.311
    again = client.post(f"/api/conversations/{cid}/messages", json={"content": "again"})
    assert wait_run(client, cid, again.json()["run"]["id"])["runs"][-1]["status"] == "completed"
    assert "--disable-slash-commands" in claude_app.record()["argv"]


def test_a_tool_it_ran_without_its_hook_is_on_record_as_unasked(
    claude_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _ = claude_app([
        {"tool": "Bash", "input": {"command": "echo hi"}, "result": "hi", "unhooked": True},
        {**read("PROJECT/hello.py"), "unhooked": True},
        {**write("notes.txt"), "unhooked": True},
        {"say": "done"}])
    cid, run_id = start(client, project_dir, provider, "full_auto")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    results = {t["name"]: t["result"] for t in snap["tool_calls"]}
    assert results["run_command"].startswith(UNASKED)
    assert results["claude__Read"].startswith(UNASKED)
    assert UNASKED in " ".join(t["result"] or "" for t in snap["tool_calls"]
                                      if t["name"] == "edit_file")


def test_a_tool_its_own_rules_refused_is_not_called_unasked(
    claude_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _ = claude_app([
        {"tool": "Read", "input": {"file_path": "PROJECT/x"}, "error": "denied by a rule",
         "unhooked": True}, {"say": "done"}])
    cid, run_id = start(client, project_dir, provider, "full_auto")
    (call,) = wait_run(client, cid, run_id)["tool_calls"]
    assert call["status"] == "failed" and UNASKED not in (call["result"] or "")


# --- 5b. A prompt it withdraws is closed, never approved -------------------------------------


def test_a_prompt_it_withdraws_closes_its_card_and_nothing_is_written(
    claude_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _ = claude_app([
        {**write("hello.py", "print('hello')\n"), "cancel": 1.0}, {"say": "done"}])
    cid, run_id = start(client, project_dir, provider, "ask")
    snap = wait_run(client, cid, run_id, timeout=15)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert claude_app.record()["cancelled"] == 1
    assert [c["status"] for c in snap["file_changes"]] == ["rejected"]
    assert hello(project_dir) == "print('hi')\n"
    assert not [t for t in snap["tool_calls"] if t["status"] in ("pending", "running")]


# --- 6. Stop asks it to stop first ---------------------------------------------------------


def test_stop_sends_interrupt(claude_app, wait_run, project_dir):  # noqa: F811
    client, provider, _ = claude_app([{"say": "Looking."}, {"hang": True}])
    cid, run_id = start(client, project_dir, provider, "full_auto")
    for _ in range(500):
        snap = client.get(f"/api/conversations/{cid}").json()
        if [m for m in snap["messages"] if m["role"] == "assistant" and m["content"]]:
            break
        time.sleep(0.02)
    client.post(f"/api/runs/{run_id}/cancel")
    assert wait_run(client, cid, run_id)["runs"][0]["status"] == "cancelled"
    for _ in range(250):
        if claude_app.record()["interrupted"]:
            break
        time.sleep(0.02)
    assert claude_app.record()["interrupted"] is True


# --- 7. Whose account it is, and where its own transcript is: kept nowhere ------------------


def test_its_account_and_its_transcripts_path_are_kept_nowhere(
    claude_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _ = claude_app([read("PROJECT/hello.py"), write("notes.txt"),
                                      {"say": "done"}], account=ACCOUNT)
    cid, run_id = start(client, project_dir, provider, "full_auto")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    kept = raw.read(snap["agents"][0]["id"])
    assert kept is not None  # its stream is kept, only not these
    for where in (json.dumps(snap), json.dumps(kept)):
        # (its init line's memory paths, socket and session too: they are its own)
        for one in (*ACCOUNT.values(), "someone/.claude", "fake-session"):
            assert one not in where, one


# --- 89d: words into its turn while it works -------------------------------------------------

@pytest.mark.anyio
async def test_a_steer_is_a_user_line_into_its_turn_and_none_after_it_ended(tmp_path):
    client = ClaudeNativeClient(launcher=FAKE_CLAUDE, **plan(
        tmp_path, [{"say": "working"}, {"await_steer": 5}, {"say": "done"}]))
    took, usage, _said, items, steer = await steered(client, tmp_path)
    assert took is True and usage.output_tokens == 30
    assert record(tmp_path)["steered"] == [{"type": "user", "message": {
        "role": "user", "content": "use blue"}, "parent_tool_use_id": None,
        "session_id": "default"}]
    assert not [item for _phase, item in items if item.get("type") == "steer_unread"]
    assert await steer("too late") is False  # (its turn is over: nothing is written)
    assert len(record(tmp_path)["steered"]) == 1


@pytest.mark.anyio
async def test_a_steer_after_its_last_word_is_read_through_to_the_turn_it_takes_on_it(tmp_path):
    client = ClaudeNativeClient(launcher=FAKE_CLAUDE, **plan(
        tmp_path, [{"say": "done"}, {"await_steer": 5}], second_turn_on_steer=True, linger=True))
    took, usage, said, items, _steer = await steered(client, tmp_path, said_first=True)
    assert took is True and "heard it late" in "".join(said)
    assert usage.output_tokens == 35  # (both turns)
    assert not [item for _phase, item in items if item.get("type") == "steer_unread"]


@pytest.mark.anyio
async def test_a_message_after_a_steer_is_not_taken_for_its_reading_and_its_turn_on_it_is_read(
        tmp_path):
    # (Review M1: its last message, from a request made before the steer, came after it and
    # was taken for its reading; the turn it took on the steer was cut off.)
    client = ClaudeNativeClient(launcher=FAKE_CLAUDE, **plan(
        tmp_path, [{"say": "working"}, {"await_steer": 5}, {"say": "done"}],
        second_turn_on_steer=True, linger=True))
    took, usage, said, _items, _steer = await steered(client, tmp_path)
    assert took is True and "heard it late" in "".join(said)
    assert usage.output_tokens == 35


@pytest.mark.anyio
async def test_a_steer_its_turn_ended_before_is_said_unread_and_its_work_stands(
        tmp_path, monkeypatch):
    monkeypatch.setattr(model_native, "LATE_SECONDS", 0.5)
    client = ClaudeNativeClient(launcher=FAKE_CLAUDE, **plan(
        tmp_path, [{"say": "done"}, {"await_steer": 5}], linger=True))
    took, usage, _said, items, _steer = await steered(client, tmp_path, said_first=True)
    assert took is True and usage.output_tokens == 30
    assert ("completed", {"type": "steer_unread", "text": "use blue"}) in items


@pytest.mark.anyio
async def test_a_claude_code_that_crashes_while_its_tool_runs_fails_the_turn_at_once(tmp_path):
    # denetim-010 #3: its tool kept the limit on silence off and a child of its own held its
    # output open: the turn waited for Stop.
    client = ClaudeNativeClient(launcher=FAKE_CLAUDE, **plan(tmp_path, [
        {"tool": "Bash", "input": {"command": "pytest"}, "open": True}, {"die": 7}]))

    async def allowed(_name, _arguments):  # (KOLONİ's yes to its tool)
        return True, json.dumps({"behavior": "allow"})

    started = time.monotonic()
    with pytest.raises(ModelUnavailable, match="code 7"):
        await client.run_native("m", [{"role": "user", "content": "go"}], [], str(tmp_path),
                                allowed, nothing, nothing)
    assert time.monotonic() - started < 20


@pytest.mark.anyio
async def test_a_turn_whose_last_lines_are_read_slowly_after_it_exited_still_stands(
        tmp_path, monkeypatch):
    # Review B2: it said its last and exited while KOLONİ was still busy with what it said
    # before (a look at the project, say): not given up as a crash past the grace.
    monkeypatch.setattr(model_cli, "EXIT_GRACE_SECONDS", 0.3)
    client = ClaudeNativeClient(launcher=FAKE_CLAUDE, **plan(tmp_path, [{"say": "done"}], exits=True))

    async def slowly(_text):
        await asyncio.sleep(2)

    usage = await client.run_native("m", [{"role": "user", "content": "go"}], [],
                                    str(tmp_path), answered, slowly, nothing)
    assert usage.output_tokens == 30
