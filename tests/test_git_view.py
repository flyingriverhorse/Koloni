"""Slice 70: the project's git, read only - the top bar's status, the map's branches and
worktrees, a turn's branch switch said in the chat, and what a CLI reports with report_git
held against what git shows. Every repository here is made by the test, in its own folder."""

import contextlib
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from app import git
from app.agent import git_prompt
from tests.conftest import Gate
from tests.test_chat_flow import text
from tests.test_spawn import call, step
from tests.test_take_in_scenarios import ORIGIN, needs_git, repository

pytestmark = needs_git


def run(folder, *args):
    done = subprocess.run(["git", *args], cwd=folder, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    # (Nothing of the user's own git settings - a signing key, a hook - in these commits.)
    empty = tmp_path / "gitconfig"
    empty.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    folder = tmp_path / "repo"
    folder.mkdir()
    (folder / "a.txt").write_text("a\n")
    repository(folder)
    return folder


def commit(folder, name):
    (folder / name).write_text(name)
    run(folder, "add", name)
    run(folder, "commit", "-q", "-m", name)


def test_status_says_the_branch_and_how_many_files_are_not_committed(repo):
    seen = git.look(repo)
    assert (seen["branch"], seen["changed"], seen["branches"]) == ("main", 0, [])
    assert seen["worktrees"] == [{"path": seen["worktrees"][0]["path"], "branch": "main",
                                  "here": True}]
    (repo / "a.txt").write_text("changed\n")
    (repo / "new.txt").write_text("new\n")
    assert git.look(repo)["changed"] == 2


def test_other_branches_are_ahead_behind_and_joined_or_not(repo):
    run(repo, "switch", "-q", "-c", "fix-login")
    commit(repo, "one")
    commit(repo, "two")
    run(repo, "switch", "-q", "main")
    run(repo, "branch", "docs")  # nothing of its own: it is in main already
    commit(repo, "three")
    branches = {one["name"]: one for one in git.look(repo)["branches"]}
    assert (branches["fix-login"]["ahead"], branches["fix-login"]["behind"]) == (2, 1)
    assert branches["fix-login"]["joined"] is False
    assert (branches["docs"]["ahead"], branches["docs"]["behind"], branches["docs"]["joined"]) \
        == (0, 1, True)
    assert branches["docs"]["last_at"]


def test_branches_say_their_last_commit_and_remote_tracking_ones_are_listed_too(repo):
    # K-dallar: as last fetched - nothing is fetched; origin/HEAD only points at another.
    run(repo, "switch", "-q", "-c", "feature")
    commit(repo, "feature work")
    run(repo, "update-ref", "refs/remotes/origin/feature", "HEAD")
    run(repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/feature")
    run(repo, "switch", "-q", "main")
    seen = git.look(repo)
    branches = {one["ref"]: one for one in seen["branches"]}
    assert sorted(branches) == ["refs/heads/feature", "refs/remotes/origin/feature"]
    remote = branches["refs/remotes/origin/feature"]
    assert (remote["name"], remote["remote"], remote["ahead"], remote["subject"]) == (
        "origin/feature", True, 1, "feature work")
    assert remote["sha"] == run(repo, "rev-parse", "--short", "feature")
    assert branches["refs/heads/feature"]["remote"] is False
    assert (seen["current"]["name"], seen["current"]["subject"]) == ("main", "as it was")


def test_a_worktree_is_listed_with_its_branch(repo, tmp_path):
    run(repo, "worktree", "add", "-q", "-b", "side", str(tmp_path / "side"))
    seen = git.look(repo)
    assert [(one["branch"], one["here"]) for one in seen["worktrees"]] == [
        ("main", True), ("side", False)]
    assert os.path.samefile(seen["branches"][0]["worktree"], tmp_path / "side")


def test_a_branch_name_is_never_taken_for_an_option(repo, tmp_path):
    # git refuses such a name itself; one an agent wrote by hand is compared as a ref.
    run(repo, "update-ref", "refs/heads/--output=x", "HEAD")
    names = [one["name"] for one in git.look(repo)["branches"]]
    assert "--output=x" in names
    assert not (repo / "x").exists()


def test_a_folder_that_is_no_repository_shows_no_git(tmp_path, repo):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert git.look(plain) is None and git.where(plain) is None
    inside = repo / "sub"
    inside.mkdir()
    assert git.look(inside) is None  # (a subfolder of one: shortcut, no git shown)


@pytest.mark.parametrize("finds_it", [True, False])
def test_git_that_does_not_answer_in_time_shows_no_git(repo, tmp_path, monkeypatch, finds_it):
    # A stand-in for git that hangs - at once, or once it has said where the repository is.
    where = tmp_path / "slow"
    where.mkdir()
    top, folder = run(repo, "rev-parse", "--show-toplevel"), run(repo, "rev-parse",
                                                                  "--absolute-git-dir")
    (where / "git.py").write_text(
        "import sys, time\n"
        f"if {finds_it} and 'rev-parse' in sys.argv: print({top!r}); print({folder!r}); "
        "sys.exit(0)\n"
        "time.sleep(30)\n", encoding="utf-8")
    if sys.platform == "win32":
        program = where / "git.cmd"
        program.write_text(f'@"{sys.executable}" "{where / "git.py"}" %*\r\n')
    else:
        program = where / "git"
        program.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{where / "git.py"}" "$@"\n')
        program.chmod(0o755)
    monkeypatch.setattr(git, "find", lambda: str(program))
    monkeypatch.setattr(git, "LOOK_SECONDS", 1.0)
    began = time.monotonic()
    assert git.look(repo) is None and git.where(repo) is None
    assert time.monotonic() - began < 10  # (each of the two stopped at its limit, not at 15 s)


# --- a turn's start and end ----------------------------------------------------------------

BEFORE = {"branch": "main", "head": "h1", "names": ["main"],
          "worktrees": [{"path": "/p", "branch": "main"}]}


def test_a_branch_switch_is_said_with_the_cli_and_not_reported(tmp_path):
    after = {**BEFORE, "branch": "fix-login", "names": ["main", "fix-login"]}
    assert git.turn_note(tmp_path, BEFORE, after, "Codex", []) == (
        "Codex switched the project to branch fix-login during this turn (it was on main). "
        "Not reported.")
    # Several CLIs, or none: nobody is named.
    said = [("Coder", {"branch": "fix-login", "why": "asked"})]
    assert git.turn_note(tmp_path, BEFORE, after, None, said) == (
        "The project was switched to branch fix-login during this turn (it was on main).")


def test_a_new_worktree_is_said_and_what_was_said_but_not_seen(tmp_path):
    after = {**BEFORE, "worktrees": [*BEFORE["worktrees"],
                                     {"path": str(tmp_path / "wt"), "branch": "side"}]}
    said = [("Coder", {"branch": "nowhere", "commits": 2, "why": "x"}),
            ("Coder", {"commits": 1, "why": "y"})]
    # (Commits said of another branch are not looked for: its HEAD is not the project's.)
    assert git.turn_note(tmp_path, BEFORE, after, "Codex", said).splitlines() == [
        f"Codex opened a worktree at {tmp_path / 'wt'} on branch side during this turn. "
        "Not reported.",
        "Coder said branch nowhere: said, not seen in git.",
        "Coder said 1 commits: said, not seen in git.",
    ]
    assert git.turn_note(tmp_path, BEFORE, BEFORE, "Codex", []) is None


def test_the_git_section_of_a_clis_instructions():
    said = git_prompt("main", in_copy=True, reports=True)
    assert "on branch “main”" in said or "on branch \"main\"" in said
    assert "Don't switch branches, open worktrees, commit or merge - KOLONİ does that" in said
    assert "ask the user first, and say why and which branch it should be merged into" in said
    assert "a copy of it, which is not a git repository" in said
    assert "report_git" in said
    assert "report_git" not in git_prompt("", in_copy=False, reports=False)
    assert "no branch" in git_prompt("", in_copy=False, reports=False)


def test_a_turn_that_switches_the_branch_is_said_in_the_chat_with_what_the_cli_said(
    make_client, wait_run, repo
):
    held = Gate()
    client, model = make_client([
        step(call("report_git", {"branch": "gone", "merge_into": "main", "why": "a fix"}, "r")),
        held.step(text("done")),
        text("again"),
    ])
    model.command = "claude"  # (taken for a CLI: what it is told, and offered)
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(repo)}).json()["id"]
    assert client.get(f"/api/projects/{pid}/git").json()["branch"] == "main"
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    run_id = client.post(f"/api/conversations/{cid}/messages",
                         json={"content": "go"}).json()["run"]["id"]
    held.wait_partial()
    run(repo, "switch", "-q", "-c", "fix-login")  # (as a CLI's own command would)
    held.release()
    wait_run(client, cid, run_id)
    # (Said once the turn is over: looked for till it is.)
    deadline = time.monotonic() + 10
    while True:
        snap = client.get(f"/api/conversations/{cid}").json()
        if any(m["role"] == "git" for m in snap["messages"]):
            break
        assert time.monotonic() < deadline, "no git line"
        time.sleep(0.05)
    system = model.calls[0][0]["content"]
    assert "Git: the project is a git repository, on branch" in system
    assert "report_git" in system
    assert any(one["function"]["name"] == "report_git" for one in model.tool_args[0])
    said = [m["content"] for m in snap["messages"] if m["role"] == "git"]
    # The one CLI of the turn is named by its provider (as "Codex switched ...").
    assert said == ["Local switched the project to branch fix-login during this turn (it was "
                    "on main). Not reported.\nLead said branch gone: said, not seen in git."]
    # The map shows what was said, and that git does not.
    seen = client.get(f"/api/projects/{pid}/git").json()
    assert seen["branch"] == "fix-login"
    assert [(r["agent"], r["branch"], r["merge_into"], r["seen"]) for r in seen["reports"]] == [
        ("Lead", "gone", "main", False)]
    # No agent is given KOLONİ's line: the next turn's Lead does not see it.
    run_id = client.post(f"/api/conversations/{cid}/messages",
                         json={"content": "and?"}).json()["run"]["id"]
    wait_run(client, cid, run_id)
    assert "switched the project" not in str(model.calls[-1])


