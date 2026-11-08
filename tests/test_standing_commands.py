"""A command that names a file which steers later turns (`NOT_WRITTEN_UNATTENDED`) is asked at
every level, Full auto too, and refused in a turn nobody watches (B-79).

Found live (25 Oct): a native Claude Code Lead at Full auto was refused `write_file` on
`.claude/settings.json`, then wrote it with `Set-Content` - no card. KOLONİ's own
`run_command` wrote `.github\\canli.yml` the same way.
"""

import os
import sys
from pathlib import Path

import pytest

from app import commands
from app.model_native import _unwrapped
from tests.fakes import Script, ScriptedExecutor
from tests.test_agent_commands import cmd
from tests.test_agent_writes import wait_status
from tests.test_chat_flow import start_in_mode, text
from tests.test_claude_native import (
    claude_app,  # noqa: F401  (a fixture)
    unattended,
)
from tests.test_claude_native import start as start_claude
from tests.test_codex_app_server_scenarios import ACCEPT, RUN, answers
from tests.test_command_safety_scenarios import waiting
from tests.test_native_agent import native_app  # noqa: F401  (a fixture)
from tests.test_native_agent import start as start_native
from tests.test_spawn import call, step
from tests.test_trigger_scenarios import NOBODY, allow, finished, results, run_now, setup, trigger

LIVE = ("New-Item -ItemType Directory -Force C:\\p\\.claude; Set-Content -Path "
        "'C:\\p\\.claude\\settings.json' -Value '{\"permissions\":{\"allow\":[\"Bash\"]}}'")

STANDING = [
    LIVE,
    "New-Item -ItemType Directory -Force .github | Out-Null; Set-Content .github\\canli.yml x",
    "New-Item .github\\x.yml",
    "echo x > AGENTS.md",
    "copy a .mcp.json",
    "Set-Content -Path:.claude\\x y",
    "echo x > .cl`aude\\settings.json",
    'echo x > ".cl""aude/settings.json"',
    "echo x > CLAUDE.md.",
    "cp hook .git/hooks/pre-commit",
    "Set-Content .VSCODE\\tasks.json x",
    # .git/config written unnamed: it runs at the next git command
    'git config core.fsmonitor "python evil.py"', "git -C . config alias.x '!rm -rf .'",
    "npm test && git config --unset core.hooksPath", "git config set core.pager x",
    # by a wildcard or a short name (review of batch-11)
    "Set-Content .cla?de\\settings.json x", "echo x > .claud[e]/settings.json",
    "Copy-Item x .claude*", "Set-Content CLAUDE~1\\settings.json x",
    "echo x > GITHUB~1\\WORKFL~1\\a.yml", "copy x MCP~1.JSO",
    # a patch writes what it names, unnamed here
    "git apply fix.patch", "git -C . am < mail.mbox", "patch -p1 < fix.diff",
    # B-188: a part of a chain that writes one; a name written in inline code
    "python x.py; echo x > .github/y", "cat .github/a | tee .github/b",
    "python -c \"open('.github/x', 'w').write('y')\"",
    "node -e \"require('fs').writeFileSync('AGENTS.md', 'x')\"", 'Remove-Item ".cla*"',
    # (a pipeline is judged whole: what is read is handed on to a writer)
    "ls .github/workflows | xargs -I{} cp evil.yml {}",
    "Get-ChildItem .claude | ForEach-Object { Set-Content $_.FullName x }",
    # (`deploy.py -c` is no interpreter's inline code: its wildcard still counts)
    'deploy.py -c ".cla*"',
    ".venv/Scripts/python.exe -c \"open('.claude/x', 'w')\"",
    # (a chain split inside a substitution or quotes is judged whole: the review's three)
    'cp evil.yml "$(:; ls -d .github; :)/workflows/ci.yml"',
    'cp evil.yml "$(ls -d .github && :)/workflows/ci.yml"',
    "Set-Content \"$(Get-ChildItem .claude; '')/settings.json\" x",
    "cat AGENTS.md; echo 'x; y' > AGENTS.md",
    # (a short name in inline code: no wildcard there, but a name all the same)
    "python -c \"open('CLAUDE~1/settings.json', 'w')\"",
]

# Reads, as any read runs (only_reads): naming such a file does not ask.
READS = ["cat AGENTS.md", "Get-Content CLAUDE.md", "ls .github", "git log -- .github",
         "git show HEAD:.github/x.yml"]

