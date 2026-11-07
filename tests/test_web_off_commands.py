"""K-web-komut: while a web tool is off on the Tools page, a command that reaches the internet
is asked on a card at every level, Full auto too, and says why (the user's decision, 28 Oct).

Found live (28 Oct): web_search and http_request off, a Codex Lead at Full auto still reached
GitHub with PowerShell's `Invoke-RestMethod`. With web on, nothing changes."""

import sqlite3

import pytest
from alembic import command as alembic

from app import skills
from app.commands import reaches_network, web_off_reason
from tests.fakes import Script, ScriptedExecutor
from tests.test_agent_commands import approve, cmd
from tests.test_agent_writes import wait_status
from tests.test_builtin_tools import switch
from tests.test_chat_flow import start_in_mode, text
from tests.test_chat_teams_scenarios import OWN
from tests.test_codex_app_server_scenarios import DECLINE, RUN, answers
from tests.test_command_safety_scenarios import waiting
from tests.test_copilot_agent import copilot_native  # noqa: F401  (a fixture)
from tests.test_copilot_agent import start as copilot_start
from tests.test_migration_0002 import _config
from tests.test_native_agent import native_app  # noqa: F401  (a fixture)
from tests.test_native_agent import start as codex_start
from tests.test_skill_scenarios import add, give, skill_dir  # noqa: F401  (a fixture)
from tests.test_spawn import begin, call, step
from tests.test_trigger_scenarios import allow

LIVE = "Invoke-RestMethod https://api.github.com/repos/koloni/koloni"
REACHES = [
    LIVE,
    "curl https://x.test",
    "curl.exe -s x.test",
    "C:\\tools\\wget.exe x.test",
    "iwr x.test -OutFile a.html",
    '"C:\\WINDOWS\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" -Command "irm x.test"',
    "(New-Object Net.WebClient).DownloadString('x')",
    "Start-BitsTransfer -Source x -Destination y",
    "Test-NetConnection github.com -Port 443",
    "git clone git@github.com:a/b.git",
    "git -C sub fetch origin",
    "npm test && git pull",
    "pip install requests",
    "python -m pip install requests",
    "uv pip install x",
    "npm ci",
    "ssh host ls",
    "python fetch.py https://x.test",
    # (review, 28 Oct) by its path, a word that publishes, inside a shell, more of the list
    "C:\\Windows\\System32\\curl.exe x", "/usr/bin/curl x",
    "npm publish", "docker push x", "twine upload dist/*", "cargo publish",
    'cmd /c "pip install x"', "powershell -Command \"git clone x\"", "bash -c 'npm publish'",
    "[System.Net.Http.HttpClient]::new()", "[Net.WebRequest]::Create('x')",
    "[System.Net.Sockets.TcpClient]::new('x', 80)", "winget install x", "choco install x",
    "scoop install x", "Install-Module PSReadLine", "git submodule update --init",
    "git lfs pull", "pip download x", "$u = 'https://' + $h",
    "certutil -urlcache -split -f x.test/a a.exe", "bitsadmin /transfer job x.test/a C:\\a.exe",
]
STAYS = ['python -c "print(1)"', "pytest -q", "git status", "git commit -m 'fix'",
         "python curl_test.py", "Get-Content README.md", "npm test", "npx tsc --noEmit",
         # (review, 28 Oct) a path's part or a file's name is no program; a stash is no push
         "pytest tests/aws/test_s3.py", "ls helm/charts", "Get-Content terraform/main.tf",
         "cat docs/curl.md", "python scripts/gh.py", "cat ~/.ssh/config", "git stash push",
         "python -m pytest tests/test_ssh.py", "git checkout -b fix-curl",
         "certutil -hashfile dist/app.zip SHA256"]


@pytest.mark.parametrize("command", REACHES)
def test_a_command_that_reaches_the_internet_is_seen(command):
    assert reaches_network(command)


@pytest.mark.parametrize("command", STAYS)
def test_an_ordinary_command_does_not(command):
    assert reaches_network(command) == ""


