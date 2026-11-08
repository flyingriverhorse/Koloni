"""What a project's files hold, so that changes made behind KOLONİ's back can be seen.

A CLI agent in native mode changes files with tools of its own - its patch tool, or
any shell command. KOLONİ reads the project's text files before such an agent starts
and looks again whenever the agent has done something; what differs is a change.
"""

import contextlib
import hashlib
import os
import re
from pathlib import Path

from app.workspace import PTH_GLOBS, _name, is_kept_code, standing_names

# Folders that are not looked into: other people's code and build output.
UNREAD_FOLDERS = frozenset({
    ".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", "target",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".next", ".tox", "htmlcov",
})
MAX_FILE_BYTES = 256 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
# How a link or a junction at a standing path is held in `standing`, before where it leads.
LINK = b"\0a link to:"
# The mode a standing file had with the bytes it held (`standing`), by its path and their
# digest: one put back as it was is as runnable as it was then (a hook, on Linux and macOS).
# shortcut: kept for the app's life, one small entry for each version seen; prune if it grows.
MODES: dict[tuple[str, str], int] = {}


def mode_of(path: Path, data: bytes) -> int | None:
    return MODES.get((os.path.abspath(path), hashlib.sha256(data).hexdigest()))


def _is_link(path: Path) -> bool:
    """A symbolic link or a junction: it may lead out of the project."""
    try:
        return path.is_symlink() or path.is_junction()
    except OSError:
        return True


def hooks_path(config: bytes | None) -> str | None:
    """The folder `core.hooksPath` names in a `.git/config`, as written; None for none.
    shortcut: the file itself only - an `include.path` or the user's global config is not read."""
    core = re.search(rb"(?ims)^[ \t]*\[core\][^\[]*", config or b"")
    said = core and re.search(rb"(?im)^[ \t]*hookspath[ \t]*=[ \t]*(.*?)[ \t]*$", core[0])
    return (said[1].decode("utf-8", "replace").strip('"') or None) if said else None


def hooks_folder(root: Path, config: bytes | None) -> str | None:
    """The folder `core.hooksPath` names (`hooks_path`) by its path in the project - also where
    it is written whole -, casefolded on Windows; None for none, or one outside the project."""
    hooks = hooks_path(config)
    if not hooks:
        return None
    try:
        rel = os.path.relpath(os.path.normcase(os.path.normpath(root / hooks)),
                              os.path.normcase(os.path.normpath(root)))
    except ValueError:  # (another drive)
        return None
    return None if rel == "." or rel.split(os.sep)[0] == ".." else Path(rel).as_posix()


def _standing_path(parts: tuple[str, ...]) -> bool:
    """Whether a path in the project stands over later turns (`standing`)."""
    if parts and _name(parts[0]) == ".git":
        # (Of git's folder its hooks - not the samples, which it never runs - and its config;
        # and `.git` itself where it is a file or a link.)
        return len(parts) == 1 or _name(parts[1]) == "hooks" and not parts[-1].endswith(
            ".sample") or len(parts) == 2 and _name(parts[1]) == "config"
    return bool(standing_names(parts))


# KOLONİ's runtime folder (`Settings.runtime_root`), set by `AgentRunner` at its start: where it
# is inside a project (KOLONİ on its own repository), `standing` does not walk it.
RUNTIME: Path | None = None


def _runtime_in(root: Path) -> tuple[str, ...] | None:
    """`RUNTIME` as a path in the project, by names as `_name` gives them; None where it is
    not inside the project."""
    with contextlib.suppress(ValueError, OSError):
        if RUNTIME is not None:
            return tuple(map(_name, RUNTIME.resolve().relative_to(root.resolve()).parts))
    return None


def _scratch(parts: tuple[str, ...], name: str) -> bool:
    """Whether a folder `name` in the project folder at `parts` is the agents' scratch,
    `.koloni/tmp/` (K-koloni-klasor): thousands of files a browser profile rewrites each run -
    no look of "what changed" reads it (`standing`, `ProjectView.changes`)."""
    return len(parts) == 1 and _name(parts[0]) == ".koloni" and _name(name) == "tmp"


