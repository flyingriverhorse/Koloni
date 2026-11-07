"""B-316 (live, 30 Oct): at Full auto a Debugger's commands each waited for the user. Its reads
of AGENTS.md through a pipe (`| Select-Object -First 150`) were taken for a write of it
(`names_standing`); its test runs filtered by `Select-String` were taken for a search of the
whole folder (`search_reason`), the folder holding a secret file. The commands, as said."""

import pytest

from app import commands
from app.model_native import _unwrapped
from tests.fakes import Script, ScriptedExecutor
from tests.test_agent_commands import cmd
from tests.test_chat_flow import start_in_mode, text
from tests.test_codex_app_server_scenarios import ACCEPT, RUN, answers
from tests.test_command_safety_scenarios import waiting
from tests.test_native_agent import native_app  # noqa: F401  (a fixture)
from tests.test_native_agent import start as start_native

LOOK = r"git status --short; git log -1 --oneline; Get-Content AGENTS.md | Select-Object -First 150"
TEST = (r'cd skyulf-core; ..\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider '
        r'tests/integration/platforms/test_databricks_candidate.py --tb=short 2>&1 | '
        r'Select-String -Pattern "^tests|^skyulf|Error" | Select-Object -First 90')
EDIT = (r"cd skyulf-core; $p='tests/integration/platforms/test_databricks_candidate.py'; "
        r"$c=[System.IO.File]::ReadAllText($p); $c=$c.Replace('a','b'); "
        r"[System.IO.File]::WriteAllText($p,$c); git diff --stat -- $p; "
        r"..\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider $p --tb=short 2>&1 | "
        r'Select-String -Pattern "^tests|Error|passed|failed" | Select-Object -First 50')
NARROW = (r'cd skyulf-core; ..\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider '
          r'tests/integration/platforms/test_databricks_candidate.py -k "never_mutates" '
          r'--tb=short 2>&1 | Select-String -Pattern "passed|failed|Error" ; Get-Content '
          r"skyulf/integrations/databricks/training/fitting/candidate.py | Select-Object -Skip 596 "
          r"-First 70")
LIVE = [LOOK, TEST, EDIT, NARROW]
SHELL = r'"C:\WINDOWS\System32\WindowsPowerShell\v1.0\powershell.exe" -Command '


def codex(line: str) -> str:
    """The line Codex runs a command in (`POWERSHELL_LINE`): in single quotes, or - one that
    holds one - in double quotes."""
    return (SHELL + '"' + line.replace('"', '""') + '"' if "'" in line
            else SHELL + "'" + line + "'")


# What still asks: a pipe that writes or runs code, a secret, .koloni; a search of the folder.
STILL_ASKS = [
    "Get-Content AGENTS.md | Out-File x",
    "Get-Content x | Tee-Object AGENTS.md",
    "Get-Content x | Set-Content AGENTS.md",
    "Get-Content AGENTS.md | ForEach-Object { $_ }",
    "Get-Content AGENTS.md | Select-Object @{n='x';e={1}}",
    "Get-Content AGENTS.md | Select-Object -First (Remove-Item x)",
    "Get-Content AGENTS.md | sort /o AGENTS.md",
    "Get-Content .env | Select-Object -First 1",
    "Get-Content .koloni/x | Select-Object -First 1",
]
STILL_SEARCHES = ["cd x; gci -r | sls KEY", "cd x; gi * | sls KEY", "python x.py; gci | sls KEY",
                  "python x.py 2>&1 | gc *", "cd x; Get-ChildItem -Recurse | Select-String KEY"]


@pytest.mark.parametrize("line", LIVE)
def test_the_debuggers_commands_ask_nothing_at_full_auto(line):
    assert _unwrapped(codex(line)) == line
    for said in (line, codex(line)):
        assert commands.danger(said) == "" and not commands.searches_folder(said)
    assert commands.copy_reason(line, True, "C:\\p", "C:\\p\\runtime") == ""
    assert commands.installs(line) == ""


@pytest.mark.parametrize("line", STILL_ASKS)
def test_a_pipe_that_writes_runs_code_or_opens_a_secret_still_asks(line):
    assert commands.danger(line) and commands.danger(codex(line))


@pytest.mark.parametrize("line", STILL_SEARCHES)
def test_what_hands_select_string_files_is_still_a_search(line):
    assert commands.searches_folder(line)


@pytest.mark.parametrize("line", LIVE)
def test_at_full_auto_koloni_s_own_command_runs_unasked_beside_a_secret(
        make_client, wait_run, project_dir, line):
    (project_dir / ".env").write_text("KEY=FAKE\n", encoding="utf-8")
    (project_dir / "AGENTS.md").write_text("# rules\n", encoding="utf-8")
    executor = ScriptedExecutor([Script(["ok\n"])])
    client, _ = make_client([cmd(line), text("done")], executor=executor)
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    snap = wait_run(client, cid, run_id)
    assert snap["commands"][0]["status"] == "exited" and len(executor.started) == 1


