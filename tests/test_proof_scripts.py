"""Check by kind of work, 0.1.7's Scripts: a `.sh` / `.bash` script read by `bash -n`, a `.ps1` /
`.psm1` one by PowerShell's own parser - never run. The row logic is tested everywhere with a
stand-in shell (a Python one); bash and PowerShell themselves where this machine has them -
that their reading runs nothing a script says (a flag file is never made)."""

import json
import sys

import pytest

from app import proof, proof_kinds
from app.proof_kinds import check_scripts
from tests.fakes import ScriptedExecutor
from tests.test_agent_writes import write
from tests.test_chat_flow import text
from tests.test_proof_end_scenarios import PASS, begin, texts

BROKEN = "if true; then\n  echo hi\nfi\nfi\n"
# A stand-in bash -n: a stray `fi` is its syntax error, at its line; a script that asks it to
# hang hangs; what it was started with (its variables) it says where the script asks.
FAKE_BASH = r"""
import os, sys, time
text = sys.stdin.read()
if "hang" in text:
    time.sleep(30)
if "BASH_ENV" in text and "BASH_ENV" in os.environ:
    sys.stderr.write("fake: line 1: BASH_ENV was passed\n")
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
# A stand-in PowerShell parser: what it is given on stdin, judged as KOLONİ's script would
# answer - a `using assembly` that reached it is "Cannot load assembly".
FAKE_PS = r"""
import json, re, sys
text = sys.stdin.read()
if "garbage" in text:
    print("not json")
    sys.exit(0)
errors = []
if re.search(r"(?im)(^|;)\s*using\s+assembly", text):
    errors.append({"line": 1, "message": "Cannot load assembly './x.dll'."})
for n, line in enumerate(text.split("\n"), 1):
    if line.strip() == "if ( {":
        errors.append({"line": n, "message": "Missing closing '}' in statement block."})
print(json.dumps(errors[:1]))
"""


def said(root, files: dict[str, str], **more) -> list[tuple[str, str]]:
    for rel, body in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(body, encoding="utf-8")
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
    # (Its parser looks a `using assembly` up as it reads it: each such line, `using module` and
    # a #requires that names modules or assemblies, is taken out first - the lines kept.)
    body = (
        "using assembly ./x.dll\n  USING Module ./m.psm1\n$a = 1; using assembly y.dll\n"
        "#Requires -Modules Az\n#requires -Version 5\n'using assembly is just words'\nif ( {\n"
    )
    assert said(tmp_path, {"a.ps1": body}) == [
        ("failed", "a.ps1:7: does not parse - Missing closing '}' in statement block.")
    ]
    assert proof_kinds._RESOLVED.sub("", body).split("\n")[:6] == [
        "",
        "",
        "$a = 1;",
        "",
        "#requires -Version 5",
        "'using assembly is just words'",
    ]


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
