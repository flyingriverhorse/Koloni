"""Running git, for the two things KOLONİ uses it for: merging one file's text line by
line (`git merge-file`, on three files of KOLONİ's own - no repository is touched), and
the commit the user asked for with their own click, in their project.

git is looked up anew at each use and started by its full path, never through a shell,
with nothing to read from, a time limit, and an environment that says neither where
KOLONİ keeps its settings nor which repository git is to work on: that is the folder it
is started in, whatever KOLONİ itself was started with.
"""

import contextlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path, PureWindowsPath

from app.executors.winjob import Job
from app.workspace import in_scratch, is_secret, stray_in_koloni

# A merge of one file of at most 1 MiB; a look at a repository.
SHORT_SECONDS = 15.0
# The user's own hooks run in a commit, and may take their time.
COMMIT_SECONDS = 180.0
# How much of what git (or a hook) said is passed on with a refusal.
TAIL = 2000
NOT_FOUND = "git was not found on this machine"
SUBFOLDER = ("the project folder is a subfolder of a git repository: a commit is offered only "
             "where the project is the repository's top folder")
# What would send git to another repository than the one it is started in.
_ELSEWHERE = frozenset({"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"})
# What is under way in a repository while one of these is in its git folder.
_UNDER_WAY = {
    "MERGE_HEAD": "a merge", "CHERRY_PICK_HEAD": "a cherry-pick", "REVERT_HEAD": "a revert",
    "rebase-merge": "a rebase", "rebase-apply": "a rebase", "BISECT_LOG": "a bisect",
}


class Refused(Exception):
    """git could not, or may not, do what was asked: the message says why, for the user."""


def find() -> str | None:
    """Where git is, as a full path; None where there is none. One found in the folder
    KOLONİ happens to stand in comes back as a relative path, and is not taken. Nor is
    a batch file (`.cmd`, `.bat` - a wrapper around git): Windows runs one through its
    command interpreter, which reads the line once more, and an `&` in a file's name or
    in a commit's message would be a command of its own there."""
    found = shutil.which("git")
    if not found or not os.path.isabs(found):
        return None
    # (Windows drops the dots and spaces a name ends with: `git.cmd.` is `git.cmd`.)
    return None if found.rstrip(". ").lower().endswith((".cmd", ".bat")) else found


def run(argv: list[str], cwd: Path, seconds: float, stdin: bytes | None = None, /, *,
        program: str = "git", **more: str) -> tuple[int, bytes, bytes]:
    """Run git (or `program`: gh) to its end: its exit code, what it wrote, and what it said
    beside that. `stdin`: what it reads - a list of paths, which no command line on Windows
    holds a few hundred of. `more`: further variables for its environment. Refused when it cannot be
    started, or does not end in time - then it, and whatever it started (a hook), is killed."""
    process, job = _started(argv, cwd, subprocess.DEVNULL if stdin is None else subprocess.PIPE,
                            subprocess.PIPE, program, more)
    try:
        out, err = process.communicate(stdin, timeout=seconds)
    except subprocess.TimeoutExpired:
        _kill(process, job)
        process.communicate()
        raise Refused(f"{program} did not end within {seconds:.0f} seconds and was stopped"
                      ) from None
    finally:
        if job is not None:
            job.terminate()  # nothing it started is left running; the job is released
    return process.returncode, out, err


def _started(argv: list[str], cwd: Path, stdin: int, stderr: int, program: str,
             more: dict[str, str]) -> tuple[subprocess.Popen, Job | None]:
    """git started as `run` starts it, its output piped: the process, and its job (Windows)."""
    env = {
        key: value for key, value in os.environ.items()
        if not key.upper().startswith("KOLONI_") and key.upper() not in _ELSEWHERE
    }
    # (Windows looks for a program in the folder it is started in first: not here. And
    # a look at the user's repository takes no lock it could do without: it neither
    # rewrites their index nor stands in the way of a git command of their own.)
    env.update({
        "NoDefaultCurrentDirectoryInExePath": "1", "GIT_TERMINAL_PROMPT": "0",
        "GIT_OPTIONAL_LOCKS": "0", **more,
    })
    try:
        process = subprocess.Popen(
            argv, cwd=cwd, env=env, stdin=stdin, stdout=subprocess.PIPE, stderr=stderr,
            start_new_session=sys.platform != "win32",
        )
    except (OSError, ValueError) as exc:
        why = getattr(exc, "strerror", None) or exc
        raise Refused(f"{program} could not be started: {why}") from None
    # In a job of its own (Windows): the whole tree can be ended, as a command's is.
    job = None
    if sys.platform == "win32":
        job = Job.for_process(int(getattr(process, "_handle")))  # noqa: B009
    return process, job


def fed_to(argv: list[str], cwd: Path, seconds: float, take: Callable[[bytes], bool], /,
           **more: str) -> int | None:
    """git started as `run` starts it, what it writes handed to `take` a piece at a time as it
    comes - an output too big to hold (a listing of a tree of a million files): where `take`
    answers False, git and what it started are ended. Its exit code; None: `take` stopped it.
    Refused where it cannot be started or does not end within `seconds`."""
    process, job = _started(argv, cwd, subprocess.DEVNULL, subprocess.DEVNULL, "git", more)
    late = threading.Event()
    timer = threading.Timer(seconds, lambda: (late.set(), _kill(process, job)))
    timer.start()
    try:
        assert process.stdout is not None  # (piped)
        while chunk := os.read(process.stdout.fileno(), 65_536):
            if not take(chunk):
                _kill(process, job)
                process.wait()
                return None
        process.wait()
    except BaseException:  # (`take` failed: git is ended with it, on POSIX too)
        _kill(process, job)
        process.wait()
        raise
    finally:
        timer.cancel()
        if process.stdout is not None:
            process.stdout.close()
        if job is not None:
            job.terminate()
    if late.is_set():
        raise Refused(f"git did not end within {seconds:.0f} seconds and was stopped")
    return process.returncode


def _kill(process: subprocess.Popen, job: Job | None) -> None:
    if job is not None:
        job.terminate()
    elif sys.platform != "win32":
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(process.pid, signal.SIGKILL)
    with contextlib.suppress(OSError):
        process.kill()


def merge_file(
    folder: Path, project: bytes, base: bytes, agent: bytes, favour: str | None = None
) -> tuple[int, bytes]:
    """Merge the changes from `base` to `agent` into `project`, line by line, as git does
    it: `git merge-file -p project base agent` on three files written into a new folder
    in `folder` (a folder of KOLONİ's own; git looks for no repository in it or above
    it), which is gone afterwards. Returns git's exit code and the merged bytes: 0 where
    everything went together, the number of clashes (up to 127) where the same lines
    changed on both sides - the output then has git's marks in it - and anything else
    where git could not merge at all (a file that is not text). `favour`: "ours" takes
    the project's lines at each clash and "theirs" the agent's; whatever went together
    is kept either way. Refused where git is not there, or does not run."""
    git = find()
    if git is None:
        raise Refused(NOT_FOUND)
    try:
        # (A folder that cannot be deleted right now is no failed merge: it is in the
        # copy's own folder, and goes with it.)
        with tempfile.TemporaryDirectory(
            dir=folder, prefix="merge-", ignore_cleanup_errors=True
        ) as held:
            for name, data in (("project", project), ("base", base), ("agent", agent)):
                (Path(held) / name).write_bytes(data)
            code, out, _said = run(
                [git, "merge-file", "-p", *([f"--{favour}"] if favour else []),
                 "project", "base", "agent"],
                Path(held), SHORT_SECONDS, GIT_CEILING_DIRECTORIES=str(folder),
            )
    except OSError as exc:
        raise Refused(f"the files to merge could not be written: {exc.strerror or exc}") from None
    return code, out


def _in(project: Path, git: str, *args: str, seconds: float = SHORT_SECONDS, **more: str):
    """git in the user's project. Its file-watching hook is not started (a repository's
    settings name the program), a folder that only holds a git folder's own files is no
    repository to it (`repository`), and a path is a path, whatever characters it has.
    `more`: further variables for its environment (`run`)."""
    return _fed(project, git, None, *args, seconds=seconds, **more)


def _fed(project: Path, git: str, stdin: bytes | None, /, *args: str,
         seconds: float = SHORT_SECONDS, **more: str):
    """`_in`, with `stdin` for git to read."""
    return run(
        [git, "-c", "core.fsmonitor=false", "-c", "safe.bareRepository=explicit",
         "--literal-pathspecs", *args],
        project, seconds, stdin, **more,
    )


def _nul(paths: Iterable[str]) -> bytes:
    """Paths for git to read, each ended by a NUL (`-z`, `--pathspec-file-nul`)."""
    return b"".join(path.encode("utf-8", "surrogateescape") + b"\0" for path in paths)


def _text(*said: bytes) -> str:
    return "\n".join(part.decode("utf-8", "replace").strip() for part in said if part.strip())


def repository(project: Path, seconds: float = SHORT_SECONDS) -> tuple[str, Path]:
    """git, and the git folder of the repository whose top folder the project is.
    Refused, with why, where git is not there or the project is not such a folder.

    Such a folder has a `.git` of its own: a folder or - a linked worktree, a submodule -
    the file that says where its git folder is. git by itself would also take a folder
    that merely holds a git folder's files (HEAD, config, objects, refs) for one, and
    run what that config names: files of any name, which an agent may write and have
    taken. A `.git` is never taken from a working copy (`copies.NOT_COPIED`), and git is
    told the same (`_in`)."""
    git = find()
    if git is None:
        raise Refused(NOT_FOUND)
    if not os.path.lexists(project / ".git"):
        # (Looked for, not asked of git: the project's own files are no git folder to it.)
        raise Refused(
            SUBFOLDER if any(os.path.lexists(above / ".git") for above in project.parents)
            else "the project folder is not the top folder of a git repository")
    code, out, _said = _in(project, git, "rev-parse", "--show-toplevel", "--absolute-git-dir",
                           seconds=seconds)
    lines = out.decode("utf-8", "replace").splitlines()
    if code != 0 or len(lines) != 2:
        raise Refused("the project folder is not in a git repository")
    # (Each as it really is - a link, a short name -: git has been in its top folder already,
    # and the project's is KOLONİ's own record; neither is a path an agent wrote.)
    top, here = (os.path.normcase(os.path.realpath(one)) for one in (lines[0], project))
    if top != here:
        raise Refused("the project folder is not the top folder of its git repository")
    return git, Path(lines[1])


def summary(project: Path, sha: str) -> str | None:
    """What `git show --stat` says of a commit: the files it changed and by how many
    lines - what it holds, not the working tree, where the user's own edits stay (B-319).
    None where git does not say. Refused where the project is no repository (`repository`)."""
    git, _folder = repository(project)
    # (Taken by itself after a commit: it runs nothing of the repository's either - no
    # filter, no hook of an index it would write again, no fetch.)
    code, out, _said = _in(
        project, git, *UNASKED, "-c", "log.showRoot=true", "-c", "core.quotePath=false",
        "show", "--format=", "--stat=100", "--no-color", "--no-show-signature", "--no-ext-diff",
        "--no-textconv", "--ignore-submodules=all",
        sha, "--",
        seconds=SHORT_SECONDS, **UNASKED_ENV, **_no_filters(project, git, SHORT_SECONDS),
    )
    return _text(out)[-TAIL:] or None if code == 0 else None


# What a commit card says of a file that did not go in as the agent's change alone (`commit`).
IGNORED = "git ignores it"
STAGED = ("you have changes staged in it that the file in the project does not hold: commit "
          "or unstage them first")
NOT_THERE = "the agent's change is no longer in it as the project has it"
# A commit's own index older than this is left over from one that never ended (`commit`).
STALE_SECONDS = 3600.0


