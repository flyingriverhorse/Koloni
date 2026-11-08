"""The commit of what was taken from an agent holds the agent's change alone: the user's own
uncommitted edits in the same files stay in the working tree, and what they staged of other
files stays staged. What does not go in so is said, a sentence each, for the card. Real git,
in a repository the test makes."""

import os
import subprocess
import time
from pathlib import Path

import pytest

from app import git
from app.agent import _held, prune_commit_sides
from tests.test_take_in_scenarios import git as in_repo
from tests.test_take_in_scenarios import needs_git, repository

pytestmark = needs_git
LINES = "".join(f"line {n}\n" for n in range(1, 61))
WHOLE = "{} went in whole, as the project has it: any edits of your own there went into this " \
        "commit too"


def lines(**changed):
    return "".join(f"{changed.get(f'l{n}', f'line {n}')}\n" for n in range(1, 61))


def bare(folder):
    """A repository with no commit yet."""
    in_repo(folder, "init", "-q", "-b", "main")
    for key, value in (("user.email", "user@example.com"), ("user.name", "The User"),
                       ("commit.gpgsign", "false")):
        in_repo(folder, "config", key, value)


@pytest.fixture
def repo(tmp_path):
    project = tmp_path / "p"
    project.mkdir()
    (project / "a.txt").write_text(LINES, encoding="utf-8", newline="\n")
    (project / "b.txt").write_bytes(b"b\n")
    (project / "old.txt").write_bytes(b"old\n")
    (project / "pic.bin").write_bytes(b"\x00\x01\x02")
    (project / ".gitignore").write_bytes(b".env\n")
    repository(project)
    # (As Git for Windows sets it: the working tree's line ends are not the commit's.)
    in_repo(project, "config", "core.autocrlf", "true")
    return project


def taken(tmp_path, project, changes):
    """The agent's changes are taken in: each path's file as it was just before and just
    after, kept in a folder of KOLONİ's, and the project then holds the after."""
    kept = tmp_path / "kept"
    kept.mkdir(exist_ok=True)
    sides = {}
    for path, after in changes.items():
        before = (project / path).read_bytes() if (project / path).exists() else None
        pair = []
        for name, data in (("before", before), ("after", after)):
            if data is None:
                pair.append(None)
                continue
            (kept / f"{path.replace('/', '_')}.{name}").write_bytes(data)
            pair.append(kept / f"{path.replace('/', '_')}.{name}")
        sides[path] = tuple(pair)
        if after is None:
            (project / path).unlink()
        else:
            (project / path).parent.mkdir(parents=True, exist_ok=True)
            (project / path).write_bytes(after)
    return sides


def head(project, path):
    return in_repo(project, "show", f"HEAD:{path}")


def test_the_commit_holds_the_agents_line_and_the_users_own_stay_out(repo, tmp_path):
    (repo / "a.txt").write_text(lines(l1="USER"), encoding="utf-8", newline="\n")
    (repo / "b.txt").write_bytes(b"b staged\n")                 # the user's, staged
    in_repo(repo, "add", "b.txt")
    sides = taken(tmp_path, repo, {"a.txt": lines(l1="USER", l50="AGENT").encode()})
    sha, notes = git.commit(repo, ["a.txt"], "Coder: line 50", sides=sides)
    assert notes == [] and sha == in_repo(repo, "rev-parse", "HEAD")
    assert head(repo, "a.txt") + "\n" == lines(l50="AGENT")    # line 50 alone
    assert in_repo(repo, "show", "--stat", "--format=", "HEAD").startswith("a.txt")
    # line 1 is still the user's own, in the working tree; b.txt is still staged, not committed
    assert (repo / "a.txt").read_text(encoding="utf-8") == lines(l1="USER", l50="AGENT")
    unstaged = in_repo(repo, "diff", "--", "a.txt")
    assert "\n-line 1\n+USER\n" in unstaged and "AGENT" not in unstaged
    assert in_repo(repo, "diff", "--cached", "--name-only") == "b.txt"
    assert in_repo(repo, "diff", "--name-only") == "a.txt"
    assert head(repo, "b.txt") == "b"


def test_new_deleted_and_binary_files_go_in_as_the_agent_left_them(repo, tmp_path):
    sides = taken(tmp_path, repo, {
        "new.txt": b"new\n", "old.txt": None, "pic.bin": b"\x00\xff\x00"})
    sha, notes = git.commit(repo, ["new.txt", "old.txt", "pic.bin"], "Coder: files", sides=sides)
    assert notes == []
    assert head(repo, "new.txt") == "new"
    assert "old.txt" not in in_repo(repo, "ls-tree", "--name-only", "HEAD").split()
    assert in_repo(repo, "cat-file", "-s", "HEAD:pic.bin") == "3"
    assert (repo / "pic.bin").read_bytes() == b"\x00\xff\x00"
    assert in_repo(repo, "status", "--porcelain") == ""


