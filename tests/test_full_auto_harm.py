"""K-fullauto-sorma, slice 1: at Full auto nothing asks but harm - and harm asks. A command that
deletes or overwrites (`danger`) or sends something off this machine (`sends_off`) is a card at a
watched Full auto turn as it is in a job while the user is away (`harms`), KOLONİ's own and a
native CLI's alike, and its card offers no rule; an http_request that is not a bare GET or HEAD
is asked too. What does neither runs as before."""

import os
import time

import pytest

from app.commands import danger, harms, runs_another, sends_off, suggest_prefix
from tests.fakes import Script, ScriptedExecutor
from tests.test_agent_commands import approve, cmd
from tests.test_agent_writes import wait_status
from tests.test_chat_flow import start_in_mode, text
from tests.test_codex_app_server_scenarios import ACCEPT, RUN, answers
from tests.test_native_agent import native_app  # noqa: F401  (a fixture)
from tests.test_native_agent import start as start_native
from tests.test_spawn import call, step
from tests.test_web_tool_scenarios import Net, get, go, results, setup
from tests.test_web_tools import asked_of, decide

ASKED = ["rm -rf build", "git push origin main", "curl -X POST https://x -d @f", "rm build/x.txt",
         "curl -d @f https://x", "curl -X PUT https://x",
         "Invoke-WebRequest -Method Post -Body x https://x", "gh pr create", "scp a.txt host:"]
# A line that only fetches sends nothing off the machine: no card at Full auto (a night job
# asks about any network program, `sends_off`).
FETCHES = ["curl https://x.test/a.json", "gh pr list"]
# (the shapes `_only_fetches` reads: curl's clustered short options, wget's and PowerShell's
# switches, gh's read subcommands and `gh api` with nothing to send)
ONLY_FETCH = ["curl -sSfL -o x https://x", "curl -X GET https://x", "curl -D h https://x",
              "wget -q -T 3 -O /dev/null http://e", "wget --method=GET http://e",
              "Invoke-WebRequest https://x -Method Get", "iwr https://x -OutFile a",
              "gh pr view 1", "gh status", "gh auth status", "gh api repos/x",
              "gh run list --limit 5", "gh", "gh --version", "gh -h", "gh pr checkout 1",
              "gh pr diff 1", "gh repo clone x", "gh run download 1", "gh search repos x",
              "curl -G -d a=b https://x", "curl -sG --data-urlencode q=1 https://x"]
SENDS = ["curl -XPOST https://h", "curl -sd x https://h", "curl -dfoo https://h",
         "curl -Ff=@a https://h", "curl -sSfT a https://h", "curl --request=DELETE https://x",
         "curl --json {} https://x", "curl.exe -d x https://h", "wget --post-data a=1 http://e",
         "wget --method=PUT http://e", "Invoke-WebRequest https://x -Method:Post",
         "irm https://x -Body a", "gh api repos/x -X POST", "gh api repos/x -f a=b",
         "gh api --method POST x", "gh release upload v1 a.zip", "pytest -q && curl -d x https://h",
         "gh api -XPOST repos/x/issues", "gh api repos/x -XDELETE", "gh api repos/x -fa=b",
         "curl -G -T a https://x"]
# What a shell or a wrapper is handed: a night job asks for the shell (`runs_another`), Full
# auto for what is inside.
IN_A_SHELL = ['cmd /c "git push"', 'powershell -c "git push"',
              'powershell -Command "curl -d x https://h"', "sh -c 'rm -rf x'", "cmd /c del x"]


def why_asked(snap, asked):
    return next(t for t in snap["tool_calls"] if t["id"] == asked["tool_call_id"])["why_asked"]


@pytest.mark.parametrize("command", FETCHES + ONLY_FETCH)
def test_a_line_that_only_fetches_is_no_harm_but_a_night_job_still_asks(command):
    assert harms(command) == "" and sends_off(command) != ""


@pytest.mark.parametrize("command", IN_A_SHELL)
def test_a_send_or_a_delete_inside_a_shell_is_harm(command):
    assert harms(command) != "" and harms('python -c "print(1)"') == ""


