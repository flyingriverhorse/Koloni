"""Native Copilot at protocol 4 (1.0.114, measured 20 Nov 2026): every tool of its own is asked
through KOLONİ's preToolUse hook - which never answers "allow" - and judged as the request it
would have made; a PowerShell command is put in the project first; a tool that ran past the
hook stops the turn. Only the stand-in (`fake_copilot_headless.py`) runs here."""

import json
from pathlib import Path

import pytest

import app.model_native
from app.model_native import CopilotNativeClient, _hook_answer
from tests.test_agent_writes import wait_status
from tests.test_claude_native import nothing_was_asked
from tests.test_codex_app_server_scenarios import card_for, proposed, watched
from tests.test_copilot_agent import copilot_native, start  # noqa: F401  (a fixture)
from tests.test_copilot_headless_scenarios import (
    APPROVE,
    BUILT_IN,
    REJECT,
    SCRATCH_LINE,
    TWO,
    UNASKED,
    answers,
    scratch,
)


def p4(copilot_native, script, **more):  # noqa: F811
    """A Copilot that speaks protocol 4, as 1.0.114 does."""
    return copilot_native(script, protocol=4, version="1.0.114", **more)


def at_root(copilot_native, command):  # noqa: F811
    root = copilot_native.record()["create"]["workingDirectory"]
    return f"Set-Location -LiteralPath '{root}' -ErrorAction Stop; {command}"