@pytest.mark.skipif(os.name == "nt", reason="Windows keeps no such bit: a new file is 100644")
def test_a_new_file_the_agent_made_runnable_is_committed_so(repo, tmp_path):
    sides = taken(tmp_path, repo, {"run.sh": b"#!/bin/sh\n"})
    os.chmod(repo / "run.sh", 0o755)
    git.commit(repo, ["run.sh"], "Coder: a script", sides=sides)
    assert in_repo(repo, "ls-tree", "HEAD", "run.sh").startswith("100755 ")


def test_where_the_users_edit_and_the_agents_touch_the_same_lines_the_file_goes_in_whole(
    repo, tmp_path
):
    """And so does one of the user's that is not text, and one with nothing kept of it:
    each said by name, for the card."""
    (repo / "a.txt").write_text(lines(l50="USER"), encoding="utf-8", newline="\n")
    (repo / "pic.bin").write_bytes(b"\x00user")
    sides = taken(tmp_path, repo, {"a.txt": lines(l50="AGENT").encode(),
                                   "pic.bin": b"\x00agent", "b.txt": b"b agent\n"})
    del sides["b.txt"]
    sha, notes = git.commit(repo, ["a.txt", "b.txt", "pic.bin"], "Coder: all", sides=sides)
    assert notes == ["a.txt, b.txt, pic.bin went in whole, as the project has them: any edits "
                     "of your own there went into this commit too"]
    assert head(repo, "a.txt") + "\n" == lines(l50="AGENT")
    assert head(repo, "b.txt") == "b agent"
    assert in_repo(repo, "status", "--porcelain") == ""


def test_a_new_file_git_ignores_is_left_out_and_said(repo, tmp_path):
    """`git add` would refuse it; the index takes anything it is given."""
    sides = taken(tmp_path, repo, {".env": b"SECRET=1\n", "b.txt": b"b agent\n"})
    sha, notes = git.commit(repo, [".env", "b.txt"], "Coder: env", sides=sides)
    assert notes == [".env was left out of the commit: git ignores it"]
    assert in_repo(repo, "ls-tree", "--name-only", "HEAD").split() == [
        ".gitignore", "a.txt", "b.txt", "old.txt", "pic.bin"]
    # alone, there is nothing to commit - and that says why
    sides = taken(tmp_path, repo, {".env": b"SECRET=2\n"})
    with pytest.raises(git.Refused, match="nothing to commit.*.env was left out of the commit: "
                                          "git ignores it"):
        git.commit(repo, [".env"], "Coder: env", sides=sides)


def test_in_a_repository_with_no_commit_yet_an_ignored_file_is_left_out_too(tmp_path):
    project = tmp_path / "p"
    project.mkdir()
    bare(project)
    (project / ".gitignore").write_bytes(b".env\n")
    (project / ".env").write_bytes(b"SECRET=1\n")
    (project / "a.txt").write_bytes(b"A\n")
    (project / "b.txt").write_bytes(b"not this\n")
    sha, notes = git.commit(Path(project), [".env", "a.txt"], "first")
    assert notes == [WHOLE.format("a.txt"), ".env was left out of the commit: git ignores it"]
    assert in_repo(project, "ls-tree", "--name-only", "HEAD") == "a.txt"


def test_a_file_whose_change_was_taken_back_is_not_committed(repo, tmp_path):
    """The working tree no longer holds the agent's line: committing it would put into history
    what the user undid."""
    sides = taken(tmp_path, repo, {"a.txt": lines(l50="AGENT").encode(), "b.txt": b"b agent\n"})
    (repo / "a.txt").write_text(LINES, encoding="utf-8", newline="\n")     # taken back
    sha, notes = git.commit(repo, ["a.txt", "b.txt"], "Coder: both", sides=sides)
    assert notes == ["a.txt was left out of the commit: the agent's change is no longer in it "
                     "as the project has it"]
    assert head(repo, "a.txt") + "\n" == LINES and head(repo, "b.txt") == "b agent"
    # written over since, on its own lines: still the agent's - and the user's line stays out
    sides = taken(tmp_path, repo, {"a.txt": lines(l50="AGENT").encode()})
    (repo / "a.txt").write_text(lines(l2="USER", l50="AGENT"), encoding="utf-8", newline="\n")
    _sha, notes = git.commit(repo, ["a.txt"], "Coder: again", sides=sides)
    assert notes == [] and head(repo, "a.txt") + "\n" == lines(l50="AGENT")
    # alone, nothing is committed, and that says why
    sides = taken(tmp_path, repo, {"b.txt": b"b again\n"})
    (repo / "b.txt").write_bytes(b"b agent\n")
    with pytest.raises(git.Refused, match="nothing to commit.*no longer in it"):
        git.commit(repo, ["b.txt"], "Coder: b", sides=sides)