def standing(root: str | Path) -> dict[str, bytes]:  # noqa: C901
    """K-yazma-denetimi: every file of the project that tells later turns what they may do or
    runs by itself, by its path in the project, with its bytes - a path with a name of
    `NOT_WRITTEN_UNATTENDED` in it (of git's folder only its hooks and its config), the folder
    `core.hooksPath` names in the project, and an environment's `.pth` files (`PTH_GLOBS`). A
    link or a junction at such a path is held as `LINK` and where it leads, and not gone
    into. No size or text limit and no mtime shortcut: the set is small.
    shortcut: a file KOLONİ cannot read is not in it, nor what is written through a link that
    was there before (a linked worktree's git folder, a `.venv` linked in); read those too if
    an agent is seen to write there. The scratch `.koloni/tmp/` is not walked (`_scratch`).
    shortcut: so a standing name inside it (`.koloni/tmp/.claude/settings.json`) is not put
    back here - a command or file tool that writes one by name is still asked
    (`standing_names` judges the path's other parts); walk it if a CLI is seen to read one."""
    root = Path(root)
    found: dict[str, bytes] = {}

    def take(path: Path) -> None:
        rel = path.relative_to(root).as_posix()
        if _is_link(path):
            try:
                found[rel] = LINK + os.fsencode(os.readlink(path))
            except OSError:
                found[rel] = LINK
        else:
            with contextlib.suppress(OSError):
                found[rel] = data = path.read_bytes()
                # (the first mode seen wins: an agent's chmod +x of the same bytes is not "as
                # it was")
                MODES.setdefault((os.path.abspath(path), hashlib.sha256(data).hexdigest()),
                                 path.stat().st_mode & 0o777)

    # KOLONİ's own runtime inside the project (KOLONİ on its own repository): the copies it
    # holds carry the project's standing files - its, not the project's; not walked, as
    # `copies._scan` avoids it. (Seen with K-koloni-klasor: every copy's .koloni/.gitignore
    # was "taken back".)
    own = _runtime_in(root)
    for folder, folders, files in os.walk(root):
        here = Path(folder)
        parts = here.relative_to(root).parts
        # (In git's folder only hooks/ is walked; elsewhere not Claude Code's own worktrees
        # in .claude/ - whole checkouts, not its settings. shortcut: by that one name; prune
        # others the day a CLI keeps big folders there.)
        in_git = bool(parts) and _name(parts[0]) == ".git"
        in_claude = bool(parts) and _name(parts[-1]) == ".claude"
        folders[:] = [name for name in folders if (
            (len(parts) > 1 or _name(name) == "hooks") if in_git
            else not parts and _name(name) == ".git"
            or name not in UNREAD_FOLDERS and not (in_claude and _name(name) == "worktrees"))
            and tuple(map(_name, (*parts, name))) != own and not _scratch(parts, name)
            and not is_kept_code((*parts, name))]
        for name in [name for name in folders if _is_link(here / name)]:
            if _standing_path((*parts, name)):
                take(here / name)
        folders[:] = [name for name in folders if not _is_link(here / name)]
        for name in files:
            if _standing_path((*parts, name)):
                take(here / name)
    hooks = hooks_folder(root, found.get(".git/config"))
    with contextlib.suppress(OSError):
        parts = Path(hooks).parts if hooks else ()
        # (In the project only - `hooks_folder` -, and not through a link.)
        if parts and not any(
                _is_link(root.joinpath(*parts[:n])) for n in range(1, len(parts) + 1)):
            for path in root.joinpath(*parts).iterdir():
                if (path.is_file() or _is_link(path)) and not path.name.endswith(".sample"):
                    take(path)
    for pattern in PTH_GLOBS:
        for path in root.glob(pattern):
            parts = path.relative_to(root).parts
            # (Not through a link: an environment linked in is not the project's.)
            if not any(_is_link(root.joinpath(*parts[:n])) for n in range(1, len(parts))):
                take(path)
    return found


class ProjectView:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self._known: dict[str, str] = {}  # project-relative path -> text
        self._stamp: dict[str, tuple[int, int]] = {}  # path -> (mtime, size) when last looked at
        self._unread: set[str] = set()  # files seen but not kept: too large, or not text
        self._total = 0  # bytes of text kept
        self._looked = False
        # Files that appeared or changed at the last look but may not be opened (a CLI's
        # sandbox can create files the user's own account cannot read).
        self.blocked: list[str] = []
        # R161: files that appeared or changed but are not kept as text (a docx, a pdf, a
        # picture a command made): gathered over the looks until the caller takes them.
        self.made: set[str] = set()
        self.changes()  # the first look takes everything in and reports nothing

    def covers(self, relative: str) -> bool:
        """Whether a change to this file would be noticed with its earlier content."""
        return relative in self._known

    def paths(self) -> list[str]:
        """Every file the last look found, text or not, by its path in the project."""
        return list(self._stamp)

    def changes(self) -> list[tuple[str, str | None, str | None]]:  # noqa: C901
        """What changed since the last look: (path, before, after).

        `before` is None for a new file and `after` is None for a deleted one. Files
        that are too large, not text, behind a link, or in a folder that is not looked
        into are never reported.
        """
        first, self._looked = not self._looked, True
        self.blocked = []
        found: list[tuple[str, str | None, str | None]] = []
        present: set[str] = set()
        for folder, folders, files in os.walk(self.root):
            here = Path(folder)
            # Never through a link or junction: what is behind it is not the project.
            parts = here.relative_to(self.root).parts
            folders[:] = [
                name for name in folders
                if name not in UNREAD_FOLDERS and not _is_link(here / name)
                and not _scratch(parts, name) and not is_kept_code((*parts, name))
            ]
            for name in files:
                path = here / name
                if _is_link(path):
                    continue
                try:
                    relative = path.relative_to(self.root).as_posix()
                    status = path.stat()
                except (OSError, ValueError):
                    continue
                present.add(relative)
                stamp = (status.st_mtime_ns, status.st_size)
                if self._stamp.get(relative) == stamp:
                    continue
                self._stamp[relative] = stamp
                before = self._known.get(relative)
                was_unread = relative in self._unread
                self._forget(relative)
                try:
                    text = self._read(path, status.st_size)
                except OSError:
                    text = None
                    if not first:
                        self.blocked.append(relative)
                if text is None:
                    if not first and relative not in self.blocked:
                        self.made.add(relative)
                    self._unread.add(relative)
                    continue
                self._unread.discard(relative)
                self._known[relative] = text
                self._total += status.st_size
                # A file that could not be read before has no "before" to compare with.
                if not first and not was_unread and before != text:
                    found.append((relative, before, text))
        for relative in [r for r in self._known if r not in present]:
            found.append((relative, self._known[relative], None))
            self._forget(relative)
        for relative in [r for r in self._stamp if r not in present]:
            del self._stamp[relative]
        self._unread &= present
        return found

    def _forget(self, relative: str) -> None:
        old = self._known.pop(relative, None)
        if old is not None:
            self._total -= len(old.encode("utf-8"))

    def _read(self, path: Path, size: int) -> str | None:
        if size > MAX_FILE_BYTES or self._total + size > MAX_TOTAL_BYTES:
            return None
        try:
            return path.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            return None