# K-r132: a wrapper's option that takes a value - its value is no program - and one not known
# here (`-exec`, PowerShell's prefix of -ExecutionPolicy; `-euo pipefail`): judged both ways.
BEHIND_A_WRAPPER = [
    "timeout 5 rm -rf C:/x", "nice -n 5 rm -rf C:/x", "env A=1 rm -rf C:/x",
    "xargs -a f rm -rf C:/x", "cmd /v:on /c del /q C:\\x",
    "powershell -ExecutionPolicy Bypass -Command Remove-Item C:\\x",
    "A=1 rm -rf C:/x", "sudo -u bob rm -rf x", "ionice -c 3 rm -rf x", "stdbuf -o L rm -rf x",
    "exec -a n rm -rf x", "bash -euo pipefail -c 'rm -rf x'", "env -S 'rm -rf x'",
    "powershell -exec Bypass -Command Remove-Item C:\\x", "timeout 5 git push --force",
    # (review of K-r132) a quoted line that starts with a variable; `start`'s long switches;
    # a command line in an option's value
    "sh -c 'A=1 git push --force'", 'bash -lc "A=1 git push --force"',
    'cmd /c "A=1 git push --force"', "sudo 'A=1 git push --force'",
    "env -i 'A=1 git push --force'", "sh -c 'A=1 rm -rf x'", 'bash -c "FOO=bar rm -rf /"',
    "env -S 'A=1 rm -rf x'", "timeout 5 sh -c 'A=1 rm -rf x'", "env 'A=1 2' rm -rf x",
    "start /wait /b del x", "start /min del x", "cmd /c start /wait del x", "cmd /k del x",
    "cmd /s /c del x", "env --split-string='rm -rf x'", "env -S'rm -rf x'",
    "flock lock -c 'rm -rf x'", "su root -c 'rm -rf x'", "su -c 'rm -rf x'",
    "bash +o posix -c 'rm -rf x'",
]


@pytest.mark.parametrize("command", BEHIND_A_WRAPPER)
def test_a_delete_behind_a_wrappers_option_is_harm(command):
    assert harms(command) != "" and suggest_prefix(command) == ""


@pytest.mark.parametrize("command", ["timeout 5 pytest", "env A=1 pytest", "nice -n 5 pytest",
                                     "xargs -0 grep foo", "cmd /v:on /c echo hi",
                                     "sh -c 'echo hi'", "bash -c 'pytest -q'"])
def test_what_a_wrapper_runs_that_harms_nothing_is_no_harm(command):
    assert harms(command) == "" and danger(command) == ""


# Security review 0.1.0, finding 4: what a PowerShell line runs in a block is looked into.
@pytest.mark.parametrize("command", [
    "(rm x)", "echo $(rm x)", "if(1){rm x}", "gci | % { ri $_ }", "& { rm -r src }",
    "[IO.Directory]::Delete('src', $true)", "[System.IO.File]::Delete('a.py')",
    "$p='a'; [ io.file ]::delete($p)", "Clear-Content app.py", "clc app.py",
    "Get-ChildItem | ForEach-Object { Remove-Item $_ }", "if ($x) { git push --force }",
])
def test_a_delete_inside_a_powershell_block_is_harm(command):
    assert harms(command) != ""


@pytest.mark.parametrize("command", [
    "if(1){cmd /c x.bat}", "$(env)", "Write-Output (bash -c x)", "& (gcm cmd) /c x.bat",
    "$c='ri'; & $c x", "&('r'+'i') x", "Start-Process cmd -ArgumentList '/c','x.bat'",
    "gci; Start-Process cmd",
])
def test_a_shell_inside_a_powershell_block_runs_another(command):
    assert runs_another(command) != ""


@pytest.mark.parametrize("command", [
    "Get-ChildItem | Select-Object Name", "Get-ChildItem | Where-Object { $_.Length -gt 0 }",
    "(Get-Date).AddDays(-1)", "Get-Content (Join-Path src a.py)", "[IO.File]::ReadAllText('a')",
    "Get-ChildItem | ForEach-Object { $_.FullName }", "Measure-Command { pytest -q }",
    "[IO.File]::WriteAllText('a.py', $t.Replace('a', 'b'))",  # (an edit, as Set-Content is)
])
def test_an_ordinary_powershell_block_is_no_harm(command):
    assert harms(command) == ""