# --- a working copy as its work goes on -----------------------------------------------------


def test_a_working_copy_says_what_it_changed_so_far_once_per_file(
    make_client, wait_run, project_dir, monkeypatch
):
    from app.api import agents as agents_api
    from tests.test_take_in_scenarios import edit, start

    held = Gate()
    client, pid, cid, run_id = start(make_client, project_dir, [
        step(edit("two", "TWO", "e1")), step(edit("TWO", "TWO again", "e2")),
        held.step(text("done"))])
    held.wait_partial()
    coder = next(a for a in client.get(f"/api/conversations/{cid}").json()["agents"]
                 if a["name"] == "Coder")
    copy = client.get(f"/api/agents/{coder['id']}/copy").json()
    # Two edits of one file: one file, from what it held to what it holds now.
    assert [(f["path"], f["kind"], f["additions"], f["deletions"]) for f in copy["files"]] == [
        ("lines.txt", "modify", 1, 1)]
    assert "+TWO again" in copy["files"][0]["diff"]
    assert copy["agent_id"] == coder["id"] and os.path.isdir(copy["folder"])
    board = client.get(f"/api/projects/{pid}/board").json()
    row = next(a for c in board["conversations"] for a in c["agents"] if a["name"] == "Coder")
    assert row["changed"] == {"files": 1, "additions": 1, "deletions": 1}
    # Open folder: the copy's own folder, never one a request names; only from the app's page.
    opened = []
    monkeypatch.setattr(agents_api, "open_folder", opened.append)
    assert client.post(f"/api/agents/{coder['id']}/copy/open",
                       headers={"Origin": "http://evil.example"}).status_code == 403
    assert client.post(f"/api/agents/{coder['id']}/copy/open").status_code == 204
    assert [str(one) for one in opened] == [copy["folder"]]
    lead = next(a for a in client.get(f"/api/conversations/{cid}").json()["agents"]
                if a["name"] == "Lead")
    assert client.get(f"/api/agents/{lead['id']}/copy").status_code == 404
    held.release()
    wait_run(client, cid, run_id)