ORDINARY = ["Get-Content README.md", "git status", "cat .gitignore", "ls .claudes",
            "echo claude", "git clone https://example.com/x.git", "npm test",
            "git config --get user.name", "git config user.name", "git config --list",
            "git config -l", "git config get user.name", "git -c core.pager=cat log",
            "git apply --check fix.patch", "patch --dry-run -p1 < fix.diff", "ls *.json",
            "Copy-Item a build/*.o", "Copy-Item a PROGRA~1.TXT", *READS,
            # B-188 (live): asked at Full auto, "Names .github"; a read in a chain is a read,
            # and a `*` in inline code is code
            "python train.py; cat .github/workflows/ci.yml; python -c \"import sys; "
            "sys.path.insert(0, '.'); from model import *; print(rmse())\"",
            "python -c \"import glob; print(glob.glob('.gith*'))\""]


# B-198 (live): Codex's own search passed .koloni by, and waited as "Names .koloni"
PASSES_BY = ["rg --files --hidden -g '!**/.koloni/**' -g '!**/.codex/**'",
             "rg TODO --glob=!.koloni/** --iglob '!.github'", "grep -r --exclude-dir=.koloni x .",
             "grep -r --exclude .koloni/x y .", "find . -not -path './.koloni/*' -name '*.md'",
             "find . ! -path '*/.github/*'"]
# (what does open or write one still asks: told to pass one by, it names another)
STILL_NAMES = ["rg -g '!.koloni' x > .koloni/rules.md", "grep -r --exclude-from .koloni/x y .",
               "rg -g '.koloni/**' x", "rg -g '!x' x > .github/y",
               # (to any other program, or past `--`, such words are a file's names: the review's)
               "cp -- --exclude .koloni/rules.md", "Copy-Item --exclude .koloni\\rules.md",
               "Move-Item --exclude .github\\workflows\\ci.yml", "rg -g '!x' y | tee .github/x",
               "rg x -- --exclude .koloni/x"]


# B-198 (the coordinator's call): a lone search that only reads reads what it names, as `cat` does
CODEX_SEARCH = "rg --files --hidden -g AGENTS.md -g '!.koloni'"
SEARCH_READS = [CODEX_SEARCH, "rg foo .github/", "grep -rn TODO .github", "rg -i foo CLAUDE.md",
                "find .github -name '*.yml'", "ag foo .claude"]
# (what it pipes, redirects, runs or edits still asks)
SEARCH_DOES = ["rg foo .github/ > out.txt", "find .github -delete", "find .github -exec cp x {} +",
               "rg --pre ./x foo .github", "rg -g AGENTS.md x | tee AGENTS.md", "rg -r y x .github",
               ".\\rg x .github"]

# B-307 (live): Codex's Coders' search, in the PowerShell line it runs each command in - and the
# reads after it; a script handed to a shell reads what it names when every part of it reads.
POWERSHELL = '"C:\\WINDOWS\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" -Command "{}"'
REA_SEARCH = POWERSHELL.format("Get-Location; rg --files -g AGENTS.md -g etl.py -g '!node_modules'")
SCRIPT_READS = [REA_SEARCH, "Test-Path .\\AGENTS.md", POWERSHELL.format("Test-Path .\\AGENTS.md"),
                "rg --files --hidden -g AGENTS.md",
                POWERSHELL.format("rg --files --hidden -g AGENTS.md"),
                'powershell -Command "Get-Location; Get-Content AGENTS.md"',
                "pwsh -NoProfile -c 'Get-Content CLAUDE.md'", "cmd /c rg x .github",
                'cmd /d /c "type AGENTS.md"']