def commit(  # noqa: C901
    project: Path, paths: list[str], message: str, no_hooks: Path | None = None,
    sides: dict[str, tuple[Path | None, Path | None]] | None = None,
) -> tuple[str, list[str]]:
    """Commit the agent's part of these files of the project, and nothing else, as the
    user. The commit is made from an index of its own (HEAD, and each file as HEAD has it
    with the agent's change put in): what the user staged of other files stays staged and
    out of it, and their own edits in these files stay in the working tree, not committed.
    The agent's change: from what the file held just before it was taken to just after
    (`sides`: files of KOLONİ's that hold those bytes; None for a side without the file).

    Not as the agent's change alone - and said, in the sentences that come back with the
    commit's id, for its card: a file with no `sides`, or whose change does not go onto
    HEAD's file by itself (the user's own edits touch the same lines, or it is not text),
    goes in whole, as the working tree has it. Left out: a new file git ignores; one whose
    working-tree file no longer holds the agent's change (taken back, written over); one
    the user staged something in that the working tree does not hold - setting the index
    again would lose it. A commit hook that changed what went in is named. Afterwards the
    real index has the committed paths as the commit does (a staged edit of the user's in
    one of them is unstaged, in the working tree still); where git would not, that is said.

    The repository's own identity and its own hooks: it is the user's commit - but for
    `no_hooks`, the user's choice where an agent changed them (K-yazma-denetimi): git's
    hooks folder is then an empty one, made in that folder of KOLONİ's for this commit
    alone (not in the temp folder, which a sandboxed CLI may write). Refused, with why,
    where it cannot be made; the files then stay as they are."""
    git, folder = repository(project)
    if _in(project, git, "symbolic-ref", "-q", "HEAD")[0] != 0:
        raise Refused("HEAD is not on a branch")
    under_way = next((what for name, what in _UNDER_WAY.items() if (folder / name).exists()), None)
    if under_way:
        raise Refused(f"{under_way} is under way in the repository: finish or abort it first")
    if no_hooks is not None:
        no_hooks.mkdir(parents=True, exist_ok=True)
    for stale in folder.glob("koloni-index-*"):
        with contextlib.suppress(OSError):
            if time.time() - stale.stat().st_mtime > STALE_SECONDS:
                stale.unlink()
    # (In the git folder, which agents are kept from: not the temp folder.)
    index = folder / f"koloni-index-{os.urandom(8).hex()}"
    alone = {"GIT_INDEX_FILE": str(index)}
    try:
        with tempfile.TemporaryDirectory(prefix="no-hooks-", dir=no_hooks) as empty:
            # (Each index write too: a post-index-change hook runs there.)
            hooks = ("-c", f"core.hooksPath={empty}") if no_hooks is not None else ()

            def fed(what: str, stdin: bytes | None, /, *args: str, **more: str) -> bytes:
                code, out, said = _fed(project, git, stdin, *hooks, *args,
                                       seconds=COMMIT_SECONDS, **more)
                if code != 0:
                    raise Refused(f"git {what} failed: {_text(out, said)[-TAIL:]}")
                return out

            def must(what: str, *args: str, **more: str) -> bytes:
                return fed(what, None, *args, **more)

            born = _in(project, git, "rev-parse", "-q", "--verify", "HEAD")[0] == 0
            put, whole, left = _agents_parts(project, git, paths, sides or {}, fed, born)
            notes = ([f"{', '.join(whole)} went in whole, as the project has "
                      f"{'it' if len(whole) == 1 else 'them'}: any edits of your own there went "
                      "into this commit too"] if whole else [])
            notes += [f"{path} was left out of the commit: {why}" for path, why in left.items()]
            if born and (folder / "index").exists():
                # The user's index for what it knows of each file (none is read again for
                # nothing), with HEAD's content alone in it. Its own time too: git reads a
                # file changed in the second the index was written again, not by its stat
                # alone (racy git); a copy timed later took a same-size rewrite as unchanged.
                shutil.copy2(folder / "index", index)
            must("read-tree", "read-tree", *(["--reset", "HEAD"] if born else ["--empty"]), **alone)
            # (Every list of paths on stdin: Windows' command line holds a few hundred at most.)
            gone = [path for path, _mode, blob in put if blob is None]
            if known := [(path, mode, blob) for path, mode, blob in put if blob]:
                fed("update-index", b"".join(f"{mode} {blob}\t".encode("ascii") + _nul([path])
                                             for path, mode, blob in known),
                    "update-index", "--add", "-z", "--index-info", **alone)
            if gone:
                fed("update-index", _nul(gone), "update-index", "--force-remove", "-z", "--stdin",
                    **alone)
            if whole:
                fed("add", _nul(whole), "update-index", "--add", "--remove", "-z", "--stdin",
                    **alone)
            if _in(project, git, "diff", "--cached", "--quiet", "--no-ext-diff",
                   seconds=SHORT_SECONDS, **alone)[0] == 0:
                raise Refused("; ".join([
                    "there is nothing to commit: these files are as the last commit has them",
                    *notes]))
            tree = must("write-tree", "write-tree", **alone).decode("ascii").strip()
            must("commit", "commit", "-m", message, **alone)
            code, out, _said = _in(project, git, "rev-parse", "HEAD")
            if code != 0 or not out.strip():
                raise Refused("the commit was made, but its id could not be read")
            sha = out.decode("ascii", "replace").strip()
            # What a commit hook put in, or took out, besides.
            code, out, _said = _in(project, git, "diff-tree", "-r", "-z", "--name-only",
                                   "--no-renames", tree, sha)
            changed = [one.decode("utf-8", "surrogateescape") for one in out.split(b"\0") if one]
            if code != 0 or changed:
                notes.append(f"a commit hook changed what went in: {', '.join(changed)}"
                             if code == 0 else "what a commit hook changed could not be read")
            back = [path for path in paths if path not in left]
            back += [path for path in changed if path not in back]
            # The real index has these paths as the commit does; the commit stands whatever
            # this says (the user's own git may hold the index right now).
            if _fed(project, git, _nul(back), *hooks, "reset", "-q", "--pathspec-from-file=-",
                    "--pathspec-file-nul", seconds=COMMIT_SECONDS)[0] != 0:
                named = " ".join(f'"{path}"' if " " in path else path for path in back)
                notes.append(f"KOLONİ couldn't update git's index: run `git reset -- {named}`")
    finally:
        for stale in (index, index.with_name(index.name + ".lock")):
            with contextlib.suppress(OSError):
                stale.unlink()
    return sha, notes


def _agents_parts(  # noqa: C901
    project: Path, git: str, paths: list[str], sides: dict, fed, born: bool
) -> tuple[list, list, dict]:
    """For `commit`: each file as HEAD has it with the agent's change put in, as (path,
    mode, blob id; None: no file); the paths that go in whole instead; and those left out,
    with why. Each file is written into git's objects as `git add` would (the repository's
    filters and line ends, by path), and the agent's change put onto another with `git
    merge-file` (git 2.43 or later)."""

    def entries(out: bytes) -> dict[str, list[str]]:
        found = {}
        for entry in out.split(b"\0"):
            if entry:
                fields, _tab, name = entry.partition(b"\t")
                found[name.decode("utf-8", "surrogateescape")] = fields.decode("ascii").split()
        return found

    def merged(ours: str | None, base: str | None, theirs: str | None) -> str | None:
        if ours is None or base is None or theirs is None:
            return None
        code, out, _said = _in(project, git, "merge-file", "--object-id", ours, base, theirs,
                               seconds=COMMIT_SECONDS)
        # (Lines both changed, not text, or a git before 2.43: None.)
        return out.decode("ascii", "replace").strip() if code == 0 else None

    # (All of them, and these paths picked out: no command line on Windows holds a few hundred.
    # `-t`: a folder of that name too, as `ls-tree HEAD -- folder` has it.)
    tree = entries(fed("ls-tree", None, "ls-tree", "-r", "-t", "-z", "HEAD")) if born else {}
    heads = {path: (tree[path][0], tree[path][2]) for path in paths if path in tree}
    # (The user's own index: what they staged.)
    index = entries(fed("ls-files", None, "ls-files", "-s", "-z"))
    staged = {path: index[path][1] for path in paths if path in index}
    left = {}
    for path in paths:
        if path in heads:
            continue
        # As `git add` has it: a file the index does not track that .gitignore leaves out is
        # not added. (One at a time: the answer is the exit code. Not `_in`: check-ignore
        # refuses --literal-pathspecs; "./" keeps a leading ":" from being pathspec magic.)
        code, out, said = run(
            [git, "-c", "core.fsmonitor=false", "-c", "safe.bareRepository=explicit",
             "check-ignore", "-q", "--", f"./{path}"], project, COMMIT_SECONDS)
        if code not in (0, 1):
            raise Refused(f"git check-ignore failed: {_text(out, said)[-TAIL:]}")
        if code == 0:
            left[path] = IGNORED
    there = [path for path in paths if path not in left and (project / path).is_file()]
    # (A line each, quoted as C has it: a newline in a name, or a quote first, is the name's.)
    quoted = "".join('"{}"\n'.format(path.replace("\\", "\\\\").replace('"', '\\"').replace(
        "\n", "\\n").replace("\r", "\\r")) for path in there)
    found = iter(fed("hash-object", quoted.encode("utf-8", "surrogateescape"), "hash-object",
                     "-w", "--stdin-paths").decode("ascii").split() if there else [])
    now = {path: next(found, None) for path in there}
    put, whole = [], []
    for path in paths:
        if path in left:
            continue
        mode, head = heads.get(path, (None, None))
        here = now.get(path)
        if path in staged and staged[path] not in (head, here):
            left[path] = STAGED
            continue
        files = [str(side) for side in sides.get(path, ()) if side is not None]
        code, out, _said = _in(project, git, "hash-object", "-w", f"--path={path}", "--", *files,
                               seconds=COMMIT_SECONDS) if files else (0, b"", b"")
        ids = iter(out.decode("ascii", "replace").split())
        if path not in sides or code != 0:
            whole.append(path)
            continue
        before, after = (next(ids, None) if side is not None else None for side in sides[path])
        # The agent's change is in the file as the project has it now, or nothing is committed.
        # (A file it made, written to since: whether it still is cannot be told - whole.)
        if here != after and before is None and None not in (here, after):
            whole.append(path)
            continue
        if here != after and (None in (here, before, after) or merged(here, before, after) != here):
            left[path] = NOT_THERE
            continue
        if mode is None:  # a new file: as the working tree has it (no such bit on Windows)
            mode = "100755" if here and os.name != "nt" and os.stat(
                project / path).st_mode & 0o100 else "100644"
        if before == head:  # nothing of the user's in it: the agent's file is the commit's
            put.append((path, mode, after))
        elif None in (before, after, head) or mode not in ("100644", "100755") or not (
                together := merged(head, before, after)):
            whole.append(path)
        else:
            put.append((path, mode, together))
    return put, whole, left


# --- a look at the project's git, read only (slice 70) -------------------------------------
# The top bar, the map and a turn's start and end look by themselves: a repository that does
# not answer within this, all its commands together, shows no git.
LOOK_SECONDS = 5.0
# shortcut: only the branches committed to last are compared with the project's (one
# rev-list each); page through the rest if a repository with more is asked about.
MOST_BRANCHES = 10
# shortcut: the map lists this many branches, local and remote-tracking, the latest first; add
# a "more" row if a repository with more is met.
MOST_LISTED = 50
# K-dallar: each branch, local and remote-tracking (as last fetched - KOLONİ fetches nothing),
# the latest commit first: its full name, whether it only points at another (origin/HEAD), its
# last commit's short id and time, and its subject - last, so a tab in it stays in it.
REFS = ("for-each-ref", "--sort=-committerdate",
        "--format=%(refname)%09%(symref)%09%(objectname:short)%09%(committerdate:iso-strict)"
        "%09%(contents:subject)", "refs/heads/", "refs/remotes/")
FILTER_KEYS = ("clean", "smudge", "process")
# What every look KOLONİ takes by itself is given (`summary` too; never the user's own
# commit): no object is fetched from a promisor remote of a partial clone - which would run
# the remote's upload-pack, or ssh, as its settings name - and no transport may be used at all.
# shortcut (security): git still reads the files its settings or .git name - include.path,
# core.excludesFile, core.attributesFile, objects/info/alternates, a worktree's gitdir,
# core.worktree -, and one on a network path makes it reach that host; no setting turns that
# off. Writing such a file takes writing .git/, which agents are kept from
# (NOT_WRITTEN_UNATTENDED, `copies.NOT_COPIED`) - by name; written unnamed, .git/config and
# .git/hooks are put back after the command (K-yazma-denetimi), but objects/info/alternates is
# not looked at; look at those files first if that changes.
UNASKED = ("-c", "protocol.allow=never")
UNASKED_ENV = {"GIT_NO_LAZY_FETCH": "1"}