def test_a_file_with_staged_changes_the_working_tree_does_not_hold_is_left_out(repo, tmp_path):
    """Setting the index again would lose them."""
    sides = taken(tmp_path, repo, {"a.txt": lines(l50="AGENT").encode(), "b.txt": b"b agent\n"})
    (repo / "a.txt").write_text(lines(l1="STAGED", l50="AGENT"), encoding="utf-8", newline="\n")
    in_repo(repo, "add", "a.txt")
    (repo / "a.txt").write_text(lines(l1="LATER", l50="AGENT"), encoding="utf-8", newline="\n")
    sha, notes = git.commit(repo, ["a.txt", "b.txt"], "Coder: both", sides=sides)
    assert notes == ["a.txt was left out of the commit: you have changes staged in it that the "
                     "file in the project does not hold: commit or unstage them first"]
    assert head(repo, "a.txt") + "\n" == LINES and head(repo, "b.txt") == "b agent"
    assert "+STAGED" in in_repo(repo, "diff", "--cached", "--", "a.txt")      # still staged


def test_a_commit_hook_that_adds_the_users_files_is_named(repo, tmp_path):
    (repo / "b.txt").write_bytes(b"b the user's\n")
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_bytes(b"#!/bin/sh\ngit add -u\n")
    hook.chmod(0o755)
    sides = taken(tmp_path, repo, {"a.txt": lines(l50="AGENT").encode()})
    sha, notes = git.commit(repo, ["a.txt"], "Coder: line 50", sides=sides)
    assert notes == ["a commit hook changed what went in: b.txt"]
    assert head(repo, "b.txt") == "b the user's"
    assert in_repo(repo, "status", "--porcelain") == ""       # nor is it shown as taken back


def test_where_git_will_not_set_the_index_afterwards_the_card_says_what_to_run(repo, tmp_path):
    """The user's own git holds it: the commit stands, and the index is not left as if the
    agent's change were taken back without a word."""
    sides = taken(tmp_path, repo, {"a.txt": lines(l50="AGENT").encode()})
    lock = repo / ".git" / "index.lock"
    lock.write_bytes(b"")
    try:
        sha, notes = git.commit(repo, ["a.txt"], "Coder: line 50", sides=sides)
    finally:
        lock.unlink()
    assert sha == in_repo(repo, "rev-parse", "HEAD")
    assert notes == ["KOLONİ couldn't update git's index: run `git reset -- a.txt`"]


def test_a_file_whose_change_the_user_committed_already_is_nothing_to_commit(repo, tmp_path):
    sides = taken(tmp_path, repo, {"b.txt": b"b agent\n"})
    in_repo(repo, "commit", "-q", "-am", "by hand")
    stale = repo / ".git" / "koloni-index-left-over"
    stale.write_bytes(b"")
    os.utime(stale, (time.time() - 2 * git.STALE_SECONDS,) * 2)
    with pytest.raises(git.Refused, match="nothing to commit"):
        git.commit(repo, ["b.txt"], "take it", sides=sides)
    assert not [one for one in (repo / ".git").iterdir() if one.name.startswith("koloni-index")]


def test_the_first_commit_of_a_repository_takes_the_files_whole(tmp_path):
    project = tmp_path / "p"
    project.mkdir()
    bare(project)
    (project / "a.txt").write_bytes(b"A\n")
    (project / "b.txt").write_bytes(b"not this\n")
    sha, notes = git.commit(Path(project), ["a.txt"], "first")
    assert notes == [WHOLE.format("a.txt")]
    assert in_repo(project, "ls-tree", "--name-only", "HEAD") == "a.txt"


def test_a_crlf_file_in_a_subfolder_has_the_agents_line_alone_too(tmp_path):
    """As a project on Windows has it: line ends converted on the way in, a file below the top."""
    project = tmp_path / "p"
    (project / "src").mkdir(parents=True)
    bare(project)
    in_repo(project, "config", "core.autocrlf", "true")
    crlf = lambda **changed: lines(**changed).replace("\n", "\r\n").encode()  # noqa: E731
    (project / "src" / "a.txt").write_bytes(crlf())
    in_repo(project, "add", "-A")
    in_repo(project, "commit", "-q", "-m", "as it was")
    blob = subprocess.run(["git", "cat-file", "blob", "HEAD:src/a.txt"], cwd=project,
                          capture_output=True, check=True).stdout
    assert b"\r" not in blob                                     # git keeps it with LF
    (project / "src" / "a.txt").write_bytes(crlf(l1="USER"))
    sides = taken(tmp_path, project, {"src/a.txt": crlf(l1="USER", l50="AGENT")})
    _sha, notes = git.commit(project, ["src/a.txt"], "Coder: line 50", sides=sides)
    assert notes == []
    assert head(project, "src/a.txt") + "\n" == lines(l50="AGENT")
    assert in_repo(project, "diff", "--name-only") == "src/a.txt"
    assert (project / "src" / "a.txt").read_bytes() == crlf(l1="USER", l50="AGENT")