# (one with a part that writes, redirects, runs code or a script, or is handed no script, is
# judged whole - and .koloni and a secret still ask, as before)
SCRIPT_DOES = ['powershell -Command "Get-Location; Set-Content AGENTS.md x"',
               'powershell -Command "rg x > AGENTS.md"',
               "powershell -EncodedCommand UwBlAHQALQBDAG8AbgB0AGUAbgB0AA== AGENTS.md",
               'powershell -Command "Get-Content AGENTS.md | Set-Content x"',
               "powershell -Command \"iex 'x'; Get-Content AGENTS.md\"",
               'powershell -Command "& .\\x.ps1; Get-Content AGENTS.md"',
               'powershell -Command ".\\x.ps1 AGENTS.md"',
               'powershell -File x.ps1 AGENTS.md',
               'powershell -ExecutionPolicy Bypass -Command "Get-Content AGENTS.md"',
               'cmd /c "type AGENTS.md & echo x > AGENTS.md"',
               'powershell -Command "Get-Location; rg x .koloni"',
               'powershell -Command "Get-Content .env; Get-Content AGENTS.md"',
               # (a shell of the folder's own, which an agent can write)
               '.\\powershell.exe -Command "Get-Content AGENTS.md"', "./pwsh -c 'cat AGENTS.md'"]


@pytest.mark.parametrize("line", SCRIPT_READS)
def test_b307_a_shells_script_of_reads_reads_the_files_that_steer_later_turns(line):
    assert commands.names_standing(line) == ""


@pytest.mark.parametrize("line", SCRIPT_DOES)
def test_b307_a_shells_script_that_does_more_than_read_still_asks(line):
    assert commands.danger(line)


@pytest.mark.parametrize("line", [REA_SEARCH, "Test-Path .\\AGENTS.md",
                                  'powershell -Command "Get-Location; Get-Content AGENTS.md"'])
def test_b307_at_full_auto_a_shells_script_of_reads_runs_unasked(
        make_client, wait_run, project_dir, line):
    executor = ScriptedExecutor([Script(["AGENTS.md\n"])])
    client, _ = make_client([cmd(line), text("done")], executor=executor)
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    snap = wait_run(client, cid, run_id)
    assert snap["commands"][0]["status"] == "exited" and len(executor.started) == 1


def test_b307_at_full_auto_native_codexs_search_in_a_line_it_does_not_unwrap_runs_unasked(
        native_app, wait_run, project_dir):  # noqa: F811
    # (`_unwrapped` takes only `-Command` right after the program: the CLI's path, command_runner)
    line = REA_SEARCH.replace(" -Command ", " -NoProfile -Command ")
    client, provider, _ = native_app([{"run": line}, {"say": "ok"}])
    cid, run_id = start_native(client, project_dir, provider, "full_auto")
    snap = wait_run(client, cid, run_id)
    assert [c["status"] for c in snap["commands"]] != ["proposed"]
    assert answers(native_app) == [(RUN, ACCEPT)]


LIVE_LINES = [(said.startswith("reads"), line) for said, line in (
    block.split("\n", 1) for block in (Path(__file__).parent / "codex_powershell_lines.txt")
    .read_text(encoding="utf-8").split("\n=== ")[1:])]


def test_b307_codexs_line_joined_as_a_posix_shells_words_is_unwrapped():
    assert _unwrapped(LIVE_LINES[0][1].strip()) == (
        "Get-Location; rg --files -g AGENTS.md -g etl.py -g '*snapshot*' -g '!node_modules' "
        "-g '!.venv' -g '!venv' -g '!.git'; Get-ChildItem -Force -Name")


@pytest.mark.parametrize(("reads", "line"), LIVE_LINES)
def test_b307_at_full_auto_native_codexs_live_lines(native_app, wait_run, project_dir, reads, line):  # noqa: F811
    client, provider, _ = native_app([{"run": line.strip()}, {"say": "ok"}])
    cid, run_id = start_native(client, project_dir, provider, "full_auto")
    if reads:
        wait_run(client, cid, run_id)
        assert answers(native_app) == [(RUN, ACCEPT)]
        return
    (asked,) = wait_status(client, cid, "waiting_approval")["commands"]
    assert asked["command"].startswith("$trainBytes") and "agents.md" in asked["danger"].lower()
    client.post(f"/api/commands/{asked['id']}/reject")
    wait_run(client, cid, run_id)


@pytest.mark.parametrize("mode, name", [("full_auto", ".github\\x.yml"), ("auto_edit", "AGENTS.md")])
def test_b307_one_that_writes_one_still_waits(make_client, wait_run, project_dir, mode, name):
    executor = ScriptedExecutor([])
    line = f'powershell -Command "Get-Location; Set-Content {name} x"'
    client, _ = make_client([cmd(line), text("Understood.")], executor=executor)
    cid, run_id = start_in_mode(client, project_dir, mode)
    asked = waiting(client, cid, 1)[0]
    assert name.split("\\")[0].lower() in asked["danger"].lower()
    client.post(f"/api/commands/{asked['id']}/reject")
    wait_run(client, cid, run_id)
    assert executor.started == []