def _no_filters(project: Path, git: str, seconds: float) -> dict[str, str]:
    """Settings, as environment variables, that turn off every filter driver the
    repository's settings name: a
    look git takes by itself (status, diff) runs no program of the repository's, as a
    file it finds changed would otherwise go through its clean filter. Listing them runs
    nothing. Not for the user's own commit (`commit`): that keeps the repository's filters.
    shortcut: a file a filter keeps (Git LFS) may be counted as changed here; read its
    pointer instead if users are misled by it."""
    code, out, _said = _in(project, git, *UNASKED, "config", "--name-only", "--get-regexp",
                           r"^filter\.", seconds=seconds, **UNASKED_ENV)
    names = sorted({
        line.strip()[len("filter."):].rpartition(".")[0]
        for line in out.decode("utf-8", "replace").splitlines() if line.strip()
    } if code == 0 else set())
    # (Not `-c`: that is cut at the first "=", and a driver's name may hold one.)
    pairs = [(f"filter.{name}.{key}", "") for name in names if name for key in FILTER_KEYS]
    pairs += [(f"filter.{name}.required", "false") for name in names if name]
    return {"GIT_CONFIG_COUNT": str(len(pairs)),
            **{f"GIT_CONFIG_KEY_{n}": key for n, (key, _value) in enumerate(pairs)},
            **{f"GIT_CONFIG_VALUE_{n}": value for n, (_key, value) in enumerate(pairs)}}


def _left(until: float) -> float:
    """What is left of a look's time (`until`, on the monotonic clock); Refused once spent."""
    left = until - time.monotonic()
    if left <= 0:
        raise Refused(f"git did not answer within {LOOK_SECONDS:.0f} seconds")
    return left


def _said(project: Path, git: str, until: float, *args: str, **more: str) -> str | None:
    """What a read-only git command wrote (`UNASKED`); None where it did not end well.
    Refused once the look's time (`until`, on the monotonic clock) is spent."""
    code, out, _said = _in(project, git, *UNASKED, *args, seconds=_left(until), **UNASKED_ENV,
                           **more)
    return out.decode("utf-8", "replace") if code == 0 else None


def _worktrees(listed: str) -> list[dict]:
    """`worktree list --porcelain` as {path, branch}: branch None where its HEAD is on none."""
    found: list[dict] = []
    for block in listed.replace("\r\n", "\n").split("\n\n"):
        lines = dict(line.partition(" ")[::2] for line in block.splitlines() if line)
        if "worktree" in lines and "bare" not in lines:
            branch = lines.get("branch", "")
            found.append({"path": lines["worktree"],
                          "branch": branch.removeprefix("refs/heads/") or None})
    return found


# The project's branches, the latest commit first: a name and its last commit's time.
BRANCHES = ("for-each-ref", "--sort=-committerdate",
            "--format=%(refname:lstrip=2)%09%(committerdate:iso-strict)", "refs/heads/")


def _where(project: Path, git: str, until: float) -> dict | None:
    branch = _said(project, git, until, "branch", "--show-current")
    listed = _said(project, git, until, "worktree", "list", "--porcelain")
    rows = _said(project, git, until, *BRANCHES)
    if branch is None or listed is None or rows is None:
        return None
    # (Nothing of the commit is read: a signature on it is never checked here.)
    head = _said(project, git, until, "rev-parse", "--verify", "-q", "HEAD")  # None: no commit
    dates = dict(row.partition("\t")[::2] for row in rows.splitlines() if row)
    return {"branch": branch.strip(), "head": (head or "").strip() or None,
            "worktrees": _worktrees(listed), "names": list(dates), "dates": dates}


def _looking(project: Path, above: bool = False) -> tuple[str, float]:
    """git, and when the look's time is up - Refused where the project shows no git. `above`:
    a subfolder of a repository shows it too (`_above`)."""
    until = time.monotonic() + LOOK_SECONDS
    return (_above(project, LOOK_SECONDS) if above
            else repository(project, LOOK_SECONDS)[0]), until


def _above(project: Path, seconds: float) -> str:
    """git, where the project is a repository's top folder (`repository`) or a folder in one
    whose top folder has a `.git` of its own - for what a working copy holds, never a commit.
    Refused where it is neither.
    shortcut: a project in a home folder that is a dotfiles repository (`*` ignored) is copied
    with what that repository tracks of it; ask before copying so if that is ever seen."""
    try:
        return repository(project, seconds)[0]
    except Refused as exc:
        if str(exc) != SUBFOLDER:
            raise
    git = find()
    if git is None:
        raise Refused(NOT_FOUND)
    code, out, _said = _in(project, git, *UNASKED, "rev-parse", "--show-toplevel",
                           seconds=seconds, **UNASKED_ENV)
    top = out.decode("utf-8", "replace").strip()
    if code != 0 or not top or not os.path.lexists(Path(top) / ".git") or not Path(
            os.path.realpath(project)).is_relative_to(os.path.realpath(top)):
        raise Refused("the project folder is not in a git repository")
    return git


def where(project: Path) -> dict | None:
    """Where the project stands in git, as a turn's start and end are compared: its branch
    ("" where HEAD is on none), its last commit, its worktrees and its branches' names.
    None where it shows no git: not a repository's top folder (`repository`), no git, or
    one that does not answer in time. Only reads, and runs no program the repository names.
    shortcut: a project in a subfolder of a repository shows no git, as it is offered no
    commit (`repository`); read the repository above it if users of monorepos miss it."""
    try:
        return _where(project, *_looking(project))
    except Refused:
        return None


RECENT = 5  # commits a new conversation's lead is told of (K-devir-3)


def recent(project: Path) -> list[tuple[str, str, str]] | None:
    """The project's last RECENT commits, newest first, each (short id, when, subject) as
    git's log says them - the subject is the repository's words. A look as `where` takes
    one: read only, in its time. None where it shows no git, or has no commit yet."""
    try:
        git, until = _looking(project)
        said = _said(project, git, until, "log", f"-{RECENT}", "--date=format:%d %b %H:%M",
                     "--format=%h%x09%cd%x09%s")
    except Refused:
        return None
    return [(sha, when, subject) for sha, when, subject in (
        line.split("\t", 2) for line in (said or "").splitlines() if line.count("\t") >= 2)
    ] or None


def look(project: Path) -> dict | None:
    """The project's git for the top bar and the map, read only: `where`, how many files
    are changed and not committed, its branch's last commit (`current`), and each other
    branch, local or remote-tracking (the latest `MOST_LISTED`), with its last commit - the
    latest `MOST_BRANCHES` also against the project's: ahead, behind -, whether it is joined
    (merged into it) and its worktree's folder. None as for `where`.

    A branch's name is the repository's, which an agent may have written: it is never
    given to git as it is - `refs/heads/<name>` cannot be taken for an option."""
    try:
        git, until = _looking(project)
        seen = _where(project, git, until)
        if seen is None:
            return None
        off = _no_filters(project, git, _left(until))
        status = _said(project, git, until, "status", "--porcelain",
                       "--ignore-submodules=all", **off)
        rows = _said(project, git, until, *REFS)
        if status is None or rows is None:
            return None
        joined = set((_said(project, git, until, "for-each-ref", "--merged=HEAD",
                            "--format=%(refname)", "refs/heads/", "refs/remotes/") or ""
                      ).split()) if seen["head"] else set()
        folders = {one["branch"]: one["path"] for one in seen["worktrees"] if one["branch"]}
        branches, current = [], None
        for row in rows.splitlines():
            ref, symref, sha, at, subject = (row.split("\t", 4) + [""] * 5)[:5]
            if symref or not ref.startswith(("refs/heads/", "refs/remotes/")):
                continue
            remote = ref.startswith("refs/remotes/")
            name = ref.removeprefix("refs/remotes/" if remote else "refs/heads/")
            one = {"name": name, "ref": ref, "remote": remote, "sha": sha or None,
                   "subject": subject.strip() or None, "last_at": at or None,
                   "joined": ref in joined, "worktree": None if remote else folders.get(name)}
            if not remote and name == seen["branch"]:
                current = {**one, "ahead": 0, "behind": 0}
                continue
            if len(branches) == MOST_LISTED:
                break
            counts = _said(project, git, until, "rev-list", "--left-right", "--count",
                           f"HEAD...{ref}") if seen["head"] and len(branches) < MOST_BRANCHES \
                else None
            # (left: the project's commits the branch lacks; right: the branch's own)
            behind, ahead = (int(n) for n in counts.split()) if counts else (None, None)
            branches.append({**one, "ahead": ahead, "behind": behind})
    except Refused:
        return None
    here = folder_key(str(project), project)
    return {**seen, "changed": len(status.splitlines()), "branches": branches,
            "current": current,
            "worktrees": [{**one, "here": folder_key(one["path"], project) == here}
                          for one in seen["worktrees"]]}


def state(project: Path) -> str | None:
    """How the project's repository stands, as one text that changes when anything in it
    does (K-tetik-degismedi): its HEAD, what `git status` lists, and the size and time of
    each file listed (a file changed again is listed the same). A look as `look` takes one:
    one look's time for all of it, read only, and no program of the repository's runs (no
    filter, no fetch). None where it shows no git (`where`).
    shortcut: a submodule counts by its commit (`--ignore-submodules=dirty`, which also
    keeps git out of its folder): an edit inside one that is not committed there changes
    nothing here; look into submodules, with their own filters off, if that is missed."""
    try:
        git, until = _looking(project)
        head = _said(project, git, until, "rev-parse", "--verify", "-q", "HEAD")  # None: none
        off = _no_filters(project, git, _left(until))
        listed = _said(project, git, until, "status", "--porcelain=v1", "-z", "--no-renames",
                       "--untracked-files=all", "--ignore-submodules=dirty", **off)
    except (Refused, OSError, ValueError):
        return None
    if listed is None:
        return None
    lines = [(head or "").strip()]
    for entry in listed.split("\0"):
        if len(entry) < 4 or in_scratch(entry[3:]):
            continue
        try:
            info = os.lstat(project / entry[3:])
            lines.append(f"{entry}\t{info.st_size}\t{info.st_mtime_ns}")
        except (OSError, ValueError):
            lines.append(f"{entry}\tgone")
    return "\n".join(lines)


def _letter(xy: str) -> str:
    """One letter for a `status --porcelain` entry's two columns, as the Workspace marks a
    change: D over the rest, R by its new path, A (a copy too), ? untracked, else M."""
    if xy == "??":
        return "?"
    if "D" in xy:
        return "D"
    if xy[0] == "R":
        return "R"
    return "A" if "A" in xy or xy[0] == "C" else "M"


def changes(project: Path) -> list[dict] | None:
    """The files changed in the working tree and not committed, for the Workspace's Changes
    tab (K-degisenler): each by its path from the project (git's own slashes) and one letter
    (`_letter`), sorted by path; untracked files one by one, ignored ones not at all, nor a
    secret by its name (`is_secret`: the tree hides it too). A look as `look` takes one: read
    only, no program of the repository's runs. None where the project shows no git (`where`),
    or git does not answer in time.
    shortcut: one look's time (LOOK_SECONDS) for the status of a big repository too - past
    it the tab falls back to KOLONİ's record; give the tab its own, longer time if that is seen.
    shortcut: every row is sent (100k untracked files: one list, one render); cap it as
    `project_files.MOST_LISTED` caps a folder if that is seen."""
    try:
        git, until = _looking(project)
        off = _no_filters(project, git, _left(until))
        listed = _said(project, git, until, "status", "--porcelain=v1", "-z",
                       "--untracked-files=all", "--ignore-submodules=all", **off)
    except Refused:
        return None
    if listed is None:
        return None
    found: list[dict] = []
    entries = iter(listed.split("\0"))
    for entry in entries:
        if len(entry) < 4:
            continue
        if not is_secret(entry[3:]) and not in_scratch(entry[3:]) and not stray_in_koloni(
                entry[3:]):
            found.append({"path": entry[3:], "status": _letter(entry[:2])})
        if entry[0] in "RC":
            next(entries, None)  # (the path it was renamed or copied from)
    return sorted(found, key=lambda one: one["path"])