@pytest.mark.parametrize("line", [("nice -x " * 1300)[:10_240], "nice " + "-x " * 3400,
                                  "start /b " * 1200, "env --split-string='env " * 400])
def test_a_line_padded_with_options_is_judged_at_once_and_asked(line):
    # (review of K-r132: every reading of each unknown option took 24 s for 6 KB, in the
    # server's thread - each list of commands shown judges it again; and a line in an option's
    # value, looked into, doubled them at each)
    began = time.perf_counter()
    said = harms(line)
    limit = 3.0 if os.environ.get("CI") else 1.0  # (a shared CI runner took 1.0006 s; the bug was 24 s)
    assert time.perf_counter() - began < limit and "what runs is not seen" in said


@pytest.mark.parametrize("command", ASKED[1:3] + ASKED[4:] + SENDS)
def test_a_line_that_sends_is_harm(command):
    assert harms(command) == sends_off(command) != ""


@pytest.mark.parametrize("command", ASKED)
def test_at_full_auto_what_deletes_or_sends_off_is_a_card_with_no_rule(
        make_client, wait_run, project_dir, command):
    executor = ScriptedExecutor([])
    client, _ = make_client([cmd(command), text("left it")], executor=executor)
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    snap = wait_status(client, cid, "waiting_approval")
    (asked,) = snap["commands"]
    assert asked["status"] == "proposed" and why_asked(snap, asked) == harms(command) != ""
    # (R118: the record carries the card's reason, a push's too - not `danger`'s alone, which is none)
    assert (asked["danger"], asked["suggested_prefix"]) == (harms(command), "")
    client.post(f"/api/commands/{asked['id']}/reject")
    wait_run(client, cid, run_id)
    assert executor.started == []


@pytest.mark.parametrize("command", ["git stash push", 'python -c "print(1)"', *FETCHES])
def test_at_full_auto_what_does_neither_runs_unasked(make_client, wait_run, project_dir, command):
    executor = ScriptedExecutor([Script(["1\n"])])
    client, _ = make_client([cmd(command), text("done")], executor=executor)
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    snap = wait_run(client, cid, run_id)
    assert snap["commands"][0]["status"] == "exited" and len(executor.started) == 1
    assert snap["tool_calls"][0]["why_asked"] is None


def test_at_full_auto_a_native_clis_push_is_a_card_too(
        native_app, wait_run, project_dir):  # noqa: F811
    client, provider, _ = native_app([
        {"run": "git push origin main", "output": "ok\n"}, {"say": "pushed"}])
    cid, run_id = start_native(client, project_dir, provider, "full_auto")
    snap = wait_status(client, cid, "waiting_approval")
    (asked,) = snap["commands"]
    assert (asked["status"], asked["origin"], asked["suggested_prefix"]) == ("proposed", "cli", "")
    assert why_asked(snap, asked) == harms("git push origin main")
    assert approve(client, asked["id"]).status_code == 200
    wait_run(client, cid, run_id)
    assert answers(native_app) == [(RUN, ACCEPT)]


def test_at_full_auto_a_request_that_is_not_a_bare_get_is_asked(
        make_client, wait_run, project_dir, monkeypatch):
    net = Net(monkeypatch, {"example.com": (200, "text/plain", "ok")})
    client, _model, _pid, cid = setup(make_client, project_dir, [
        step(get("https://example.com/a", "g")),
        step(call("http_request", {"method": "POST", "url": "https://example.com/b", "body": "x"},
                  "p")),
        text("done")])
    run_id = go(client, cid)["id"]
    _snap, asked = asked_of(client, cid)  # the bare GET went unasked; the POST waits
    assert (asked["method"], asked["target"]) == ("POST", "https://example.com/b")
    assert [method for method, _url, _ip in net.asked] == ["GET"]
    assert decide(client, asked).status_code == 200
    snap = wait_run(client, cid, run_id)
    assert [status for status, _ in results(snap, "http_request")] == ["succeeded"] * 2
    assert [method for method, _url, _ip in net.asked] == ["GET", "POST"]