# K-fullauto-sorma 2: at Full auto a command that only names an instruction file (AGENTS.md,
# CLAUDE.md, GEMINI.md) runs unasked - in a shell's script too; every other standing name asks.
@pytest.mark.parametrize("line", ["echo x > AGENTS.md", 'cmd /c "echo x > CLAUDE.md"',
                                  'powershell -Command "Get-Location; Set-Content AGENTS.md x"'])
def test_at_full_auto_a_command_naming_an_instruction_file_alone_runs_unasked(
        make_client, wait_run, project_dir, line):
    executor = ScriptedExecutor([Script(["ok\n"])])
    client, _ = make_client([cmd(line), text("done")], executor=executor)
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    snap = wait_run(client, cid, run_id)
    assert snap["commands"][0]["status"] == "exited" and len(executor.started) == 1


def test_an_instruction_file_is_left_out_only_where_asked_and_only_it():
    assert commands.standing_asked("echo x > AGENTS.md") == "agents.md"
    assert commands.standing_asked("echo x > AGENTS.md", False) == ""
    assert commands.standing_asked("echo x > .claude/x", False) == ".claude"
    assert commands.standing_asked("git apply fix.patch", False) == commands.PATCH
    assert commands.harms('cmd /c "echo x > GEMINI.md"', False) == ""
    assert "agents.md" in commands.harms('cmd /c "echo x > AGENTS.md"')
    assert commands.harms('cmd /c "rm -rf build"', False)  # (harm stays harm)


@pytest.mark.parametrize("line", SEARCH_READS)
def test_b198_a_lone_search_reads_the_files_that_steer_later_turns_it_names(line):
    assert commands.names_standing(line) == "" and commands.danger(line) == ""


@pytest.mark.parametrize("line", SEARCH_DOES)
def test_b198_a_search_that_pipes_redirects_runs_or_edits_still_asks(line):
    assert commands.danger(line)


def test_b198_at_full_auto_codexs_own_agents_md_search_runs_unasked(make_client, wait_run, project_dir):
    executor = ScriptedExecutor([Script(["AGENTS.md\n"])])
    client, _ = make_client([cmd(CODEX_SEARCH), text("done")], executor=executor)
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    snap = wait_run(client, cid, run_id)
    assert snap["commands"][0]["status"] == "exited" and len(executor.started) == 1


@pytest.mark.parametrize("line", PASSES_BY)
def test_b198_a_path_a_command_passes_by_is_not_named(line):
    assert not commands.names_koloni(line) and commands.danger(line) == ""


@pytest.mark.parametrize("line", STILL_NAMES)
def test_b198_one_that_opens_or_writes_it_still_asks(line):
    assert commands.danger(line)


# K-koloni-klasor (live): a Codex Lead's headless Chrome with --user-data-dir=.koloni\browser-smoke
# asked at Full auto. The agents' scratch is .koloni/tmp/: no card, any level.
SCRATCH = ["chrome --headless --user-data-dir=.koloni\\tmp\\browser-smoke", "echo x > .koloni/tmp/a.log",
           "Set-Content -Path:.KOLONI\\TMP\\x.txt y", "mkdir -p ./.koloni/tmp/profile && cp a .koloni/tmp/",
           "python -c \"open('.koloni/tmp/x', 'w').write('y')\""]