def diff(project: Path, rel: str) -> str | None:
    """One file's unified diff against HEAD, whole (every unchanged line in it, as a
    file change's diff is read whole) - read only, as `changes`. None where HEAD has nothing
    to compare it with: untracked, or no commit yet - the whole file is the change then.
    Refused where the project shows no git, or git does not answer in time.
    shortcut: a file renamed and changed shows as all added (its diff is against its new
    name only); ask `status` for the old name and diff against `HEAD:<old>` if that misleads.
    shortcut: `ls-files` matches the name as given - on Windows a hand-typed `HELLO.PY` for a
    tracked `hello.py` shows as all added (the tab itself sends git's own spelling).
    shortcut: git writes the whole `--unified` diff before its size is checked (`diff_of`) -
    a huge file shrunk or deleted is piped into memory till then, bounded by the look's time;
    ask `cat-file -s HEAD:<rel>` first if that is seen."""
    git, until = _looking(project)
    off = _no_filters(project, git, _left(until))
    # (HEAD's files too: a deletion staged with `git rm` is in neither index nor tree.)
    named = _said(project, git, until, "ls-files", "-z", "--with-tree=HEAD", "--", rel)
    if not named:
        return None
    # (A pathspec: a folder - gone from disk too - would bring every file in it, a secret too.)
    if set(named.split("\0")) - {""} != {rel}:
        raise Refused("not one file of the project")
    return _said(project, git, until, "diff", "HEAD", "--no-color", "--no-ext-diff",
                 "--no-textconv", "--ignore-submodules=all", "--unified=1000000", "--", rel,
                 **off)


# --- a branch, read without switching to it (K-dallar) ---------------------------------------
# Looks as `look` takes them: read only, in one look's time, no program of the repository's run
# (no filter, textconv or external diff, no fetch). Nothing is checked out, nothing written.


def _branch(project: Path, ref: str) -> tuple[str, float]:
    """git and the look's time for one of the project's branches by its full name (`look`'s
    `ref`). Refused for any other name: what is handed to git is a name it listed, and one
    that starts with "refs/" is never taken for an option."""
    git, until = _looking(project)
    listed = _said(project, git, until, "for-each-ref", "--format=%(refname)", "refs/heads/",
                   "refs/remotes/")
    if listed is None or ref not in listed.splitlines():
        raise Refused("no such branch")
    return git, until


def _tree(said: str) -> list[tuple[str, str, str, str, str]]:
    """`ls-tree -z --long` as (mode, type, object id, size, name)."""
    found = []
    for entry in said.split("\0"):
        fields, tab, name = entry.partition("\t")
        if tab and len(parts := fields.split()) == 4:
            mode, kind, blob, size = parts
            found.append((mode, kind, blob, size, name))
    return found


def folder_at(project: Path, ref: str, rel: str) -> list[dict] | None:
    """One folder of a branch ("" its top), as the Files window lists one: each entry's name,
    kind ("dir", "file") and size - a link or a submodule left out, as a link is in the
    project. None where the branch has no such folder. Refused as `_branch`."""
    git, until = _branch(project, ref)
    said = _said(project, git, until, "ls-tree", "-z", "--long", f"{ref}:{rel}")
    if said is None:
        return None
    return [{"name": name, "kind": "dir" if kind == "tree" else "file",
             "size": None if kind == "tree" else int(size)}
            for mode, kind, _id, size, name in _tree(said)
            if kind in ("tree", "blob") and mode != "120000"]


def file_at(project: Path, ref: str, rel: str, most: int) -> bytes | int | None:
    """A file of a branch: its bytes - or only its size, where that is over `most` (nothing
    is read then). None where the branch has no such file: a folder, a link or a submodule is
    none. Refused as `_branch`."""
    git, until = _branch(project, ref)
    said = _said(project, git, until, "ls-tree", "-z", "--long", ref, "--", rel)
    found = [entry for entry in _tree(said or "") if entry[4] == rel]
    if not found or found[0][1] != "blob" or found[0][0] == "120000":
        return None
    _mode, _kind, blob, size, _name = found[0]
    if int(size) > most:
        return int(size)
    code, out, _err = _in(project, git, *UNASKED, "cat-file", "blob", blob,
                          seconds=_left(until), **UNASKED_ENV)
    return out if code == 0 else None


def changes_at(project: Path, ref: str) -> list[dict] | None:
    """What a branch changed since it left the project's (`git diff HEAD...<ref>`), for the
    Changes tab as `changes` lists the working tree's - no secret by its name, no link or
    submodule on either side. None with no commit of the project's to compare from. Refused
    as `_branch`."""
    git, until = _branch(project, ref)
    said = _said(project, git, until, "diff", "--raw", "-z", "--no-renames", "--no-ext-diff",
                 "--no-textconv", "--ignore-submodules=all", f"HEAD...{ref}")
    if said is None:
        return None
    parts = said.split("\0")
    found = []
    # (each ":<old mode> <new mode> <old id> <new id> <letter>", then its path)
    for fields, path in zip(parts[::2], parts[1::2], strict=False):
        words = fields.lstrip(":").split()
        if len(words) == 5 and path and not is_secret(path) and not {
                "120000", "160000"} & set(words[:2]):
            found.append({"path": path, "status": words[4] if words[4] in "AD" else "M"})
    return sorted(found, key=lambda one: one["path"])


def diff_at(project: Path, ref: str, rel: str) -> str | None:
    """One file's diff from the project's branch to `ref` since they parted (`HEAD...<ref>`),
    whole, as `diff` reads one. None with no commit to compare from. Refused as `_branch`.
    Refused for a path that is not one file it lists (`changes_at`): git takes it for a
    pathspec, and a folder would bring every file in it, a secret too.
    shortcut: as `diff`, the whole diff is piped before its size is checked."""
    listed = changes_at(project, ref)
    if listed is None:
        return None
    if rel not in {one["path"] for one in listed}:
        raise Refused("not a file this branch changed")
    git, until = _branch(project, ref)
    return _said(project, git, until, "diff", "--no-color", "--no-ext-diff", "--no-textconv",
                 "--ignore-submodules=all", "--unified=1000000", f"HEAD...{ref}", "--", rel)


def unsaved(project: Path) -> str | None:
    """Why git keeps the project's branch where it is, in words, from the git map's Switch
    (K-dallar): a merge or the like under way, or files changed and not committed - untracked
    ones one by one, a secret too, none in the agents' scratch -, or git that did not say. None
    for none of these. A look as `look` takes one."""
    # (Not taken for clean: `git switch` carries uncommitted edits onto the other branch.)
    silent = "git did not say in time whether files are changed — try again"
    try:
        git, folder = repository(project, LOOK_SECONDS)
        until = time.monotonic() + LOOK_SECONDS
        off = _no_filters(project, git, _left(until))
        listed = _said(project, git, until, "status", "--porcelain=v1", "-z",
                       "--untracked-files=all", "--ignore-submodules=dirty", **off)
    except Refused:
        return silent
    if listed is None:
        return silent
    under_way = next((what for name, what in _UNDER_WAY.items() if (folder / name).exists()), None)
    if under_way:
        return f"{under_way} is under way in the repository — finish or abort it first"
    entries, changed = iter(listed.split("\0")), 0
    for entry in entries:
        changed += len(entry) > 3 and not in_scratch(entry[3:])
        if entry[:1] in ("R", "C"):
            next(entries, None)  # (the path it was renamed or copied from)
    if not changed:
        return None
    return (f"{changed} {'file' if changed == 1 else 'files'} changed, not saved in git — commit "
            "or set aside first")


def switch(project: Path, name: str, new: bool, no_hooks: Path) -> None:
    """Switch the project to its branch `name` - or to a new one of that name, made where it
    stands (`new`) -, the user's own click in the git map. No hook of the repository's runs:
    git's hooks folder is an empty one made in `no_hooks` (a folder of KOLONİ's, as `commit`
    makes one) - a post-checkout hook, or a `core.hooksPath` folder in the project an agent
    may have written, would run unlooked at. A file git ignores that the branch has is not
    written over (--no-overwrite-ignore: the user's own `.env`). Refused, with why, for a name
    git does not take for a branch, one that is no branch of the project (a remote's is not
    made into one: --no-guess), and where git will not - a file in the way, the branch open
    in another worktree.
    shortcut (security): a filter driver `.git/config` names still runs as files are written
    (smudge); agents are kept from `.git/config` (K-yazma-denetimi). Turn filters off here, as
    `_no_filters` does for a look, if that changes."""
    git, _folder = repository(project)
    # (Before git sees it: a leading "-" would be an option, and `check-ref-format` takes no "--".)
    if not name or name.startswith("-") or _in(
            project, git, "check-ref-format", "--branch", name)[0] != 0:
        raise Refused(f"{name!r} is not a name git takes for a branch")
    there = _in(project, git, "show-ref", "--verify", "-q", f"refs/heads/{name}")[0] == 0
    if there == new:
        raise Refused(f"there is a branch {name} already" if new
                      else f"{name} is not a branch of the project")
    no_hooks.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="no-hooks-", dir=no_hooks) as empty:
        code, out, said = _in(project, git, "-c", f"core.hooksPath={empty}", "switch",
                              "--no-guess", "--no-overwrite-ignore",
                              *(["-c", name] if new else ["--", name]), seconds=COMMIT_SECONDS)
    if code != 0:
        told = "\n".join(part.decode("utf-8", "replace") for part in (out, said))
        held = [line.strip() for line in told.splitlines() if line.startswith("\t")]
        if "would be overwritten" in told and held:
            raise Refused(f"{', '.join(held[:5])} would be written over by {name}'s own: a file "
                          "of yours git leaves out - move it aside first")
        raise Refused(f"git switch failed: {_text(out, said)[-TAIL:]}")


# Paths handed to one `check-ignore`: far below what a Windows command line holds.
IGNORED_AT_ONCE = 200


def ignored(project: Path, paths: list[str], above: bool = False) -> set[str]:
    """B-189: those of `paths` (relative to the project, as given) its git leaves out by
    .gitignore - git's own `check-ignore`, a look as `look` takes one: read only, no program
    of the repository's run. A tracked file is never one (git's rule). Empty where the
    project shows no git or git does not answer: nothing is left out then. `above`: in a
    subfolder of a repository too (`_above`), as for a copy made of what git tracks."""
    # (Not `--literal-pathspecs`, which check-ignore refuses: a name that starts with `:`,
    # pathspec magic to it, is not asked - so not left out.)
    asked = {path.replace("\\", "/"): path for path in paths if not path.startswith(":")}
    found: set[str] = set()
    try:
        git, until = _looking(project, above) if asked else ("", 0.0)
        names = list(asked)
        for at in range(0, len(names), IGNORED_AT_ONCE):
            # (exit 1: none of them is ignored; 128: git could not say - nothing is.)
            # shortcut: a line each (`-z` needs the names on stdin: `run`'s `stdin`); a name git
            # quotes - a tab, a newline, a quote in it - is not matched, so not left out.
            code, out, _err = run(
                [git, "-c", "core.fsmonitor=false", "-c", "safe.bareRepository=explicit",
                 *UNASKED, "-c", "core.quotePath=false", "check-ignore", "--",
                 *names[at:at + IGNORED_AT_ONCE]],
                project, _left(until), **UNASKED_ENV)
            said = out.decode("utf-8", "replace").splitlines() if code == 0 else []
            found |= {asked[name] for name in said if name in asked}
    except Refused:
        return set()
    return found


def listed(project: Path) -> list[str] | None:
    """What a working copy of a project too big to copy whole holds (`copies.make`), where it is
    in a git repository (`_above`): the files git tracks and those it does not ignore
    (`ls-files`, started in the project: relative to it, and only below it) - a submodule, or a
    repository inside, by its folder. None where it shows no git or git does not answer: no
    copy is made then, as before. A look as `look` takes one: read only, no hook, filter or
    fetch of the repository's."""
    try:
        git = _above(project, SHORT_SECONDS)
        code, out, _said = _in(project, git, *UNASKED, "ls-files", "-z", "--cached", "--others",
                               "--exclude-standard", seconds=SHORT_SECONDS, **UNASKED_ENV)
        return [path for path in out.decode("utf-8").split("\0") if path] if code == 0 else None
    except (Refused, UnicodeDecodeError):
        return None


def folder_key(path: str, project: Path) -> str:
    """A folder as two names of it are compared - relative ones from the project - by its
    name alone: nothing on disk is asked (a network path an agent wrote is never opened)."""
    return os.path.normcase(os.path.normpath(os.path.join(project, path)))


