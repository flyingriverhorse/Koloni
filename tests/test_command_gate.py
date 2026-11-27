"""K-koordinasyon's command gate (review round 3): what a command is asked may only go up.

Round 2 cured over-asks by narrowing what recognised a harm, and each narrow recogniser failed
open where it missed: commands 650e22a asked about ran with no card. `command_gate.json` holds
each line's verdict as 650e22a gave it - the reviewers' probe lines, the briefs' lines and the
command tests' strings - and HEAD must give at least that: `harm_class` (none < soft < always),
a card from `copy_reason` in a copy with links, `installs()`, `web_off_reason` with
http_request off (review round 4). A line meant to go down (an
over-ask cured) is in its `allow`, with why; a known regression still open, in its `xfail`; a
line meant to go up (a hole 650e22a had too: a continued line) in its `up` - harm at least. A line
a branch's worktree must ask (k-okuyucu-3: a write to a place built at run time) is in `shared`,
one a rule never covers (a shell a runner is handed) in `unruled`, with that rule, and one its
rule must still cover, as no harm and no other program run (a runner's program's own words), in
`ruled`."""

import json
import os
import re
import sys
from pathlib import Path

from app import commands, copies

GATE = json.loads(Path(__file__).with_name("command_gate.json").read_text(encoding="utf-8"))
RANK = {"": 0, "soft": 1, "always": 2}


def spellings(path: str) -> dict[str, str]:
    """A path as the probes spelt it: as it is, its `\\` doubled, with `/`, in upper and lower
    case, and Git Bash's `/c/...`."""
    forms = {
        "": path,
        "|dbl": path.replace("\\", "\\\\"),
        "|fwd": path.replace("\\", "/"),
        "|up": path.upper(),
        "|low": path.lower(),
    }
    if re.match(r"[A-Za-z]:", path):
        forms["|bash"] = f"/{path[0].lower()}{path[2:]}".replace("\\", "/")
    return forms


def tokens(tmp_path: Path) -> dict[str, str]:
    """The gate's `<x>` paths, made in this test's folder as the probes laid them out."""
    runtime = tmp_path / "runtime"
    held, users = copies.folders(runtime)[0], copies._both(runtime)[1]
    bases = {
        "uown": users / "a" / "tree",
        "users": users,
        "own": held / "a" / "tree",
        "held": held,
        "worktree": tmp_path / "wt" / "x",
        "project": tmp_path / "proj",
        "runtime": runtime,
        "tmp": tmp_path,
    }
    found = {
        f"<{name}{suffix}>": form
        for name, path in bases.items()
        for suffix, form in spellings(str(path)).items()
    }
    # (the user's data folder as KOLONİ finds it - %LOCALAPPDATA% on Windows, XDG's elsewhere -:
    # no LOCALAPPDATA off Windows)
    local = str(copies._user_data())
    rel = str(users)[len(local) :]
    return {**found, "<la_rel>": rel, "<la_rel|fwd>": rel.replace("\\", "/"), "<la>": local}


def verdict(line: str, tmp_path: Path) -> tuple[int, bool, bool, bool]:
    project, runtime = tmp_path / "proj", tmp_path / "runtime"
    own = copies.folders(runtime)[0] / "a" / "tree"
    card = commands.copy_reason(
        line, True, str(project), runtime, own, ".", [str(project), str(tmp_path / "wt" / "x")]
    )
    return (
        RANK[commands.harm_class(line)],
        bool(card),
        bool(commands.installs(line)),
        bool(commands.web_off_reason(line, ["http_request"])),
    )


def test_no_command_is_asked_less_than_650e22a_asked_it(tmp_path, monkeypatch):
    # (conftest puts the user's data folder at <tmp>/user-data: `%LOCALAPPDATA%` names it)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "user-data"))
    values = tokens(tmp_path)
    below = []
    for template, harm, card, install, win32, web in GATE["lines"]:
        if win32 and sys.platform != "win32" or template in GATE["allow"]:
            continue
        line = re.sub(r"<[a-z_]+(?:\|[a-z]+)?>", lambda m: values.get(m[0], m[0]), template)
        harm = max(harm, 1) if template in GATE["up"] else harm  # (meant to go up: harm at least)
        now = verdict(line, tmp_path)
        if now[0] < harm or card and not now[1] or install and not now[2] or web and not now[3]:
            below.append(template)
    xfail = set(GATE["xfail"])
    regressed = [line for line in below if line not in xfail]
    fixed = [
        line
        for line in GATE["xfail"]
        if line not in below
        and (sys.platform == "win32" or not next(row[4] for row in GATE["lines"] if row[0] == line))
    ]
    assert not regressed, "asked less than at 650e22a:\n" + "\n".join(regressed)
    assert not fixed, "asked again - take them out of command_gate.json's xfail:\n" + "\n".join(
        fixed
    )


