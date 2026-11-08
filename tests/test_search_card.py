"""A command that searches a whole folder is asked at every level, Full auto too, while that
folder holds a secret file (the user's decision, 24 October). Written before the code.

Found in a real run (slice 89e): native agy at Full auto ran
`Get-ChildItem -Path . -Force -Recurse -File | Select-String -Pattern "FAKE"`. It named no
`.env`, so `names_secret` let it through, and `.env`'s line went to the model.
"""

import json

import pytest

from app import commands
from tests.fakes import Script, ScriptedExecutor
from tests.test_agent_commands import approve, cmd
from tests.test_chat_flow import start, start_in_mode, text
from tests.test_claude_native import claude_app  # noqa: F401  (a fixture)
from tests.test_claude_native import start as start_claude
from tests.test_command_safety_scenarios import waiting
from tests.test_spawn import call, step
from tests.test_trigger_scenarios import NOBODY, allow, finished, results, run_now, setup, trigger

AGY = 'Get-ChildItem -Path . -Force -Recurse -File | Select-String -Pattern "FAKE"'

SEARCHES = [
    AGY,
    "cmd /c findstr /si key *",
    "findstr /S KEY app.py",
    "grep -rn KEY .",
    "grep -R KEY",
    "grep --recursive KEY .",
    "rg KEY",
    "ripgrep KEY",
    "ag KEY",
    "ack KEY",
    "git grep KEY",
    "powershell -Command 'Select-String -Path * -Pattern x'",
    '"C:\\WINDOWS\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" -Command \'rg KEY\'',
    "Select-String -Pattern KEY",
    "sls KEY *",
    "Get-ChildItem -Recurse | Get-Content",
    "gci -rec -File | % { gc $_ }",
    "Get-Content *",
    "gc *.env*",
    "type *",
    "cat *",
    "find . -type f -exec cat {} +",
    "find . -name '*.py' | xargs grep KEY",
    "ls -R | xargs cat",
    "npm test && rg KEY",
    "Select-String -Pattern KEY -Path (Get-ChildItem -Recurse -File)",
    "gc (gci -r -File)",
    "sls KEY -Path (gci -r).FullName",
    "git --no-pager grep KEY",
    "git -C . grep KEY",
    # (B-46: what a pipe hands Select-String or a reader is still seen)
    "Get-ChildItem -Recurse | Select-String KEY",
    "Select-String -Path .\\* -Pattern KEY",
    "gci | sls KEY",
    "rg --files | Get-Content",
    "rg --files-with-matches KEY",
    # (found in review, 25 Oct) what else hands Select-String files; grep's other recursion
    "gi * | sls KEY",
    "Get-Item * | Select-String KEY",
    "Resolve-Path * | sls KEY",
    "git ls-files --others | % { gc $_ } | sls KEY",
    "grep -d recurse KEY .",
    "grep --directories recurse KEY .",
    "grep -drecurse KEY .",
    "gci -Depth 9 -File | gc",
    # a lister of one level handed to Get-Content opens each file it names (29 Oct)
    "gci | gc", "ls | cat", "dir -File | Get-Content", "gci tests | gc", "gci | gc | sls KEY",
    # (review, 29 Oct) opened in a block, or past a stage that only shapes the names
    "gci | % { gc $_ }", "Get-ChildItem | foreach-object { Get-Content $_ }",
    "gci | select -first 3 | gc", "gci | sort | gc",
]

ORDINARY = [
    "npm test",
    "git status",
    "git commit -m 'fix the search'",
    "Get-Content README.md",
    "grep KEY app.py",
    "Select-String -Path README.md -Pattern KEY",
    "Select-String KEY README.md",
    "findstr /c:test app.py",
    "ls",
    "ls -la",
    "Get-ChildItem",
    "Get-ChildItem -Recurse",
    "find . -name x",
    "pytest -q",
    "python x.py",
    # (seen live, 24 Oct: B-46) names only; what came down a pipe from the web
    "rg --files -g AGENTS.md",
    "curl.exe -s https://example.com | Select-String -Pattern '<title>'",
    "gci", "gc a.py", "gci | measure-object", "gci | select name", "ls | head",
]


@pytest.mark.parametrize("command", SEARCHES)
def test_a_search_of_the_whole_folder_is_seen(command):
    assert commands.searches_folder(command)


@pytest.mark.parametrize("command", ORDINARY)
def test_an_ordinary_command_is_no_search(command):
    assert not commands.searches_folder(command)


def test_in_full_auto_a_search_is_asked_where_the_project_holds_a_secret(
        make_client, wait_run, project_dir):
    (project_dir / ".env").write_text("KEY=FAKE\n", encoding="utf-8")
    executor = ScriptedExecutor([])
    client, _ = make_client([cmd("rg KEY"), text("Understood.")], executor=executor)
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    asked = waiting(client, cid, 1)[0]
    assert "searches the whole folder" in asked["danger"]
    client.post(f"/api/commands/{asked['id']}/reject")
    snap = wait_run(client, cid, run_id)
    assert executor.started == [] and snap["tool_calls"][0]["status"] == "denied"


