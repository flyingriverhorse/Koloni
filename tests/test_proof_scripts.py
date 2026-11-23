"""Check by kind of work, 0.1.7's Scripts: a `.sh` / `.bash` script read by `bash -n`, a `.ps1` /
`.psm1` one by PowerShell's own parser - never run. The row logic is tested everywhere with a
stand-in shell (a Python one); bash and PowerShell themselves where this machine has them -
that their reading runs nothing a script says (a flag file is never made)."""

import json
import sys
from pathlib import Path

import pytest

from app import proof, proof_kinds
from app.proof_kinds import check_scripts
from app.workspace import WorkspaceError
from tests.conftest import scaled
from tests.fakes import ScriptedExecutor
from tests.test_agent_writes import write
from tests.test_chat_flow import text
from tests.test_proof_end_scenarios import PASS, begin, texts

BROKEN = "if true; then\n  echo hi\nfi\nfi\n"
# A stand-in bash -n: a stray `fi` is its syntax error, at its line; a script that asks it to
# hang hangs - or leaves a child behind holding its pipes; what it was started with (its
# variables, its folder) it says where the script asks.
FAKE_BASH = r"""
import os, subprocess, sys, time
text = sys.stdin.read()
if "grandchild" in text:
    subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    if "hang" not in text:
        sys.exit(0)
if "hang" in text:
    time.sleep(30)
if "BASH_ENV" in text and "BASH_ENV" in os.environ:
    sys.stderr.write("fake: line 1: BASH_ENV was passed\n")
    sys.exit(2)
if "where?" in text:
    sys.stderr.write(f"fake: line 1: in {os.getcwd()}\n")
    sys.exit(2)
lines = text.split("\n")
if "exit 127" in text:
    sys.exit(127)
for n, line in enumerate(lines, 1):
    if line == "fi" and lines.count("fi") > 1 and n == len(lines) - 1:
        sys.stderr.write(f"fake: line {n}: syntax error near unexpected token `fi'\n")
        sys.stderr.write(f"fake: line {n}: `fi'\n")
        sys.exit(2)
"""
# A stand-in PowerShell parser: what it is given on stdin, judged as its parser would answer -
# whatever would make it look something up that reached it says so ("Cannot load assembly",
# "Could not find the module"), a class on a type of a module it was not given is TypeNotFound.
FAKE_PS = r"""
import json, re, sys
text = sys.stdin.read()
if "garbage" in text:
    print("not json")
    sys.exit(0)
errors = []
if re.search(r"(?i)\busing\b(?!:)(?!\s+namespace)", text.replace("`", "")):
    errors.append({"line": 1, "message": "Cannot load assembly './x.dll'.", "id": "x"})
if re.search(r"(?i)import-dscresource", text.replace("`", "")):
    errors.append({"line": 1, "message": "Could not find the module 'x'.", "id": "x"})
for n, line in enumerate(text.split("\n"), 1):
    if line.strip() == "if ( {":
        errors.append({"line": n, "message": "Missing closing '}' in statement block.", "id": "x"})
    if line.startswith("class Q : R"):
        errors.append({"line": n, "message": "Unable to find type [R].", "id": "TypeNotFound"})
print(json.dumps(errors[:1]))
"""


def said(root, files: dict[str, str], **more) -> list[tuple[str, str]]:
    for rel, body in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(body.encode("utf-8"))  # (as written: no CR LF of Windows')
    return [(one["state"], one["text"]) for one in check_scripts(root, list(files), **more)]


@pytest.fixture
def stand_in(monkeypatch):
    monkeypatch.setattr(proof_kinds, "_bash", lambda: [sys.executable, "-c", FAKE_BASH])
    monkeypatch.setattr(proof_kinds, "_powershell", lambda: [sys.executable, "-c", FAKE_PS])


# --- the rows, with a stand-in shell -------------------------------------------------------------