def test_the_gate_holds_its_lines_once_and_every_allowed_line_has_a_reason():
    names = [row[0] for row in GATE["lines"]]
    assert len(names) == len(set(names))
    assert set(GATE["allow"]) <= set(names) and set(GATE["xfail"]) <= set(names)
    assert set(GATE["up"]) <= set(names) and not set(GATE["up"]) & set(GATE["allow"])
    assert set(GATE["shared"]) <= set(names) and not set(GATE["shared"]) & set(GATE["allow"])
    assert set(GATE["unruled"]) <= set(names) and not set(GATE["unruled"]) & set(GATE["allow"])
    assert set(GATE["ruled"]) <= set(names) and not set(GATE["ruled"]) & set(GATE["unruled"])
    assert all(reason.strip() for reason in GATE["allow"].values())


def test_in_a_branchs_worktree_every_shared_line_is_asked():
    # (k-okuyucu-3: `verdict` reads a copy's card; a branch's worktree asks `reaches_shared_git`
    # too - a write to a place built at run time may be the user's own repository)
    missing = [line for line in GATE["shared"] if not commands.reaches_shared_git(line, "koloni/x")]
    assert not missing, "\n".join(missing)


def test_no_rule_covers_an_unruled_line():
    # (k-okuyucu-3 round 3: a shell or a program a runner is handed - `poetry run cmd /c ...` - is
    # never covered by the runner's rule, its program spelt by a path too)
    covered = [line for line, rule in GATE["unruled"].items() if commands.matches(line, rule)]
    assert not covered, "\n".join(covered)


def test_a_ruled_line_is_still_covered_and_runs_no_other_program():
    # (k-okuyucu-3 round 4: a runner's program's own words are no program - `uv run ruff format .`
    # is ruff's, covered by `uv run ruff` and no harm; nor does it run another program)
    asked = [
        line
        for line, rule in GATE["ruled"].items()
        if not commands.matches(line, rule)
        or commands.harm_class(line)
        or commands.runs_another(line)
    ]
    assert not asked, "\n".join(asked)


def test_every_line_is_read_as_written_too():
    # (k-okuyucu-2: a stripped, joined or normalised reading may only add - never stand in for
    # the line as written: a data heredoc's body once cut the commands after it)
    missing = [row[0] for row in GATE["lines"] if row[0] not in commands._readings(row[0])]
    assert not missing, "\n".join(missing[:20])


def _link_out(link: Path, target: Path) -> None:
    """A folder link in the project leading out of it: a junction on Windows (no developer mode
    needed), a symlink elsewhere; skipped where neither can be made."""
    import subprocess

    import pytest

    try:
        if sys.platform == "win32":
            subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), str(target)],
                check=True,
                capture_output=True,
            )
        else:
            os.symlink(target, link, target_is_directory=True)
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("no folder link can be made here")


def test_a_read_through_a_link_out_of_the_project_is_no_plain_read(tmp_path):
    # (k-okuma-yol: `read_file` refuses `out/data.txt` - "outside the project folder" - and
    # this read of it ran unasked below Full auto; a planted link, or a repository's symlink)
    project, outside = tmp_path / "proj", tmp_path / "outside"
    project.mkdir()
    outside.mkdir()
    (outside / "data.txt").write_text("s", encoding="utf-8")
    (project / "a.py").write_text("x = 1\n", encoding="utf-8")
    (project / "notes").mkdir()
    _link_out(project / "out", outside)
    asked = ["cat out/data.txt", "head -n 5 out/data.txt", "ls out", "cat out"]
    if sys.platform == "win32":
        asked += [r"type out\data.txt", r"gc -Path:out\data.txt", "Get-Content out/data.txt"]
    for line in asked:
        assert commands.only_reads(line), line  # (by its words alone, a plain read)
        assert not commands.reads_here(line, project, True), line
    # (from a folder below, `..` reads stay what `only_reads` says; the link is still followed)
    assert not commands.reads_here("cat data.txt", project, False, "out")
    for line in ["cat a.py", "ls .", "ls notes", "cat missing.txt", "head -n 5 a.py"]:
        assert commands.reads_here(line, project, True), line


