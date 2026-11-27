"""Coordination §4: whether what a plain delete names (`disposable_targets`) is
disposable - a build or cache folder git ignores, a clean worktree of the user's, a merged local
branch nobody stands on - checked against the folder it runs in and the project's git. Any doubt
(git that does not answer, a link, a folder not read) is no: its card, as before. Blocking: call
it off the event loop.

shortcut: the folder is looked at as it is then - KOLONİ's own command a second time just before
it runs (`AgentRunner._command_call`); one changed between that look and the delete (a folder
swapped for a junction, a link put in it) is not seen. On this machine (21 Nov 2026) Windows
PowerShell 5.1.26100's and PowerShell 7's `Remove-Item -Recurse` and Git Bash's `rm -rf` follow
neither a junction inside the folder nor a folder that is one; older Windows 10 builds of
PowerShell 5.1 follow both. Look as it runs, in the shell, if such a build is met."""

import os
import re
import stat
from collections.abc import Callable
from pathlib import Path

from app import git, git_looks
from app.commands import (
    POSIX,
    POWERSHELL,
    _holds_link,
    secret_files,
)
from app.copies import LINKED
from app.workspace import Workspace, _held

# Coordination §4: the deletes KOLONİ can check by itself, where the user allowed them in the
# project (`Project.disposable_deletes`) - a build or cache folder, a worktree, a branch. Read
# from a line this plain only: words of ASCII letters, digits and `_ . / -`, one space between
# them - no quote, backslash, drive, comment, splat, variable, wildcard or other space a shell
# reads past a plain word - and no option that is not read here.
DISPOSABLE_NAMES = frozenset(
    {
        "build",
        "dist",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        "coverage",
        ".next",
        ".turbo",
        "target",
    }
)
_DISPOSABLE_LINE = re.compile(r"[A-Za-z0-9_./-]+(?: [A-Za-z0-9_./-]+)*")
# Each shell's own forms, as each reads them - measured in Windows PowerShell 5.1 (22 Nov
# 2026): Remove-Item and its aliases, `-r` its -Recurse, `-fo` its -Force, one path (`-rf`, `-f`
# and a second path are errors, nothing deleted); sh's rm by its own name and options, as many
# paths as it is given. (its deleters, its recursions, its other flags, its forcings, most paths)
_DELETE_FORMS = {
    POWERSHELL: (
        frozenset({"remove-item", "ri", "rm", "del", "erase"}),
        frozenset({"-recurse", "-r"}),
        frozenset({"-force", "-fo", "-path", "-literalpath"}),
        frozenset({"-force", "-fo"}),
        1,
    ),
    POSIX: (
        frozenset({"rm"}),
        frozenset({"-r", "-R", "-rf", "-fr", "-Rf", "-fR"}),
        frozenset({"-f", "--force"}),
        frozenset({"-f", "--force", "-rf", "-fr", "-Rf", "-fR"}),
        None,
    ),
}


def disposable_targets(command: str, shell: str | None) -> list[tuple[str, str, bool]] | None:
    """What a line deletes where it is nothing but a delete KOLONİ can check: ("folder", its
    path, forced) for each build or cache folder of the `shell`'s own recursive delete (`rm -r`
    in sh, `Remove-Item -Recurse` in PowerShell; a shell not known: none); ("worktree", its path,
    False) for `git worktree remove <path>`; ("branch", its name, forced) for each of `git branch
    -d|-D` (git's, every shell's alike). None for any other line. What it names only: whether
    each is disposable is for the checks of its folder."""
    if not _DISPOSABLE_LINE.fullmatch(command):
        return None
    words = command.split(" ")
    if words[0] == "git":
        return _worktree_target(words[1:]) or _branch_targets(words[1:])
    return _folder_targets(words, shell)


def _plain_name(part: str) -> bool:
    """A path's or a branch's part as every shell and file system reads it: not empty, no
    dot-name, nothing Windows opens as another (`node_modules.` is `node_modules`)."""
    return bool(part) and not part.startswith(".") and not part.endswith(".")