# --- the fix round: a look at git runs nothing of the repository's -----------------------


def marker(tmp_path: Path, name: str, passes: bool = True) -> tuple[Path, str]:
    """A program that leaves a mark when it runs and passes its input through (`passes`;
    else it ends at once): the mark, and the program as a command line (forward slashes:
    git's shell and Windows both)."""
    mark, script = tmp_path / f"ran-{name}", tmp_path / f"mark-{name}.py"
    script.write_text("import pathlib, sys\npathlib.Path(sys.argv[1]).write_text('x')\n"
                      + ("sys.stdout.write(sys.stdin.read())\n" if passes else ""),
                      encoding="utf-8")
    line = f'"{Path(sys.executable).as_posix()}" "{script.as_posix()}" "{mark.as_posix()}"'
    return mark, line


def touched(path: Path) -> None:
    """The file as it was, but not to git's eye: its time moved on (stat-dirty)."""
    at = path.stat().st_mtime + 100
    os.utime(path, (at, at))


def test_no_filter_of_the_repositorys_runs_for_the_automatic_status_or_summary(repo, tmp_path):
    mark, line = marker(tmp_path, "filter")
    (repo / ".gitattributes").write_text("* filter=x\n")
    run(repo, "config", "filter.x.clean", line)
    run(repo, "config", "filter.x.required", "true")
    touched(repo / "a.txt")
    # (The repository is as the review found it: git's own status runs the filter.)
    run(repo, "status", "--porcelain")
    assert mark.exists()
    mark.unlink()
    touched(repo / "a.txt")
    assert git.look(repo)["changed"] >= 1  # (.gitattributes, not committed)
    assert git.where(repo) is not None
    assert not mark.exists()
    # Nor for what is said of a commit made of a Take in's files (`git show --stat`).
    touched(repo / "a.txt")
    git.summary(repo, "HEAD")
    assert not mark.exists()