def test_a_script_that_does_not_parse_fails_with_its_shells_line(tmp_path, stand_in):
    rows = said(
        tmp_path,
        {
            "bad.sh": BROKEN,
            "ok.bash": "echo hi\n",
            "bad.ps1": '"a"\nif ( {\n',
            "mod.psm1": "function f { 1 }\n",
        },
    )
    assert rows == [
        ("failed", "bad.sh:4: does not parse - syntax error near unexpected token `fi'"),
        ("passed", "ok.bash: parses"),
        ("failed", "bad.ps1:2: does not parse - Missing closing '}' in statement block."),
        ("passed", "mod.psm1: parses"),
    ]


def test_what_powershell_would_look_up_never_reaches_its_parser(tmp_path, stand_in):
    # (Its parser looks a `using assembly` up as it reads it: each such statement, `using module`
    # and a #requires that names modules or assemblies, is taken out first - the lines kept.)
    body = (
        "using assembly ./x.dll\n  USING Module ./m.psm1\n$a = 1; using assembly y.dll; $b = 2\n"
        "#Requires -Modules Az\n#requires -Version 5\nusing namespace System.IO\nif ( {\n"
    )
    assert said(tmp_path, {"a.ps1": body}) == [
        ("failed", "a.ps1:7: does not parse - Missing closing '}' in statement block.")
    ]
    kept, blanked = proof_kinds._unresolved(body)
    assert blanked and kept.split("\n")[:6] == [
        "",
        "",
        "$a = 1;; $b = 2",
        "",
        "#requires -Version 5",
        "using namespace System.IO",
    ]


@pytest.mark.parametrize(
    "body",
    [
        # (review of k-scripts, B1: pwsh 7 reads an Import-DscResource module's files at any path)
        "Configuration C { Import-DscResource -ModuleName '//host/share/m'\n Node x { } }\n",
        # (B2: each a `using` the blanking does not take out - so never given to the parser)
        "<# c #>using assembly ./x.dll\n'x'\n",
        "using <# c #> assembly ./x.dll\n'x'\n",
        "\u00a0using assembly ./x.dll\n'x'\n",
        "using\u00a0assembly ./x.dll\n'x'\n",
        "\x0cusing assembly ./x.dll\n'x'\n",
        "\x0busing module ./x\n'x'\n",
        "using `\nassembly ./x.dll\n'x'\n",
        # (U3: "using" in a comment or a string is read - but where a boundary is not sure, the
        # whole text is looked at, as before: `<#` or a quote inside a word, a line a backtick
        # goes on, a "…" with code in it, PowerShell's other quote marks, an unended string)
        "Write-Output a<#; Import-DscResource -ModuleName x #>\n",
        "Write-Output don't stop'\nImport-DscResource\n",
        "x`\n# Import-DscResource -ModuleName x\n",
        'Write-Output "$(1) using it"\n',
        "'a’ + 'Import-DscResource'\n",
        "'unended using it\n",
        "$x = 1 # using it\n",  # (a comment after code: read, not taken out)
        # (a statement whose taking out would change the rest: a comment's end, a quote)
        "<#\nusing module x #>\n$y = 1\n",
        "using assembly 'a;b.dll'\n'x'\n",
        # (re-check: a backtick inside a keyword leaves it the keyword to pwsh 7)
        "Configuration C { Import-Dsc`Resource -ModuleName '//h/s/m'\n Node x { } }\n",
        "us`ing module ./x\n'x'\n",
    ],
)
def test_a_script_that_would_have_its_parser_look_something_up_is_not_read(
    tmp_path, stand_in, body
):
    ((state, line),) = said(tmp_path, {"a.ps1": body})
    assert (state, line) == ("note", "a.ps1: not checked: it loads a module or an assembly")


@pytest.mark.parametrize(
    ("body", "row"),
    [
        # (a lone CR ends a line as PowerShell reads it: what follows it is a statement)
        ("# a\rusing module ./x\r'x'\r", ("passed", "a.ps1: parses")),
        ("using module Foo\r$x = 1\rif ( {\r", ("failed", "a.ps1:3: does not parse - Missing")),
        # (a type of a module taken out: not the script's fault)
        (
            "using module ./m\nclass Q : R { }\n",
            ("note", "a.ps1: not checked: it uses a type of a module KOLONİ does not load"),
        ),
    ],
)
def test_lines_end_as_powershell_ends_them_and_a_type_left_unread_is_said(
    tmp_path, stand_in, body, row
):
    ((state, line),) = said(tmp_path, {"a.ps1": body})
    assert (state, line[: len(row[1])]) == row, line