def _folder_targets(words: list[str], shell: str | None) -> list[tuple[str, str, bool]] | None:
    """A bare deleter's recursive delete of build or cache folders below where it runs, in the
    shell's own form (PowerShell's names and options in any case, sh's as spelt; no trailing
    slash: `build/` is where a link named build leads)."""
    if shell not in _DELETE_FORMS:
        return None
    deleters, recursions, others, forcings, most = _DELETE_FORMS[shell]
    read: Callable[[str], str] = str.casefold if shell == POWERSHELL else str
    flags = {read(word) for word in words[1:] if word.startswith("-")}
    paths = [word for word in words[1:] if not word.startswith("-")]
    if (
        read(words[0]) not in deleters
        or not paths
        or not flags & recursions
        or not flags <= recursions | others
        or most is not None
        and len(paths) > most
    ):
        return None
    for path in paths:
        *above, name = path.split("/")
        if name not in DISPOSABLE_NAMES or not all(
            _plain_name(part) and part.casefold() not in LINKED for part in above
        ):
            return None
    return [("folder", path, bool(flags & forcings)) for path in paths]


def _worktree_target(rest: list[str]) -> list[tuple[str, str, bool]] | None:
    """`git worktree remove <path>` alone - never forced; up and absolute paths too (a
    worktree is registered where it is)."""
    if len(rest) != 3 or rest[:2] != ["worktree", "remove"] or rest[2].startswith("-"):
        return None
    parts = rest[2].split("/")
    if all(
        part == ".." or _plain_name(part) and part.casefold() not in LINKED
        for part in (parts if parts[0] else parts[1:])
    ):  # (`/x/wt`: from the root)
        return [("worktree", rest[2], False)]
    return None


def _branch_targets(rest: list[str]) -> list[tuple[str, str, bool]] | None:
    """`git branch -d|-D <name>...`: none of KOLONİ's own (`koloni/…` - Windows and macOS find
    `Koloni/x`'s ref file as `koloni/x`'s)."""
    if len(rest) < 3 or rest[0] != "branch" or rest[1] not in ("-d", "-D"):
        return None
    for name in rest[2:]:
        parts = name.split("/")
        if (
            name.startswith("-")
            or parts[0].casefold() == "koloni"
            or not all(map(_plain_name, parts))
        ):
            return None
    return [("branch", name, rest[1] == "-D") for name in rest[2:]]


NAMES = {"folder": "build folder", "worktree": "worktree", "branch": "branch"}
# Why a delete found disposable is asked all the same: its second look, just before it runs (a
# card of the turn waited for meanwhile), did not find what the first did.
CHANGED = "what it deletes changed between KOLONİ's first look and its run: asked as any delete is"
# Never disposable, whatever git says the default branch is.
NEVER = ("main", "master")


def what(
    command: str,
    project: Path,
    root: Path,
    cwd: str | None,
    *,
    in_copy: bool,
    copies_at: list[Path],
    keep: str | None,
    shell: str | None,
) -> str | None:
    """What a delete deletes, said as its row says it ("build folder dist; branch old"), where
    each thing it names is disposable; None where any is not, or it is no such delete. `root`:
    where it runs - the project, or a copy's tree (`in_copy`: a build folder there only); `cwd`:
    where in it (None: not known - nothing is disposable); `copies_at`: KOLONİ's copies folders
    (`copies.folders`); `keep`: the branch the turn began on; `shell`: the one it runs in
    (`commands.POWERSHELL`, `POSIX`; None: not known - no folder's delete is read)."""
    targets = disposable_targets(command, shell)
    if targets is None or cwd is None:
        return None
    gits = {kind for kind, _target, _force in targets if kind != "folder"}
    here = os.path.normpath(os.path.join(os.path.realpath(root), cwd))
    # (a worktree, a branch: the project's own, never a copy's - nor another repository's in it)
    if gits and (in_copy or not _the_projects_git(root, here)):
        return None
    seen = git.where(project) if gits else None
    default = git_looks.default_branch(project) if "branch" in gits else None
    for kind, target, force in targets:
        if not (
            kind == "folder"
            and _folder(project, root, here, target)
            or kind == "worktree"
            and seen is not None
            and _worktree(project, here, target, seen, copies_at)
            or kind == "branch"
            and seen is not None
            and default is not None
            and _branch(project, target, force, seen, keep, default)
        ):
            return None
    return "; ".join(f"{NAMES[kind]} {target}" for kind, target, _force in targets)