# B-316 (live): two searches the user saw refused as searches of the whole folder - both kept to
# a folder that holds no secret file. Asked only where the scope reaches one, or is not read off
# the line.
SCOPED = [
    ("$f='skyulf-core/skyulf/integrations/x.py'; Select-String -Path $f -Pattern 'from_payload'; "
     "$t=[IO.File]::ReadAllText('skyulf-core/skyulf/integrations/x.py'); "
     "[IO.File]::WriteAllText('skyulf-core/skyulf/integrations/x.py',$t.Replace('a','b')); "
     'Select-String -Path tests/integration/platforms/*.py -Pattern "from_payload" | Select -First 20'
     ' | % {"$($_.Path | Split-Path -Leaf):$($_.LineNumber)"}'),
    ('git grep -n -i -E "legacy|required_windows" -- skyulf-core/tests/integration/platforms | '
     'Select-String -Pattern "monitor|performance" | Select-Object -First 40'),
    "rg KEY tests/integration/platforms", "rg KEY -g '*.py'", "grep -rn KEY tests --include=*.py",
    "Get-ChildItem tests -Recurse | Select-String KEY", "Select-String -LiteralPath tests/a.py,tests/b.py KEY",
]
REACHES = ["git grep x", "git grep x -- .", "rg KEY", "rg KEY . -g '*env*'", "gci -Recurse | sls KEY",
           "Select-String -Path tests/*,.env* -Pattern x", "$g = gci -r; Select-String x -Path $g",
           "cd tests; rg KEY ..", "Select-String -Pattern KEY -Path (Get-ChildItem -Recurse -File)",
           "rg KEY config", "powershell -Command 'Get-ChildItem -Recurse | Select-String KEY'",
           # (found in review: a shell's script by another flag; a lister of another chain's
           # part; a name assigned twice, or assigned what is no literal)
           'bash -lc "gci -r | sls KEY"', 'powershell -com "gci -r | sls KEY"',
           "gci tests -Recurse | Out-Null; gci config | sls KEY",
           "$d='tests'; $d='config'; rg KEY $d", "$d='con' + 'fig'; rg KEY $d"]
# Found in the security review of 20bfc21d: each read a secret unasked there. The scope is read
# only where every word of the search is understood; anything else asks.
BYPASSES = [
    "grep -rn -C 3 KEY", "grep -r -A 1 KEY",  # (an option's value taken for the pattern)
    "gci -Recurse -ea 0 | sls KEY",  # (an option not in the table)
    "gci -Recurse -ErrorAction SilentlyContinue | Select-String -Pattern KEY",
    "rg --hidden --color never KEY", "rg --hidden -r x KEY", "grep -r -T KEY . src",
    "git grep --untracked KEY -- ':/'", "git grep --no-index KEY -- ':!src'",  # (pathspec magic)
    "git -C .. grep --no-index KEY -- proj",  # (git told where before grep)
    "rg --hidden KEY $env:USERPROFILE", "grep -r KEY $(pwd)",  # (no plain literal)
    "rg --hidden KEY (Get-Location).Path", "cd ..; rg --hidden KEY proj",
    "$f='src'; $F='sub'; rg --hidden KEY $f",  # (a name in another case is the same)
    "$f='src'; Set-Variable f sub; rg --hidden KEY $f",
    "rg --hidden KEY -g '*.{py,env}'",  # (a brace in a glob)
    "rg --hidden KEY sub.",  # (Windows drops a trailing dot: `sub`)
    "gci -Recurse -Filter env* | sls KEY",  # (-Filter matches 8.3 short names: ENV~1)
    # (re-review of 5785e482: rg's globs are gitignore's - `/` anchors, `**/` is no folder too;
    # and `set` is Set-Variable's alias)
    "rg --hidden -g '/*' KEY", "rg --hidden -g '/.e*' KEY", "rg -uu -g '**/sub/**' KEY",
    "rg -g '**/config/**' KEY", "rg -g '/config/**' KEY", "rg --iglob '/CONFIG/*' KEY",
    "$f='src'; set f sub; rg --hidden KEY $f",
]
# What a pipe hands its text to may be another program by an alias or a function of the line's
# own: then no stage is taken for a sink (re-review of 5785e482).
RENAMED_SINKS = [
    "Set-Alias Select-Object Set-Content; Get-Content x | Select-Object AGENTS.md",
    "New-Alias Sort-Object Set-Content; Get-Content x | Sort-Object AGENTS.md",
    "sal Select-Object Set-Content; Get-Content x | Select-Object AGENTS.md",
    "nal Sort-Object Set-Content; Get-Content x | Sort-Object AGENTS.md",
    "function Sort-Object { $input | Set-Content $args[0] }; Get-Content x | Sort-Object AGENTS.md",
    "filter Sort-Object { Set-Content $args[0] $_ }; Get-Content x | Sort-Object AGENTS.md",
]