def foreign_folder(path: str, project: Path) -> bool:
    """Whether a folder an agent names is not to be taken: a network path, or an absolute
    one outside the project. (A relative one - a worktree beside it - is.)"""
    if path.startswith(("\\\\", "//")):
        return True
    if not (os.path.isabs(path) or PureWindowsPath(path).anchor):  # (`/x`: 3.13's isabs)
        return False
    root, key = folder_key(".", project), folder_key(path, project)
    return key != root and not key.startswith(root.rstrip(os.sep) + os.sep)


def turn_note(
    project: Path, before: dict, after: dict, cli: str | None, said: list[tuple[str, dict]]
) -> str | None:
    """What a turn did to the project's git, for the chat: its branch switched, a worktree
    opened - each "not reported" where no agent said so with report_git - and what an agent
    said it did that git does not show ("said, not seen in git"). `before` and `after` are
    `where` at the turn's start and end; `cli`: the one CLI agent of the turn, named as the
    doer; None where there were none or several ("during this turn"). `said`: (agent, what
    it reported). None where there is nothing to say. Lines of text, never run anywhere."""
    lines = []
    told_branches = {one.get("branch") for _who, one in said}
    told_folders = {
        folder_key(one["worktree"], project) for _who, one in said if one.get("worktree")}
    if after["branch"] != before["branch"]:
        to, was = after["branch"] or "no branch", before["branch"] or "no branch"
        line = (f"{cli} switched the project to branch {to}" if cli
                else f"The project was switched to branch {to}")
        line += f" during this turn (it was on {was})."
        lines.append(line if after["branch"] in told_branches else f"{line} Not reported.")
    had = {folder_key(one["path"], project) for one in before["worktrees"]}
    for one in after["worktrees"]:
        if (key := folder_key(one["path"], project)) in had:
            continue
        on = f" on branch {one['branch']}" if one["branch"] else ""
        line = (f"{cli} opened a worktree at {one['path']}{on}" if cli
                else f"A worktree was opened at {one['path']}{on}") + " during this turn."
        lines.append(line if key in told_folders else f"{line} Not reported.")
    folders = {folder_key(one["path"], project) for one in after["worktrees"]}
    for who, one in said:
        # (Commits are looked for on the project's own branch only: made in another worktree
        # or on another branch, its HEAD does not show them.)
        here = not one.get("worktree") and one.get("branch") in (None, after["branch"])
        missing = [
            *([f"branch {one['branch']}"] if one.get("branch")
              and one["branch"] not in after["names"] else []),
            *([f"a worktree at {one['worktree']}"] if one.get("worktree")
              and folder_key(one["worktree"], project) not in folders else []),
            *([f"{one['commits']} commits"] if one.get("commits") and here
              and after["head"] == before["head"] and after["branch"] == before["branch"]
              else []),
        ]
        if missing:
            lines.append(f"{who} said {', '.join(missing)}: said, not seen in git.")
    return "\n".join(lines) or None


# How much of each field of report_git is kept and shown: the agent's own words.
FIELD_CHARS = 300


def reported(args: dict, project: Path) -> dict:
    """What an agent said with report_git, as KOLONİ keeps, compares and shows it: each text
    field stripped and cut to `FIELD_CHARS`, commits a whole number over 0. ValueError, with
    why, where it says no why, or names a worktree that is a network path or an absolute
    one outside the project (`foreign_folder`): such a folder is never looked at."""
    said: dict = {
        key: value.strip()[:FIELD_CHARS]
        for key in ("branch", "worktree", "merge_into", "why")
        if isinstance(value := args.get(key), str) and value.strip()
    }
    commits = args.get("commits")
    if isinstance(commits, int) and not isinstance(commits, bool) and commits > 0:
        said["commits"] = commits
    if "why" not in said:
        raise ValueError("report_git needs why: in a sentence, why it was done")
    if "worktree" in said and foreign_folder(said["worktree"], project):
        raise ValueError("worktree: give its folder relative to the project, or a path inside "
                         "it; a network path or another place is not taken")
    return said


# --- a team's own branch (K-dal-takim) -------------------------------------------------------
# A worktree on `koloni/<name>`, in the copies folder (`copies.make_branch`); KOLONİ's commit of
# its agents' work there; the merge into the user's branch. No hook of the repository's runs: an
# empty hooks folder, as `switch` makes one - the code is an agent's, not yet the user's.
# shortcut (security): a worktree shares the user's .git - a command of an agent in it can
# `git update-ref` their branches or write .git/config, as a command in the project can; the
# project's watch (K-yazma-denetimi) is what sees .git/config and hooks. Look closer if agents
# are ever seen to.
BRANCH_PREFIX = "koloni/"
BRANCH_CHARS = 40
KOLONI_ID = {"GIT_AUTHOR_NAME": "KOLONİ", "GIT_AUTHOR_EMAIL": "koloni@localhost",
             "GIT_COMMITTER_NAME": "KOLONİ", "GIT_COMMITTER_EMAIL": "koloni@localhost"}


def branch_name(said: str) -> str:
    """The short name an Orchestrator gave (`login form`) as a branch's (`login-form`): small
    letters, digits and dashes. ValueError for one with none of those."""
    name = "-".join("".join(c if c.isascii() and c.isalnum() else " " for c in said.lower()
                            ).split())[:BRANCH_CHARS].strip("-")
    if not name:
        raise ValueError("on_branch: give a short name of letters and digits, as login-form")
    return name


def task_branch(title: str, task_id: str) -> str:
    """A backlog task's branch name: its title's and 4 of its id's - two tasks of one title get
    two names (R165). Short enough that `branch_name` leaves it as it is."""
    try:
        name = branch_name(title)[:BRANCH_CHARS - 5].strip("-")
    except ValueError:
        name = "task"  # (a title of no letter or digit)
    return f"{name}-{task_id[:4]}"


def _on_a_branch(project: Path) -> tuple[str, Path, str]:
    """git, its folder and the branch the project is on. Refused where HEAD is on none, or has
    no commit, or a merge or the like is under way."""
    git, folder = repository(project)
    code, out, _said = _in(project, git, "symbolic-ref", "-q", "--short", "HEAD")
    if code != 0:
        raise Refused("HEAD is detached (on no branch): switch the project to a branch first")
    if _in(project, git, "rev-parse", "-q", "--verify", "HEAD")[0] != 0:
        raise Refused("the project has no commit yet: a branch starts from one")
    under_way = next((what for name, what in _UNDER_WAY.items() if (folder / name).exists()), None)
    if under_way:
        raise Refused(f"{under_way} is under way in the repository: finish or abort it first")
    return git, folder, out.decode("utf-8", "replace").strip()


def add_worktree(
    project: Path, tree: Path, name: str, no_hooks: Path
) -> tuple[str, str, str]:
    """Open a worktree at `tree` (a folder that is not there yet) on a new branch
    `koloni/<name>` - `-2`, `-3` where that is taken - from where the project's branch is: no
    hook, no filter of the repository's runs. Returns the branch, the project's branch it was
    made from and that one's commit (what `branch_look` holds a merge to). Refused, with why,
    as `_on_a_branch`, and where git will not."""
    git, _folder, into = _on_a_branch(project)
    code, out, _said = _in(project, git, "for-each-ref", "--format=%(refname:lstrip=2)",
                           f"refs/heads/{BRANCH_PREFIX}")
    taken = set(out.decode("utf-8", "replace").split()) if code == 0 else set()
    try:
        name = branch_name(name)
    except ValueError as exc:
        raise Refused(str(exc)) from None
    branch, count = f"{BRANCH_PREFIX}{name}", 1
    while branch in taken:
        count += 1
        branch = f"{BRANCH_PREFIX}{name}-{count}"
    code, out, _said = _in(project, git, "rev-parse", "--verify", "HEAD")
    sha = out.decode("ascii", "replace").strip()
    code, out, said = _worktree_add(project, git, no_hooks, "-b", branch, str(tree), sha)
    if code != 0:
        raise Refused(f"git worktree add failed: {_text(out, said)[-TAIL:]}")
    return branch, into, sha


def reopen_worktree(
    project: Path, tree: Path, branch: str, no_hooks: Path, start: Sequence[str] | None,
    tip: str | None = None,
) -> tuple[str, str, str]:
    """Open a worktree at `tree` on KOLONİ's branch `branch` as it is - an agent that stopped on it
    goes on there (`add_worktree` without -b): its commits stay, new work goes on top. Returns as
    `add_worktree` does, with the `start` on record - (branch, commit) it was first made from:
    what `branch_look` holds a merge to, so a project moved off it since makes the merge the
    user's word. Refused, with why: no start on record; no such branch any more (merged,
    deleted); `tip` - the commit it stopped on (else its start) - not in it: another branch of
    that name since; git will not - it is checked out in another worktree."""
    if not branch.startswith(BRANCH_PREFIX):
        raise Refused(f"{branch} is not a branch KOLONİ made")
    if not start:
        raise Refused(f"where its branch {branch} was made from is not on record")
    git, _folder, _into = _on_a_branch(project)
    code, out, _said = _in(project, git, "rev-parse", "--verify", "-q", f"refs/heads/{branch}")
    if code != 0:
        raise Refused(f"there is no branch {branch} any more: merged or deleted")
    ref = out.decode("ascii", "replace").strip()
    # shortcut: no tip on record where its agent was stopped (Stop) or its copy kept, so its start
    # stands in - a later branch of that name made from the same commit passes; record the tip at
    # each of KOLONİ's commits on it if that is ever met.
    if _in(project, git, "merge-base", "--is-ancestor", tip or start[1], ref)[0] != 0:
        raise Refused(f"its branch {branch} is not the one it stopped on: another of that name "
                      "since")
    # A worktree whose folder was deleted by hand stays on git's record, and git refuses the
    # branch while it does: that record alone goes, by its own path, no hook run (`drop_branch`).
    listed = _in(project, git, *UNASKED, "worktree", "list", "--porcelain",
                 seconds=SHORT_SECONDS, **UNASKED_ENV)[1]
    for one in _worktrees(listed.decode("utf-8", "replace")):
        if one["branch"] == branch and not os.path.lexists(one["path"]):
            no_hooks.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="no-hooks-", dir=no_hooks) as empty:
                _in(project, git, "-c", f"core.hooksPath={empty}", "worktree", "remove",
                    "--", one["path"])
    code, out, said = _worktree_add(project, git, no_hooks, str(tree), branch)
    if code != 0:
        raise Refused(f"its branch {branch} could not be opened again: {_text(out, said)[-TAIL:]}")
    return branch, start[0], start[1]


def _worktree_add(project: Path, git: str, no_hooks: Path, *args: str):
    """`git worktree add` with no hook or filter of the repository's."""
    no_hooks.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="no-hooks-", dir=no_hooks) as empty:
        return _in(project, git, *UNASKED, "-c", f"core.hooksPath={empty}", "worktree", "add",
                   *args, seconds=COMMIT_SECONDS, **UNASKED_ENV,
                   **_no_filters(project, git, SHORT_SECONDS))


def commit_branch(
    tree: Path, branch: str, paths: list[str], message: str, no_hooks: Path
) -> bool:
    """Commit these files of `branch`'s worktree as they are there - made, changed or gone -
    and nothing else, as KOLONİ, unsigned, with no hook or filter of the repository's. False
    where that changes nothing (none, or an agent committed them itself). Refused, with why,
    where git will not - and where the worktree is on another branch now (an agent's `git
    switch`): never onto one of the user's."""
    git = find()
    if git is None:
        raise Refused(NOT_FOUND)
    code, out, _said = _in(tree, git, "symbolic-ref", "-q", "--short", "HEAD")
    if code != 0 or out.decode("utf-8", "replace").strip() != branch:
        raise Refused(f"its worktree is no longer on {branch}")
    if not paths:
        return False
    off = _no_filters(tree, git, SHORT_SECONDS)
    no_hooks.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="no-hooks-", dir=no_hooks) as empty:
        listed = Path(empty) / "paths"  # (a list, not a command line: any number of them)
        listed.write_bytes(b"\0".join(path.encode("utf-8") for path in paths))
        hooks = ("-c", f"core.hooksPath={empty}", "-c", "commit.gpgsign=false")
        code, out, said = _in(tree, git, *hooks, "add", "-A", f"--pathspec-from-file={listed}",
                              "--pathspec-file-nul", seconds=COMMIT_SECONDS, **off)
        if code != 0:
            raise Refused(f"git add failed: {_text(out, said)[-TAIL:]}")
        if _in(tree, git, "diff", "--cached", "--quiet", "--no-ext-diff")[0] == 0:
            return False
        code, out, said = _in(tree, git, *hooks, "commit", "-q", "--no-verify", "-m", message,
                              seconds=COMMIT_SECONDS, **KOLONI_ID, **off)
    if code != 0:
        raise Refused(f"git commit failed: {_text(out, said)[-TAIL:]}")
    return True