def test_windows_powershell_alone_leaves_powershell_7s_scripts_unread(monkeypatch):
    # (5.1, where no PowerShell 7 is: a Configuration loads DSC's module; `??`, `&&` are 7's)
    told = {}

    def read_by(_argv, text, _seconds):
        told["text"] = text
        message = "Unexpected token '??' in expression or statement."
        return 0, json.dumps([{"line": 1, "message": message, "id": "UnexpectedToken"}]), ""

    monkeypatch.setattr(proof_kinds, "_read_by", read_by)
    shell = [r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"]
    for script in ("Configuration C { Node x { } }\n", "$a = $b ?? 1\n"):
        with pytest.raises(WorkspaceError, match="it needs PowerShell 7"):
            proof_kinds._powershell_said(shell, script)
    assert told["text"] == "$a = $b ?? 1\n"  # (a Configuration was never given to it)


def test_a_problem_the_script_had_before_the_turn_is_a_note(tmp_path, stand_in):
    rows = said(tmp_path, {"a.sh": BROKEN}, before={"a.sh": BROKEN})
    assert rows == [
        (
            "note",
            "a.sh:4: does not parse - syntax error near unexpected token `fi' - so before this turn",
        )
    ]
    # (one that parsed before is the turn's)
    assert said(tmp_path, {"a.sh": BROKEN}, before={"a.sh": "echo\n"})[0][0] == "failed"


def test_what_is_not_read_is_said(tmp_path, stand_in, monkeypatch):
    (tmp_path / "utf16.ps1").write_bytes("'x'\n".encode("utf-16"))
    monkeypatch.setattr(proof_kinds, "MOST_SCRIPT", 64)
    monkeypatch.setattr(proof_kinds, "BASH_SECONDS", 1)
    rows = said(
        tmp_path,
        {
            ".env.sh": "export KEY=1\n",
            "big.sh": "#" * 65,
            "hang.sh": "hang\n",
            "gone.sh": "exit 127\n",
            "odd.ps1": "garbage\n",
        },
    )
    rows += [(one["state"], one["text"]) for one in check_scripts(tmp_path, ["utf16.ps1"])]
    assert rows == [
        ("note", ".env.sh: not checked: a secret file is never read"),
        ("note", "big.sh: not checked: it is over 0 MB"),
        ("note", "hang.sh: not checked: reading it took over 1 s"),
        ("note", "gone.sh: not checked: bash ended with 127"),
        ("note", "odd.ps1: not checked: PowerShell's parser gave no answer"),
        ("note", "utf16.ps1: not checked: it is not UTF-8 text"),
    ]


def test_no_shell_here_is_said(tmp_path, monkeypatch):
    monkeypatch.setattr(proof_kinds, "_bash", lambda: None)
    monkeypatch.setattr(proof_kinds, "_powershell", lambda: None)
    assert said(tmp_path, {"a.sh": "echo\n", "a.ps1": "'x'\n"}) == [
        ("note", "a.sh: not checked: no bash here"),
        ("note", "a.ps1: not checked: no PowerShell here"),
    ]


def test_at_most_twenty_a_turn(tmp_path, stand_in):
    rows = said(tmp_path, {f"s{n:02}.sh": "echo\n" for n in range(23)})
    assert rows[-1] == ("note", "Scripts not checked: s20.sh, s21.sh, s22.sh - at most 20 a turn")
    assert [state for state, _line in rows[:-1]] == ["passed"] * 20


def test_a_shell_gets_none_of_the_users_variables(tmp_path, stand_in, monkeypatch):
    monkeypatch.setenv("BASH_ENV", str(tmp_path / "maker.sh"))
    assert said(tmp_path, {"env.sh": "BASH_ENV\n"}) == [("passed", "env.sh: parses")]


@pytest.mark.parametrize(
    ("platform", "found", "git", "bash"),
    [
        ("win32", None, "Git/cmd/git.exe", "Git/usr/bin/bash.exe"),
        ("win32", None, "Git/mingw64/bin/git.exe", "Git/usr/bin/bash.exe"),
        ("win32", r"C:\Windows\System32\bash.exe", None, None),
        ("win32", r"C:\Users\u\AppData\Local\Microsoft\WindowsApps\bash.exe", None, None),
        ("win32", r"D:\tools\msys\usr\bin\bash.exe", None, r"D:\tools\msys\usr\bin\bash.exe"),
        ("linux", "/usr/bin/bash", None, "/usr/bin/bash"),
        ("linux", None, None, None),
    ],
)
def test_bash_is_gits_on_windows_never_wsls(tmp_path, monkeypatch, platform, found, git, bash):
    if git:
        (tmp_path / git).parent.mkdir(parents=True)
        (tmp_path / git).write_text("")
        (tmp_path / bash).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / bash).write_text("")
    named = {"git": str(tmp_path / git) if git else None, "bash": found}
    monkeypatch.setattr(proof_kinds.sys, "platform", platform)
    monkeypatch.setattr(proof_kinds.shutil, "which", lambda name, **_more: named.get(name))
    assert proof_kinds._bash() == ([str(tmp_path / bash) if git else bash] if bash else None)