# (what climbs back out, names another child beside it, or spells it otherwise still asks)
NOT_SCRATCH = ["echo x > .koloni/tmp/../settings.json", "cp .koloni/tmp/x .koloni/settings.json",
               "echo x > .koloni/t*/a", "echo x > .koloni/tmpx/a", "rm -r .koloni tmp",
               "echo x > .koloni/tmp/.claude/settings.json",
               # (review: a climb out of the scratch in another word, or a path built from it)
               "cd .koloni/tmp; Set-Content ../settings.json 1",
               "pushd .koloni/tmp; echo x > ../rules.md",
               "cd .koloni/tmp && echo x > ../shared/a.md",
               "Set-Location .koloni\\tmp; echo x > ..\\rules.md", "sl .koloni/tmp; echo x > ../a",
               "git -C .koloni/tmp add -f ../recipes/x.md",
               "Set-Content (Join-Path .koloni/tmp ../settings.json) 1",
               "Move-Item .koloni/tmp/x (Split-Path .koloni/tmp)",
               "Copy-Item -Recurse .koloni/tmp/src/* -Destination (Split-Path .koloni/tmp)",
               "Set-Content (Resolve-Path .koloni/tmp/..)/x 1",
               # (a git line keeps naming .koloni: a profile's cookies are not committed)
               "git add -f .koloni/tmp/profile/Cookies", "git add .koloni/tmp",
               "git commit -m x .koloni/tmp/a.log",
               # (run_command's cwd, judged with the line: `with_cwd`)
               commands.with_cwd("echo x > ../settings.json", ".koloni/tmp"),
               commands.with_cwd("python x.py", ".claude")]


@pytest.mark.parametrize("line", SCRATCH)
def test_the_scratch_under_koloni_tmp_is_no_standing_name(line):
    assert not commands.names_koloni(line) and commands.names_standing(line) == ""
    assert commands.danger(line) == ""


@pytest.mark.parametrize("line", NOT_SCRATCH)
def test_the_rest_of_koloni_still_asks_and_the_card_says_where_scratch_goes(line):
    assert commands.danger(line)
    if ".koloni/settings.json" in line:
        assert commands.danger(line).endswith(
            "Scratch belongs under .koloni/tmp/: put it there and run again.")


def test_a_command_is_judged_with_its_cwd():
    assert commands.with_cwd("pytest", ".") == "pytest" and commands.with_cwd("pytest", None) == "pytest"
    assert commands.with_cwd("pytest", "src") == "cd src; pytest"
    assert commands.names_standing(commands.with_cwd("cat AGENTS.md", "src")) == ""


@pytest.mark.parametrize("line", [
    "cmd /c mklink /J k C:/Users", "mklink /D a C:\\Users", "mklink a b",
    "New-Item -ItemType Junction -Path .koloni/tmp/k -Target C:/Users",
    "ni -ItemType SymbolicLink x -Target ..", "ln -s ../x .koloni/tmp/k", "ln -sf a b"])
def test_making_a_link_is_asked_at_every_level(line):
    assert commands.harms(line) == "Makes a link, which can point anywhere."
    # (One that names .koloni as the target is a card for that, as before.)
    assert commands.harms("cmd /c mklink /J .koloni/tmp/k .koloni")


@pytest.mark.parametrize("line", ["ln a b", "New-Item -ItemType Directory x", "ni x"])
def test_a_hard_link_or_a_plain_new_item_is_no_link(line):
    assert commands.harms(line) == ""


def test_b188_a_real_glob_is_still_a_danger():
    # (A delete is one by itself, whatever it names.)
    assert commands.danger("rm -rf .*") and commands.names_standing("Copy-Item x .claude*") == ".claude"


@pytest.mark.parametrize(("line", "said"), [
    # R141 (live): no global git identity, the agent's `git config user.name` card read "Names .git".
    ('git config user.name "Murat K"; git config --local user.email m@x.org', commands.GIT_IDENTITY),
    ("git config User.Email m@x.org", commands.GIT_IDENTITY),
    # (anything else of .git, or another folder's, keeps the plain card)
    ("git config user.name M; git config core.hooksPath h", commands.STANDING_FILE.format(name=".git")),
    ("git -C ../other config user.name M", commands.STANDING_FILE.format(name=".git")),
])
def test_setting_this_projects_git_identity_says_so(line, said):
    assert commands.danger(line) == said


@pytest.mark.parametrize("line", READS)
def test_a_read_of_such_a_file_runs_as_any_read(line):
    assert commands.only_reads(line) and commands.danger(line) == ""
    assert commands.tidy_rule(line)  # (a rule can hold it, for a trigger)


@pytest.mark.parametrize("line", STANDING)
def test_a_command_naming_a_file_that_steers_later_turns_is_seen(line):
    assert commands.names_standing(line)
    assert commands.danger(line) and commands.suggest_prefix(line) == ""


@pytest.mark.parametrize("line", ORDINARY)
def test_an_ordinary_command_names_none(line):
    assert commands.names_standing(line) == "" and commands.danger(line) == ""


