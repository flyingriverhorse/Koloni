"""K-koordinasyon's command gate (review round 3): what a command is asked may only go up.

Round 2 cured over-asks by narrowing what recognised a harm, and each narrow recogniser failed
open where it missed: commands 650e22a asked about ran with no card. `command_gate.json` holds
each line's verdict as 650e22a gave it - the reviewers' probe lines, the briefs' lines and the
command tests' strings - and HEAD must give at least that: `harm_class` (none < soft < always),
a card from `copy_reason` in a copy with links, `installs()`, `web_off_reason` with
http_request off (review round 4). A line meant to go down (an
over-ask cured) is in its `allow`, with why; a known regression still open, in its `xfail`; a
line meant to go up (a hole 650e22a had too: a continued line) in its `up` - harm at least. A line
a branch's worktree must ask (k-okuyucu-3: a write to a place built at run time) is in `shared`."""

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
    forms = {"": path, "|dbl": path.replace("\\", "\\\\"), "|fwd": path.replace("\\", "/"),
             "|up": path.upper(), "|low": path.lower()}
    if re.match(r"[A-Za-z]:", path):
        forms["|bash"] = f"/{path[0].lower()}{path[2:]}".replace("\\", "/")
    return forms


def tokens(tmp_path: Path) -> dict[str, str]:
    """The gate's `<x>` paths, made in this test's folder as the probes laid them out."""
    runtime = tmp_path / "runtime"
    held, users = copies.folders(runtime)[0], copies._both(runtime)[1]
    bases = {"uown": users / "a" / "tree", "users": users, "own": held / "a" / "tree",
             "held": held, "worktree": tmp_path / "wt" / "x", "project": tmp_path / "proj",
             "runtime": runtime, "tmp": tmp_path}
    found = {f"<{name}{suffix}>": form for name, path in bases.items()
             for suffix, form in spellings(str(path)).items()}
    local = os.environ["LOCALAPPDATA"]
    rel = str(users)[len(local):]
    return {**found, "<la_rel>": rel, "<la_rel|fwd>": rel.replace("\\", "/"), "<la>": local}


def verdict(line: str, tmp_path: Path) -> tuple[int, bool, bool, bool]:
    project, runtime = tmp_path / "proj", tmp_path / "runtime"
    own = copies.folders(runtime)[0] / "a" / "tree"
    card = commands.copy_reason(line, True, str(project), runtime, own, ".",
                                [str(project), str(tmp_path / "wt" / "x")])
    return (RANK[commands.harm_class(line)], bool(card), bool(commands.installs(line)),
            bool(commands.web_off_reason(line, ["http_request"])))


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
    fixed = [line for line in GATE["xfail"] if line not in below and (
        sys.platform == "win32" or not next(row[4] for row in GATE["lines"] if row[0] == line))]
    assert not regressed, "asked less than at 650e22a:\n" + "\n".join(regressed)
    assert not fixed, "asked again - take them out of command_gate.json's xfail:\n" + "\n".join(
        fixed)


def test_the_gate_holds_its_lines_once_and_every_allowed_line_has_a_reason():
    names = [row[0] for row in GATE["lines"]]
    assert len(names) == len(set(names))
    assert set(GATE["allow"]) <= set(names) and set(GATE["xfail"]) <= set(names)
    assert set(GATE["up"]) <= set(names) and not set(GATE["up"]) & set(GATE["allow"])
    assert set(GATE["shared"]) <= set(names) and not set(GATE["shared"]) & set(GATE["allow"])
    assert all(reason.strip() for reason in GATE["allow"].values())


def test_in_a_branchs_worktree_every_shared_line_is_asked():
    # (k-okuyucu-3: `verdict` reads a copy's card; a branch's worktree asks `reaches_shared_git`
    # too - a write to a place built at run time may be the user's own repository)
    missing = [line for line in GATE["shared"] if not commands.reaches_shared_git(line, "koloni/x")]
    assert not missing, "\n".join(missing)


def test_every_line_is_read_as_written_too():
    # (k-okuyucu-2: a stripped, joined or normalised reading may only add - never stand in for
    # the line as written: a data heredoc's body once cut the commands after it)
    missing = [row[0] for row in GATE["lines"] if row[0] not in commands.readings(row[0])]
    assert not missing, "\n".join(missing[:20])
