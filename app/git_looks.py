"""Coordination §4: what the checks of a disposable delete ask of the project's git
(`app.disposable`), beside `app.git` (that file is at its size limit), asking as it asks."""

import os
from pathlib import Path

from app.git import UNASKED, UNASKED_ENV, Refused, _in, _left, _looking, _said, run

# Coordination §4: what the checks of a disposable delete ask of the project's git
# (`app.disposable`) - looks as `where` takes them: read only, no program of the repository's
# run, None where git does not answer.


def default_branch(project: Path) -> str | None:
    """The project's default branch: the remote's (origin/HEAD), else the one git starts a
    repository on (init.defaultBranch), else main or master where there is one; None where
    git says none of these."""
    try:
        git, until = _looking(project)
        remote = (
            _said(project, git, until, "symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD")
            or ""
        ).strip()
        if remote.startswith("origin/") and remote != "origin/":
            return remote.removeprefix("origin/")
        started = (
            _said(project, git, until, "config", "--get", "init.defaultBranch") or ""
        ).strip()
        return started or next(
            (
                name
                for name in ("main", "master")
                if _said(project, git, until, "rev-parse", "--verify", "-q", f"refs/heads/{name}")
                is not None
            ),
            None,
        )
    except Refused:
        return None


def ahead(project: Path, base: str, branch: str) -> int | None:
    """How many commits the local `branch` has that the local `base` has not; None where git
    does not say (either is no local branch)."""
    try:
        said = _said(
            project,
            *_looking(project),
            "rev-list",
            "--count",
            f"refs/heads/{base}..refs/heads/{branch}",
            "--",
        )
    except Refused:
        return None
    return int(said) if said and said.strip().isdigit() else None


def kept_under(project: Path, rel: str) -> bool | None:
    """Whether git keeps a file at `rel` (the project's, `/` between its parts) or below it, in
    any case of its letters (NTFS and APFS open `build` as `Build`): one it tracks, or a new one
    it does not ignore (`!build/keep.txt` under `build/*`); None where git does not say.
    (Not `_in`: its `--literal-pathspecs` turns off the pathspec's `icase`.)"""
    try:
        git, until = _looking(project)
        code, out, _said = run(
            [
                git,
                "-c",
                "core.fsmonitor=false",
                "-c",
                "safe.bareRepository=explicit",
                *UNASKED,
                "ls-files",
                "-z",
                "--cached",
                "--others",
                "--exclude-standard",
                "--",
                f":(literal,icase){rel}",
            ],
            project,
            _left(until),
            **UNASKED_ENV,
        )
    except Refused:
        return None
    return bool(out) if code == 0 else None


def not_committed(tree: Path) -> list[str] | None:
    """What a worktree's folder holds that none of its commits does, as git's own look before
    `worktree remove` may not see it: a changed file, a new one it does not ignore (whatever
    `status.showUntrackedFiles` says), a tracked one marked skip-worktree or assume-unchanged,
    whose changes git hides - and "HEAD" where its last commit is on no branch, tag or remote
    (a detached one's: its reflog goes with the worktree); None where git does not say."""
    try:
        git, until = _looking(tree)
        changed = _said(
            tree, git, until, "ls-files", "-z", "--modified", "--others", "--exclude-standard"
        )
        tagged = _said(tree, git, until, "ls-files", "-z", "-v")
        alone = _said(
            tree,
            git,
            until,
            "rev-list",
            "-n1",
            "HEAD",
            "--not",
            "--branches",
            "--tags",
            "--remotes",
        )
    except Refused:
        return None
    if changed is None or tagged is None or alone is None:
        return None
    return (
        [one for one in changed.split("\0") if one]
        + [one[2:] for one in tagged.split("\0") if one and not one.startswith("H ")]
        + (["HEAD"] if alone.strip() else [])
    )


def left_out(tree: Path) -> list[str] | None:
    """What git leaves out by its ignore rules in a worktree's folder - a file, or a folder as one
    (`build/`) -, which `worktree remove` deletes with it; None where git does not say."""
    try:
        said = _said(
            tree,
            *_looking(tree),
            "ls-files",
            "-z",
            "--others",
            "--ignored",
            "--exclude-standard",
            "--directory",
        )
    except Refused:
        return None
    return None if said is None else [one for one in said.split("\0") if one]


def same_repository(project: Path, folder: Path) -> bool:
    """Whether git run in `folder` is the project's own: the same top folder and git folder
    (`rev-parse --show-toplevel --git-common-dir`) - not a repository of its own in it, a
    worktree's, nor a bare one (it has no top folder, and `_in` uses no bare one it was not
    named: a mirror.git/ in the project). False where git does not say."""
    try:
        git, until = _looking(project)

        def found(where: Path) -> tuple[str, ...] | None:
            code, out, _said = _in(
                where,
                git,
                *UNASKED,
                "rev-parse",
                "--path-format=absolute",
                "--show-toplevel",
                "--git-common-dir",
                seconds=_left(until),
                **UNASKED_ENV,
            )
            lines = out.decode("utf-8", "replace").splitlines()
            return (
                tuple(os.path.normcase(os.path.realpath(line)) for line in lines)
                if (code == 0 and len(lines) == 2)
                else None
            )

        own = found(project)
        return own is not None and found(folder) == own
    except Refused:
        return False