# What of a branch is never merged unasked: what tells git itself how to read the tree - which
# files it leaves out, how it turns them on the way in and out, where submodules come from - and an
# entry that is no file: a link (120000), a submodule (160000).
GIT_OWN = frozenset({".gitattributes", ".gitmodules", ".gitignore", ".lfsconfig"})
NOT_FILES = frozenset({"120000", "160000"})
# A squash that stopped half way (`merge_branch`): what is in the user's tree, and its undo.
HALF_SAID = (" - what it wrote is in your working tree and index; `git reset --merge` undoes it, "
             "keeping your own uncommitted edits")
HALF_SQUASH = ("a half-done squash is in your tree (files staged or unmerged): `git reset "
               "--merge` undoes it - nothing is merged until then")


def _touched(project: Path, git: str, ref: str) -> dict[str, tuple[str, str]]:
    """What `ref` changed since it left the project's branch: by path, git's letter and the new
    entry's mode (`diff --raw`; "000000" for one deleted). Read only, as `look`."""
    code, out, said = _in(project, git, *UNASKED, "diff", "--raw", "-z", "--no-renames",
                          "--no-ext-diff", "--no-textconv", f"HEAD...{ref}",
                          seconds=SHORT_SECONDS, **UNASKED_ENV)
    if code != 0:
        raise Refused(f"git diff failed: {_text(out, said)[-TAIL:]}")
    parts = out.decode("utf-8", "replace").split("\0")
    found = {}
    # (each ":<old mode> <new mode> <old id> <new id> <letter>", then its path)
    for fields, path in zip(parts[::2], parts[1::2], strict=False):
        words = fields.lstrip(":").split()
        if len(words) == 5 and path:
            found[path] = (words[4][:1], words[1])
    return found


def _in_the_way(project: Path, git: str, touched: Iterable[str]) -> set[str]:
    """Of the paths a branch changes, those git would merge over unasked: the project has the
    file on disk and git does not track it (untracked, or one git ignores - `.env`, a local
    config: git takes those for its own to write over), or a folder above it is no plain folder
    there (a file git ignores where the branch needs a folder - `build` - a link, a junction)."""
    code, out, said = _in(project, git, *UNASKED, "ls-files", "-z", seconds=SHORT_SECONDS,
                          **UNASKED_ENV)
    if code != 0:
        raise Refused(f"git ls-files failed: {_text(out, said)[-TAIL:]}")
    tracked = {one.decode("utf-8", "replace") for one in out.split(b"\0") if one}

    def odd(rel: str) -> bool:  # (a folder above: anything but a plain folder git does not track)
        place = project / rel
        return rel not in tracked and os.path.lexists(place) and (
            place.is_symlink() or place.is_junction() or not place.is_dir())

    found = set()
    for path in touched:
        parts = path.split("/")
        if path not in tracked and os.path.lexists(project / path) or any(
                odd("/".join(parts[:at])) for at in range(1, len(parts))):
            found.add(path)
    return found


def committed_since(tree: Path, start: str) -> list[str]:
    """The files commits made in a branch's worktree changed since `start` (an agent's own
    `git commit`), by path - read only. Empty where git does not say."""
    git = find()
    if git is None:
        return []
    code, out, _said = _in(tree, git, *UNASKED, "diff", "--name-only", "-z", "--no-renames",
                           "--no-ext-diff", start, "HEAD", seconds=SHORT_SECONDS, **UNASKED_ENV)
    listed = out.split(b"\0")
    return [one.decode("utf-8", "replace") for one in listed if one] if code == 0 else []


def branch_look(
    project: Path, branch: str, start: tuple[str, str] | None = None
) -> dict:
    """How `branch` would merge into the project's: {"into": the project's branch, "files":
    what the branch changed since they parted, by path, with git's letter (A, M, D, T) - a
    secret too, "conflicts": the files both changed that git does not put together, "dirty":
    what of the user's git would not merge over - any staged change (git refuses a merge then,
    whatever the files), and an uncommitted file the branch changes - or what git would merge
    over unasked (`_in_the_way`), "special": what the branch changes of git's own reading of the
    tree (`GIT_OWN`) or that is no file (`NOT_FILES`) - never merged unasked, "drift": where the
    project is no longer on the branch `start` names (branch, commit), or that branch no longer
    holds that commit (reset) - why the merge is the user's word, None otherwise, "half": where a
    squash that stopped half way is in the project's tree (`SQUASH_MSG`, or files left unmerged)
    - why nothing is merged, None otherwise, "tip": the branch's commit all this is of (what is
    then scanned and merged: `holding`, `merge_branch`)}. Read only, as `look`. Refused as
    `_on_a_branch`."""
    git, folder, into = _on_a_branch(project)
    code, out, said = _in(project, git, "rev-parse", "--verify", "-q", f"refs/heads/{branch}")
    if code != 0:
        raise Refused(f"there is no branch {branch} any more")
    ref = out.decode("ascii", "replace").strip()  # (pinned: what is looked at is what is merged)
    code, out, said = _in(project, git, *UNASKED, "merge-tree", "--write-tree", "--name-only",
                          "--no-messages", "-z", "HEAD", ref, seconds=SHORT_SECONDS, **UNASKED_ENV)
    if code not in (0, 1):
        raise Refused(f"git merge-tree failed: {_text(out, said)[-TAIL:]}")
    # (Its first entry is the merged tree's id; on a conflict the files follow.)
    conflicts = {one.decode("utf-8", "replace") for one in out.split(b"\0")[1:] if one}
    touched = _touched(project, git, ref)
    code, out, said = _in(project, git, *UNASKED, "status", "--porcelain=v1", "-z",
                          "--no-renames", "--untracked-files=all", "--ignore-submodules=dirty",
                          seconds=SHORT_SECONDS, **UNASKED_ENV,
                          **_no_filters(project, git, SHORT_SECONDS))
    if code != 0:
        raise Refused(f"git status failed: {_text(out, said)[-TAIL:]}")
    dirty = {
        entry[3:] for entry in out.decode("utf-8", "replace").split("\0")
        if len(entry) > 3 and not in_scratch(entry[3:])
        and (entry[0] not in " ?!" or entry[3:] in touched)}
    dirty |= _in_the_way(project, git, touched)
    special = sorted(path for path, (_letter, mode) in touched.items() if mode in NOT_FILES
                     or path.rsplit("/", 1)[-1].rstrip(" .").casefold() in GIT_OWN)
    unmerged = _in(project, git, *UNASKED, "ls-files", "-u", "-z", seconds=SHORT_SECONDS,
                   **UNASKED_ENV)[1]
    half = HALF_SQUASH if (folder / "SQUASH_MSG").exists() or unmerged else None
    drift = None
    if start is not None:
        made_from, sha = start
        if into != made_from:
            drift = f"made from {made_from}, the project is on {into} now"
        elif _in(project, git, "merge-base", "--is-ancestor", sha, "HEAD")[0] != 0:
            drift = f"{into} no longer holds the commit {sha[:10]} the branch was made from"
    return {"into": into, "files": {path: letter for path, (letter, _) in sorted(touched.items())},
            "conflicts": sorted(conflicts), "dirty": sorted(dirty), "special": special,
            "drift": drift, "half": half, "tip": ref}


def holding(
    project: Path, tip: str, paths: Iterable[str], needles: Sequence[bytes]
) -> list[str]:
    """Of these files at the commit `tip` (`branch_look`'s), those whose content there - what a
    merge of it brings in - holds any of `needles` (bytes): read from git's objects, as stored,
    no filter. Fails closed: a file that cannot be read counts as holding one - but a submodule,
    which has no content here. `paths`: files the branch did not delete. Refused as
    `repository`."""
    git, _folder = repository(project)
    found = []
    for path in paths if needles else ():
        code, out, _said = _in(project, git, *UNASKED, "cat-file", "blob", f"{tip}:{path}",
                               seconds=SHORT_SECONDS, **UNASKED_ENV)
        if code != 0:
            kind = _in(project, git, *UNASKED, "cat-file", "-t", f"{tip}:{path}",
                       seconds=SHORT_SECONDS, **UNASKED_ENV)[1].strip()
            if kind != b"commit":
                found.append(path)
        elif any(needle in out for needle in needles):
            found.append(path)
    return found


def held_since(
    project: Path, start: str, tip: str, needles: Sequence[bytes], branch: str | None = None
) -> bool:
    """D2: whether any commit from `start` to `tip` - the agents' own steps, which a branch kept
    after its squash keeps - holds one of `needles` (bytes) in its message or a file it wrote
    (`holding`); with `branch`, any its reflog still names too (one amended away). Fails
    closed: where git does not list them, it counts as holding one."""
    if not needles:
        return False
    git, _folder = repository(project)
    logged: list[str] = []
    if branch is not None:
        code, out, _said = _in(project, git, *UNASKED, "rev-list", "-g", f"refs/heads/{branch}",
                               seconds=SHORT_SECONDS, **UNASKED_ENV)
        if code != 0:
            return True
        logged = out.decode("ascii", "replace").split()
    code, out, _said = _in(project, git, *UNASKED, "rev-list", f"^{start}", tip, *logged,
                           seconds=SHORT_SECONDS, **UNASKED_ENV)
    if code != 0:
        return True
    for commit in out.decode("ascii", "replace").split():
        code, raw, _said = _in(project, git, *UNASKED, "cat-file", "commit", commit,
                               seconds=SHORT_SECONDS, **UNASKED_ENV)
        if code != 0 or any(needle in raw for needle in needles):
            return True
        code, files, _said = _in(project, git, *UNASKED, "diff-tree", "--no-commit-id", "-m",
                                 "-r", "-z", "--name-only", "--diff-filter=d", "--no-renames",
                                 commit, seconds=SHORT_SECONDS, **UNASKED_ENV)
        if code != 0 or holding(project, commit, {
                one.decode("utf-8", "replace") for one in files.split(b"\0") if one}, needles):
            return True
    return False


def branch_diffs(project: Path, branch: str, paths: list[str]) -> dict[str, str]:
    """Each of these files' diff from where the project's branch and `branch` parted, as a look
    takes one (`diff_at`): no filter, textconv or external diff - and none of a secret by its
    name (`is_secret`). `paths`: files, as `branch_look` lists them. Refused as `repository`."""
    git, _folder = repository(project)
    off = _no_filters(project, git, SHORT_SECONDS)
    found = {}
    for path in paths:
        if is_secret(path):
            continue
        code, out, _said = _in(project, git, *UNASKED, "diff", "--no-color", "--no-ext-diff",
                               "--no-textconv", "--ignore-submodules=all",
                               f"HEAD...refs/heads/{branch}", "--", path,
                               seconds=SHORT_SECONDS, **UNASKED_ENV, **off)
        if code == 0:
            found[path] = out.decode("utf-8", "replace")
    return found