def test_scripts_are_a_part_on_by_default():
    assert "scripts" in proof.PARTS and "scripts" in proof.ON_UNLESS_UNTICKED


# --- the shells themselves, where this machine has them: they read, they never run -------------

needs_bash = pytest.mark.skipif(proof_kinds._bash() is None, reason="no bash here")
needs_powershell = pytest.mark.skipif(proof_kinds._powershell() is None, reason="no PowerShell")


@needs_bash
def test_bash_finds_a_syntax_error_and_runs_nothing(tmp_path, monkeypatch):
    (tmp_path / "maker.sh").write_text("touch flag-bash-env\n", encoding="utf-8")
    monkeypatch.setenv("BASH_ENV", str(tmp_path / "maker.sh"))
    runs = (
        'echo "$(touch flag-sub)" `touch flag-tick`\n'
        "cat <<EOF\n$(touch flag-heredoc)\nEOF\n"
        "alias ls='touch flag-alias'\nls\n"
        "trap 'touch flag-trap' EXIT\n"
        "f() { touch flag-function; }\nf\n"
    )
    rows = said(tmp_path, {"runs.sh": runs, "bad.sh": BROKEN})
    assert rows[0] == ("passed", "runs.sh: parses")
    state, line = rows[1]
    assert state == "failed" and line.startswith("bad.sh:4: does not parse - "), line
    assert not list(tmp_path.glob("flag-*")), list(tmp_path.glob("flag-*"))


@needs_powershell
def test_powershells_parser_finds_a_syntax_error_and_runs_nothing(tmp_path):
    (tmp_path / "evil.psm1").write_text(
        "Set-Content -Path (Join-Path $PSScriptRoot 'flag-module') -Value 'ran'\n"
        "class Evil { [string] $Name }\n",
        encoding="utf-8",
    )
    (tmp_path / "x.dll").write_bytes(b"x")  # (one byte: no assembly - never looked up)
    runs = (
        "using assembly ./x.dll\nusing assembly ./missing.dll\nusing module ./evil.psm1\n"
        "#requires -Modules ./evil.psm1\n"
        "class Mine { static [string] $X = (Set-Content flag-static 'ran') }\n"
        "$b = [ScriptBlock]::Create(\"Set-Content flag-create 'ran'\")\n"
        "\"$(Set-Content flag-sub 'ran')\"\n"
        "function f { begin { Set-Content flag-begin 'ran' } }\n"
        "BEGIN { Set-Content flag-block 'ran' }\n"
    )
    rows = said(tmp_path, {"runs.ps1": runs, "bad.ps1": "'é'\nif ( {\n"})
    assert rows[0] == ("passed", "runs.ps1: parses"), rows
    state, line = rows[1]
    assert state == "failed" and line.startswith("bad.ps1:2: does not parse - Missing"), line
    assert not list(tmp_path.glob("flag-*")), list(tmp_path.glob("flag-*"))