def test_the_reason_only_while_a_web_tool_is_off():
    assert web_off_reason("curl https://x.test", frozenset()) == ""
    assert web_off_reason("curl https://x.test", {"read_attachment"}) == ""
    assert web_off_reason("pytest -q", {"http_request"}) == ""
    said = web_off_reason("curl https://x.test", {"web_search"})
    assert said.startswith("web is off on the Tools page (web_search is off); this command "
                           "reaches the internet: curl")


def began_off(make_client, project_dir, steps, executor, off=("web_search", "http_request")):
    client, _ = make_client(steps, executor=executor)
    client.headers.update(OWN)
    for name in off:
        switch(client, name, False).raise_for_status()
    return client, *start_in_mode(client, project_dir, "full_auto")


def test_web_off_at_full_auto_curl_is_a_card_that_says_why(make_client, wait_run, project_dir):
    executor = ScriptedExecutor([])
    client, cid, run_id = began_off(make_client, project_dir,
                                    [cmd("curl https://x.test"), text("left it")], executor)
    snap = wait_status(client, cid, "waiting_approval")
    (asked,) = snap["commands"]
    assert asked["status"] == "proposed"
    why = next(t for t in snap["tool_calls"] if t["id"] == asked["tool_call_id"])["why_asked"]
    assert why.startswith("web is off on the Tools page") and "reaches the internet: curl" in why
    assert (asked["web_off"], asked["suggested_prefix"]) == (True, "")  # (no rule on its card)
    client.post(f"/api/commands/{asked['id']}/reject")
    wait_run(client, cid, run_id)
    assert executor.started == []


def test_an_always_run_rule_does_not_cover_it_while_web_is_off_nor_is_one_offered(
        make_client, wait_run, project_dir):
    executor = ScriptedExecutor([Script(["a\n"])])
    client, _ = make_client([cmd("curl https://x.test"), text("done")], executor=executor)
    client.headers.update(OWN)
    switch(client, "http_request", False).raise_for_status()
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    allow(client, cid, "curl")  # (ticked before: "Always run curl")
    run_id = client.post(f"/api/conversations/{cid}/messages",
                         json={"content": "fetch it"}).json()["run"]["id"]
    asked = waiting(client, cid, 1)[0]  # the rule is there, and it still asks
    assert (asked["web_off"], asked["suggested_prefix"]) == (True, "")
    approve(client, asked["id"])
    wait_run(client, cid, run_id)


@pytest.mark.parametrize("off", [("web_search", "http_request"), ()])
def test_what_does_not_reach_it_or_web_on_runs_as_before(make_client, wait_run, project_dir, off):
    command = "curl https://x.test" if not off else 'python -c "print(1)"'
    executor = ScriptedExecutor([Script(["1\n"])])
    client, cid, run_id = began_off(make_client, project_dir, [cmd(command), text("done")],
                                    executor, off)
    snap = wait_run(client, cid, run_id)
    assert snap["commands"][0]["status"] == "exited" and len(executor.started) == 1
    assert snap["tool_calls"][0]["why_asked"] is None


def test_codex_at_full_auto_asks_for_the_live_command_while_web_is_off(
        native_app, wait_run, project_dir):  # noqa: F811
    client, provider, _ = native_app([{"run": LIVE, "output": "{}\n"}, {"say": "ok"}])
    client.headers.update(OWN)
    switch(client, "http_request", False).raise_for_status()
    cid, run_id = codex_start(client, project_dir, provider)
    snap = wait_status(client, cid, "waiting_approval")
    (asked,) = snap["commands"]
    assert (asked["command"], asked["status"], asked["origin"]) == (LIVE, "proposed", "cli")
    why = next(t for t in snap["tool_calls"] if t["id"] == asked["tool_call_id"])["why_asked"]
    assert why.startswith("web is off on the Tools page (http_request is off)")
    assert "reaches the internet: Invoke-RestMethod" in why
    assert (asked["web_off"], asked["suggested_prefix"]) == (True, "")
    client.post(f"/api/commands/{asked['id']}/reject")
    wait_run(client, cid, run_id)
    assert answers(native_app) == [(RUN, DECLINE)]