def merge_branch(
    project: Path, tip: str, message: str, no_hooks: Path, into: str,
    start: str | None = None,
) -> str:
    """Bring a branch's commit `tip` - the one `branch_look` looked at and its scans read - into
    the project's branch as ONE commit (`merge --squash <tip>`, then a commit as KOLONİ): what the
    agents left, not how they got there - a secret committed and taken out, a file made and
    deleted, stay out of the user's history. No hook, filter, signing, link, submodule update or
    autostash of the repository's. Returns the commit's id.
    shortcut: with filters off a file Git LFS keeps comes in as its pointer text; turn the
    filters on for LFS paths alone if an LFS project is put on a branch.

    Looked at again first, as `branch_look` does, and Refused, with why, with nothing changed:
    the project is not on `into` (the branch the card named), or - `start` - no longer holds
    that commit; something is staged (it would go into the commit); a file git would write over
    unasked (`_in_the_way`). Nothing is forced, reset or aborted: where git stops half way on a
    conflict met since, or the commit fails, what it wrote stays for the user, and the refusal
    says so.
    shortcut: a file the user makes in the milliseconds between that look and git's write is
    still written over (git takes an untracked one for its own); hold the files if ever seen."""
    git, folder, now = _on_a_branch(project)
    if now != into:
        raise Refused(f"the project is on {now} now, not {into}: look at the card again")
    if start and _in(project, git, "merge-base", "--is-ancestor", start, "HEAD")[0] != 0:
        raise Refused(f"{now} no longer holds the commit {start[:10]} the branch was made from")
    if _in(project, git, "diff", "--cached", "--quiet", "--no-ext-diff")[0] != 0:
        raise Refused("changes are staged in the project: commit or unstage them first")
    ref = tip
    if way := sorted(_in_the_way(project, git, _touched(project, git, ref))):
        raise Refused(f"{', '.join(way[:5])} would be written over: move it aside first")
    off = _no_filters(project, git, SHORT_SECONDS)
    no_hooks.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="no-hooks-", dir=no_hooks) as empty:
        own = ("-c", f"core.hooksPath={empty}", "-c", "commit.gpgsign=false", "-c",
               "core.symlinks=false", "-c", "submodule.recurse=false", "-c",
               "merge.autoStash=false", "-c", "rebase.autoStash=false")
        code, out, said = _in(project, git, *UNASKED, *own, "merge", "--squash", ref,
                              seconds=COMMIT_SECONDS, **UNASKED_ENV, **off)
        if code != 0:
            # (Said as it is: git may have refused before writing anything.)
            wrote = (folder / "SQUASH_MSG").exists() or _in(
                project, git, "diff", "--cached", "--quiet", "--no-ext-diff")[0] != 0
            raise Refused(f"git merge --squash failed{HALF_SAID if wrote else ''}: "
                          f"{_text(out, said)[-TAIL:]}")
        if _in(project, git, "diff", "--cached", "--quiet", "--no-ext-diff")[0] != 0:
            code, out, said = _in(project, git, *UNASKED, *own, "commit", "-q", "--no-verify",
                                  "-m", message, seconds=COMMIT_SECONDS, **UNASKED_ENV,
                                  **KOLONI_ID, **off)
            if code != 0:
                raise Refused(f"git commit failed{HALF_SAID}: {_text(out, said)[-TAIL:]}")
    _code, out, _said = _in(project, git, "rev-parse", "HEAD")
    return out.decode("ascii", "replace").strip()


def drop_branch(
    project: Path, tree: Path, branch: str, no_hooks: Path, force: bool = False,
    keep: bool = False,
) -> None:
    """A branch's worktree folder is gone: git's record of it goes, and the branch - only where
    it is merged, but for `force` (the user turned it down); never where the user said `keep`
    ("Keep this branch after merging"). Never a branch not KOLONİ's own
    (`BRANCH_PREFIX`), and git's record only once the folder is gone: its files are deleted by
    `copies.remove`, never by git, which would go through a link. No hook of the repository's
    runs (`no_hooks`: where an empty hooks folder is made, as `commit` makes one). Refused
    where git will not: a branch with work on it that is not merged stays."""
    if not branch.startswith(BRANCH_PREFIX):
        raise Refused(f"{branch} is not a branch KOLONİ made")
    git, _folder = repository(project)
    no_hooks.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="no-hooks-", dir=no_hooks) as empty:
        hooks = ("-c", f"core.hooksPath={empty}")
        if not os.path.lexists(tree):
            _in(project, git, *hooks, "worktree", "remove", str(tree))  # (git's record only)
        if keep:
            return
        code, out, said = _in(project, git, *hooks, "branch", "-D" if force else "-d", branch)
    if code != 0:
        raise Refused(f"git branch failed: {_text(out, said)[-TAIL:]}")



# --- D2: an agent puts a conflict together in the branch's worktree -------------------------
# The user's branch is merged INTO the koloni branch, in its worktree - the user's own tree and
# branch are not touched - an agent resolves what clashed there, and the branch then merges as
# ever (`branch_look`, `merge_branch`). Nothing of it is left half way: what is not put together
# is undone there (`undo_merge_in`).
# shortcut: a merge driver the repository's own config names (`merge.<name>.driver`, picked by a
# .gitattributes) still runs in this merge, as in `merge_branch`'s squash; blank them as
# `_no_filters` blanks filters if a project with one is put on a branch.
MARKS = (b"<<<<<<< ", b">>>>>>> ")


def _on(tree: Path, branch: str) -> str:
    """git, where the worktree `tree` is on `branch`; Refused otherwise (an agent's switch)."""
    git = find()
    if git is None:
        raise Refused(NOT_FOUND)
    code, out, _said = _in(tree, git, "symbolic-ref", "-q", "--short", "HEAD")
    if code != 0 or out.decode("utf-8", "replace").strip() != branch:
        raise Refused(f"its worktree is no longer on {branch}")
    return git


def _head(tree: Path, git: str, ref: str = "HEAD") -> str | None:
    code, out, _said = _in(tree, git, "rev-parse", "--verify", "-q", f"{ref}^{{commit}}")
    return out.decode("ascii", "replace").strip() if code == 0 else None


def _unmerged(tree: Path, git: str) -> list[str]:
    out = _in(tree, git, *UNASKED, "ls-files", "-u", "-z", seconds=SHORT_SECONDS,
              **UNASKED_ENV)[1]
    return sorted({entry.split(b"\t", 1)[1].decode("utf-8", "replace")
                   for entry in out.split(b"\0") if b"\t" in entry})


def merge_in(tree: Path, branch: str, into: str, no_hooks: Path) -> tuple[str, str, list[str]]:
    """Merge the user's branch `into` - its commit now - into `branch`'s worktree `tree`, as
    KOLONİ: no hook, filter, signing, link or autostash of the repository's. Returns the
    worktree's commit before it (what `undo_merge_in` goes back to), the user's commit merged,
    and the files left conflicting there - none where git merged cleanly and committed.
    Refused, with nothing left half way, where the worktree is not on `branch` or git would
    not merge."""
    git = _on(tree, branch)
    sha, before = _head(tree, git, f"refs/heads/{into}"), _head(tree, git)
    if sha is None or before is None:
        raise Refused(f"there is no branch {into} any more")
    off = _no_filters(tree, git, SHORT_SECONDS)
    # (An undo is `reset --hard`: not over a change the line left uncommitted - a file held back.)
    code, out, said = _in(tree, git, *UNASKED, "status", "--porcelain", "--untracked-files=no",
                          seconds=SHORT_SECONDS, **UNASKED_ENV, **off)
    if code != 0 or out.strip():
        raise Refused("the branch holds changes not committed (a file held back): resolve it "
                      "yourself")
    no_hooks.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="no-hooks-", dir=no_hooks) as empty:
        own = ("-c", f"core.hooksPath={empty}", "-c", "commit.gpgsign=false", "-c",
               "core.symlinks=false", "-c", "submodule.recurse=false", "-c",
               "merge.autoStash=false")
        code, out, said = _in(tree, git, *UNASKED, *own, "merge", "--no-ff", "--no-edit",
                              "--no-verify", "-m", f"Merge {into} into {branch}", sha,
                              seconds=COMMIT_SECONDS, **UNASKED_ENV, **KOLONI_ID, **off)
    if code == 0:
        return before, sha, []
    left = _unmerged(tree, git)
    if not left:
        undo_merge_in(tree, branch, before, no_hooks)
        raise Refused(f"git merge failed: {_text(out, said)[-TAIL:]}")
    # A clash git marks no lines of - a file changed on one side and deleted on the other, one that
    # is no text - leaves one side whole, with nothing `resolved` could tell from a choice: not
    # an agent's.
    if unmarked := [path for path in left if not _marked(tree / path)]:
        undo_merge_in(tree, branch, before, no_hooks)
        raise Refused(f"{', '.join(unmarked[:5])} clashes in no text lines (deleted on one side, "
                      "or not text): resolve it yourself")
    return before, sha, left


def _marked(place: Path) -> bool:
    """Whether a file holds a line git marks a conflict with; False where it cannot be read."""
    try:
        return any(line.startswith(MARKS) for line in place.read_bytes().splitlines())
    except OSError:
        return False


def resolved(tree: Path, branch: str, before: str, sha: str, paths: Iterable[str]) -> str | None:
    """Why the merge `merge_in` began in a worktree is not put together - None where it is: it
    is committed, holds the user's commit `sha`, and none of `paths` (the files that clashed)
    holds git's conflict marks at that commit. Fails closed: one that cannot be read there
    counts as marked; one deleted there does not."""
    git = _on(tree, branch)
    head = _head(tree, git)
    if _head(tree, git, "MERGE_HEAD") or _unmerged(tree, git) or head in (None, before):
        return "the merge was not committed"
    if _in(tree, git, "merge-base", "--is-ancestor", sha, "HEAD")[0] != 0:
        return "the branch does not hold your branch's commit"
    marked = []
    for path in paths:
        code, out, _said = _in(tree, git, *UNASKED, "cat-file", "blob", f"HEAD:{path}",
                               seconds=SHORT_SECONDS, **UNASKED_ENV)
        if code == 0 and any(line.startswith(MARKS) for line in out.splitlines()) or (
                code != 0 and _in(tree, git, "cat-file", "-e", f"HEAD:{path}")[0] == 0):
            marked.append(path)
    return f"{', '.join(marked[:5])} still holds git's conflict marks" if marked else None


def undo_merge_in(tree: Path, branch: str, before: str, no_hooks: Path) -> None:
    """Back to `before` in a branch's worktree: a merge under way there is undone, and what was
    committed since - the agents' work before it is on `before`. In KOLONİ's worktree alone, no
    hook or filter of the repository's. Refused where the worktree is not on `branch`."""
    git = _on(tree, branch)
    off = _no_filters(tree, git, SHORT_SECONDS)
    no_hooks.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="no-hooks-", dir=no_hooks) as empty:
        code, out, said = _in(tree, git, *UNASKED, "-c", f"core.hooksPath={empty}", "-c",
                              "core.symlinks=false", "-c", "submodule.recurse=false", "reset",
                              "-q", "--hard", before, seconds=COMMIT_SECONDS, **UNASKED_ENV, **off)
    if code != 0:
        raise Refused(f"git reset failed: {_text(out, said)[-TAIL:]}")


# --- "How finished work reaches main": a pull request (the user's decision of 3 Nov) ---------
# KOLONİ pushes ONE commit - the branch's tip tree on where it left the user's branch: what the
# squash would bring in, not the agents' own steps - and runs `gh pr create`; it never merges the
# pull request. Both run in KOLONİ's process, never as an agent's command. Measured on gh 2.91.0
# (3 Nov): `gh auth status` exits 1 logged out; `gh repo view` fails where no remote is GitHub's.
# shortcut: GitHub alone (gh), pushed to the remote "origin" - a fork's (upstream) set-up, GitLab
# and the like are not; and the user's own commits not pushed yet go up under it. A real pull
# request is to be tried live once, with the user's OK.
# shortcut: the repository's own `core.sshCommand`, credential helper, `insteadOf` and proxy run in
# the push - that is how the user reaches GitHub, and blanking them would break it; a config
# changed during the turn is asked about first (`_merge_branch`, as Take in's commit asks).
GH_ENV = {"GH_PROMPT_DISABLED": "1", "GH_NO_UPDATE_NOTIFIER": "1", "NO_COLOR": "1",
          "GIT_TERMINAL_PROMPT": "0"}
PUSH_SECONDS = 120.0
# How a push may reach the remote: no protocol that runs a program (`ext::`), nor plain http;
# a local one (file) for a remote on this machine.
# No tag goes along (`followTags`), nothing is signed, no submodule pushed.
PUSH_OWN = ("-c", "protocol.allow=never", "-c", "protocol.https.allow=always", "-c",
            "protocol.ssh.allow=always", "-c", "protocol.file.allow=always", "-c",
            "push.recurseSubmodules=no", "-c", "push.followTags=false", "-c", "push.gpgSign=false")
NO_GH = "gh (GitHub's CLI) is not installed"
NOT_IN = "gh is not logged in: run gh auth login"
NO_ANSWER = "gh did not answer, or the project is no git repository's top folder"


def gh() -> list[str] | None:
    """How gh, GitHub's CLI, is started - found as `find` finds git: a full path, and no batch
    file (Windows reads its line once more: a title is a pull request's task text)."""
    found = shutil.which("gh")
    if not found or not os.path.isabs(found):
        return None
    return None if found.rstrip(". ").lower().endswith((".cmd", ".bat")) else [found]