def test_a_signed_commit_is_not_checked_by_the_look(repo, tmp_path):
    mark, line = marker(tmp_path, "gpg")
    checker = tmp_path / "gpg"
    checker.write_text(f"#!/bin/sh\n{line}\n", encoding="utf-8", newline="\n")
    checker.chmod(0o755)
    body = run(repo, "cat-file", "commit", "HEAD").split("\n")
    at = next(i for i, one in enumerate(body) if one.startswith("committer ")) + 1
    body[at:at] = ["gpgsig -----BEGIN PGP SIGNATURE-----", " ", " iQ==",
                   " -----END PGP SIGNATURE-----"]
    crafted = tmp_path / "commit.txt"
    crafted.write_text("\n".join(body) + "\n", encoding="utf-8", newline="\n")
    signed = run(repo, "hash-object", "-t", "commit", "-w", str(crafted))
    run(repo, "update-ref", "refs/heads/main", signed)
    run(repo, "config", "log.showSignature", "true")
    run(repo, "config", "gpg.program", checker.as_posix())
    # (As the review found it: git's own log runs the checker.)
    run(repo, "log", "-1", "--format=%H")
    assert mark.exists()
    mark.unlink()
    assert git.where(repo)["head"] == signed
    assert git.look(repo)["head"] == signed
    assert not mark.exists()


def test_branches_are_listed_as_names_whatever_the_head_tags_or_columns(repo):
    run(repo, "branch", "side")
    run(repo, "tag", "main")  # (a tag of a branch's name: no "heads/main")
    run(repo, "config", "column.ui", "always")
    seen = git.look(repo)
    assert sorted(seen["names"]) == ["main", "side"]
    assert [one["name"] for one in seen["branches"]] == ["side"]
    run(repo, "checkout", "-q", "--detach")
    seen = git.look(repo)
    assert seen["branch"] == "" and sorted(seen["names"]) == ["main", "side"]
    assert sorted(one["name"] for one in seen["branches"]) == ["main", "side"]