def test_in_full_auto_a_search_runs_unasked_where_the_project_holds_none(
        make_client, wait_run, project_dir):
    executor = ScriptedExecutor([Script(["hello.py:1:x\n"])])
    client, _ = make_client([cmd("rg KEY"), text("done")], executor=executor)
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    snap = wait_run(client, cid, run_id)
    assert snap["commands"][0]["status"] == "exited" and len(executor.started) == 1


def test_where_the_project_holds_no_secret_a_searchs_card_says_nothing_of_one(
        make_client, wait_run, project_dir):
    # (B-44: the line once showed on every search card at Ask)
    client, _ = make_client([cmd("rg TODO"), text("done")], executor=ScriptedExecutor([]))
    cid, run_id = start(client, project_dir)
    asked = waiting(client, cid, 1)[0]
    assert asked["danger"] == ""
    # (nor where nobody looked: the answer to a decision does not say it either)
    assert client.post(f"/api/commands/{asked['id']}/reject").json()["danger"] == ""
    wait_run(client, cid, run_id)


def test_where_the_project_holds_no_secret_a_clis_search_card_says_nothing_of_one(
        claude_app, wait_run, project_dir):  # noqa: F811
    bash = {"tool": "Bash", "ask": True, "input": {"command": "rg TODO"}, "result": "x"}
    client, provider, _ = claude_app([bash, {"say": "done"}])
    cid, run_id = start_claude(client, project_dir, provider, "ask")
    asked = waiting(client, cid, 1)[0]
    assert asked["origin"] == "cli" and asked["danger"] == ""
    client.post(f"/api/commands/{asked['id']}/reject")
    wait_run(client, cid, run_id)


def test_an_always_run_rule_does_not_cover_a_search_while_the_project_holds_a_secret(
        make_client, wait_run, project_dir):
    (project_dir / ".env").write_text("KEY=FAKE\n", encoding="utf-8")
    executor = ScriptedExecutor([Script(["x\n"]), Script(["y\n"])])
    client, _ = make_client([cmd("rg TODO", "k1"), cmd("rg KEY", "k2"), text("done")],
                            executor=executor)
    cid, run_id = start(client, project_dir)
    first = waiting(client, cid, 1)[0]
    assert first["suggested_prefix"] == "rg"
    approve(client, first["id"], remember=True)
    second = waiting(client, cid, 2)[1]  # the rule `rg` is there, and it still asks
    assert second["command"] == "rg KEY"
    approve(client, second["id"])
    wait_run(client, cid, run_id)


def test_a_native_clis_search_is_asked_in_full_auto_where_the_project_holds_a_secret(
        claude_app, wait_run, project_dir):  # noqa: F811
    (project_dir / ".env").write_text("KEY=FAKE\n", encoding="utf-8")
    bash = {"tool": "Bash", "ask": True, "input": {"command": AGY}, "result": "x"}
    client, provider, _ = claude_app([bash, {"say": "done"}])
    cid, run_id = start_claude(client, project_dir, provider, "full_auto")
    asked = waiting(client, cid, 1)[0]
    assert asked["origin"] == "cli" and asked["command"] == AGY
    client.post(f"/api/commands/{asked['id']}/reject")
    snap = wait_run(client, cid, run_id)
    assert [v["behavior"] for v in claude_app.record()["asked"]] == ["deny"]
    noted = json.loads(snap["tool_calls"][0]["arguments"])
    assert "searches the whole folder" in noted["reason"] and ".env" in noted["reason"]


def test_with_nobody_watching_a_search_is_refused_though_its_rule_is_ticked(
        make_client, wait_run, project_dir):
    (project_dir / ".env").write_text("KEY=FAKE\n", encoding="utf-8")
    client, _, pid, cid = setup(make_client, project_dir, {"Lead": [
        step(call("run_command", {"command": "rg KEY"}, "c")), text("done")]})
    rule = allow(client, cid, "rg KEY")
    made = trigger(client, pid, cid, permissions={"write": False, "commands": [rule], "agents": 0})
    run_id = run_now(client, made["id"])
    snap = finished(client, wait_run, cid, run_id)
    ((name, status, said),) = results(snap, run_id)
    assert (name, status) == ("run_command", "denied") and NOBODY in said
    assert "searches the whole folder" in said
    assert [c for c in snap["commands"] if c["run_id"] == run_id] == []


def test_a_secret_installed_in_node_modules_or_venv_or_in_git_is_not_counted(tmp_path):
    for kept in ("node_modules/pkg/.env", ".venv/lib/x.pem", ".git/config", "src/.env.example"):
        (tmp_path / kept).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / kept).write_text("x", encoding="utf-8")
    assert commands.secret_held(tmp_path.resolve()) is None
    assert commands.search_reason("rg KEY", tmp_path.resolve()) == ""
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / ".env").write_text("x", encoding="utf-8")
    commands._held.clear()  # (the answer is kept a few seconds)
    assert ".env" in commands.search_reason("rg KEY", tmp_path.resolve())