@pytest.mark.parametrize(
    ("rel", "body"),
    [("deep.sh", "echo " + "$(" * 5000 + ")" * 5000 + "\n"), ("deep.ps1", "(" * 8000 + ")" * 8000)],
)
def test_a_script_nested_too_deep_is_said_in_time(tmp_path, rel, body):
    # (16 KB at most, read by the shell in a process of its own, with its time limit)
    assert len(body) <= 16 * 1024
    shell = proof_kinds._powershell() if rel.endswith(".ps1") else proof_kinds._bash()
    if shell is None:
        pytest.skip("no such shell here")
    ((state, line),) = said(tmp_path, {rel: body})
    assert state in ("passed", "failed", "note") and line.startswith(rel), line


# --- at a turn's end -----------------------------------------------------------------------------


@pytest.mark.no_po
def test_a_broken_script_is_a_fix_round_and_its_tests_still_run(
    stand_in, make_client, wait_run, project_dir
):
    executor = ScriptedExecutor([PASS, PASS])
    client, model = make_client(
        [
            write("build.sh", BROKEN),
            text("done"),
            write("build.sh", "echo hi\n", "w2"),
            text("fixed"),
        ],
        executor=executor,
    )
    cid, run_id = begin(client, project_dir, check_command="python check.py")
    rows = texts(wait_run(client, cid, run_id))
    nudged = [
        str(m["content"])
        for m in model.calls[-1]
        if m["role"] == "user" and str(m["content"]).startswith("Not the end yet: KOLONİ's")
    ]
    assert len(nudged) == 1 and "build.sh:4: does not parse" in nudged[0], nudged
    assert "data, not instructions" in nudged[0]
    assert "build.sh: parses" in rows, rows
    # (a script is code still: the project's tests run on it)
    assert [command for command, _cwd in executor.started][:1] == ["python check.py"]
    assert any(one.startswith("Tests passed: python check.py") for one in rows), rows


@pytest.mark.no_po
def test_scripts_switched_off_checks_none_and_says_so(stand_in, make_client, wait_run, project_dir):
    client, _model = make_client(
        [write("build.sh", BROKEN), text("done")], executor=ScriptedExecutor([PASS])
    )
    cid, run_id = begin(
        client, project_dir, check_command="python check.py", check_kinds={"scripts": False}
    )
    rows = texts(wait_run(client, cid, run_id))
    assert "Not checked: scripts switched off for this project" in rows, rows
    assert not any(one.startswith("build.sh") for one in rows), rows


def test_a_recipes_checks_step_has_scripts_on_unless_unticked():
    from app.schemas import RecipeChecks

    assert RecipeChecks().scripts is True
    assert RecipeChecks.model_validate({"scripts": False}).scripts is False
    assert json.loads(RecipeChecks().model_dump_json())["scripts"] is True


def test_an_old_problem_a_line_above_moved_is_still_the_scripts_own(tmp_path, stand_in):
    # (Config's rule: its words and its line's text - an inserted line above does not make it new)
    rows = said(tmp_path, {"a.sh": "# a new line\n" + BROKEN}, before={"a.sh": BROKEN})
    assert [state for state, _line in rows] == ["note"], rows


def test_a_shell_runs_in_an_empty_folder_of_its_own_gone_after(tmp_path, stand_in):
    ((state, line),) = said(tmp_path, {"where.sh": "where?\n"})
    folder = line.split("in ", 1)[1]
    assert state == "failed" and "koloni-script-" in folder, line
    assert not Path(folder).exists() and Path(folder).resolve() != tmp_path.resolve()


def test_past_its_time_the_whole_tree_is_killed_and_a_held_pipe_waits_not(
    tmp_path, stand_in, monkeypatch
):
    # (Review: a child the shell left behind, holding its pipes, kept a 2 s read for 25 s.)
    import time

    monkeypatch.setattr(proof_kinds, "BASH_SECONDS", 1)
    started = time.monotonic()
    rows = said(tmp_path, {"hung.sh": "grandchild hang\n", "left.sh": "grandchild\n"})
    assert rows == [
        ("note", "hung.sh: not checked: reading it took over 1 s"),
        ("passed", "left.sh: parses"),
    ]
    assert time.monotonic() - started < scaled(15)


