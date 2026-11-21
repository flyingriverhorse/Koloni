"""Coordination §4: whether what a plain delete names (`commands.disposable_targets`) is
disposable - a build or cache folder git ignores, a clean worktree of the user's, a merged local
branch nobody stands on - checked against the folder it runs in and the project's git. Any doubt
(git that does not answer, a link, a folder not read) is no: its card, as before. Blocking: call
it off the event loop.

shortcut: the folder is looked at as it is now; one changed between this look and the delete (a
folder swapped for a junction, a link put in it - Windows PowerShell 5.1's `Remove-Item
-Recurse` follows one) is not seen. Look again as it runs if that is ever met."""

import os
import stat
from pathlib import Path

from app import commands, git
from app.commands import DISPOSABLE_NAMES, _holds_link, disposable_targets, secret_files

NAMES = {"folder": "build folder", "worktree": "worktree", "branch": "branch"}
# Never disposable, whatever git says the default branch is.
NEVER = ("main", "master")


def what(command: str, project: Path, root: Path, cwd: str | None, *, in_copy: bool,
         copies_at: list[Path], keep: str | None) -> str | None:
    """What a delete deletes, said as its row says it ("build folder dist; branch old"), where
    each thing it names is disposable; None where any is not, or it is no such delete. `root`:
    where it runs - the project, or a copy's tree (`in_copy`: a build folder there only); `cwd`:
    where in it (None: not known - nothing is disposable); `copies_at`: KOLONİ's copies folders
    (`copies.folders`); `keep`: the branch the turn began on."""
    targets = disposable_targets(command)
    if targets is None or cwd is None:
        return None
    gits = {kind for kind, _target, _force in targets if kind != "folder"}
    if gits and in_copy:  # (a worktree, a branch: the project's own, never a copy's)
        return None
    here = os.path.normpath(os.path.join(os.path.realpath(root), cwd))
    seen = git.where(project) if gits else None
    default = git.default_branch(project) if "branch" in gits else None
    for kind, target, force in targets:
        if not (kind == "folder" and _folder(project, root, here, target)
                or kind == "worktree" and seen is not None
                and _worktree(project, here, target, seen, copies_at)
                or kind == "branch" and seen is not None and default is not None
                and _branch(project, target, force, seen, keep, default)):
            return None
    return "; ".join(f"{NAMES[kind]} {target}" for kind, target, _force in targets)


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
    link on the way to it), no link below it, ignored by the project's git and holding no file
    git tracks (its path in the project is its path in a copy)."""
    top = os.path.realpath(root)
    spelt = os.path.normpath(os.path.join(here, rel))
    real = _a_folder(spelt)
    inside = os.path.relpath(spelt, top).replace("\\", "/") if real else ".."
    if real != os.path.normcase(spelt) or inside.split("/")[0] in ("..", "."):
        return False
    return (not _holds_link([real]) and git.ignored(project, [inside + "/"]) == {inside + "/"}
            and git.tracked_under(project, inside) is False)


def _worktree(project: Path, here: str, path: str, seen: dict, copies_at: list[Path]) -> bool:
    """A worktree git lists of the project - not its main one, nor the project's own or one the
    project is in, not locked (KOLONİ's are while their agents work), not in KOLONİ's copies
    folders - that holds no link, no secret file and nothing git ignores but build and cache
    folders: git deletes what it ignores with the worktree."""
    real = _a_folder(os.path.normpath(os.path.join(here, path)))
    own = _real(project)
    listed = [one for one in seen["worktrees"][1:] if _real(one["path"]) == real]
    if real is None or not listed or listed[0]["locked"] or _under(own, real) or any(
            _under(real, _real(held)) for held in copies_at):
        return False
    commands._held.pop(Path(real), None)  # (walked anew: a walk kept for 10 s misses a new one)
    left = git.left_out(Path(real))
    return left is not None and all(
        DISPOSABLE_NAMES & set(one.rstrip("/").split("/")) for one in left) and not (
        _holds_link([real]) or secret_files(Path(real)))


def _branch(project: Path, name: str, force: bool, seen: dict, keep: str | None,
            default: str) -> bool:
    """A local branch by its exact name, not where the project, the turn or a worktree stands,
    not the default (nor main or master), not KOLONİ's own (Windows and macOS find a ref file
    in any case: compared so); forced (`-D`) only with no commit the default has not."""
    standing = {seen["branch"], keep, default, *NEVER,
                *(one["branch"] for one in seen["worktrees"])}
    return (name in seen["names"]
            and name.casefold() not in {one.casefold() for one in standing if one}
            and not name.casefold().startswith(git.BRANCH_PREFIX)
            and (not force or git.ahead(project, default, name) == 0))