def test_the_other_files_of_the_repository_are_not_read_again(repo, tmp_path):
    """The commit's own index starts from the user's, which knows them: their clean filter
    does not run for each."""
    ran = tmp_path / "ran.txt"
    for n in range(30):
        (repo / f"more{n}.txt").write_bytes(b"more\n")
    in_repo(repo, "add", "-A")
    in_repo(repo, "commit", "-q", "-m", "more")
    (repo / ".gitattributes").write_bytes(b"*.txt filter=counted\n")
    in_repo(repo, "config", "filter.counted.clean", f"echo x >> '{ran.as_posix()}'; cat")
    # (older than the index: a file as new as it is read again - by whole seconds on Linux)
    for one in repo.rglob("*"):
        if ".git" not in one.relative_to(repo).parts:
            os.utime(one, (time.time() - 5,) * 2)
    in_repo(repo, "add", "-A")
    in_repo(repo, "commit", "-q", "-m", "counted")
    ran.unlink(missing_ok=True)
    sides = taken(tmp_path, repo, {"a.txt": lines(l50="AGENT").encode()})
    git.commit(repo, ["a.txt"], "Coder: line 50", sides=sides)
    assert head(repo, "a.txt") + "\n" == lines(l50="AGENT")
    assert len(ran.read_text().split()) < 10


def test_a_file_that_cannot_be_read_is_no_deletion(tmp_path):
    """What the commit is told of a side: None only where there is no file at all."""
    (tmp_path / "a.txt").write_bytes(b"A")
    (tmp_path / "folder").mkdir()
    assert _held(tmp_path / "a.txt") == b"A"
    assert _held(tmp_path / "gone.txt") is None
    assert _held(tmp_path / "folder") is False and _held(None) is False


def test_what_was_kept_for_a_commit_goes_once_none_is_offered(tmp_path):
    class Merge:
        def __init__(self, state):
            self.commit = {"state": state}

    held = {"offered": Merge("offered"), "committed": Merge("committed")}

    class Session:
        def get(self, _model, merge_id):
            return held.get(merge_id)

    for name in ("offered", "committed", "gone"):
        (tmp_path / "commit-sides" / name).mkdir(parents=True)
    prune_commit_sides(tmp_path, Session())
    assert [one.name for one in (tmp_path / "commit-sides").iterdir()] == ["offered"]
    prune_commit_sides(tmp_path / "nothing", Session())       # no folder: nothing to do


def test_two_thousand_files_go_in_though_no_command_line_holds_them(tmp_path):
    # (Windows' command line holds 32K characters: some 300 such paths, WinError 206)
    project = tmp_path / "p"
    paths = [f"generated/a/long/folder/name/module_{n:04}_with_a_long_name.py"
             for n in range(2000)] + ["ü dosya.txt"]
    for path in paths:
        (project / path).parent.mkdir(parents=True, exist_ok=True)
        (project / path).write_bytes(b"one\n")
    repository(project)
    for path in paths[1:]:
        (project / path).write_bytes(b"two\n")
    (project / paths[0]).unlink()
    sha, _notes = git.commit(project, paths, "Coder: generated")
    assert in_repo(project, "show", f"{sha}:{paths[-1]}") == "two"
    assert in_repo(project, "rev-list", "--count", "HEAD") == "2"
    assert in_repo(project, "status", "--porcelain") == ""


def test_a_rewrite_of_the_same_size_in_the_second_the_index_was_written_goes_in(tmp_path):
    # Racy git: the user's index and a file it knows written in one second, and the file
    # written again with as many bytes then. Its stat is as the index has it; git reads it
    # again only because the index is as new as it. (Seen on macOS and Linux runners.)
    project = tmp_path / "p"
    project.mkdir()
    file = project / "a.txt"
    file.write_bytes(b"one\n")
    then = (int(time.time()) - 10) * 10**9
    os.utime(file, ns=(then, then))
    repository(project)
    file.write_bytes(b"two\n")
    for written in (file, project / ".git" / "index"):
        os.utime(written, ns=(then, then))
    sha, _notes = git.commit(project, ["a.txt"], "Coder: two")
    assert in_repo(project, "show", f"{sha}:a.txt") == "two"
    assert in_repo(project, "status", "--porcelain") == ""