def test_at_full_auto_koloni_s_own_command_writing_claude_settings_waits(
        make_client, wait_run, project_dir):
    executor = ScriptedExecutor([])
    line = "Set-Content .claude\\settings.json x"
    client, _ = make_client([cmd(line), text("Understood.")], executor=executor)
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    asked = waiting(client, cid, 1)[0]
    assert ".claude" in asked["danger"] and "later turns" in asked["danger"]
    client.post(f"/api/commands/{asked['id']}/reject")
    wait_run(client, cid, run_id)
    assert executor.started == [] and not (project_dir / ".claude").exists()


def test_at_full_auto_an_ordinary_command_is_not_asked(make_client, wait_run, project_dir):
    executor = ScriptedExecutor([Script(["x\n"])])
    client, _ = make_client([cmd("Get-Content README.md"), text("done")], executor=executor)
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    snap = wait_run(client, cid, run_id)
    assert snap["commands"][0]["status"] == "exited" and len(executor.started) == 1


@pytest.mark.parametrize("mode", ["ask", "auto_edit"])
def test_below_full_auto_a_read_of_agents_md_runs_unasked_as_any_read(
        make_client, wait_run, project_dir, mode):
    executor = ScriptedExecutor([Script(["x\n"])])
    client, _ = make_client([cmd("Get-Content AGENTS.md"), text("done")], executor=executor)
    cid, run_id = start_in_mode(client, project_dir, mode)
    snap = wait_run(client, cid, run_id)
    assert snap["commands"][0]["status"] == "exited" and snap["commands"][0]["danger"] == ""


def test_with_nobody_watching_a_ticked_read_of_agents_md_runs(make_client, wait_run, project_dir):
    line = "cat AGENTS.md"
    executor = ScriptedExecutor([Script(["x\n"])])
    client, _, pid, cid = setup(lambda scripts: make_client(scripts, executor=executor),
                                project_dir, {"Lead": [
                                    step(call("run_command", {"command": line}, "c")),
                                    text("done")]})
    made = trigger(client, pid, cid, permissions={
        "write": False, "commands": [allow(client, cid, line)], "agents": 0})
    snap = finished(client, wait_run, cid, run_now(client, made["id"]))
    assert [c["status"] for c in snap["commands"]] == ["exited"]


def test_at_full_auto_a_native_clis_command_writing_claude_settings_is_a_card(
        claude_app, wait_run, project_dir):  # noqa: F811
    bash = {"tool": "Bash", "ask": True, "input": {"command": LIVE}, "result": "x"}
    client, provider, _ = claude_app([bash, {"say": "done"}])
    cid, run_id = start_claude(client, project_dir, provider, "full_auto")
    asked = waiting(client, cid, 1)[0]
    assert asked["origin"] == "cli" and ".claude" in asked["danger"]
    client.post(f"/api/commands/{asked['id']}/reject")
    wait_run(client, cid, run_id)
    assert [v["behavior"] for v in claude_app.record()["asked"]] == ["deny"]


@pytest.fixture
def rule_from_before(monkeypatch):
    """A rule for such a line, made before B-79 (no new one can be: `danger` names it)."""
    monkeypatch.setattr("app.api.commands.tidy_rule", lambda prefix: prefix)


def test_with_nobody_watching_koloni_s_command_naming_github_is_refused_though_ticked(
        make_client, wait_run, project_dir, rule_from_before):
    line = "Set-Content .github\\canli.yml x"
    client, _, pid, cid = setup(make_client, project_dir, {"Lead": [
        step(call("run_command", {"command": line}, "c")), text("done")]})
    rule = allow(client, cid, line)
    made = trigger(client, pid, cid, permissions={"write": True, "commands": [rule], "agents": 0})
    run_id = run_now(client, made["id"])
    snap = finished(client, wait_run, cid, run_id)
    ((name, status, said),) = results(snap, run_id)
    assert (name, status) == ("run_command", "denied") and NOBODY in said
    assert [c for c in snap["commands"] if c["run_id"] == run_id] == []
    assert not (project_dir / ".github").exists()