def _origin(project: Path) -> str:
    """The address of the project's remote "origin" (where a pull request's branch is pushed),
    as its config says it; "" where there is none."""
    try:
        git, _folder = repository(project)
    except Refused:
        return ""
    code, out, _said = _in(project, git, *UNASKED, "config", "--get", "remote.origin.url",
                           seconds=SHORT_SECONDS, **UNASKED_ENV)
    return out.decode("utf-8", "replace").strip() if code == 0 else ""


def github_remote(project: Path) -> bool:
    """Whether the project's "origin" is on github.com - read from its config."""
    return "github.com" in _origin(project).lower()


def _names(url: str, repo: str) -> bool:
    """Whether a remote's address is GitHub's `repo` ("owner/name"): https or ssh, `.git` or not -
    github.com itself as the host (not `evilgithub.com`, nor a path that holds it)."""
    host = r"(?:^(?:https?|ssh|git)://(?:[^/@]+@)?|^[^/@:]+@)github\.com(?::\d+)?"
    return re.fullmatch(fr"{host}[:/]{re.escape(repo)}(?:\.git)?/?", url.strip(),
                        re.IGNORECASE) is not None


def _gh_env(project: Path, empty: str) -> dict[str, str]:
    """gh's environment: the git it runs in the project itself (to read its remotes, its status)
    runs no file watcher, hook or filter of the repository's - as KOLONİ's own git calls."""
    git, _folder = repository(project)
    off = _no_filters(project, git, SHORT_SECONDS)
    count = int(off["GIT_CONFIG_COUNT"])
    for at, (key, value) in enumerate((("core.fsmonitor", "false"), ("core.hooksPath", empty)),
                                      count):
        off[f"GIT_CONFIG_KEY_{at}"], off[f"GIT_CONFIG_VALUE_{at}"] = key, value
    return {**GH_ENV, **off, "GIT_CONFIG_COUNT": str(count + 2)}


def gh_repo(project: Path) -> tuple[str | None, str | None]:
    """The GitHub repository ("owner/name") gh takes the project for, and None - or None and
    why there is none: gh is not installed, not logged in, or no remote is GitHub's."""
    command = gh()
    if command is None:
        return None, NO_GH
    try:
        with tempfile.TemporaryDirectory(prefix="no-hooks-") as empty:
            env = _gh_env(project, empty)
            if run([*command, "auth", "status"], project, SHORT_SECONDS, **env)[0] != 0:
                return None, NOT_IN
            code, out, _said = run([*command, "repo", "view", "--json", "nameWithOwner", "-q",
                                    ".nameWithOwner"], project, SHORT_SECONDS, **env)
    except Refused:
        return None, NO_ANSWER
    name = out.decode("utf-8", "replace").strip()
    if code != 0 or "/" not in name or name.startswith("-") or len(name.split()) != 1:
        return None, "no remote of the project is on GitHub"
    return name, None


def pr_ready(project: Path) -> tuple[str | None, str | None]:
    """The GitHub repository a pull request of the project goes to (`gh_repo`), and None - or
    None and why there is none."""
    name, why = gh_repo(project)
    if name is None:
        return None, why
    if not _names(_origin(project), name):
        # (What is pushed goes to origin: the pull request must be of that repository.)
        return None, f"origin is not {name}, the repository gh opens pull requests on"
    return name, None


# --- Item 57: a chat started from a GitHub issue - read with the user's own gh, never a token --
# shortcut: gh issue JSON fields not measured live (`gh issue list/view --json`, as gh's manual
# names them), measure once with the user's OK.
ISSUE_URL = re.compile(r"https://github\.com/([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+)/issues/(\d{1,9})")
ISSUE_SECONDS = 30.0  # (gh asks GitHub: longer than a look at the repository)
MOST_ISSUE = 20_000  # characters of an issue's text, its comments with it
# (read_attachment gives 400 lines at once: the whole issue, its frame with it, in one read)
MOST_LINES = 380
CUT = "\n…(cut: the rest is on GitHub)"


def issue_ref(raw: str) -> str:
    """What gh is given for an issue the user names: its number in the project's repository
    (`#12`, `12`) or its address on github.com - written anew from what was matched, so
    nothing else reaches gh's command line. Refused, for anything else."""
    raw = raw.strip()
    if number := re.fullmatch(r"#?(\d{1,9})", raw):
        return str(int(number[1]))
    # (Nor a name of dots alone - a way up - or one that starts as an option.)
    if (found := ISSUE_URL.fullmatch(raw)) and not any(
            name.strip(".") == "" or name.startswith("-") for name in (found[1], found[2])):
        return f"https://github.com/{found[1]}/{found[2]}/issues/{int(found[3])}"
    raise Refused("an issue is its number (#12) or its address (https://github.com/owner/repo/"
                  "issues/12)")


def _gh_json(project: Path, *args: str) -> object:
    """What a read-only `gh issue` command answers, as JSON. Refused, with why."""
    # shortcut: what gh writes is read whole, bounded by its time (`ISSUE_SECONDS`) alone - `run`
    # reads with `communicate`; read in pieces and stop at a few MB if a huge answer is seen.
    # shortcut: gh runs in the project with its git hooks off (`_gh_env`), so a project that is no
    # git repository's top folder opens no issue, not even by address; run it elsewhere if asked.
    command = gh()
    if command is None:
        raise Refused(NO_GH)
    with tempfile.TemporaryDirectory(prefix="no-hooks-") as empty:
        env = _gh_env(project, empty)
        if run([*command, "auth", "status"], project, SHORT_SECONDS, program="gh", **env)[0]:
            raise Refused(NOT_IN)
        code, out, said = run([*command, "issue", *args], project, ISSUE_SECONDS, program="gh",
                              **env)
    if code != 0:
        raise Refused(f"gh issue {args[0]} failed: {_text(out, said)[-TAIL:]}")
    try:
        return json.loads(out.decode("utf-8", "replace"))
    except ValueError:
        raise Refused(f"gh issue {args[0]} said no JSON") from None


def issues(project: Path) -> tuple[list[dict], str | None]:
    """The open issues of the project's GitHub repository, latest first (gh's own order) - or
    none and why: gh not installed or logged in, no GitHub remote, gh failed."""
    name, why = gh_repo(project)
    if name is None:
        return [], why
    # shortcut: the first 30 open issues, no search or paging; add them when a repository's list
    # is seen to be longer than that and the one wanted is not pasted.
    try:
        found = _gh_json(project, "list", f"--repo={name}", "--state=open", "--limit=30",
                         "--json=number,title,url,updatedAt")
    except Refused as refused:
        return [], str(refused)
    return [{"number": one["number"], "title": str(one.get("title") or ""),
             "url": str(one.get("url") or ""), "updated_at": one.get("updatedAt")}
            for one in found if isinstance(one, dict) and isinstance(one.get("number"), int)
            ] if isinstance(found, list) else [], None


def issue(project: Path, ref: str) -> dict:
    """One issue (`issue_ref`'s): its number, its address, and its text - title, state,
    author, body, then each comment, oldest first - cut at `MOST_ISSUE`. One by number is of
    the project's repository; one by address of any. Refused, with why."""
    ref = issue_ref(ref)
    if ref.isdigit():
        name, why = gh_repo(project)
        if name is None:
            raise Refused(why)
        args = [ref, f"--repo={name}"]
    else:
        args = [ref]
    found = _gh_json(project, "view", *args, "--json=number,title,body,url,state,author,comments")
    if not isinstance(found, dict) or not isinstance(found.get("number"), int):
        raise Refused("gh issue view said no issue")

    def who(one: dict) -> str:
        author = one.get("author")
        return str(author.get("login") or "?") if isinstance(author, dict) else "?"

    url, state = str(found.get("url") or ""), str(found.get("state") or "").lower()
    parts = [f"Issue #{found['number']}: {found.get('title') or ''}",
             f"{url} ({state}, opened by {who(found)})", "",
             str(found.get("body") or "").strip() or "(no text)"]
    for one in found.get("comments") or []:
        if isinstance(one, dict):
            parts += ["", f"--- {who(one)} commented:", str(one.get("body") or "").strip()]
    lines = "\n".join(parts).splitlines()  # (as read_attachment counts them)
    text = "\n".join(lines)
    # shortcut: cut from the end - the newest comments go first; keep the body and the latest
    # comments, cutting the middle, if a long thread's end is seen to matter.
    if len(text) > MOST_ISSUE or len(lines) > MOST_LINES:
        text = "\n".join(text[:MOST_ISSUE - len(CUT)].split("\n")[:MOST_LINES - 1]) + CUT
    return {"number": found["number"], "url": url, "text": text}


def push_one(
    project: Path, tip: str, branch: str, into: str, start: str, message: str, no_hooks: Path
) -> str:
    """Push the branch's commit `tip` to the remote "origin", as `branch` there, as ONE commit
    by KOLONİ - its tree, on where it left the project's branch `into`: what `merge_branch`
    would bring in, not the agents' own steps (a secret committed and taken out). Only where
    origin has that place already (`refs/remotes/origin/<into>` holds it): the user's own
    commits not pushed yet do not go up under it - nor, `start`, the commit the branch was made
    from (a local branch of theirs it left since). Never forced: a branch of that name there
    already refuses it. No hook, tag or signing of the repository's; git's own receive-pack.
    Returns the commit pushed. Refused, with why."""
    if not branch.startswith(BRANCH_PREFIX):
        raise Refused(f"{branch} is not a branch KOLONİ made")
    git, _folder = repository(project)
    code, out, said = _in(project, git, *UNASKED, "merge-base", f"refs/heads/{into}", tip,
                          seconds=SHORT_SECONDS, **UNASKED_ENV)
    if code != 0:
        raise Refused(f"git merge-base failed: {_text(out, said)[-TAIL:]}")
    base = out.decode("ascii", "replace").strip()
    if any(_in(project, git, "merge-base", "--is-ancestor", one, f"refs/remotes/origin/{into}")[0]
           for one in (base, start)):
        raise Refused(f"push {into} first: commits of yours not on origin yet would go up with "
                      "the pull request")
    code, out, said = _in(project, git, *UNASKED, "-c", "commit.gpgsign=false", "commit-tree",
                          f"{tip}^{{tree}}", "-p", base, "-m", message,
                          seconds=SHORT_SECONDS, **UNASKED_ENV, **KOLONI_ID)
    if code != 0:
        raise Refused(f"git commit-tree failed: {_text(out, said)[-TAIL:]}")
    sha = out.decode("ascii", "replace").strip()
    no_hooks.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="no-hooks-", dir=no_hooks) as empty:
        # (`--receive-pack`, not `-c remote.origin.receivepack`: the repository's config wins
        # over that.)
        code, out, said = _in(project, git, *PUSH_OWN, "-c", f"core.hooksPath={empty}", "push",
                              "--no-verify", "--quiet", "--receive-pack=git-receive-pack",
                              "origin", f"{sha}:refs/heads/{branch}",
                              seconds=PUSH_SECONDS, **UNASKED_ENV)
    if code != 0:
        raise Refused(f"git push failed: {_text(out, said)[-TAIL:]}")
    return sha


def open_pr(
    project: Path, repo: str, branch: str, into: str, title: str, body: str, folder: Path
) -> str:
    """`gh pr create` of `branch` (pushed: `push_one`) into `into` on GitHub's `repo`, its body
    from a file in `folder`; returns the pull request's address. Refused, with why."""
    command = gh()
    if command is None:
        raise Refused(NO_GH)
    folder.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pr-", dir=folder) as held:
        written, empty = Path(held) / "body.md", Path(held) / "hooks"
        written.write_text(body, encoding="utf-8")
        empty.mkdir()
        # (Each value with "=": one that starts with a dash is no option.)
        code, out, said = run([*command, "pr", "create", f"--repo={repo}", f"--head={branch}",
                               f"--base={into}", f"--title={title}", f"--body-file={written}"],
                              project, PUSH_SECONDS, program="gh",
                              **_gh_env(project, str(empty)))
    if code != 0:
        raise Refused(f"gh pr create failed: {_text(out, said)[-TAIL:]}")
    url = next((word for word in reversed(out.decode("utf-8", "replace").split())
                if word.startswith("https://")), None)
    if url is None:
        raise Refused(f"gh pr create said no address: {_text(out, said)[-TAIL:]}")
    return url
