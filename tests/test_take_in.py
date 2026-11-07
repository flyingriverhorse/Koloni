"""Taking a sub-agent's work in (slice 30), beyond its acceptance set: what the copy keeps
to merge by, the files that cannot be merged line by line, the user's choices - also on a
copy kept over a restart - the check where it times out, runs in a container or is of an
earlier state, the commit's refusals, and how git is run.
"""

import contextlib
import json
import os
import shutil
import sqlite3
import sys
import time

import pytest
from alembic import command as alembic
from sqlalchemy import select

from app import agent as runner
from app import copies, git
from app.agent import MAX_LINES_COMPARED, _merge_file, _projects_lines
from app.config import load_settings
from app.db.models import FileChange, Merge, ToolCall
from app.main import create_app
from app.schemas import MergeCommitOut
from tests.conftest import Gate
from tests.fakes import Script, ScriptedExecutor, ScriptedModel
from tests.keyed import TestClient
from tests.test_chat_flow import text
from tests.test_claim_scenarios import agent, calls, write
from tests.test_copy_later_scenarios import again
from tests.test_copy_runner import at_work, card_of, kept_folders
from tests.test_copy_scenarios import seen
from tests.test_migration_0002 import _config
from tests.test_parallel import until
from tests.test_spawn import call, step
from tests.test_take_in_scenarios import (
    CHECK,
    LINES,
    LONG,
    ORIGIN,
    card,
    edit,
    lines,
    meanwhile,
    needs_git,
    of,
    repository,
    same,
    start,
)
from tests.test_take_in_scenarios import git as in_repo
from tests.test_trigger_scenarios import allow, run_now, trigger

NUMBERS = ["one", "two", "three", "four", "five", "six", "seven"]


def run(command, id="c"):
    return call("run_command", {"command": command}, id)


def with_(**changed):
    """The seven lines, some of them changed: `with_(two="TWO")`."""
    return [changed.get(line, line) for line in NUMBERS]


# --- what a copy keeps to merge by -----------------------------------------------------------


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "p"
    root.mkdir()
    (root / "lines.txt").write_bytes(LINES.encode())
    return root


@needs_git
def test_what_a_file_was_copied_from_is_kept_beside_the_tree_and_two_changes_go_together(
    project, tmp_path
):
    copy = copies.make(project, tmp_path / "rt", "a")
    assert copy.started_from("lines.txt") == LINES.encode()
    assert (copy.root.parent / copies.BASE / "lines.txt").read_bytes() == LINES.encode()
    assert not (copy.root / copies.BASE).exists()          # beside the tree, not in it
    (copy.root / "lines.txt").write_bytes(LINES.replace("two", "TWO-agent").encode())
    (project / "lines.txt").write_bytes(LINES.replace("six", "SIX-user").encode())
    one = _merge_file(copy, "lines.txt")
    # the diff is from the project's file as it is now: the user's line is no part of it
    assert one["state"] == "merged" and "+TWO-agent" in one["diff"]
    assert "SIX-user" not in one["diff"] and (one["additions"], one["deletions"]) == (1, 1)
    assert copy.results["lines.txt"]["merged"].decode().split("\n")[:-1] == with_(
        two="TWO-agent", six="SIX-user")
    # nothing of the merge is left in the copy's folder, and nothing was written yet
    assert sorted(p.name for p in copy.root.parent.iterdir()) == ["base", "base.json", "tree"]
    assert "SIX-user" not in (copy.root / "lines.txt").read_text(encoding="utf-8")
    # it is there again after a restart, for a copy that was kept
    copy.save()
    assert copies.load(project, tmp_path / "rt", "a").started_from("lines.txt") == LINES.encode()


def test_which_files_hold_both_sides_together_is_written_down_and_read_as_anothers_word(
    project, tmp_path
):
    """For a restart; and the note is in the copy's folder, where a command could reach."""
    copy = copies.make(project, tmp_path / "rt", "a")
    copy.join("lines.txt", b"the two together\n", b"the project's\n")
    copy.save()
    assert copies.load(project, tmp_path / "rt", "a").joined == copy.joined != {}
    note = copy.root.parent / copies.BASE_FILE
    held = json.loads(note.read_text(encoding="utf-8"))
    for said in ([1], "x", {"lines.txt": 5, "../x": "d", "no-such.txt": "d"}):
        note.write_text(json.dumps({**held, "joined": said}), encoding="utf-8")
        assert copies.load(project, tmp_path / "rt", "a").joined == {}


@needs_git
def test_a_file_taken_from_another_agent_brings_what_it_started_from_with_it(project, tmp_path):
    """`refresh`: the project got another agent's change, and this copy had left the file
    alone. What it changes later is merged on that, not on what it was first copied from."""
    other = copies.make(project, tmp_path / "rt", "b")
    new = LINES.replace("two", "TWO-a").encode()
    (project / "lines.txt").write_bytes(new)
    assert other.refresh("lines.txt") and other.started_from("lines.txt") == new
    (other.root / "lines.txt").write_bytes(new.replace(b"six", b"SIX-b"))
    (project / "lines.txt").write_bytes(new.replace(b"four", b"FOUR-user"))
    assert _merge_file(other, "lines.txt")["state"] == "merged"
    assert other.results["lines.txt"]["merged"].decode().split("\n")[:-1] == with_(
        two="TWO-a", four="FOUR-user", six="SIX-b")
    # and what was taken of this copy is what it is made from afterwards
    (project / "lines.txt").write_bytes((other.root / "lines.txt").read_bytes())
    other.taken("lines.txt")
    assert other.started_from("lines.txt") == new.replace(b"six", b"SIX-b")
    assert other.state("lines.txt") is None