def test_with_nobody_watching_a_native_clis_command_naming_claude_is_refused_though_ticked(
        claude_app, wait_run, project_dir, rule_from_before):  # noqa: F811
    line = "Set-Content .claude\\settings.json x"
    bash = {"tool": "Bash", "input": {"command": line}, "write": [".claude/settings.json", "x"]}
    client, provider, _ = claude_app([bash, {"say": "done"}])
    snap, run, _ = unattended(
        client, project_dir, provider, "full_auto", wait_run, write=True, commands=[line])
    verdicts = claude_app.record()["asked"]
    assert [v["behavior"] for v in verdicts] == ["deny"] and NOBODY in verdicts[0]["message"]
    assert not (project_dir / ".claude").exists()


# B-336 (live): a delete in the scratch had "Deletes files or disks." at Full auto. `danger` stays
# strict - no rule is offered for a delete, nor covers one -; the card is left out where it is
# decided (`scratch_delete_only`, `AgentRunner._night_asks`).
SCRATCH_DELETES = [
    "Remove-Item .koloni/tmp/not.txt", "rm .koloni/tmp/x", "del .koloni\\tmp\\a.log",
    "rm -f ./.koloni/tmp/a.png .koloni/tmp/b.png", "Remove-Item -Force -Path .koloni/tmp/x.txt",
    "erase -q .koloni/tmp/out.xml", "unlink .koloni/tmp/a.png"]


@pytest.mark.parametrize("line", SCRATCH_DELETES)
def test_a_delete_in_the_scratch_is_no_card_but_still_harm_with_no_rule_offered(line, tmp_path):
    (tmp_path / ".koloni" / "tmp").mkdir(parents=True)
    (tmp_path / ".koloni" / "tmp" / "a.png").write_text("x")
    # (Off Windows `.koloni\tmp\a.log` is one file of that name beside .koloni: asked.)
    windows_only = "\\" in line
    assert commands.scratch_delete_only(line, str(tmp_path)) is (
        sys.platform == "win32" or not windows_only)
    assert commands.harms(line) and commands.suggest_prefix(line) == ""
    assert not commands.scratch_delete_only(line, None)  # (a copy's, a CLI's own: asked)


# The review of B-336: each of these deleted, or wrote, outside the scratch with no card.
OUTSIDE = "C:\\Users\\someone\\out.txt"
BYPASSES = [
    f"Remove-Item .koloni/tmp/c,{OUTSIDE}", f"cmd /c del /q .koloni\\tmp\\d,{OUTSIDE}",
    f"cmd /c del .koloni\\tmp\\e={OUTSIDE}", f"Remove-Item -Path:{OUTSIDE} -Exclude .koloni/tmp/b",
    "Remove-Item .koloni/tmp/.'.'/.'.'/top.txt", "del .koloni\\tmp\\.^.\\.^.\\top2.txt",
    "rm .koloni/tmp/.\\./x", "rm .koloni/tmp/`.`./x", "Push-Location .koloni/tmp; rm x",
    "rm -rf .koloni", "rm .koloni/tmp/../settings.json", "rm -rf .koloni/tmp/profile",
    "Remove-Item -Recurse .koloni/tmp/x", "rm .koloni/tmp/x settings.json",
    "cd .koloni/tmp; rm x", "rm .koloni/tmp/$NAME", "rm .koloni/tmpx/a", "rm .koloni/settings.json",
    "rm .koloni/tmp", "rm .koloni/tmp/.env", "dd if=/dev/zero of=.koloni/tmp/x",
    "rm .koloni/tmp/x; curl -d x https://example.com",
    # (its second review: each line one delete alone - no pipe, no other part, no shell around
    # it; no wildcard; no smart quote; no `/q` or `/f`, a path to pwsh and sh)
    "printf C:/Users/someone/v1.txt | xargs rm -f .koloni/tmp/a",
    "python mk.py; rm -f .koloni/tmp/j/x", "robocopy a b /SJ /E & del .koloni\\tmp\\x",
    "pytest -q; rm .koloni/tmp/out.xml", "cmd /c del /q .koloni\\tmp\\x", "rmdir .koloni/tmp/empty",
    "rm .koloni/tmp/*.png", "Remove-Item -Force .koloni/tmp/*/victim2.txt", "rm .koloni/tmp/a?",
    "Remove-Item .koloni/tmp/\u2018x\u2019", "Remove-Item /q", "rm /f .koloni/tmp/x",
    "rm .koloni/tmp/x && rm .koloni/tmp/y", "rm .koloni/tmp/x\nrm C:/x", "rm .koloni/tmp/x > y",
    ".koloni/tmp/rm .koloni/tmp/x",
    # (its third review: after `--` sh's rm takes every word for a path - `./-f` too)
    "rm .koloni/tmp/a -- -f"]