def test_a_cr_lf_shell_script_is_read_and_said(tmp_path, stand_in):
    rows = said(tmp_path, {"w.sh": BROKEN.replace("\n", "\r\n"), "ok.sh": "echo hi\r\n"})
    assert rows == [
        ("failed", "w.sh:4: does not parse - syntax error near unexpected token `fi'"),
        ("note", "w.sh: Windows line endings (CR LF) - bash on Linux will not run it as it is"),
        ("passed", "ok.sh: parses"),
        ("note", "ok.sh: Windows line endings (CR LF) - bash on Linux will not run it as it is"),
    ]


@needs_bash
def test_bash_reads_with_extglob_on(tmp_path):
    rows = said(
        tmp_path,
        {
            "glob.sh": "shopt -s extglob\ncase $1 in @(a|b)) echo y ;; esac\nls !(foo)\n",
            "bad.sh": "echo !(\n",
        },
    )
    assert rows[0] == ("passed", "glob.sh: parses") and rows[1][0] == "failed", rows


def test_a_using_variable_is_no_statement_and_is_read(tmp_path, stand_in):
    # (`$using:x` hands a variable to a remote or parallel block: nothing is looked up)
    assert said(tmp_path, {"a.ps1": "$x = 1\n1..2 | ForEach-Object -Parallel { $using:x }\n"}) == [
        ("passed", "a.ps1: parses")
    ]


def test_no_folder_of_a_read_is_left_behind_whatever_its_shell_left_running(
    tmp_path, stand_in, monkeypatch
):
    # (Six empty koloni-script-* folders stayed in %TEMP%: a process the shell left behind held
    # its folder as its own, and the folder's removal failed unsaid. Now what the shell started
    # ends with the read - its job on Windows, its group elsewhere - and the folder goes.)
    import tempfile

    temp = tmp_path / "temp"
    temp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(temp))
    monkeypatch.setattr(proof_kinds, "BASH_SECONDS", 2)
    rows = said(tmp_path / "p", {"left.sh": "grandchild\n", "hung.sh": "grandchild hang\n"})
    assert [state for state, _text in rows] == ["passed", "note"], rows
    assert list(temp.iterdir()) == []


@needs_powershell
def test_using_in_a_comment_or_a_string_is_read(tmp_path):
    # (U3: each of these was "not checked: it loads a module or an assembly")
    files = {
        "a.ps1": "# Build using dotnet\n$x = 1\n",
        "b.ps1": "# Using the default path\nWrite-Output 'we are using it'\n",
        "c.ps1": "<#\n.SYNOPSIS\nDeploys using az.\n#>\nparam($a)\n",
        "d.ps1": "$s = @'\nusing module ./evil.psm1\nImport-DscResource\n'@\n$s\n",
    }
    assert said(tmp_path, files) == [("passed", f"{rel}: parses") for rel in files]


# (each kind of part U3 blanks, and the boundaries it is not sure of - ZZZ for any keyword: no lookup)
TOKENS = [
    "# Build ZZZ dotnet\n$x = 1\n",
    "<#\n.SYNOPSIS\nDeploys ZZZ az.\n#>\nparam($a)\n",
    "$x = 1 # ZZZ it\n",
    'Write-Output "ZZZ $x"\n',
    "$s = @'\nZZZ module x\n'@\n",
    '$s = @"\nZZZ $x\n"@\n',
    "Write-Output a<#c#>b\n",
    "Write-Output don't stop'\nZZZ\n",
    "${a'b} = 1\nZZZ\n",
    "$x = 'a''b'; ZZZ\n",
    '$x = "a""b`"c"; ZZZ\n',
    "x`\n# ZZZ\n",
    "$a = @'\n  '@\nZZZ\n'@\n",
    "<# a #> <# b #>ZZZ\n",
    "$h = @{ 'k' = \"v\" } # c\n",
    "Write-Output 'a<#b'; ZZZ #> \n",
    "[string]'x' # ZZZ\n",
    "Write-Host @'\nx\n'@ ; ZZZ\n",
]
_SPANS = r"""
$text = [Console]::In.ReadToEnd()
$tokens = $null; $errors = $null
$null = [System.Management.Automation.Language.Parser]::ParseInput($text, [ref]$tokens, [ref]$errors)
ConvertTo-Json -Compress @($tokens | Where-Object { $_.Kind -in 'Comment', 'StringLiteral',
  'StringExpandable', 'HereStringLiteral', 'HereStringExpandable' } |
  ForEach-Object { @{ s = $_.Extent.StartOffset; e = $_.Extent.EndOffset } })
"""