@pytest.mark.parametrize("why", ["rewritten", "gone", "large", "a link"])
def test_what_stands_beside_the_tree_is_believed_no_further_than_its_digest(
    project, tmp_path, why
):
    """A command could reach the folder beside the tree; a copy from before this slice has
    none; a file over 1 MiB is not kept. Each is then asked about whole, and says why."""
    if why == "large":
        (project / "lines.txt").write_bytes(b"x\n" * (copies.MAX_BASE_TEXT // 2 + 1))
    copy = copies.make(project, tmp_path / "rt", "a")
    kept = copy.root.parent / copies.BASE / "lines.txt"
    if why == "rewritten":
        kept.write_bytes(b"what a command would like the start to have been\n")
    elif why == "gone":
        kept.unlink()
    elif why == "a link":
        kept.unlink()
        secret = tmp_path / "elsewhere.txt"
        secret.write_bytes(LINES.encode())              # the very bytes: still not read
        try:
            os.symlink(secret, kept)
        except OSError:
            pytest.skip("this account may not make links")
    assert copy.started_from("lines.txt") is None
    (copy.root / "lines.txt").write_bytes(b"the agent's\n")
    (project / "lines.txt").write_bytes(b"the user's\n")
    one = _merge_file(copy, "lines.txt")
    assert one["state"] == "conflict" and one["whole"] is True
    assert "not merged line by line: what it held when the copy was made was not kept" in one["note"]
    assert "lines.txt" not in copy.results


@needs_git
def test_git_merges_three_files_of_its_own_and_leaves_nothing_behind(tmp_path):
    base, mine, theirs = (LINES.replace(*change).encode() for change in (
        ("x", "x"), ("two", "TWO-user"), ("two", "TWO-agent")))
    assert git.merge_file(tmp_path, base, base, theirs) == (0, theirs)
    assert git.merge_file(tmp_path, mine, base, theirs)[0] == 1          # one clash
    assert git.merge_file(tmp_path, mine, base, theirs, "ours") == (0, mine)
    assert git.merge_file(tmp_path, mine, base, theirs, "theirs") == (0, theirs)
    code, _made = git.merge_file(tmp_path, b"\x00a", b"\x00b", b"\x00c")  # not text
    assert code not in range(128)
    assert list(tmp_path.iterdir()) == []


# --- how git is run --------------------------------------------------------------------------

STAND_IN = r"""
import json, os, sys, time
args = sys.argv[1:]
with open(os.environ["STAND_IN_RECORD"], "a", encoding="utf-8") as record:
    record.write(json.dumps({
        "argv": args, "cwd": os.getcwd(), "stdin": sys.stdin.read(),
        "env": {name: os.environ.get(name) for name in (
            "NoDefaultCurrentDirectoryInExePath", "GIT_TERMINAL_PROMPT", "GIT_DIR",
            "GIT_WORK_TREE", "GIT_CEILING_DIRECTORIES", "GIT_OPTIONAL_LOCKS", "GIT_INDEX_FILE")},
        "koloni": sorted(name for name in os.environ if name.upper().startswith("KOLONI_")),
    }) + "\n")
time.sleep(float(os.environ.get("STAND_IN_SLEEPS", "0")))
while args and args[0] in ("-c", "--literal-pathspecs"):
    args = args[2:] if args[0] == "-c" else args[1:]
if args[0] == "merge-file":
    sys.stdout.buffer.write(open("agent", "rb").read())
elif args[:2] == ["rev-parse", "--show-toplevel"]:
    print(os.getcwd()); print(os.path.join(os.getcwd(), ".git"))
elif args[:2] == ["rev-parse", "HEAD"]:
    print("0123abc")
elif args[:3] == ["diff", "--cached", "--quiet"] or args[0] == "check-ignore":
    sys.exit(1)
"""


@pytest.fixture
def stand_in(tmp_path, monkeypatch):
    """A `git` that writes down how it was called and answers as git would where all goes
    well; returns what it wrote down so far, call by call."""
    where = tmp_path / "stand-in"
    where.mkdir()
    (where / "git.py").write_text(STAND_IN, encoding="utf-8")
    if os.name == "nt":
        (where / "git.cmd").write_text(
            f'@"{sys.executable}" "{where / "git.py"}" %*\r\n', encoding="utf-8")
        # A batch file is not taken for git (`find`): here it stands for one that was
        # found, and what is looked at is how that is run.
        monkeypatch.setattr(git, "find", lambda: str(where / "git.cmd"))
    else:
        program = where / "git"
        program.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{where / "git.py"}" "$@"\n')
        program.chmod(0o755)
    monkeypatch.setenv("PATH", str(where) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("STAND_IN_RECORD", str(tmp_path / "record.jsonl"))
    # What KOLONİ happens to run with is not git's to see, nor to be sent elsewhere by.
    monkeypatch.setenv("KOLONI_MODEL_API_KEY", "a secret")
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "another-repository" / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(tmp_path / "another-repository"))

    def said():
        written = tmp_path / "record.jsonl"
        return [json.loads(line) for line in written.read_text(encoding="utf-8").splitlines()]

    return said


def test_git_merges_in_a_folder_of_its_own_with_nothing_of_kolonis_to_see(stand_in, tmp_path):
    folder = tmp_path / "copy"
    folder.mkdir()
    assert git.merge_file(folder, b"P", b"B", b"A", "theirs") == (0, b"A")
    (called,) = stand_in()
    assert called["argv"] == ["merge-file", "-p", "--theirs", "project", "base", "agent"]
    # in a folder made for it inside the copy's own, gone afterwards; no repository above it
    assert same(os.path.dirname(called["cwd"]), folder) and list(folder.iterdir()) == []
    assert called["env"] == {
        "NoDefaultCurrentDirectoryInExePath": "1", "GIT_TERMINAL_PROMPT": "0", "GIT_DIR": None,
        "GIT_WORK_TREE": None, "GIT_CEILING_DIRECTORIES": str(folder), "GIT_OPTIONAL_LOCKS": "0",
        "GIT_INDEX_FILE": None}
    assert called["koloni"] == [] and called["stdin"] == ""


def test_the_commit_is_of_the_paths_alone_in_the_project_and_starts_no_watcher(stand_in, tmp_path):
    project = tmp_path / "p"
    project.mkdir()
    # a folder with no `.git` of its own is no repository, whatever git would say of it
    with pytest.raises(git.Refused, match="not the top folder of a git repository"):
        git.commit(project, ["a.txt"], "take it")
    assert not (tmp_path / "record.jsonl").exists()             # git was not even asked
    # nor where a folder above holds the repository: that is said (K-alt-klasor-git)
    (project / "sub").mkdir()
    with pytest.raises(git.Refused, match="not the top folder of a git repository"):
        git.commit(project / "sub", ["a.txt"], "take it")
    (project / ".git").mkdir()
    with pytest.raises(git.Refused, match="a subfolder of a git repository"):
        git.commit(project / "sub", ["a.txt"], "take it")
    assert not (tmp_path / "record.jsonl").exists()
    # (Nothing kept of what the agent changed: each file goes in whole.)
    assert git.commit(project, ["a.txt", "-n", "*"], "take it") == ("0123abc", [
        "a.txt, -n, * went in whole, as the project has them: any edits of your own there went "
        "into this commit too"])
    # nor does git take a folder that only holds a git folder's files for a repository
    safe = ["-c", "core.fsmonitor=false", "-c", "safe.bareRepository=explicit"]
    always = [*safe, "--literal-pathspecs"]
    assert [one["argv"] for one in stand_in()] == [[*always, *args] for args in (
        ["rev-parse", "--show-toplevel", "--absolute-git-dir"],
        ["symbolic-ref", "-q", "HEAD"],
        ["rev-parse", "-q", "--verify", "HEAD"],
        ["ls-tree", "-r", "-t", "-z", "HEAD"],
        ["ls-files", "-s", "-z"],
    )] + [[*safe, "check-ignore", "-q", "--", f"./{path}"] for path in ("a.txt", "-n", "*")] + [
        [*always, *args] for args in (
            ["read-tree", "--reset", "HEAD"],
            ["update-index", "--add", "--remove", "-z", "--stdin"],
            ["diff", "--cached", "--quiet", "--no-ext-diff"],
            ["write-tree"],
            ["commit", "-m", "take it"],
            ["rev-parse", "HEAD"],
            ["diff-tree", "-r", "-z", "--name-only", "--no-renames", "", "0123abc"],
            ["reset", "-q", "--pathspec-from-file=-", "--pathspec-file-nul"],
        )]
    # the paths on stdin, not the command line: Windows' holds some 300 (WinError 206)
    assert [one["stdin"] for one in stand_in()] == [""] * 9 + ["a.txt\0-n\0*\0"] + [""] * 5 + [
        "a.txt\0-n\0*\0"]
    # the commit is made from an index of its own, in the git folder; the user's is set after
    index = [one["env"]["GIT_INDEX_FILE"] for one in stand_in()]
    assert index[:8] == [None] * 8 and index[-3:] == [None] * 3 and len(set(index[8:13])) == 1
    assert same(os.path.dirname(index[8]), project / ".git") and not os.path.exists(index[8])
    for called in stand_in():
        assert same(called["cwd"], project) and called["koloni"] == []
        assert called["env"]["GIT_DIR"] is None and called["env"]["GIT_WORK_TREE"] is None
        assert called["env"]["GIT_TERMINAL_PROMPT"] == "0"
        assert called["env"]["NoDefaultCurrentDirectoryInExePath"] == "1"
        # a look at the user's repository takes no lock it could do without
        assert called["env"]["GIT_OPTIONAL_LOCKS"] == "0"


def test_git_does_not_run_for_ever(stand_in, tmp_path, monkeypatch):
    monkeypatch.setenv("STAND_IN_SLEEPS", "60")
    began = time.monotonic()
    with pytest.raises(git.Refused, match="did not end within 1 seconds"):
        git.run([git.find(), "status"], tmp_path, 1.0)
    assert time.monotonic() - began < 30


def test_a_merge_whose_own_folder_cannot_be_deleted_is_still_a_merge(tmp_path, monkeypatch):
    """(Windows: something still has a file of it open.) The folder goes with the copy."""
    with contextlib.ExitStack() as still_open:

        def ran(argv, cwd, seconds, **more):
            still_open.enter_context(open(cwd / "project", "rb"))
            return 0, b"the two together", b""

        monkeypatch.setattr(git, "find", lambda: "git")
        monkeypatch.setattr(git, "run", ran)
        assert git.merge_file(tmp_path, b"P", b"B", b"A") == (0, b"the two together")


# What Windows' command interpreter would act on, were it to read them: a name an agent
# may give a file, and a line a commit's message may be proposed from.
BY_NAME = "a&mkdir,BY-NAME&.txt"
BY_MESSAGE = 'do "&mkdir BY-MESSAGE&" it'
needs_batch = pytest.mark.skipif(os.name != "nt", reason="a batch file is Windows' own")


@pytest.fixture
def batch_git(tmp_path, monkeypatch):
    """A `git.cmd` first on PATH that passes everything on to the real git, as a wrapper
    somebody installed would."""
    where = tmp_path / "wrapper"
    where.mkdir()
    (where / "git.cmd").write_text(f'@"{shutil.which("git")}" %*\r\n', encoding="utf-8")
    monkeypatch.setenv("PATH", str(where) + os.pathsep + os.environ["PATH"])


def folders(top):
    return sorted(one.name for one in top.iterdir() if one.is_dir())


def test_a_batch_file_is_not_git_and_neither_is_one_in_the_folder_koloni_stands_in(
    tmp_path, monkeypatch
):
    """Windows runs a batch file through its command interpreter, which reads the line
    once more; and it drops the dots and spaces a name ends with."""
    for name in ("git.cmd", "git.BAT", "git.cmd.", "git.bat ", "git.CMD . "):
        monkeypatch.setattr(git.shutil, "which", lambda _git, found=str(tmp_path / name): found)
        assert git.find() is None, name
    # one found beside KOLONİ comes back as a relative path: that is not git
    monkeypatch.setattr(git.shutil, "which", lambda name: "git.exe")
    assert git.find() is None
    with pytest.raises(git.Refused, match="git was not found"):
        git.merge_file(tmp_path, b"a", b"b", b"c")
    monkeypatch.setattr(git.shutil, "which", lambda name: str(tmp_path / "git.exe"))
    assert git.find() == str(tmp_path / "git.exe")


@needs_git
@needs_batch
def test_a_git_that_is_a_batch_file_is_not_started_with_a_name_or_a_message(project, batch_git):
    """An `&` in either would be a command of its own: nothing is made in the project."""
    repository(project)
    (project / BY_NAME).write_bytes(b"A")
    meanwhile(project, "two", "TWO")
    assert git.find() is None
    for asked in (lambda: git.summary(project, "HEAD"),
                  lambda: git.commit(project, [BY_NAME], "take it"),
                  lambda: git.commit(project, ["lines.txt"], BY_MESSAGE)):
        with pytest.raises(git.Refused, match="git was not found"):
            asked()
    assert folders(project) == [".git"]
    assert in_repo(project, "log", "--format=%s") == "as it was"


@needs_git
@needs_batch
def test_where_git_is_a_batch_file_a_file_is_asked_about_whole_and_no_commit_is_offered(
    make_client, wait_run, project_dir, batch_git
):
    """KOLONİ goes on as where there is no git: it says so, and offers what needs none."""
    repository(project_dir)
    held = Gate()
    client, _pid, cid, run_id = start(make_client, project_dir, [
        step(write(BY_NAME, "A")), step(edit("two", "TWO-agent", "e2")),
        held.step(text("A done"))], project={"git_commit": True})
    held.wait_partial()
    meanwhile(project_dir, "six", "SIX-user")
    held.release()
    merge = card(client, cid)
    assert of(merge)["whole"] is True and "git was not found" in of(merge)["note"]
    assert client.post(f"/api/merges/{merge['id']}/approve",
                       json={"choices": {"lines.txt": "agent"}, "shown": seen(merge)}).status_code == 200
    snap = wait_run(client, cid, run_id, timeout=LONG)
    (merge,) = snap["merges"]
    assert merge["status"] == "applied" and (project_dir / BY_NAME).read_bytes() == b"A"
    assert merge["commit"] is None
    assert client.post(f"/api/merges/{merge['id']}/commit",
                       json={"message": BY_MESSAGE}).status_code == 409
    assert folders(project_dir) == [".git"]
    assert in_repo(project_dir, "log", "--format=%s") == "as it was"


# --- what is a repository ---------------------------------------------------------------------

PLANTED_RAN = "PLANTED-RAN"


def planted(tmp_path):
    """What an agent's command could put at the top of a project that is no repository:
    a git folder's own files - HEAD, objects, refs, an index - with a config that makes
    the folder its own work tree and names a program git runs on each file it reads (a
    clean filter; it leaves `PLANTED_RAN` where it ran). Returns the folder that holds
    them, with the `.gitattributes` that sends `a.txt` through the program."""
    seed, held = tmp_path / "seed", tmp_path / "planted"
    seed.mkdir()
    (seed / "a.txt").write_bytes(b"A\n")
    (seed / ".gitattributes").write_bytes(b"*.txt filter=planted\n")
    repository(seed)
    shutil.copytree(seed / ".git", held)
    shutil.copy(seed / ".gitattributes", held)
    with (held / "config").open("a", encoding="utf-8") as config:
        config.write('[core]\n\tworktree = .\n[filter "planted"]\n'
                     f'\tclean = "echo ran > {PLANTED_RAN}; cat"\n')
    return held


@needs_git
@pytest.mark.parametrize("beside", ["nothing", "an empty .git"])
def test_a_folder_that_only_holds_a_git_folders_files_is_no_repository(tmp_path, beside):
    """git itself would take it for one, and run what its config names."""
    project = planted(tmp_path)
    (project / "a.txt").write_bytes(b"B\n")
    if beside == "an empty .git":           # past KOLONİ's own look: git is told as well
        (project / ".git").mkdir()
    for asked in (lambda: git.repository(project), lambda: git.summary(project, "HEAD"),
                  lambda: git.commit(project, ["a.txt"], "take it")):
        with pytest.raises(git.Refused, match="the project folder is not"):
            asked()
    assert not (project / PLANTED_RAN).exists()


@needs_git
def test_the_folder_of_a_linked_worktree_is_a_repository(tmp_path):
    """Its `.git` is a file that says where its git folder is: the commit is made there."""
    main, linked = tmp_path / "main", tmp_path / "linked"
    main.mkdir()
    (main / "a.txt").write_bytes(b"A\n")
    repository(main)
    in_repo(main, "worktree", "add", "-q", "-b", "other", str(linked))
    (linked / "a.txt").write_bytes(b"B\n")
    kept = tmp_path / "kept"
    kept.mkdir()
    (kept / "before").write_bytes(b"A\n")
    (kept / "after").write_bytes(b"B\n")
    sha, whole = git.commit(linked, ["a.txt"], "take it",
                            sides={"a.txt": (kept / "before", kept / "after")})
    assert sha == in_repo(linked, "rev-parse", "HEAD") and whole == []
    assert "1 insertion(+), 1 deletion(-)" in git.summary(linked, sha)
    assert in_repo(main, "log", "--format=%s", "other") == "take it\nas it was"
    assert in_repo(linked, "status", "--porcelain") == ""


@needs_git
def test_git_files_an_agent_plants_in_a_project_run_nothing_when_its_work_is_taken(
    make_client, wait_run, project_dir, tmp_path
):
    """The project is no repository, and committing what is taken is switched on."""
    (project_dir / "a.txt").write_bytes(b"A\n")
    plants = f"import shutil;shutil.copytree(r'{planted(tmp_path)}','.',dirs_exist_ok=True)"
    client, _pid, cid, run_id = start(make_client, project_dir, [
        step(run(f'python -c "{plants}"')), step(write("a.txt", "B\n")), text("A done")],
        project={"git_commit": True})
    snap = wait_run(client, cid, run_id, timeout=LONG)
    (merge,) = snap["merges"]
    # all of it is in the project, as any file an agent made is - and is nothing to git
    assert merge["status"] == "applied" and (project_dir / "HEAD").exists()
    assert (project_dir / "a.txt").read_bytes() == b"B\n"
    assert merge["commit"] is None and not (project_dir / PLANTED_RAN).exists()
    assert client.post(f"/api/merges/{merge['id']}/commit",
                       json={"message": "take it"}).status_code == 409
    assert not (project_dir / PLANTED_RAN).exists()


# --- files that go together, and files that do not --------------------------------------------


@needs_git
@pytest.mark.parametrize("choice", [None, "agent"])
def test_a_file_with_windows_line_ends_keeps_them(make_client, wait_run, project_dir, choice):
    dos = LINES.replace("\n", "\r\n").encode()
    (project_dir / "dos.txt").write_bytes(dos)
    held = Gate()
    client, _pid, cid, run_id = start(make_client, project_dir, [
        step(edit("two", "TWO-agent", path="dos.txt")), held.step(text("A done"))])
    held.wait_partial()
    meanwhile(project_dir, "six", "SIX-user", path="dos.txt")
    wanted = dos.replace(b"two", b"TWO-agent").replace(b"six", b"SIX-user")
    if choice:                                       # the same line too: asked about
        meanwhile(project_dir, "two", "TWO-user", path="dos.txt")
    held.release()
    if choice:
        merge = card(client, cid)
        assert of(merge, "dos.txt")["whole"] is False
        assert client.post(f"/api/merges/{merge['id']}/approve",
                           json={"choices": {"dos.txt": choice}, "shown": seen(merge)}).status_code == 200
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert [m["status"] for m in snap["merges"]] == ["applied"]
    assert (project_dir / "dos.txt").read_bytes() == wanted


@needs_git
def test_the_same_change_on_both_sides_is_no_clash(make_client, wait_run, project_dir):
    held = Gate()
    client, _pid, cid, run_id = start(make_client, project_dir, [
        step(edit("two", "SAME", "e1")), step(edit("six", "SIX-agent", "e2")),
        held.step(text("A done"))])
    held.wait_partial()
    meanwhile(project_dir, "two", "SAME")
    meanwhile(project_dir, "four", "FOUR-user")
    held.release()
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert [m["status"] for m in snap["merges"]] == ["applied"]       # nobody was asked
    assert lines(project_dir) == with_(two="SAME", four="FOUR-user", six="SIX-agent")


@needs_git
def test_what_went_together_is_one_record_and_the_agents_own_say_merged(
    make_client, wait_run, project_dir
):
    """The acceptance set reads the change's diff; this reads the records themselves."""
    held = Gate()
    client, _pid, cid, run_id = start(make_client, project_dir, [
        step(edit("two", "TWO-agent", "e1")), step(edit("three", "THREE-agent", "e2")),
        held.step(text("A done"))])
    held.wait_partial()
    meanwhile(project_dir, "six", "SIX-user")
    held.release()
    snap = wait_run(client, cid, run_id, timeout=LONG)
    with client.app.state.session_factory() as session:
        rows = session.scalars(select(FileChange).where(FileChange.path == "lines.txt")).all()
        applied = [row for row in rows if row.status == "applied"]
        assert sorted(row.status for row in rows) == ["applied", "merged", "merged"]
        (one,) = applied
        assert "SIX-user" in one.before_content and "TWO-agent" not in one.before_content
        assert one.after_content.split("\n")[:-1] == with_(
            two="TWO-agent", three="THREE-agent", six="SIX-user")
        # on record under the call that opened the agent, as what a command did is
        opened = session.get_one(ToolCall, one.tool_call_id)
        assert opened.name == "spawn_agent" and one.agent_id == agent(snap, "Coder")["id"]
    # the agent's own changes are not ones to revert: they are not what the project got
    merged = next(f for f in snap["file_changes"] if f["status"] == "merged")
    assert client.post(f"/api/file-changes/{merged['id']}/revert").status_code == 409
    assert lines(project_dir) == with_(two="TWO-agent", three="THREE-agent", six="SIX-user")


@needs_git
def test_keeping_the_projects_lines_is_told_to_the_agent_that_opened_it(
    make_client, wait_run, project_dir
):
    held = Gate()
    client, _pid, cid, run_id = start(make_client, project_dir, [
        step(edit("two", "TWO-agent", "e1")), step(edit("six", "SIX-agent", "e2")),
        held.step(text("I made line two TWO-agent"))])
    held.wait_partial()
    meanwhile(project_dir, "two", "TWO-user")
    held.release()
    merge = card(client, cid)
    assert client.post(f"/api/merges/{merge['id']}/approve",
                       json={"choices": {"lines.txt": "project"}, "shown": seen(merge)}).status_code == 200
    snap = wait_run(client, cid, run_id, timeout=LONG)
    (file,) = snap["merges"][0]["files"]
    assert (file["state"], file["chose"]) == ("applied", "project")
    # the lead does not go on as if the Coder's line were there
    ((_status, told),) = calls(snap, "Lead", "spawn_agent")
    assert "In lines.txt the user kept the project's own lines where Coder had changed" in told
    assert lines(project_dir) == with_(two="TWO-user", six="SIX-agent")


def test_the_projects_lines_are_named_by_number_and_a_long_file_by_its_name_alone():
    assert _projects_lines("a\nb\nc\n", "a\nB\nc\n") == "line 2"
    assert _projects_lines("a\nb\nc\nd\ne\n", "a\nB\nC\nd\nE\nx\n") == "lines 2-3, 5-6"
    assert _projects_lines("a\nb\n", "a\n") == ""             # it only took a line out
    # (comparing is quadratic on repeated lines: 9 s on 86 KB) a long file is not compared
    many = "x = 1\n" * (MAX_LINES_COMPARED + 1)
    started = time.monotonic()
    assert _projects_lines(many, many + "y\n") == ""
    assert time.monotonic() - started < 1


@needs_git
@pytest.mark.parametrize("check", [False, True])
def test_the_lines_the_project_changed_meanwhile_are_told_as_not_the_agents(
    make_client, wait_run, project_dir, check
):
    """B-59: the Lead took the user's line 6 for the Coder's, after the check too."""
    held = Gate()
    client, _pid, cid, run_id = start(make_client, project_dir, [
        step(edit("two", "TWO-agent")), held.step(text("I changed line 2"))],
        project={"check_command": "python -c pass"} if check else None, permission_mode="ask")
    held.wait_partial()
    meanwhile(project_dir, "six", "SIX-user")
    held.release()
    merge = card(client, cid)
    assert of(merge)["state"] == "merged"
    if check:
        assert client.post(f"/api/merges/{merge['id']}/check").status_code == 200
        until(client, cid, lambda s: s["merges"][0]["check"]["state"] == "passed", timeout=LONG)
    assert client.post(f"/api/merges/{merge['id']}/approve").status_code == 200
    snap = wait_run(client, cid, run_id, timeout=LONG)
    ((_status, told),) = calls(snap, "Lead", "spawn_agent")
    assert ("In lines.txt (line 6) the project's own changes made meanwhile were kept beside "
            "Coder's: they are not Coder's doing.") in told, told
    assert lines(project_dir) == with_(two="TWO-agent", six="SIX-user")


@needs_git
def test_keeping_the_projects_lines_where_nothing_else_was_changed_takes_nothing(
    make_client, wait_run, project_dir
):
    """The file would be the project's own, letter for letter: no change of it is put on
    record as applied, and the card and the lead say that it was not taken."""
    held = Gate()
    client, _pid, cid, run_id = start(make_client, project_dir, [
        step(edit("two", "TWO-agent")), held.step(text("A done"))])
    held.wait_partial()
    meanwhile(project_dir, "two", "TWO-user")
    held.release()
    merge = card(client, cid)
    assert client.post(f"/api/merges/{merge['id']}/approve",
                       json={"choices": {"lines.txt": "project"}, "shown": seen(merge)}).status_code == 200
    snap = wait_run(client, cid, run_id, timeout=LONG)
    (merge,) = snap["merges"]
    assert merge["status"] == "discarded" and merge["kept_in"] is None
    assert (of(merge)["state"], of(merge)["chose"]) == ("refused", "project")
    assert "the user chose it" in of(merge)["note"]
    assert "not applied" in calls(snap, "Lead", "spawn_agent")[0][1]
    assert lines(project_dir) == with_(two="TWO-user")
    assert [f["status"] for f in snap["file_changes"]] == ["discarded"]


@needs_git
@pytest.mark.parametrize("deleted_by, choice", [
    ("the project", "agent"), ("the project", "project"), ("the agent", "agent"),
    ("the agent", "project")])
def test_a_file_one_side_deleted_is_asked_about_whole(
    make_client, wait_run, project_dir, deleted_by, choice
):
    gone = "python -c \"import os;os.remove('lines.txt')\""
    coder = step(edit("two", "TWO-agent")) if deleted_by == "the project" else step(run(gone))
    held = Gate()
    client, _pid, cid, run_id = start(make_client, project_dir, [coder, held.step(text("done"))])
    held.wait_partial()
    if deleted_by == "the project":
        (project_dir / "lines.txt").unlink()
    else:
        meanwhile(project_dir, "six", "SIX-user")
    held.release()
    merge = card(client, cid)
    file = of(merge)
    assert file["state"] == "conflict" and file["whole"] is True and "deleted" in file["note"]
    # the side that has no file has no time, and neither is said to be newer
    side = "project" if deleted_by == "the project" else "agent"
    assert file["sides"][side]["changed_at"] is None and file["sides"]["newer"] is None
    assert client.post(f"/api/merges/{merge['id']}/approve",
                       json={"choices": {"lines.txt": choice}, "shown": seen(merge)}).status_code == 200
    snap = wait_run(client, cid, run_id, timeout=LONG)
    (merge,) = snap["merges"]
    there = (project_dir / "lines.txt").exists()
    if choice == "agent":
        assert merge["status"] == "applied" and there is (deleted_by == "the project")
        if there:
            assert lines(project_dir) == with_(two="TWO-agent")
    else:
        # the project's is kept - also where that is no file: nothing is taken, and the
        # copy is done with, not kept
        assert there is (deleted_by == "the agent")
        assert merge["status"] == "discarded" and merge["kept_in"] is None
        assert of(merge)["state"] == "refused" and "user chose" in of(merge)["note"]
        assert "not applied" in calls(snap, "Lead", "spawn_agent")[0][1]
    assert snap["runs"][0]["status"] == "completed"


# --- a copy that was kept ---------------------------------------------------------------------


@needs_git
def test_a_kept_copy_is_decided_after_a_restart_with_the_users_choice(settings_env, project_dir):
    (project_dir / "lines.txt").write_bytes(LINES.encode())
    cid = at_work(settings_env, project_dir, [
        step(edit("two", "TWO-agent", "e1")), step(edit("six", "SIX-agent", "e2"))])
    meanwhile(project_dir, "two", "TWO-user")           # while the app is closed
    meanwhile(project_dir, "four", "FOUR-user")
    with again(settings_env) as client:
        merge = card_of(client, cid)
        file = of(merge)
        assert merge["status"] == "kept" and file["state"] == "conflict"
        assert file["whole"] is False and "+TWO-agent" in file["clash"]
        assert file["sides"]["newer"] == "project"
        # nothing is chosen for the user here either, and no check runs on a kept copy
        assert client.post(f"/api/merges/{merge['id']}/approve").status_code == 409
        refused = client.post(f"/api/merges/{merge['id']}/check",
                              json={"choices": {"lines.txt": "agent"}})
        assert refused.status_code == 409 and "kept" in refused.json()["detail"]
        assert lines(project_dir) == with_(two="TWO-user", four="FOUR-user")
        done = client.post(f"/api/merges/{merge['id']}/approve",
                           json={"choices": {"lines.txt": "agent"}, "shown": seen(merge)})
        assert done.status_code == 200 and done.json()["status"] == "applied"
        assert lines(project_dir) == with_(two="TWO-agent", four="FOUR-user", six="SIX-agent")
        assert kept_folders(settings_env) == []
        snap = client.get(f"/api/conversations/{cid}").json()
        assert sorted(f["status"] for f in snap["file_changes"]) == ["applied", "merged", "merged"]


@needs_git
def test_a_kept_copys_file_that_moved_since_its_card_is_shown_again_not_taken(
    settings_env, project_dir
):
    (project_dir / "lines.txt").write_bytes(LINES.encode())
    cid = at_work(settings_env, project_dir, [step(edit("two", "TWO-agent"))])
    meanwhile(project_dir, "six", "SIX-user")
    with again(settings_env) as client:
        merge = card_of(client, cid)
        assert of(merge)["state"] == "merged"
        meanwhile(project_dir, "two", "TWO-user")       # since the card: now the same line
        said = client.post(f"/api/merges/{merge['id']}/approve")
        assert said.status_code == 409 and said.json()["detail"].startswith("lines.txt changed")
        merge = card_of(client, cid)
        assert merge["status"] == "kept" and of(merge)["state"] == "conflict"
        assert lines(project_dir) == with_(two="TWO-user", six="SIX-user")


def test_nothing_of_a_kept_card_is_taken_once_a_file_of_it_moved_since(
    settings_env, project_dir
):
    """B-56 on a kept copy: all of the card or none of it."""
    cid = at_work(settings_env, project_dir, [
        step(write("a.txt", "A")), step(write("b.txt", "B", "w2"))])
    with again(settings_env) as client:
        merge = card_of(client, cid)
        seen = {f["path"]: f["shown"] for f in merge["files"]}
        (project_dir / "a.txt").write_text("mine", encoding="utf-8")
        said = client.post(f"/api/merges/{merge['id']}/approve", json={"shown": seen})
        assert said.status_code == 409 and said.json()["detail"].startswith("a.txt changed")
        assert not (project_dir / "b.txt").exists()
        merge = card_of(client, cid)
        assert merge["status"] == "kept" and of(merge, "a.txt")["state"] == "conflict"
        assert of(merge, "b.txt")["state"] == "ready"
        now = {f["path"]: f["shown"] for f in merge["files"]}
        done = client.post(f"/api/merges/{merge['id']}/approve",
                           json={"shown": now, "choices": {"a.txt": "agent"}})
        assert done.status_code == 200 and done.json()["status"] == "applied"
        assert (project_dir / "a.txt").read_text(encoding="utf-8") == "A"
        assert (project_dir / "b.txt").read_text(encoding="utf-8") == "B"


def test_a_kept_cards_file_the_project_keeps_rewriting_does_not_hold_up_the_rest(
    settings_env, project_dir
):
    cid = at_work(settings_env, project_dir, [
        step(write("a.txt", "A")), step(write("b.txt", "B", "w2"))])
    with again(settings_env) as client:
        merge = card_of(client, cid)
        (project_dir / "a.txt").write_text("v1", encoding="utf-8")
        assert client.post(f"/api/merges/{merge['id']}/approve").status_code == 409
        merge = card_of(client, cid)
        assert of(merge, "a.txt")["state"] == "conflict"
        (project_dir / "a.txt").write_text("v2", encoding="utf-8")     # and again
        now = {f["path"]: f["shown"] for f in merge["files"]}
        done = client.post(f"/api/merges/{merge['id']}/approve",
                           json={"shown": now, "choices": {"a.txt": "project"}})
        assert done.status_code == 200 and done.json()["status"] == "applied"
        assert (project_dir / "a.txt").read_text(encoding="utf-8") == "v2"
        assert (project_dir / "b.txt").read_text(encoding="utf-8") == "B"


@needs_git
def test_a_kept_file_that_would_now_be_put_together_another_way_is_said_not_taken(
    settings_env, project_dir
):
    """The same digests, but its card asked about it another way (here: as whole files)."""
    (project_dir / "lines.txt").write_bytes(LINES.encode())
    cid = at_work(settings_env, project_dir, [step(edit("two", "TWO-agent"))])
    meanwhile(project_dir, "six", "SIX-user")
    with again(settings_env) as client:
        merge = card_of(client, cid)
        assert of(merge)["state"] == "merged"
        with client.app.state.session_factory() as session:
            row = session.get_one(Merge, merge["id"])
            row.files = [{**one, "state": "conflict", "whole": True} for one in row.files]
            session.commit()
        said = client.post(f"/api/merges/{merge['id']}/approve", json={
            "shown": {"lines.txt": of(merge)["shown"]}, "choices": {"lines.txt": "agent"}})
        assert said.status_code == 409 and said.json()["detail"].startswith("lines.txt changed")
        assert of(card_of(client, cid))["state"] == "merged"
        assert lines(project_dir) == with_(six="SIX-user")


@needs_git
def test_two_sides_written_together_before_a_restart_are_still_one_change_to_undo(
    settings_env, project_dir
):
    """The check had the two written into the copy; the app was closed before Apply."""
    (project_dir / "lines.txt").write_bytes(LINES.encode())
    held = Gate()
    app_ = create_app(load_settings(settings_env), model=ScriptedModel({
        "Lead": [step(call("spawn_agent", {"role": "Coder", "task": "do it"}, "s")),
                 text("done")],
        "Coder": [step(edit("two", "TWO-agent")), held.step(text("A done"))],
    }))
    with TestClient(app_, base_url="http://127.0.0.1:8790") as client:
        client.headers["Origin"] = ORIGIN
        pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
        assert client.patch(f"/api/projects/{pid}",
                            json={"check_command": "python -c pass"}).status_code == 200
        cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
        assert client.patch(f"/api/conversations/{cid}", json={
            "permission_mode": "ask", "spawn_approval": "never"}).status_code == 200
        client.post(f"/api/conversations/{cid}/messages", json={"content": "go"})
        held.wait_partial()
        meanwhile(project_dir, "six", "SIX-user")
        held.release()
        merge = card(client, cid)
        assert client.post(f"/api/merges/{merge['id']}/check").status_code == 200
        until(client, cid, lambda s: s["merges"][0]["check"]["state"] == "passed", timeout=LONG)
    before = (project_dir / "lines.txt").read_bytes()
    with again(settings_env) as client:
        merge = card_of(client, cid)
        # still said to be the two together, not a file of the agent's alone
        assert merge["status"] == "kept" and of(merge)["state"] == "merged"
        done = client.post(f"/api/merges/{merge['id']}/approve")
        assert done.status_code == 200 and done.json()["status"] == "applied"
        assert lines(project_dir) == with_(two="TWO-agent", six="SIX-user")
        snap = client.get(f"/api/conversations/{cid}").json()
        assert sorted(f["status"] for f in snap["file_changes"]) == ["applied", "merged"]
        (one,) = [f for f in snap["file_changes"] if f["status"] == "applied"]
        assert client.post(f"/api/file-changes/{one['id']}/revert").status_code == 200
        assert (project_dir / "lines.txt").read_bytes() == before


# --- the check -------------------------------------------------------------------------------


def test_the_check_sees_what_the_project_changed_meanwhile_in_files_the_agent_left_alone(
    make_client, wait_run, project_dir
):
    (project_dir / "other.txt").write_bytes(b"old")
    sees = "python -c \"import sys;sys.exit(0 if open('other.txt').read()=='USER' else 1)\""
    held = Gate()
    client, _pid, cid, run_id = start(
        make_client, project_dir, [step(write("a.txt", "A")), held.step(text("A done"))],
        project={"check_command": sees})
    held.wait_partial()
    (project_dir / "other.txt").write_bytes(b"USER")
    held.release()
    snap = wait_run(client, cid, run_id, timeout=LONG)
    (merge,) = snap["merges"]
    assert merge["check"]["state"] == "passed" and merge["status"] == "applied"
    assert [f["path"] for f in merge["files"]] == ["a.txt"]            # it is not the agent's
    # on record where commands are: one of the Coder's, run in its copy
    (ran,) = snap["commands"]
    assert ran["command"] == sees and ran["agent_id"] == agent(snap, "Coder")["id"]
    assert (ran["status"], ran["exit_code"]) == ("exited", 0)


@pytest.mark.parametrize("mode, ends", [("ask", "passed"), ("auto_edit", "failed")])
def test_what_the_check_itself_writes_in_the_copy_is_neither_shown_nor_taken(
    make_client, wait_run, project_dir, mode, ends
):
    """A report it leaves, a file of the agent's it rewrites, a file of the project's it
    changes or deletes: none of it is the agent's work, whether the check passes or not.
    (Below Full auto: there a failing check goes to the Lead first, K-fullauto-sorma 2.)"""
    does = ("import os;open('report.xml','w').write('x');open('a.txt','w').write('REWRITTEN');"
            "open('lines.txt','a').write('more');os.remove('hello.py')")
    if ends == "failed":
        does += ";raise SystemExit(1)"
    client, _pid, cid, run_id = start(
        make_client, project_dir, [step(write("a.txt", "A")), text("A done")],
        project={"check_command": f"python -c \"{does}\""}, permission_mode=mode)
    merge = card(client, cid)
    assert client.post(f"/api/merges/{merge['id']}/check").status_code == 200
    snap = until(client, cid, lambda s: s["merges"][0]["check"]["state"] == ends, timeout=LONG)
    (merge,) = snap["merges"]
    # the card asks about what it asked about before, as it was: the result is of that
    assert {f["path"]: f["state"] for f in merge["files"]} == {"a.txt": "ready"}
    assert "+A" in of(merge, "a.txt")["diff"] and merge["check"]["stale"] is False
    assert client.post(f"/api/merges/{merge['id']}/approve").status_code == 200
    snap = wait_run(client, cid, run_id, timeout=LONG)
    (merge,) = snap["merges"]                               # and no second card for the rest
    assert merge["status"] == "applied" and [f["path"] for f in merge["files"]] == ["a.txt"]
    assert (project_dir / "a.txt").read_text(encoding="utf-8") == "A"
    assert not (project_dir / "report.xml").exists() and (project_dir / "hello.py").exists()
    assert lines(project_dir) == NUMBERS
    assert [f["path"] for f in snap["file_changes"]] == ["a.txt"]


def test_a_check_that_does_not_end_in_time_did_not_pass(
    make_client, wait_run, project_dir, monkeypatch
):
    monkeypatch.setattr(runner, "CHECK_SECONDS", 1)
    client, _pid, cid, run_id = start(
        make_client, project_dir, [step(write("a.txt", "A")), text("A done")],
        project={"check_command": "python -c \"import time;time.sleep(60)\""},
        permission_mode="auto_edit")  # (at Full auto it would go to the Lead first)
    merge = card(client, cid)
    assert client.post(f"/api/merges/{merge['id']}/check").status_code == 200
    snap = until(client, cid, lambda s: s["merges"][0]["check"]["state"] == "failed", timeout=LONG)
    check = snap["merges"][0]["check"]
    assert (check["state"], check["exit_code"]) == ("failed", None)
    assert "timed out after 1 seconds" in check["note"]
    assert not (project_dir / "a.txt").exists()
    assert client.post(f"/api/merges/{merge['id']}/reject").status_code == 200
    wait_run(client, cid, run_id, timeout=LONG)


def test_stop_while_the_check_runs_ends_it_and_it_is_not_left_saying_that_it_runs(
    make_client, wait_run, project_dir, tmp_path
):
    # (B-355: it runs by itself before the card, at once; the user's click runs it long.)
    runs = (tmp_path / "runs").as_posix()
    client, _pid, cid, run_id = start(
        make_client, project_dir, [step(write("a.txt", "A")), text("A done")],
        project={"check_command": f"python -c \"import pathlib,time;p=pathlib.Path('{runs}');"
                                  "n=p.exists();p.write_text('x');time.sleep(60*n)\""},
        permission_mode="ask")
    merge = card(client, cid)
    assert client.post(f"/api/merges/{merge['id']}/check").status_code == 200
    snap = until(client, cid, lambda s: [c["status"] for c in s["commands"]] == [
        "exited", "running"], timeout=LONG)
    assert snap["merges"][0]["check"]["state"] == "running"
    # while it runs nothing waits for a decision: Apply is refused, not queued - Discard
    # too - and each is told what it is that they wait for
    for decision in ("approve", "reject"):
        refused = client.post(f"/api/merges/{merge['id']}/{decision}")
        assert refused.status_code == 409
        assert "the check is still running" in refused.json()["detail"]
    assert client.post(f"/api/runs/{run_id}/cancel").status_code in (200, 202)
    snap = wait_run(client, cid, run_id, timeout=LONG)
    (merge,) = snap["merges"]
    assert merge["status"] == "kept" and not (project_dir / "a.txt").exists()  # (6 Nov)
    assert (merge["check"]["state"], merge["check"]["exit_code"]) == ("failed", None)
    assert "cut short" in merge["check"]["note"]
    assert [c["status"] for c in snap["commands"]] == ["exited", "killed"]


def test_in_a_project_whose_commands_run_in_a_container_the_check_runs_there_in_the_copy(
    make_client, wait_run, project_dir
):
    executor = ScriptedExecutor([Script(chunks=["all of it holds\n"], exit_code=0)])
    client, _model = make_client({
        "Lead": [step(call("spawn_agent", {"role": "Coder", "task": "do it"}, "s")),
                 text("done")],
        "Coder": [step(write("a.txt", "A")), text("A done")]}, executor=executor)
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    for change in ({"docker_image": "python:3.12"},
                   {"exec_location": "docker", "check_command": "python -m pytest -q"}):
        assert client.patch(f"/api/projects/{pid}", json=change).status_code == 200
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    assert client.patch(f"/api/conversations/{cid}", json={
        "permission_mode": "full_auto", "spawn_approval": "never"}).status_code == 200
    run_id = client.post(f"/api/conversations/{cid}/messages", json={"content": "go"}).json()[
        "run"]["id"]
    snap = wait_run(client, cid, run_id, timeout=LONG)
    (merge,) = snap["merges"]
    assert merge["status"] == "applied" and merge["check"]["state"] == "passed"
    assert merge["check"]["output"] == "all of it holds\n"
    # the project's own place for commands, given the copy and not the project folder
    assert executor.locations == ["docker"]
    ((ran, cwd),) = executor.started
    ((copy, _links),) = executor.copies
    assert ran == "python -m pytest -q" and copy is not None and same(cwd, copy)
    assert not same(cwd, project_dir)
    (on_record,) = snap["commands"]
    assert (on_record["location"], on_record["image"]) == ("docker", "python:3.12")


def test_a_result_of_an_earlier_state_says_so(make_client, wait_run, project_dir):
    client, _pid, cid, run_id = start(
        make_client, project_dir, [step(write("a.txt", "A")), text("A done")],
        project={"check_command": "python check.py one"}, permission_mode="ask")
    merge = card(client, cid)
    assert client.post(f"/api/merges/{merge['id']}/check").status_code == 200
    snap = until(client, cid, lambda s: s["merges"][0]["check"]["state"] == "passed", timeout=LONG)
    assert snap["merges"][0]["check"]["stale"] is False
    # the project gets a file of that name by another hand: the card's file is not as checked
    (project_dir / "a.txt").write_bytes(b"THE USER'S OWN")
    assert client.post(f"/api/merges/{merge['id']}/approve").status_code == 409
    said = card(client, cid)
    assert of(said, "a.txt")["state"] == "conflict"
    assert said["check"]["state"] == "passed" and said["check"]["stale"] is True
    # run again, on what the user now chooses, it is of this state
    assert client.post(f"/api/merges/{merge['id']}/check",
                       json={"choices": {"a.txt": "project"}}).status_code == 200
    snap = until(client, cid, lambda s: s["merges"][0]["status"] != "pending"
                 or s["merges"][0]["check"]["stale"] is False, timeout=LONG)
    snap = wait_run(client, cid, run_id, timeout=LONG)   # nothing of it is left to take
    assert (project_dir / "a.txt").read_bytes() == b"THE USER'S OWN"
    assert snap["merges"][0]["status"] == "discarded"


@pytest.mark.parametrize("words, passes", [("one", True), ("nine", False)])
def test_where_only_commands_are_asked_about_the_check_runs_by_itself_before_any_card(
    make_client, wait_run, project_dir, words, passes
):
    """Auto-edit takes a sub-agent's changes unasked - once its check passed, which runs by
    itself (B-355); one that fails brings the card, with what it said."""
    client, _pid, cid, run_id = start(
        make_client, project_dir, [step(write("a.txt", "A")), text("A done")],
        project={"check_command": f"python check.py {words}"}, permission_mode="auto_edit")
    if passes:
        snap = wait_run(client, cid, run_id, timeout=LONG)
        assert (project_dir / "a.txt").exists()
        assert [c["status"] for c in snap["commands"]] == ["exited"]
        return
    merge = card(client, cid)
    assert merge["check"]["state"] == "failed" and not (project_dir / "a.txt").exists()
    assert client.post(f"/api/merges/{merge['id']}/approve").status_code == 200
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["merges"][0]["status"] == "applied"


def test_without_a_check_command_no_check_can_be_started(make_client, wait_run, project_dir):
    client, _pid, cid, run_id = start(
        make_client, project_dir, [step(write("a.txt", "A")), text("A done")],
        permission_mode="ask")
    merge = card(client, cid)
    assert merge["check"] is None
    assert client.post(f"/api/merges/{merge['id']}/check").status_code == 409
    assert client.post(f"/api/merges/{merge['id']}/approve").status_code == 200
    wait_run(client, cid, run_id, timeout=LONG)


@needs_git
def test_nobody_watching_a_clash_is_not_decided_and_nothing_is_taken_unchecked(
    make_client, wait_run, project_dir
):
    """The trigger lets the check run - but not on what nobody chose: the copy is kept."""
    (project_dir / "lines.txt").write_bytes(LINES.encode())
    (project_dir / "check.py").write_bytes(CHECK.encode())
    held = Gate()
    client, _model = make_client({
        "Lead": [step(call("spawn_agent", {"role": "Coder", "task": "do it"}, "s")),
                 text("done")],
        "Coder": [step(edit("two", "TWO-agent", "e1")), step(write("a.txt", "A")),
                  held.step(text("A done"))]})
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    command = "python check.py one"
    assert client.patch(f"/api/projects/{pid}", json={"check_command": command}).status_code == 200
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    made = trigger(client, pid, cid, permissions={
        "write": True, "commands": [allow(client, cid, command)], "agents": 1})
    run_id = run_now(client, made["id"])
    held.wait_partial()
    meanwhile(project_dir, "two", "TWO-other")
    held.release()
    snap = wait_run(client, cid, run_id, timeout=LONG)
    (merge,) = snap["merges"]
    assert merge["status"] == "kept" and merge["kept_in"]
    assert merge["check"]["state"] == "not_run" and snap["commands"] == []
    assert {f["path"]: f["state"] for f in merge["files"]} == {
        "a.txt": "ready", "lines.txt": "conflict"}
    assert not (project_dir / "a.txt").exists() and lines(project_dir) == with_(two="TWO-other")
    assert "kept in" in calls(snap, "Lead", "spawn_agent")[0][1]


# --- the commit ------------------------------------------------------------------------------


@needs_git
def test_a_commit_is_not_named_by_koloni_s_words_written_as_the_users(make_client, wait_run, project_dir):
    # (The review of B-160: a night job tried again is a turn on "KOLONİ: the last try of this job
    # failed (...)", written as the user's - the commit is named by the chat's title, a backlog task's.)
    from app import away
    from app.db.models import Conversation
    (project_dir / "lines.txt").write_bytes(LINES.encode())
    repository(project_dir)
    client, _pid, cid, run_id = start(
        make_client, project_dir, [step(write("a.txt", "A")), text("A done")],
        project={"git_commit": True}, permission_mode="ask",
        content=away.RETRY.format(why="it timed out"))
    merge = card(client, cid)
    with client.app.state.session_factory() as session:
        session.get_one(Conversation, cid).title = "Fix the login page"
        session.commit()
    assert client.post(f"/api/merges/{merge['id']}/approve").status_code == 200
    offer = wait_run(client, cid, run_id, timeout=LONG)["merges"][0]["commit"]
    assert offer["message"] == "Coder: Fix the login page"


def taken_in_a_repository(make_client, wait_run, project_dir, before=lambda: None):
    """A Coder's a.txt and its change to line two are in the project, which is a
    repository; returns the client, the conversation's id and the merge, with its commit
    offered."""
    (project_dir / "lines.txt").write_bytes(LINES.encode())
    (project_dir / "check.py").write_bytes(CHECK.encode())
    repository(project_dir)
    before()
    client, _pid, cid, run_id = start(
        make_client, project_dir,
        [step(write("a.txt", "A")), step(edit("two", "TWO-agent")), text("A done")],
        project={"git_commit": True}, permission_mode="ask")
    merge = card(client, cid)
    assert client.post(f"/api/merges/{merge['id']}/approve").status_code == 200
    snap = wait_run(client, cid, run_id, timeout=LONG)
    return client, cid, snap["merges"][0]


@needs_git
def test_the_commit_holds_the_agents_lines_alone_and_the_users_own_stay_uncommitted(
    make_client, wait_run, project_dir
):
    """The user's own edit in a taken file stays a change of the working tree, and what they
    staged of another file stays staged: neither goes into the commit made in the agent's name."""

    def stage():
        (project_dir / "other.txt").write_bytes(b"the user's\n")
        in_repo(project_dir, "add", "other.txt")

    client, _cid, merge = taken_in_a_repository(make_client, wait_run, project_dir, before=stage)
    offer = merge["commit"]
    # (B-160: by the user's message, "go" - not the task the Lead wrote it, "do it", which live began
    # "Project folder: ./ (work with paths relative…".)
    assert offer["state"] == "offered" and offer["message"] == "Coder: go"
    meanwhile(project_dir, "seven", "SEVEN-user")       # the user's own, never committed
    done = client.post(f"/api/merges/{merge['id']}/commit", json={"message": "both"})
    assert done.status_code == 200, done.text
    assert in_repo(project_dir, "show", "HEAD:lines.txt").split("\n") == with_(two="TWO-agent")
    assert in_repo(project_dir, "show", "HEAD:a.txt") == "A"
    assert lines(project_dir) == with_(two="TWO-agent", seven="SEVEN-user")
    assert in_repo(project_dir, "diff", "--name-only") == "lines.txt"
    assert in_repo(project_dir, "diff", "--cached", "--name-only") == "other.txt"
    assert done.json()["commit"] == {**offer, "state": "committed", "message": "both",
                                     "sha": in_repo(project_dir, "rev-parse", "HEAD"),
                                     "holds": in_repo(project_dir, "show", "--format=",
                                                      "--stat=100", "HEAD"),
                                     "notes": None}
    # what was kept of the two sides is gone with the commit
    sides = client.app.state.settings.runtime_root / "commit-sides"
    assert not (sides / merge["id"]).exists()


@needs_git
def test_the_commit_cards_summary_is_of_what_the_commit_holds(make_client, wait_run, project_dir):
    """B-319 (live): the user's own uncommitted line was counted in it, which the commit leaves out."""

    def committed_other():  # (the project's "seven" is then the user's own, uncommitted)
        meanwhile(project_dir, "seven", "SEVEN-committed")
        in_repo(project_dir, "commit", "-q", "-am", "seven")

    client, _cid, merge = taken_in_a_repository(make_client, wait_run, project_dir,
                                                before=committed_other)
    assert merge["commit"]["holds"] is None  # (the working tree's diff holds the user's line)
    done = client.post(f"/api/merges/{merge['id']}/commit", json={"message": "take"})
    assert done.status_code == 200, done.text
    summary = done.json()["commit"]["holds"]
    assert "lines.txt | 2 +-" in summary and "a.txt" in summary
    assert "2 files changed, 2 insertions(+), 1 deletion(-)" in summary
    assert in_repo(project_dir, "show", "HEAD:lines.txt").split("\n") == with_(
        two="TWO-agent", seven="SEVEN-committed")
    assert lines(project_dir) == with_(two="TWO-agent")
    # a commit made before this kept the working tree's stat as its "summary": not said
    older = {"state": "committed", "message": "m", "summary": "lines.txt | 4 ++--"}
    assert MergeCommitOut.model_validate(older).holds is None


@needs_git
def test_a_commits_summary_has_no_colour_codes_where_git_is_set_to_colour_always(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"A\n")
    repository(tmp_path)
    in_repo(tmp_path, "config", "color.ui", "always")
    said = git.summary(tmp_path, "HEAD")
    assert "a.txt" in said and "\x1b" not in said


@needs_git
def test_a_commits_summary_names_a_file_by_its_own_name(tmp_path):
    (tmp_path / "ö.txt").write_bytes(b"A\n")
    repository(tmp_path)
    assert "ö.txt" in git.summary(tmp_path, "HEAD")


@needs_git
def test_a_taken_file_with_nothing_kept_of_its_sides_goes_in_whole_and_the_card_says_so(
    make_client, wait_run, project_dir
):
    """As the user's own edits touching the agent's lines would: the file as the project has it."""
    client, _cid, merge = taken_in_a_repository(make_client, wait_run, project_dir)
    kept = client.app.state.settings.runtime_root / "commit-sides" / merge["id"]
    assert sorted(merge["commit"]) == sorted(["state", "message", "sha", "holds", "asks", "notes"])
    assert len(list(kept.iterdir())) == 3       # lines.txt before and after; a.txt after
    shutil.rmtree(kept)
    meanwhile(project_dir, "seven", "SEVEN-user")
    done = client.post(f"/api/merges/{merge['id']}/commit", json={"message": "both"})
    assert done.status_code == 200, done.text
    assert done.json()["commit"]["notes"] == [
        "a.txt, lines.txt went in whole, as the project has them: any edits of your own there "
        "went into this commit too"]
    assert in_repo(project_dir, "show", "HEAD:lines.txt").split("\n") == with_(
        two="TWO-agent", seven="SEVEN-user")
    assert in_repo(project_dir, "status", "--porcelain") == ""


@needs_git
def test_what_was_taken_back_before_the_commit_is_not_committed_and_that_is_said(
    make_client, wait_run, project_dir
):
    """Its change is no longer in the project: committing it would put back into history what
    the user undid. The offer stays, and says why nothing was made."""
    client, cid, merge = taken_in_a_repository(make_client, wait_run, project_dir)
    head = in_repo(project_dir, "rev-parse", "HEAD")
    meanwhile(project_dir, "TWO-agent", "two")              # taken back, as Revert does
    (project_dir / "a.txt").unlink()
    refused = client.post(f"/api/merges/{merge['id']}/commit", json={"message": "take it"})
    assert refused.status_code == 409
    assert "a.txt was left out of the commit: the agent's change is no longer in it" in (
        refused.json()["detail"])
    assert "lines.txt was left out" in refused.json()["detail"]
    assert in_repo(project_dir, "rev-parse", "HEAD") == head
    assert card_of(client, cid)["commit"]["state"] == "offered"


@needs_git
@pytest.mark.parametrize("under_way", ["a merge", "a cherry-pick", "a rebase"])
def test_no_commit_is_made_into_something_that_is_under_way(
    make_client, wait_run, project_dir, under_way
):
    def begin():
        if under_way != "a merge":
            return
        in_repo(project_dir, "checkout", "-q", "-b", "other")
        (project_dir / "other.txt").write_bytes(b"other")
        in_repo(project_dir, "add", "other.txt")
        in_repo(project_dir, "commit", "-q", "-m", "other")
        in_repo(project_dir, "checkout", "-q", "main")
        in_repo(project_dir, "merge", "-q", "--no-ff", "--no-commit", "other")

    client, cid, merge = taken_in_a_repository(make_client, wait_run, project_dir, before=begin)
    head = in_repo(project_dir, "rev-parse", "HEAD")
    if under_way == "a cherry-pick":
        (project_dir / ".git" / "CHERRY_PICK_HEAD").write_text(head + "\n", encoding="ascii")
    elif under_way == "a rebase":
        (project_dir / ".git" / "rebase-merge").mkdir()
    refused = client.post(f"/api/merges/{merge['id']}/commit", json={"message": "take it"})
    assert refused.status_code == 409 and f"{under_way} is under way" in refused.json()["detail"]
    assert in_repo(project_dir, "rev-parse", "HEAD") == head
    assert (project_dir / "a.txt").read_text(encoding="utf-8") == "A"   # taken, not committed
    # and it stays offered: the user finishes what is under way, and commits then
    assert card_of(client, cid)["commit"]["state"] == "offered"


@needs_git
def test_a_commit_of_nothing_and_one_without_a_message_are_refused(
    make_client, wait_run, project_dir
):
    client, _cid, merge = taken_in_a_repository(make_client, wait_run, project_dir)
    for nothing in ("", "   ", "a\x00b"):
        assert client.post(f"/api/merges/{merge['id']}/commit",
                           json={"message": nothing}).status_code == 422
    # the user commits the files themselves first: there is nothing left of them to commit
    in_repo(project_dir, "add", "-A")
    in_repo(project_dir, "commit", "-q", "-m", "by hand")
    refused = client.post(f"/api/merges/{merge['id']}/commit", json={"message": "take it"})
    assert refused.status_code == 409 and "nothing to commit" in refused.json()["detail"]
    assert in_repo(project_dir, "log", "--format=%s") == "by hand\nas it was"


@needs_git
@pytest.mark.parametrize("ticked", [True, False])
def test_what_a_turn_nobody_watched_left_is_offered_its_commit_only_once_the_user_takes_it(
    make_client, wait_run, project_dir, ticked
):
    """Never in the trigger's own turn; a copy it kept is then the user's own Apply."""
    (project_dir / "lines.txt").write_bytes(LINES.encode())
    (project_dir / "check.py").write_bytes(CHECK.encode())
    repository(project_dir)
    client, _model = make_client({
        "Lead": [step(call("spawn_agent", {"role": "Coder", "task": "do it"}, "s")),
                 text("done")],
        "Coder": [step(write("a.txt", "A")), text("A done")]})
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    command = "python check.py NEVER-THERE"
    assert client.patch(f"/api/projects/{pid}", json={
        "check_command": command, "git_commit": True}).status_code == 200
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    rules = [allow(client, cid, command)] if ticked else []
    made = trigger(client, pid, cid, permissions={"write": True, "commands": rules, "agents": 1})
    snap = wait_run(client, cid, run_now(client, made["id"]), timeout=LONG)
    (merge,) = snap["merges"]
    # taken in the turn itself where the check may not run, kept where it ran and failed
    assert merge["status"] == ("kept" if ticked else "applied")
    assert merge["commit"] is None
    if ticked:
        done = client.post(f"/api/merges/{merge['id']}/approve")
        assert done.status_code == 200 and done.json()["status"] == "applied"
        assert done.json()["commit"]["state"] == "offered"
    assert in_repo(project_dir, "log", "--format=%s") == "as it was"   # and none is made


# --- the migration ---------------------------------------------------------------------------


def test_migration_0037_and_back(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    alembic.upgrade(cfg, "0036")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO projects (id, name, root_path, created_at) "
                     "VALUES ('p', 'p', 'C:/p', '2026-10-13 10:00:00')")
        conn.execute("INSERT INTO conversations (id, project_id, title, created_at, updated_at) "
                     "VALUES ('c', 'p', 't', '2026-10-13 10:00:00', '2026-10-13 10:00:00')")
        conn.execute("INSERT INTO runs (id, conversation_id, status, created_at) "
                     "VALUES ('r', 'c', 'completed', '2026-10-13 10:00:00')")
        conn.execute("INSERT INTO agents (id, run_id, role_name, name, tools, depth, status, "
                     "created_at) VALUES ('a', 'r', 'Coder', 'Coder', '[]', 1, 'completed', "
                     "'2026-10-13 10:00:00')")
        conn.execute("INSERT INTO merges (id, run_id, agent_id, status, files, created_at) "
                     "VALUES ('m', 'r', 'a', 'applied', '[]', '2026-10-13 10:00:00')")
    alembic.upgrade(cfg, "0037")
    with sqlite3.connect(db) as conn:
        # nothing is made up for what was there: no check, nothing offered for a commit
        assert conn.execute("SELECT check_command, git_commit FROM projects").fetchall() == [
            (None, 0)]
        assert conn.execute("SELECT check_state, commit_state FROM merges").fetchall() == [
            (None, None)]
        conn.execute("UPDATE projects SET check_command = 'pytest -q', git_commit = 1")
    alembic.downgrade(cfg, "0036")
    with sqlite3.connect(db) as conn:
        assert [row[1] for row in conn.execute("PRAGMA table_info(projects)")].count(
            "check_command") == 0
        assert "check_state" not in [row[1] for row in conn.execute("PRAGMA table_info(merges)")]
        assert conn.execute("SELECT id, status FROM merges").fetchall() == [("m", "applied")]


def test_a_kept_copy_is_not_told_to_press_run_which_its_card_has_not():
    # B-355's note is for a card that can run the check; a kept copy's cannot.
    from types import SimpleNamespace

    from app.agent import CHECK_PRESS_RUN, _check_is_over
    merge = SimpleNamespace(check={"command": "pytest", "state": "not_run", "note": CHECK_PRESS_RUN})
    _check_is_over(merge)
    assert merge.check == {"command": "pytest", "state": "not_run", "note": None}


def test_a_kept_copy_stored_before_take_in_was_its_word_loses_the_old_note_too():
    from types import SimpleNamespace

    from app.agent import _check_is_over
    from app.agent.merge import CHECK_PRESS_RUN_WAS
    assert CHECK_PRESS_RUN_WAS.endswith("before you Apply")
    merge = SimpleNamespace(check={"command": "pytest", "state": "not_run", "note": CHECK_PRESS_RUN_WAS})
    _check_is_over(merge)
    assert merge.check == {"command": "pytest", "state": "not_run", "note": None}