@pytest.mark.parametrize("line", RENAMED_SINKS)
def test_a_sink_renamed_in_the_line_is_no_sink(line):
    assert commands.names_standing(line) == "agents.md"


@pytest.mark.parametrize("line", [LOOK, TEST, *SCOPED[:2]])
def test_at_full_auto_codexs_line_runs_unasked_beside_a_secret(
        native_app, wait_run, project_dir, line):  # noqa: F811
    (project_dir / ".env").write_text("KEY=FAKE\n", encoding="utf-8")
    (project_dir / "tests" / "integration" / "platforms").mkdir(parents=True)
    (project_dir / "skyulf-core" / "tests" / "integration" / "platforms").mkdir(parents=True)
    client, provider, _ = native_app([{"run": codex(line)}, {"say": "ok"}])
    cid, run_id = start_native(client, project_dir, provider, "full_auto")
    wait_run(client, cid, run_id)
    assert answers(native_app) == [(RUN, ACCEPT)]


@pytest.fixture
def held(tmp_path):
    root = tmp_path / "proj"
    (root / "tests" / "integration" / "platforms").mkdir(parents=True)
    (root / "skyulf-core" / "tests" / "integration" / "platforms").mkdir(parents=True)
    (root / ".env").write_text("KEY=FAKE\n", encoding="utf-8")
    # (In another case than the search names it: `rg KEY config` reaches it on Windows.)
    (root / "Config").mkdir()
    (root / "Config" / "id_rsa").write_text("x", encoding="utf-8")
    (root / "src").mkdir()
    (root / "sub").mkdir()
    (root / "sub" / ".env").write_text("KEY=FAKE\n", encoding="utf-8")
    return root


@pytest.mark.parametrize("line", SCOPED)
def test_a_search_kept_to_a_folder_with_no_secret_asks_nothing(held, line):
    assert commands.search_reason(line, held) == "" and commands.danger(line) == ""


@pytest.mark.parametrize("line", REACHES + BYPASSES)
def test_a_search_that_reaches_a_secret_or_whose_scope_is_not_read_still_asks(held, line):
    assert "secret file" in commands.search_reason(line, held)


def test_select_string_of_a_secret_named_still_asks(held):
    assert commands.danger("Select-String -Path .env -Pattern x") == commands.SECRET_FILE


@pytest.mark.parametrize("line", SCOPED[:2])
def test_at_full_auto_the_users_scoped_searches_run_unasked_beside_a_secret(
        make_client, wait_run, project_dir, line):
    (project_dir / ".env").write_text("KEY=FAKE\n", encoding="utf-8")
    # (A path a search names is read only where it is there: as in the user's project.)
    (project_dir / "tests" / "integration" / "platforms").mkdir(parents=True)
    (project_dir / "skyulf-core" / "tests" / "integration" / "platforms").mkdir(parents=True)
    executor = ScriptedExecutor([Script(["ok\n"])])
    client, _ = make_client([cmd(line), text("done")], executor=executor)
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    snap = wait_run(client, cid, run_id)
    assert snap["commands"][0]["status"] == "exited" and len(executor.started) == 1
    # (and read again, its record says no search of the folder: as it was live)
    assert snap["commands"][0]["danger"] == ""


@pytest.mark.parametrize("line", ["git grep x", "Select-String -Path .env -Pattern x"])
def test_at_full_auto_a_search_of_the_whole_repo_or_a_secret_still_waits(
        make_client, wait_run, project_dir, line):
    (project_dir / ".env").write_text("KEY=FAKE\n", encoding="utf-8")
    executor = ScriptedExecutor([])
    client, _ = make_client([cmd(line), text("Understood.")], executor=executor)
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    asked = waiting(client, cid, 1)[0]
    assert asked["danger"] == (commands.SEARCHES_FOLDER if line == "git grep x"
                               else commands.SECRET_FILE)
    client.post(f"/api/commands/{asked['id']}/reject")
    snap = wait_run(client, cid, run_id)
    assert executor.started == []
    # (Once decided, its card is gone: the search's word with it, live and read again alike.)
    assert snap["commands"][0]["danger"] == (
        "" if line == "git grep x" else commands.SECRET_FILE)