@pytest.mark.parametrize("web_on", [False, True])
def test_a_skills_script_on_its_own_leave_is_asked_while_web_is_off_if_its_line_reaches_it(
        make_client, wait_run, project_dir, skill_dir, web_on, monkeypatch):  # noqa: F811
    # shortcut: today a script's line is only its path, which reaches nothing (`docs/curl.md`
    # is no program): this holds the gate for a line that would - one with an address.
    monkeypatch.setattr(skills, "script_line",
                        lambda folder, script: f'python -B "{folder}/{script}" https://x.test')
    executor = ScriptedExecutor([Script(["ok\n"])])
    client, _ = make_client([step(call("run_skill_script", {"skill": "tidy",
                                                            "script": "scripts/check.py"})),
                             text("done")], executor=executor)
    client.headers.update(OWN)
    add(client, skill_dir)
    give(client, "Lead", "tidy")
    if not web_on:
        switch(client, "web_search", False).raise_for_status()
    cid, run_id = begin(client, project_dir, mode="full_auto")
    if web_on:  # the skill's leave, as before
        assert wait_run(client, cid, run_id)["commands"][0]["status"] == "exited"
        return
    snap = wait_status(client, cid, "waiting_approval")
    (asked,) = snap["commands"]
    why = next(t for t in snap["tool_calls"] if t["id"] == asked["tool_call_id"])["why_asked"]
    assert "reaches the internet: https://x.test" in why
    client.post(f"/api/commands/{asked['id']}/reject")
    wait_run(client, cid, run_id)
    assert executor.started == []


def test_in_a_working_copy_web_off_is_the_reason_its_card_gives(
        make_client, wait_run, project_dir):
    # It names the project folder too (`copy_reason`): the card says web is off, and offers no
    # rule.
    named = f"curl https://x.test -o {project_dir / 'page.html'}"
    client, _ = make_client({
        "Lead": [step(call("spawn_agent", {"role": "Coder", "task": "fetch it"}, "s")),
                 text("done")],
        "Coder": [step(call("run_command", {"command": named}, "c")), text("left it")]},
        executor=ScriptedExecutor([]))
    client.headers.update(OWN)
    switch(client, "http_request", False).raise_for_status()
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never",
                        content="have the Coder fetch it")
    snap = wait_status(client, cid, "waiting_approval")
    (asked,) = [c for c in snap["commands"] if c["status"] == "proposed"]
    why = next(t for t in snap["tool_calls"] if t["id"] == asked["tool_call_id"])["why_asked"]
    assert why.startswith("web is off on the Tools page")
    assert (asked["web_off"], asked["suggested_prefix"]) == (True, "")
    client.post(f"/api/commands/{asked['id']}/reject")
    wait_run(client, cid, run_id)


def test_copilots_own_possible_url_while_web_is_off_is_the_reason(
        copilot_native, wait_run, project_dir):  # noqa: F811
    client, provider = copilot_native([
        {"shell": "python fetch.py", "urls": ["https://x.test/data"]}, {"say": "ok"}])
    client.headers.update(OWN)
    switch(client, "web_search", False).raise_for_status()
    cid, run_id = copilot_start(client, project_dir, provider)
    snap = wait_status(client, cid, "waiting_approval")
    (asked,) = snap["commands"]
    why = next(t for t in snap["tool_calls"] if t["id"] == asked["tool_call_id"])["why_asked"]
    assert "reaches the internet: https://x.test/data" in why and asked["web_off"]
    client.post(f"/api/commands/{asked['id']}/reject")
    wait_run(client, cid, run_id)


def test_migration_0105_and_back(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    alembic.upgrade(cfg, "0106")
    alembic.upgrade(cfg, "0107")
    with sqlite3.connect(db) as conn:
        assert "web_off" in {row[1] for row in conn.execute("PRAGMA table_info(commands)")}
    alembic.downgrade(cfg, "0106")
    with sqlite3.connect(db) as conn:
        assert "web_off" not in {row[1] for row in conn.execute("PRAGMA table_info(commands)")}