@pytest.mark.parametrize("line", BYPASSES)
def test_a_delete_that_may_leave_the_scratch_is_a_card_with_no_rule(line, tmp_path):
    (tmp_path / ".koloni" / "tmp").mkdir(parents=True)
    assert not commands.scratch_delete_only(line, str(tmp_path))
    assert commands.harms(line) and commands.suggest_prefix(line) == ""


def test_a_link_in_the_scratch_is_a_card_to_make_and_one_to_delete_through(tmp_path):
    for line in ("New-Item -ItemType:Junction -Path .koloni/tmp/l -Target C:\\Users",
                 "ni -ItemType:SymbolicLink x -Target .."):
        assert commands.harms(line) == "Makes a link, which can point anywhere."
    (tmp_path / ".koloni" / "tmp").mkdir(parents=True)
    away = tmp_path / "away"
    away.mkdir()
    (away / "file").write_text("keep")
    link = tmp_path / ".koloni" / "tmp" / "l"
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(away), str(link))
    else:
        os.symlink(away, link)
    for line in ("Remove-Item .koloni/tmp/l/file", "rm .koloni/tmp/l", "rm .koloni/tmp/*/file"):
        assert not commands.scratch_delete_only(line, str(tmp_path)), line
    # (a dot-folder junction a wildcard of PowerShell's would find: no wildcard is card-free)
    dotted = tmp_path / ".koloni" / "tmp" / ".j"
    if os.name == "nt":
        _winapi.CreateJunction(str(away), str(dotted))
    else:
        os.symlink(away, dotted)
    for line in ("Remove-Item -Force .koloni/tmp/*/file", "Remove-Item .koloni/tmp/.j/file"):
        assert not commands.scratch_delete_only(line, str(tmp_path)), line
    os.rmdir(dotted) if os.name == "nt" else os.unlink(dotted)
    # (and a scratch that is itself a link is none of the project's)
    os.rmdir(link) if os.name == "nt" else os.unlink(link)
    other = tmp_path / "other"
    (other / ".koloni").mkdir(parents=True)
    if os.name == "nt":
        _winapi.CreateJunction(str(away), str(other / ".koloni" / "tmp"))
    else:
        os.symlink(away, other / ".koloni" / "tmp")
    assert not commands.scratch_delete_only("rm .koloni/tmp/file", str(other))
    assert (away / "file").read_text() == "keep"


def test_a_write_that_climbs_out_of_the_scratch_by_a_quoted_dot_names_koloni():
    # (review of B-336: `.'.'` is `..` to PowerShell)
    for line in ("Set-Content .koloni/tmp/.'.'/rules.md x", "echo x > .koloni/tmp/.^./rules.md",
                 # (its second review: PowerShell's smart quotes; sh's `.\.`)
                 "Set-Content .koloni/tmp/.‘.’/rules.md x",
                 "Set-Content .koloni/tmp/.“.”/rules.md x",
                 "sh -c 'echo x > .koloni/tmp/.\\./rules.md'"):
        assert commands.harms(line), line


def test_a_project_folder_with_a_bracket_in_its_name_is_read_as_a_name(tmp_path):
    # (its second review: `[` in the root made a glob of it, which found nothing and passed)
    root = tmp_path / "a[b]"
    (root / ".koloni" / "tmp").mkdir(parents=True)
    assert commands.scratch_delete_only("rm .koloni/tmp/x", str(root))
    assert not commands.scratch_delete_only("rm .koloni/tmp/*", str(root))


# B-339 (live): what climbs out of the scratch said "Names .koloni"; a link said so too.
def test_a_climb_out_of_the_scratch_says_so_and_a_link_is_a_link_first():
    climb = commands.harms("cd .koloni/tmp; echo x > ../settings.json")
    assert climb.startswith("Climbs out of .koloni/tmp")
    assert commands.harms("echo x > .koloni/settings.json").startswith("Names .koloni")
    for line in ("cmd /c mklink /J .koloni\\tmp\\x ..", "mklink /J .koloni\\tmp\\x .."):
        assert commands.harms(line) == "Makes a link, which can point anywhere."