def cli_shell(cli: str, tool: str) -> str | None:
    """The shell a CLI's own command runs in, where KOLONİ knows it: Claude Code's Bash tool's
    bash (Git Bash on Windows), its PowerShell tool's PowerShell. None for any other: Codex and
    agy send a command with no shell said (each reaches KOLONİ named "Bash"), and Claude
    Code's Monitor is not measured."""
    return {"Bash": POSIX, "PowerShell": POWERSHELL}.get(tool) if cli == "claude" else None


def _the_projects_git(root: Path, here: str) -> bool:
    """Whether git run in `here` is the project's own (`root`'s): a folder in it reached with no
    link on the way (git finds a repository upward from where a link leads), with no `.git` in it
    or between (another repository's, a submodule's, a worktree's), and git there says so (a bare
    one, `mirror.git/`, has no `.git`)."""
    top = os.path.realpath(root)
    parts = [] if here == top else os.path.relpath(here, top).replace("\\", "/").split("/")
    return (
        _real(here) == os.path.normcase(here)
        and ".." not in parts
        and not (_another_repository(top, parts))
        and git_looks.same_repository(Path(top), Path(here))
    )


def _another_repository(top: str, parts: list[str]) -> bool:
    """Whether a `.git` - a repository's folder, or a submodule's or a worktree's file - is in a
    folder between `top` and the end of `parts`, that one too: git there is another
    repository's, or another worktree's index, not the project's."""
    return any(
        os.path.lexists(os.path.join(top, *parts[:at], ".git")) for at in range(1, len(parts) + 1)
    )


def _real(path: str | Path) -> str:
    return os.path.normcase(os.path.realpath(path))


def _under(path: str, folder: str) -> bool:
    """Whether `path` is `folder` or in it (both `_real`)."""
    return path == folder or path.startswith(folder.rstrip(os.sep) + os.sep)


def _a_folder(spelt: str) -> str | None:
    """`spelt`'s real path where it is a folder itself, no link nor junction; None otherwise."""
    try:
        if not stat.S_ISDIR(os.lstat(spelt).st_mode) or os.path.isjunction(spelt):
            return None
        return _real(os.path.realpath(spelt, strict=True))
    except (OSError, ValueError):
        return None


def _folder(project: Path, root: Path, here: str, rel: str) -> bool:
    """A build or cache folder below where the command runs: a folder there as it is spelt (no
    link on the way to it, each part in the case the disk has it), no part above it a dot-name, a
    linked folder or KOLONİ's own; nothing below it a link or a repository; ignored by the
    project's git, which keeps nothing in it in any case (its path in the project is its path in
    a copy)."""
    top = os.path.realpath(root)
    spelt = os.path.normpath(os.path.join(here, rel))
    real = _a_folder(spelt)
    parts = os.path.relpath(spelt, top).replace("\\", "/").split("/") if real else [".."]
    inside = "/".join(parts)
    if (
        real != os.path.normcase(spelt)
        or not all(_plain_name(part) and part.casefold() not in LINKED for part in parts[:-1])
        or not (_as_on_disk(top, parts))
        or _koloni_s(top, spelt)
        or _another_repository(top, parts)
    ):
        return False
    # (ignored itself, no folder above it ignored: `env/`, a venv by another name, or `data/`)
    above = ["/".join(parts[:at]) + "/" for at in range(1, len(parts))]
    return (
        not _holds_more(real)
        and git.ignored(project, [*above, inside + "/"]) == {inside + "/"}
        and git_looks.kept_under(project, inside) is False
    )


def _as_on_disk(top: str, parts: list[str]) -> bool:
    """Whether each part of a path below `top` is spelt as its folder holds it: NTFS and APFS
    open `build` as `Build`, and git tells them apart."""
    at = top
    for part in parts:
        try:
            if part not in os.listdir(at):
                return False
        except OSError:
            return False
        at = os.path.join(at, part)
    return True


def _koloni_s(top: str, spelt: str) -> bool:
    """Whether a folder is in KOLONİ's own code or record, or holds either (`koloni_s`)."""
    place, folder = Workspace(top), Path(os.path.realpath(spelt))
    return bool(place.koloni_s(folder) or place.koloni_under(folder))