def test_a_network_or_outside_worktree_is_refused_and_no_agent_path_is_opened(
    repo, tmp_path, monkeypatch
):
    for far in ("\\\\attacker\\share", "//attacker/share", str(tmp_path / "elsewhere")):
        with pytest.raises(ValueError, match="network path or another place"):
            git.reported({"worktree": far, "why": "x"}, repo)
    assert git.reported({"worktree": "../wt", "commits": True, "why": " x "}, repo) == {
        "worktree": "../wt", "why": "x"}  # (a bool is no number of commits)
    assert git.reported({"worktree": str(repo / "inner"), "why": "x"}, repo)["worktree"]
    real = os.path.realpath

    def guarded(path, *args, **kwargs):
        assert "attacker" not in str(path), "an agent's path was opened"
        return real(path, *args, **kwargs)

    monkeypatch.setattr(os.path, "realpath", guarded)
    seen = git.where(repo)
    said = [("Coder", {"worktree": "\\\\attacker\\share", "why": "x"})]
    assert "said, not seen in git" in git.turn_note(repo, seen, seen, None, said)


@pytest.mark.parametrize("limit", [100.0, 5.0])
def test_one_time_limit_for_the_whole_look(repo, monkeypatch, limit):
    # A clock of the test's own, and a git that answers as git would, each call taking one
    # second of that clock: nothing here depends on how busy the machine is.
    now, given = [0.0], []
    answers = {
        "--show-toplevel": f"{repo}\n{repo / '.git'}\n", "--show-current": "main\n",
        "worktree": f"worktree {repo}\nbranch refs/heads/main\n",
        git.REFS[2]: "refs/heads/main\t\taaa\t2026-10-27T10:00:00+00:00\tone\n"
                     "refs/heads/side\t\tbbb\t2026-10-26T10:00:00+00:00\ttwo\n",
        "--sort=-committerdate": "main\t2026-10-27T10:00:00+00:00\nside\t2026-10-26T10:00:00+00:00\n",
        "--verify": "a" * 40 + "\n", "status": "", "--merged=HEAD": "refs/heads/main\n",
        "rev-list": "0\t1\n",
    }

    def answered(project, program, *args, seconds=git.SHORT_SECONDS, **more):
        given.append(seconds)
        now[0] += 1.0
        said = next((out for key, out in answers.items() if key in args), None)
        return (1, b"", b"") if said is None else (0, said.encode(), b"")

    monkeypatch.setattr(git.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(git, "_in", answered)
    monkeypatch.setattr(git, "LOOK_SECONDS", limit)
    seen = git.look(repo)
    if limit == 100.0:
        assert seen["branches"][0]["name"] == "side"
        # Each call is given what is left of the one limit, not a limit of its own.
        assert given == [limit - n for n in range(len(given))]
    else:
        # Five calls spend the five seconds: the look gives up, and shows no git.
        assert seen is None and len(given) == 5


def start_two(make_client, repo, steps):
    client, model = make_client(steps)
    model.command = "claude"  # (a CLI: the turn's git is looked at)
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(repo)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    runs = [client.post(f"/api/conversations/{cid}/messages",
                        json={"content": word}).json()["run"]["id"] for word in ("one", "two")]
    return client, cid, runs


@pytest.mark.parametrize("held_at", [1, 2])
def test_stop_while_git_is_looked_at_ends_the_turn_and_the_next_one_starts(
    make_client, wait_run, repo, monkeypatch, held_at
):
    entered, release, seen = threading.Event(), threading.Event(), []
    real = git.where

    def where(project):
        seen.append(project)
        if len(seen) == held_at:  # 1: as the turn starts; 2: at its end
            entered.set()
            release.wait(10)
        return real(project)

    monkeypatch.setattr(git, "where", where)
    client, cid, (first, second) = start_two(make_client, repo, [text("first"), text("second")])
    try:
        assert entered.wait(10)
        client.post(f"/api/runs/{first}/cancel")
        ended = wait_run(client, cid, first)
        status = next(r for r in ended["runs"] if r["id"] == first)["status"]
        # At its start Stop stops it; at its end the turn is over already, as it was.
        assert status == ("cancelled" if held_at == 1 else "completed")
    finally:
        release.set()
    snap = wait_run(client, cid, second)
    assert next(r for r in snap["runs"] if r["id"] == second)["status"] == "completed"


# --- the second fix round: no driver name, index hook or lazy fetch runs anything ------------


def test_a_filter_whose_name_holds_an_equals_sign_does_not_run_either(repo, tmp_path):
    mark, line = marker(tmp_path, "equals")
    commit(repo, "b.txt")
    included = tmp_path / "included.cfg"
    run(repo, "config", "-f", str(included), "filter.a=b.clean", line)
    run(repo, "config", "include.path", included.as_posix())
    (repo / ".git" / "info").mkdir(exist_ok=True)
    (repo / ".git" / "info" / "attributes").write_text("b.txt filter=a=b\n")
    touched(repo / "b.txt")
    run(repo, "status", "--porcelain")  # (git's own status runs it)
    assert mark.exists()
    mark.unlink()
    touched(repo / "b.txt")
    assert git.look(repo) is not None
    touched(repo / "b.txt")
    git.summary(repo, "HEAD")
    assert not mark.exists()


def test_the_summary_writes_no_index_and_so_fires_no_hook(repo, tmp_path):
    mark, line = marker(tmp_path, "hook", passes=False)
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    hook = hooks / "post-index-change"
    hook.write_text(f"#!/bin/sh\n{line}\n", encoding="utf-8", newline="\n")
    hook.chmod(0o755)
    run(repo, "config", "core.hooksPath", hooks.as_posix())
    touched(repo / "a.txt")
    run(repo, "diff", "HEAD", "--stat")  # (git's own diff writes the index, and the hook runs)
    assert mark.exists()
    mark.unlink()
    touched(repo / "a.txt")
    index = repo / ".git" / "index"
    was = index.read_bytes()
    git.summary(repo, "HEAD")
    assert not mark.exists() and index.read_bytes() == was
    (repo / "a.txt").write_text("changed\n")
    assert "a.txt" in git.summary(repo, "HEAD")  # (what the commit holds is still said)
    assert not mark.exists() and index.read_bytes() == was


@pytest.mark.parametrize("missing", ["ref", "tree"])
def test_a_partial_clone_fetches_nothing_for_a_look(repo, tmp_path, missing):
    mark, line = marker(tmp_path, "fetch", passes=False)
    for key, value in (("core.repositoryformatversion", "1"),
                       ("extensions.partialClone", "origin"), ("remote.origin.promisor", "true"),
                       ("remote.origin.url", (tmp_path / "origin").as_uri()),
                       ("remote.origin.uploadpack", line)):
        run(repo, "config", key, value)
    if missing == "ref":  # a branch whose commit is not here
        (repo / ".git" / "refs" / "heads" / "ghost").write_text("1234567890" * 4 + "\n")
        own = ["for-each-ref", "--sort=-committerdate", "refs/heads/"]
    else:  # HEAD's tree is not here
        tree = run(repo, "rev-parse", "HEAD^{tree}")
        loose = repo / ".git" / "objects" / tree[:2] / tree[2:]
        loose.chmod(0o644)  # (git keeps its objects read only)
        loose.unlink()
        own = ["status", "--porcelain"]
    subprocess.run(["git", *own], cwd=repo, capture_output=True, timeout=30)
    assert mark.exists()  # (git's own command fetches it, and runs the upload-pack named)
    mark.unlink()
    git.where(repo)
    git.look(repo)
    with contextlib.suppress(git.Refused):
        git.summary(repo, "HEAD")
    assert not mark.exists()