@needs_powershell
@pytest.mark.parametrize("text", TOKENS)
def test_what_u3_takes_for_a_comment_or_a_string_powershell_does_too(text):
    # (never weaker than before: a character blanked for the look is one of a comment or a string
    # to PowerShell's own tokenizer - else code with a lookup in it could hide there)
    import base64
    import json
    import subprocess

    code = proof_kinds._code_of(text)
    if code is None:
        return  # (not sure: the whole text is looked at, as before)
    done = subprocess.run(  # noqa: S603 (PowerShell, its own script encoded; the text on stdin)
        [
            *proof_kinds._powershell(),
            "-NoProfile",
            "-NonInteractive",
            "-EncodedCommand",
            base64.b64encode(_SPANS.encode("utf-16-le")).decode("ascii"),
        ],
        input=text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=scaled(60),
    )
    spans = json.loads(done.stdout or "[]")
    inside = {
        at
        for one in ([spans] if isinstance(spans, dict) else spans)
        for at in range(one["s"], one["e"])
    }
    assert {at for at, (a, b) in enumerate(zip(text, code, strict=True)) if a != b} <= inside


@pytest.mark.parametrize(
    ("first", "row"),
    [
        ("#!/bin/zsh", ("note", "s.sh: not checked: its first line says it is a zsh script")),
        (
            "#!/usr/bin/env fish",
            ("note", "s.sh: not checked: its first line says it is a fish script"),
        ),
        (
            "#!/usr/bin/env -S python3 -u",
            ("note", "s.sh: not checked: its first line says it is a python3 script"),
        ),
        ("#!/bin/ksh", ("note", "s.sh: not checked: its first line says it is a ksh script")),
        # (bash reads these: no first line of that kind, sh, bash, dash, through env too)
        (
            "#!/bin/sh",
            ("failed", "s.sh:5: does not parse - syntax error near unexpected token `fi'"),
        ),
        (
            "#!/usr/bin/env bash",
            ("failed", "s.sh:5: does not parse - syntax error near unexpected token `fi'"),
        ),
        (
            "#! /bin/dash -e",
            ("failed", "s.sh:5: does not parse - syntax error near unexpected token `fi'"),
        ),
        (
            "# a comment",
            ("failed", "s.sh:5: does not parse - syntax error near unexpected token `fi'"),
        ),
    ],
)
def test_a_script_whose_first_line_names_another_shell_is_not_read_by_bash(
    tmp_path, stand_in, first, row
):
    # (U1: a valid zsh script was "does not parse" and sent back to fix)
    assert said(tmp_path, {"s.sh": f"{first}\n{BROKEN}"}) == [row]


@needs_bash
def test_what_bash_warns_of_with_exit_0_is_a_note(tmp_path):
    # (U2: a here-document ended by the file's end - bash -n exits 0 and warns: not "does not parse")
    rows = said(
        tmp_path, {"heredoc.sh": "cat <<EOF\nline\n", "zsh.sh": "#!/bin/zsh\nprint -l **/*(.)\n"}
    )
    assert rows[0] == ("passed", "heredoc.sh: parses"), rows
    assert rows[-1] == ("note", "zsh.sh: not checked: its first line says it is a zsh script")
    # (its warning, where this bash gives one - Git's 5.2 does: a note of its own)
    assert all(
        state == "note" and line.startswith("heredoc.sh:") and "bash warns - " in line
        for state, line in rows[1:-1]
    ), rows