def test_a_file_named_secret_is_no_plain_read():
    # (k-duzelt-away's review: secret.txt and secrets.txt are secrets' names - asked at every level)
    for line in ["cat secret.txt", "cat secrets.txt", "head -n 5 out/secret.txt"]:
        assert commands.names_secret(line) and not commands.only_reads(line), line


def test_a_link_to_a_secret_in_the_project_is_no_plain_read(tmp_path):
    project = tmp_path / "proj"
    (project / "keys").mkdir(parents=True)
    (project / ".env").write_text("TOKEN=x\n", encoding="utf-8")
    _link_out(project / "shown", project / "keys")
    (project / "keys" / "id_rsa").write_text("k", encoding="utf-8")
    assert not commands.reads_here("cat shown/id_rsa", project, True)


def test_every_quiet_read_of_the_gate_stays_quiet_in_a_plain_project(tmp_path, monkeypatch):
    # (following paths must not ask more: each gate line that only reads still runs unasked in
    # a project with no link and no secret)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "user-data"))
    values = tokens(tmp_path)
    project = tmp_path / "proj"
    project.mkdir(exist_ok=True)
    (project / "a.py").write_text("x = 1\n", encoding="utf-8")
    louder = []
    for template, *_rest in GATE["lines"]:
        line = re.sub(r"<[a-z_]+(?:\|[a-z]+)?>", lambda m: values.get(m[0], m[0]), template)
        if commands.only_reads(line) and not commands.reads_here(line, project, True):
            louder.append(line)
    assert not louder, "asked now, read unasked before:\n" + "\n".join(louder)


def test_quotes_inside_a_word_and_option_values_are_followed_too(tmp_path):
    # (Review of k-okuma-yol: pwsh and sh join quoted pieces of one word - `.e'nv'` is `.env` -
    # and an option's value names a file - `--file=x`, `-Path:'x'` - yet both ran unasked.)
    project, outside = tmp_path / "proj", tmp_path / "outside"
    project.mkdir()
    outside.mkdir()
    (outside / "data.txt").write_text("s", encoding="utf-8")
    (project / "README.md").write_text("hi\n", encoding="utf-8")
    (project / ".env").write_text("KEY=1\n", encoding="utf-8")
    _link_out(project / "out", outside)
    asked = [
        "Get-Content -Path:'out/data.txt'",
        "Get-Content -LiteralPath:'out/data.txt'",
        "cat out/'data.txt'",
        "grep --file=out/data.txt README.md",
        "cat .e'nv'",
        'cat ".e"nv',
        "grep -fout/data.txt README.md",
    ]
    if sys.platform == "win32":
        asked += [r'Get-Content -Path:"out\data.txt"', r"type .\.e'nv'"]
    for line in asked:
        assert not commands.reads_here(line, project, True), line
    # (the project's own .env by a quoted name is a secret's name: asked at every level)
    for line in ["cat .e'nv'", 'cat ".e"nv', r"type .\.e'nv'"]:
        assert commands.names_secret(line), line
    # (the plain forms that held still hold)
    for line in [
        "cat README.md",
        "cat 'README.md'",
        "Get-Content -Path:'README.md'",
        "grep --file=README.md README.md",
        "head -n 5 README.md",
    ]:
        assert commands.reads_here(line, project, True), line


def test_a_reads_backslash_escapes_are_followed_as_sh_reads_them(tmp_path):
    # (review of k-okuma-yol: in sh `ou\t` is `out` and `.e\nv` is `.env` - a CLI's Bash tool,
    # Git Bash on Windows too; both spellings are followed everywhere, one that is no file passes)
    project = tmp_path / "proj"
    (project / "src").mkdir(parents=True)
    (project / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (project / ".env").write_text("TOKEN=x\n", encoding="utf-8")
    assert commands.names_secret(r"cat .e\nv")
    assert not commands.reads_here(r"cat .e\nv", project, True)
    for line in [r"type src\a.py", "cat src/a.py"]:  # (pwsh's separator still a plain read)
        assert commands.reads_here(line, project, True), line
        assert not commands.names_secret(line), line


def test_an_escaped_name_through_a_link_out_of_the_project_is_no_plain_read(tmp_path):
    project, outside = tmp_path / "proj", tmp_path / "outside"
    project.mkdir()
    outside.mkdir()
    (outside / "data.txt").write_text("s", encoding="utf-8")
    _link_out(project / "out", outside)
    assert commands.only_reads(r"cat ou\t/data.txt")  # (by its words, a plain read)
    assert not commands.reads_here(r"cat ou\t/data.txt", project, True)