def _holds_more(top: str, left: int = 10_000) -> bool:
    """Whether a folder holds, anywhere below it, a link or a junction, a `.git` (a repository of
    its own, whose commits may be nowhere else), or more than is looked at (`left` entries) - or
    is not read."""
    folders = [top]
    while folders:
        try:
            with os.scandir(folders.pop()) as found:
                for entry in found:
                    left -= 1
                    if (
                        left < 0
                        or entry.name.casefold() == ".git"
                        or entry.is_symlink()
                        or entry.is_junction()
                    ):
                        return True
                    if entry.is_dir(follow_symlinks=False):
                        folders.append(entry.path)
        except (OSError, ValueError):
            return True
    return False


def _worktree(project: Path, here: str, path: str, seen: dict, copies_at: list[Path]) -> bool:
    """A worktree git lists of the project - named with no link on the way, by no end of its
    path another listed one shares; not its main one, nor the project's own or one the project
    is in, not locked (KOLONİ's are while their agents work), not in KOLONİ's copies folders -
    whose folder holds nothing its commits do not (`not_committed`), no link, no secret file
    and nothing git ignores but whole build and cache folders: git deletes what it ignores with
    the worktree."""
    spelt = os.path.normpath(os.path.join(here, path))
    real = _a_folder(spelt)
    own = _real(project)
    listed = [one for one in seen["worktrees"][1:] if _real(one["path"]) == real]
    if (
        real != os.path.normcase(spelt)
        or _climbs_past_a_name(path)
        or not listed
        or listed[0]["locked"]
        or listed[0]["branch"] is None
        or _under(own, real)
        or _ends_alike(path, seen["worktrees"], real)
        or any(_under(real, _real(held)) for held in copies_at)
    ):
        return False
    return _holds_nothing_else(real)


def _holds_nothing_else(real: str) -> bool:
    """Whether a worktree's folder holds nothing but its commits and whole build and cache
    folders git ignores, holding no repository or link of their own: git deletes what it
    ignores with the worktree. No link anywhere in it, no secret file."""
    _held.pop(Path(real), None)  # (walked anew: a walk kept for 10 s misses a new one)
    left = git_looks.left_out(Path(real))
    return (
        left is not None
        and all(
            one.endswith("/")
            and one.rstrip("/").split("/")[-1] in DISPOSABLE_NAMES
            and not _holds_more(os.path.join(real, one))
            for one in left
        )
        and git_looks.not_committed(Path(real)) == []
        and not (_holds_link([real]) or secret_files(Path(real)))
    )


def _climbs_past_a_name(path: str) -> bool:
    """Whether a `..` follows a name in a path as written: KOLONİ reads `J/..` as where it started,
    the shell from where a link J leads. A leading one climbs from where the command runs, whose
    real path is known."""
    parts = path.split("/")
    first = next((at for at, part in enumerate(parts) if part != ".."), len(parts))
    return ".." in parts[first:]


def _ends_alike(path: str, worktrees: list[dict], real: str) -> bool:
    """Whether another listed worktree's path ends with `path` as written: git looks a worktree
    up by the end of its path first (`git worktree remove J/x` is any `.../J/x`)."""
    end = "/" + path.replace("\\", "/").strip("/").casefold()
    return any(
        _real(one["path"]) != real and one["path"].replace("\\", "/").casefold().endswith(end)
        for one in worktrees
    )


def _branch(
    project: Path, name: str, force: bool, seen: dict, keep: str | None, default: str
) -> bool:
    """A local branch by its exact name, not where the project, the turn or a worktree stands,
    not the default (nor main or master), not KOLONİ's own (Windows and macOS find a ref file
    in any case: compared so); forced (`-D`) only with no commit the default has not."""
    standing = {
        seen["branch"],
        keep,
        default,
        *NEVER,
        *(one["branch"] for one in seen["worktrees"]),
    }
    return (
        name in seen["names"]
        and name.casefold() not in {one.casefold() for one in standing if one}
        and not name.casefold().startswith(git.BRANCH_PREFIX)
        and (not force or git_looks.ahead(project, default, name) == 0)
    )