def test_at_protocol_4_its_session_is_grouped_with_kolonis_hook(
    copilot_native, wait_run, project_dir  # noqa: F811
):
    client, provider = p4(copilot_native, [{"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)
    assert wait_run(client, cid, run_id)["runs"][0]["status"] == "completed"
    made = copilot_native.record()["create"]
    assert made["permissions"]["request"] is True
    assert made["permissions"]["sandbox"]["enabled"] is True
    assert made["hooks"] == {"hasHandlers": True, "enableRepositoryHooks": False}
    assert made["tools"]["availableTools"][:len(BUILT_IN)] == BUILT_IN
    assert made["skills"] == {"enabled": False} and made["enableConfigDiscovery"] is False
    assert "koloni" in made["mcp"]["servers"]
    assert made["workingDirectory"] == str(project_dir)
    assert not {"requestPermission", "sandboxConfig", "mcpServers", "availableTools",
                "enableFileHooks", "enableSkills"} & set(made)


def test_every_tool_is_asked_never_allowed_and_its_command_starts_in_the_project(
    copilot_native, wait_run, project_dir  # noqa: F811
):
    client, provider = p4(copilot_native, [{"shell": "Get-ChildItem", "output": "hello.py"},
                                           {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)  # full_auto
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    seen = copilot_native.record()
    began, before = seen["hooks"]
    assert (began["hookType"], began["answer"]["result"]) == ("sessionStart", {})
    assert before["hookType"] == "preToolUse"
    assert before["answer"]["result"]["output"] == {
        "permissionDecision": "ask",
        "modifiedArgs": {"command": at_root(copilot_native, "Get-ChildItem")}}
    assert seen["ran"] == [at_root(copilot_native, "Get-ChildItem")]
    assert answers(copilot_native) == [("hook", APPROVE)]
    # on record as the command it was asked as, without KOLONİ's prefix
    assert [(c["command"], c["status"]) for c in snap["commands"]] == [("Get-ChildItem", "exited")]


@pytest.mark.parametrize("root", ["C:/p", "C:/it's", "C:/it\u2019s", "C:/a\u2018b"])
def test_kolonis_hook_never_answers_allow(root):
    for hook in ("preToolUse", "sessionStart", "permissionRequest", "postToolUse", "agentStop"):
        for name, args in (("powershell", {"command": "rm -rf x"}), ("powershell", {"command": 1}),
                           ("bash", {"command": "ls"}), ("view", {"path": "a"}),
                           ("apply_patch", "*** Begin Patch"), ("web_fetch", None)):
            said = _hook_answer({"hookType": hook, "input": {"toolName": name, "toolArgs": args}},
                                Path(root))
            assert "allow" not in json.dumps(said), (hook, name, said)
            if hook != "preToolUse":
                assert said == {}
                continue
            output = said["output"]
            assert output["permissionDecision"] == "ask"
            modified = output.get("modifiedArgs")
            if name == "powershell" and args["command"] == "rm -rf x" and "\u2018" not in root and (
                    "\u2019" not in root):
                # (a ' in its path doubled, as PowerShell reads a single-quoted string)
                quoted = str(Path(root)).replace("'", "''")
                assert modified == {
                    "command": f"Set-Location -LiteralPath '{quoted}' -ErrorAction Stop; rm -rf x"}
            else:
                # (none for a path PowerShell may read another quote in: judged without it)
                assert modified is None, (root, name, output)


def test_a_read_only_command_is_a_card_at_ask_shown_without_the_prefix_and_runs_once_approved(
    copilot_native, wait_run, project_dir  # noqa: F811
):
    # (1.0.114 asked nothing of a read-only command, a read outside the project among them,
    # measured 20 Nov 2026; its hook's "ask" makes it ask, and KOLONİ judges it)
    client, provider = p4(copilot_native, [
        {"shell": "Get-Content ../note.txt", "quiet": True, "touches": {"ran.txt": "x"}},
        {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider, mode="ask")
    asked = wait_status(client, cid, "waiting_approval")["commands"][0]
    assert (asked["command"], asked["status"]) == ("Get-Content ../note.txt", "proposed")
    assert copilot_native.record()["ran"] == [] and not (project_dir / "ran.txt").exists()
    assert client.post(f"/api/commands/{asked['id']}/approve", json={}).status_code == 200
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert answers(copilot_native) == [("hook", APPROVE)]
    assert (project_dir / "ran.txt").exists()


def test_a_command_reading_a_secret_is_a_card_even_at_full_auto_and_refused_it_does_not_run(
    copilot_native, wait_run, project_dir  # noqa: F811
):
    (project_dir / ".env").write_text("TOKEN=x\n", encoding="utf-8")
    client, provider = p4(copilot_native, [
        {"shell": "Get-Content .env", "quiet": True, "output": "TOKEN=x"}, {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)  # full_auto
    asked = wait_status(client, cid, "waiting_approval")["commands"][0]
    assert asked["command"] == "Get-Content .env"
    client.post(f"/api/commands/{asked['id']}/reject")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert answers(copilot_native) == [("hook", REJECT)] and copilot_native.record()["ran"] == []


def test_scratch_work_runs_unasked_at_full_auto_as_koloni_put_the_command_in_the_project(
    copilot_native, wait_run, project_dir  # noqa: F811
):
    # (1.0.114 is not in SHELL_READ: its own shell is not known to start in the project - KOLONİ's
    # prefix puts it there)
    scratch(project_dir)
    client, provider = p4(copilot_native, [{"shell": SCRATCH_LINE}, {"say": "ok"}])
    statuses = watched(client)
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert answers(copilot_native) == [("hook", APPROVE)]
    nothing_was_asked(snap, statuses)
    assert [(c["command"], c["cwd"], c["status"]) for c in snap["commands"]] == [
        (SCRATCH_LINE, ".", "exited")]


def test_without_kolonis_own_prefix_its_command_is_not_known_to_start_in_the_project(
    copilot_native, wait_run, project_dir  # noqa: F811
):
    scratch(project_dir)
    client, provider = p4(copilot_native, [
        {"shell": SCRATCH_LINE, "hook_shows": "original"}, {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)  # full_auto
    asked = card_for(client, cid, SCRATCH_LINE)
    assert asked["cwd"] is None and asked["danger"].startswith("Climbs out of .koloni/tmp")
    client.post(f"/api/commands/{asked['id']}/reject")
    wait_run(client, cid, run_id)
    assert answers(copilot_native) == [("hook", REJECT)] and copilot_native.record()["ran"] == []


def test_a_two_file_apply_patch_is_asked_at_its_hook_file_by_file(
    copilot_native, wait_run, project_dir  # noqa: F811
):
    client, provider = p4(copilot_native, [{"patch": TWO}, {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider, mode="ask")
    for path in ("a.txt", "b.txt"):
        card = proposed(client, cid, path)
        assert f"+made {path[0]}" in card["diff"] and not (project_dir / "a.txt").exists()
        client.post(f"/api/file-changes/{card['id']}/approve")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert answers(copilot_native) == [("hook", APPROVE)]
    assert isinstance(copilot_native.record()["hooks"][1]["input"]["toolArgs"], str)
    assert sorted((f["path"], f["status"]) for f in snap["file_changes"]) == [
        ("a.txt", "applied"), ("b.txt", "applied")]
    assert not [t for t in snap["tool_calls"] if t["status"] in ("pending", "running")]


@pytest.mark.parametrize("patch", [
    "*** Begin Patch\n*** Add File: ../a.txt\n+x\n*** End Patch",
    "*** Begin Patch\n*** Add File: C:/a.txt\n+x\n*** End Patch",
    "*** Begin Patch\n*** Add File: a.txt\n+x\r\n*** End Patch",
    "*** Add File: a.txt\n+x"])
def test_an_apply_patch_koloni_cannot_read_file_by_file_is_declined(
    copilot_native, wait_run, project_dir, patch  # noqa: F811
):
    client, provider = p4(copilot_native, [{"patch": patch}, {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)  # full_auto
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert answers(copilot_native) == [("hook", REJECT)]
    assert [t for t in snap["tool_calls"] if t["status"] == "denied"
            and "a patch KOLONİ cannot read file by file" in t["result"]]


def test_its_native_request_after_its_hook_opens_no_second_card(
    copilot_native, wait_run, project_dir  # noqa: F811
):
    client, provider = p4(copilot_native, [
        {"shell": "pytest -q", "output": "ok", "then_native": True}, {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider, mode="ask")
    asked = wait_status(client, cid, "waiting_approval")["commands"][0]
    client.post(f"/api/commands/{asked['id']}/approve", json={})
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert answers(copilot_native) == [("hook", APPROVE), ("shell", APPROVE)]
    assert [(c["command"], c["status"]) for c in snap["commands"]] == [("pytest -q", "exited")]


def test_a_native_request_naming_something_else_after_its_hook_is_a_second_card(
    copilot_native, wait_run, project_dir  # noqa: F811
):
    other = "pytest -q; Remove-Item -Recurse build"
    client, provider = p4(copilot_native, [
        {"shell": "pytest -q", "then_native": True, "native_command": other}, {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider, mode="ask")
    asked = wait_status(client, cid, "waiting_approval")["commands"][0]
    client.post(f"/api/commands/{asked['id']}/approve", json={})
    second = card_for(client, cid, other)
    client.post(f"/api/commands/{second['id']}/reject")
    wait_run(client, cid, run_id)
    assert answers(copilot_native) == [("hook", APPROVE), ("shell", REJECT)]
    assert copilot_native.record()["ran"] == []


def test_kolonis_own_and_its_quiet_tools_pass_its_hook_without_a_card(
    copilot_native, wait_run, project_dir  # noqa: F811
):
    client, provider = p4(copilot_native, [
        {"koloni": "read_notes"}, {"tool_call": "report_intent", "args": {"intent": "Look"}},
        {"tool_call": "read_powershell", "args": {"shellId": "0"}}, {"say": "ok"}])
    statuses = watched(client)
    cid, run_id = start(client, project_dir, provider, mode="ask")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert answers(copilot_native) == [("hook", APPROVE)] * 3
    nothing_was_asked(snap, statuses)
    assert copilot_native.record()["results"][0] is not None  # by KOLONİ's own rules


def test_a_tool_koloni_does_not_know_is_declined_at_its_hook_and_on_record(
    copilot_native, wait_run, project_dir  # noqa: F811
):
    client, provider = p4(copilot_native, [
        {"tool_call": "web_fetch", "args": {"url": "https://example.com"}}, {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert answers(copilot_native) == [("hook", REJECT)]
    (declined,) = [t for t in snap["tool_calls"] if t["status"] == "denied"]
    assert "KOLONİ declined" in declined["result"]


def test_a_hook_asked_for_another_session_is_answered_too(
    copilot_native, wait_run, project_dir  # noqa: F811
):
    client, provider = p4(copilot_native, [{"shell": "Get-ChildItem"}, {"say": "ok"}],
                          hook_session="s2")
    cid, run_id = start(client, project_dir, provider)
    assert wait_run(client, cid, run_id)["runs"][0]["status"] == "completed"
    assert [h["answer"]["result"].get("output", {}).get("permissionDecision")
            for h in copilot_native.record()["hooks"]] == [None, "ask"]
    assert answers(copilot_native) == [("hook", APPROVE)]


@pytest.mark.parametrize("ending", [{}, {"no_code": True}], ids=["its-trailer", "no-exit-code"])
def test_a_tool_that_ran_past_kolonis_hook_stops_the_run(
    copilot_native, wait_run, project_dir, monkeypatch, ending  # noqa: F811
):
    # The vacuity guard: were KOLONİ's hook to say nothing, Copilot would fail open (1.0.114 asks
    # nothing of a read-only command) - and the turn stops at what ran.
    monkeypatch.setattr(app.model_native, "_hook_answer", lambda params, root: {})
    client, provider = p4(copilot_native, [
        {"shell": "Get-Content hello.py", "quiet": True, **ending}, {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    run = snap["runs"][0]
    assert run["status"] == "failed" and "without KOLONİ being asked" in run["error"], run
    assert "past KOLONİ's hook" in run["error"]
    (ran,) = [t for t in snap["tool_calls"] if t["name"] == "run_command"]
    assert UNASKED in ran["result"]


def test_its_exit_code_is_read_from_its_shell_execution_when_it_has_no_trailer(
    copilot_native, wait_run, project_dir  # noqa: F811
):
    client, provider = p4(copilot_native, [
        {"shell": "pytest -q", "output": "1 failed", "exit": 1, "trailer": False},
        {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    (ran,) = snap["commands"]
    assert (ran["status"], ran["exit_code"]) == ("exited", 1)
    assert ran["output"].strip() == "1 failed"


ROOT = Path("C:/p") if app.model_native.sys.platform == "win32" else Path("/p")


@pytest.mark.parametrize("path", ["a.txt:s", "CON", "sub/NUL.txt", "../a.txt", "~/a", "a.", "a ",
                                  " a.txt", "C:a.txt", r"\\srv\share\a", "", 3, None,
                                  "sub\x00/a"])
@pytest.mark.parametrize("tool", ["view", "create", "edit"])
def test_a_file_tool_naming_no_plain_path_stays_a_hook_request_and_is_declined(tool, path):
    args = {"path": path, "file_text": "x", "old_str": "a", "new_str": "b"}
    request = {"kind": "hook", "toolName": tool, "toolArgs": args, "toolCallId": "c"}
    assert CopilotNativeClient()._from_hook(request, ROOT, set()) == (request, False)


def test_a_file_tool_is_asked_as_the_request_it_would_have_made():
    client = CopilotNativeClient()
    whole = str(ROOT / "sub" / "a.txt")
    for path in ("sub/a.txt", whole):
        def hooked(tool, path=path, **args):
            return client._from_hook({"kind": "hook", "toolName": tool, "toolCallId": "c",
                                      "toolArgs": {"path": path, **args}}, ROOT, set())[0]
        assert hooked("view") == {"kind": "read", "toolCallId": "c", "path": whole}
        assert hooked("create", file_text="x\n") == {
            "kind": "write", "toolCallId": "c", "fileName": whole,
            "fileEdits": [{"after": {"path": whole, "content": "x\n"}}]}
        edit = hooked("edit", old_str="-- a\nb", new_str="++ c")
        assert (edit["kind"], edit["fileName"]) == ("write", whole)
        # (no line a diff's header could be read as, a file it names)
        assert not app.model_native._diff_paths(edit["diff"]) and "++ c" in edit["diff"]
        assert hooked("create") == {"kind": "hook", "toolName": "create", "toolCallId": "c",
                                    "toolArgs": {"path": path}}  # (no content said: declined)


def test_a_shell_asking_to_leave_its_sandbox_at_its_hook_says_so():
    root = ROOT
    command = app.model_native._at_root(root) + "npm install"
    for key in ("requestSandboxBypass", "request_sandbox_bypass"):
        mapped, new_shell = CopilotNativeClient()._from_hook({
            "kind": "hook", "toolName": "powershell", "toolCallId": "c",
            "toolArgs": {"command": command, key: True}}, root, set())
        assert new_shell and mapped["fullCommandText"] == "npm install"
        assert mapped["requestSandboxBypass"] is True
