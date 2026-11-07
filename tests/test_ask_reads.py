"""Below Full auto a command that only reads or lists what it names in the project runs
unasked (K-ask-okuma, the user's decision of 25 October): native Codex read each file by a
command, and a one-line patch at Ask opened some five cards (B-49). One that names a secret
file, searches the whole folder, reaches outside the project or may write is still asked.
Written before the code."""

import pytest

from app import commands
from tests.fakes import Script, ScriptedExecutor
from tests.test_agent_commands import cmd
from tests.test_agent_writes import wait_status
from tests.test_chat_flow import start, text
from tests.test_codex_app_server_scenarios import ACCEPT, DECLINE, DOUBLE, RUN, answers
from tests.test_command_safety_scenarios import waiting
from tests.test_native_agent import native_app  # noqa: F401  (a fixture)
from tests.test_native_agent import start as start_native

READS = [
    "Get-Content notes.md",
    "Get-Content -LiteralPath 'notes.md' -Raw",
    "gc src/app.py",
    "cat README.md",
    "type README.md",
    "head -n 20 app.py",
    "tail app.py",
    "grep KEY app.py",
    "Select-String -Path README.md -Pattern KEY",
    "ls",
    "ls -la src",
    "dir",
    "Get-ChildItem src",
    "git status",
    "git diff",
    "git log --oneline -5",
    "pwd",
]

ASKED = [
    "Get-Content .env",
    "cat config/.env.local",
    "rg foo",
    "grep -r KEY .",
    "Get-ChildItem -Recurse",
    "ls -R",
    "Get-Content C:\\Users\\x\\notes.md",
    "cat /etc/hosts",
    "cat ~/notes.md",
    "Get-Content ..\\other\\notes.md",
    "cat a.txt > b.txt",
    "Get-Content a.txt | Set-Content b.txt",
    "Set-Content a.txt x",
    "git -C .. status",
    "git diff --output=x.patch",
    "git diff --ext-diff",
    "git diff --no-index C:\\Windows\\win.ini a.txt",
    "git commit -m x",
    "git checkout -- a.py",
    "powershell -Command 'Get-Content a.txt'",
    "more README.md",
    "tail -f app.log",
    "Get-Content app.log -Wait",
    "python x.py",
    "npm test",
    # (found in review, 25 Oct) a program of the folder's own, by its path
    ".\\cat notes.txt",
    "./ls",
    "tools\\git status",
    # ...a PowerShell list past the checks
    "gc a,..\\..\\x",
    "gc a,.git/config",
    "gc a,\\\\host\\share\\x",
    # ...another drive's folder, a provider
    "type D:notes.txt",
    "gc env:PATH",
    "ls env:",
    "dir HKCU:Software",
    "gci -Depth 9",
    "cat x -Wait",
]


@pytest.mark.parametrize("command", READS)
def test_a_harmless_read_only_reads(command):
    assert commands.only_reads(command)


@pytest.mark.parametrize("command", ASKED)
def test_what_names_a_secret_searches_reaches_out_or_writes_does_not(command):
    assert not commands.only_reads(command)


def test_a_secret_in_a_powershell_list_is_named():
    # (Full auto too: it predates K-ask-okuma)
    assert commands.names_secret("gc a,.git/config")
    assert commands.names_secret("Get-Content README.md,config/.env.local")


def test_at_ask_a_harmless_read_runs_unasked_and_a_secret_read_is_asked(
        make_client, wait_run, project_dir):
    executor = ScriptedExecutor([Script(["hi\n"])])
    client, _ = make_client([cmd("Get-Content README.md", "k1"), cmd("Get-Content .env", "k2"),
                             text("done")], executor=executor)
    cid, run_id = start(client, project_dir)
    first, second = waiting(client, cid, 2)
    assert first["status"] == "exited" and second["command"] == "Get-Content .env"
    client.post(f"/api/commands/{second['id']}/reject")
    wait_run(client, cid, run_id)
    assert [c for c, _ in executor.started] == ["Get-Content README.md"]


@pytest.mark.parametrize("command", ["rg foo", "Set-Content a.txt x"])
def test_at_ask_a_search_where_a_secret_is_and_a_write_are_asked(
        make_client, wait_run, project_dir, command):
    (project_dir / ".env").write_text("KEY=FAKE\n", encoding="utf-8")
    executor = ScriptedExecutor([])
    client, _ = make_client([cmd(command), text("done")], executor=executor)
    cid, run_id = start(client, project_dir)
    (asked,) = waiting(client, cid, 1)
    assert asked["command"] == command
    client.post(f"/api/commands/{asked['id']}/reject")
    wait_run(client, cid, run_id)
    assert executor.started == []


def test_at_ask_git_reads_unasked_only_at_the_root_of_a_folder_with_no_secret(
        make_client, wait_run, project_dir):
    # (found in review: `git show`, `git log -p` print a committed secret's lines; and a
    # repository shaped in a subfolder could set what git runs)
    (project_dir / "sub").mkdir()
    executor = ScriptedExecutor([Script(["clean\n"])])
    client, _ = make_client([cmd("git status", "k1"), cmd("git status", "k2", cwd="sub"),
                             text("done")], executor=executor)
    cid, run_id = start(client, project_dir)
    first, second = waiting(client, cid, 2)
    assert first["status"] == "exited" and second["cwd"] == "sub"
    client.post(f"/api/commands/{second['id']}/reject")
    wait_run(client, cid, run_id)


def test_at_ask_git_is_asked_where_the_folder_holds_a_secret(make_client, wait_run, project_dir):
    (project_dir / ".env").write_text("KEY=FAKE\n", encoding="utf-8")
    executor = ScriptedExecutor([])
    client, _ = make_client([cmd("git show abc123"), text("done")], executor=executor)
    cid, run_id = start(client, project_dir)
    (asked,) = waiting(client, cid, 1)
    client.post(f"/api/commands/{asked['id']}/reject")
    wait_run(client, cid, run_id)
    assert executor.started == []


def test_at_ask_a_clis_git_is_asked_where_the_folder_holds_a_secret(
        native_app, wait_run, project_dir):  # noqa: F811
    (project_dir / ".env").write_text("KEY=FAKE\n", encoding="utf-8")
    client, provider, _ = native_app([{"run": DOUBLE.format("git log -p")}, {"say": "ok"}])
    cid, run_id = start_native(client, project_dir, provider, "ask")
    (asked,) = wait_status(client, cid, "waiting_approval")["commands"]
    assert asked["command"] == "git log -p"
    client.post(f"/api/commands/{asked['id']}/reject")
    wait_run(client, cid, run_id)
    assert answers(native_app) == [(RUN, DECLINE)]


def test_at_ask_native_codexs_read_in_its_powershell_line_runs_unasked(
        native_app, wait_run, project_dir):  # noqa: F811
    client, provider, _ = native_app([
        {"run": DOUBLE.format("Get-Content -LiteralPath 'notes.md' -Raw")},
        {"run": DOUBLE.format("Get-Content -LiteralPath '.env' -Raw")}, {"say": "ok"}])
    cid, run_id = start_native(client, project_dir, provider, "ask")
    snap = wait_status(client, cid, "waiting_approval")
    (asked,) = [c for c in snap["commands"] if c["status"] == "proposed"]
    assert asked["command"] == "Get-Content -LiteralPath '.env' -Raw"
    client.post(f"/api/commands/{asked['id']}/reject")
    wait_run(client, cid, run_id)
    assert answers(native_app) == [(RUN, ACCEPT), (RUN, DECLINE)]
