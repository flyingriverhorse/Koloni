"""Working copies: each sub-agent changes files in a copy of the project of its own.

A copy is a plain copy of the project's files in a folder under the runtime root - or in
the user's data folder, where the runtime root is inside a repository (`folder`) - outside
the project, so that neither the file watch, nor a search, nor git sees it. `.git` and the
caches are left out; the folders of installed dependencies are not copied but linked to the
project's own (a directory junction on Windows, a symlink elsewhere): they are shared, not
kept apart. What every file held when it was copied is kept (`base`), so that taking the
copy into the project can tell three things apart for each file: what it was, what the
project holds now, what the copy holds now. Of a file of at most 1 MiB the bytes are kept
too (`BASE`): a file both sides changed can then be merged line by line.

Nothing here touches the database or waits: `AgentRunner` owns the copies of the turns now
running. Deleting is the careful part - a link is removed as a link, and what it leads to
is never walked into.
"""

import contextlib
import hashlib
import json
import os
import stat
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from functools import cached_property
from pathlib import Path

from app.workspace import SCRATCH, Workspace, WorkspaceError, is_kept_code, write_bytes

# More than this is not copied: the agent works in the project, as before.
MAX_FILES = 20_000
MAX_BYTES = 500 * 1024 * 1024
# Left out of a copy, and of what is taken back from it, at any depth: git's own folder
# (a copy of it would run the repository's hooks and settings; git does not work in a
# copy) and what tools write for themselves.
NOT_COPIED = frozenset({
    ".git", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", "dist", "build",
})
# Not copied but linked to the project's own, at any depth: installed dependencies.
LINKED = frozenset({"node_modules", ".venv", "venv"})
# The teams' shared folder (`app.shared`): left out by its path, not its name - the project's
# own `shared/` folders are copied as any other. It is written and read in the project alone.
SHARED = ".koloni/shared"
# The agents' scratch (`workspace.SCRATCH`, K-koloni-klasor) is left out the same way, so what
# an agent puts there is never offered at Take in.
# The folder that holds every copy, each in a folder of its own (`folder`).
FOLDER = "copies"
# What makes a folder, and every folder below it, no place for a copy: git's own (git
# in a copy would answer with that repository) and what Codex, Claude Code and Gemini
# read as their instructions from the folders above the one they are started in.
MARKS = (".git", "AGENTS.md", "CLAUDE.md", "GEMINI.md", ".claude")
NO_PLACE = (
    "no folder for working copies is outside every repository and every CLI's "
    "instruction files"
)
# A copy's folder holds the tree the agent works in and, beside it - not in it - what
# every file held when it was copied: after a restart that is what its files are
# compared by. Beside, so that neither the agent's file tools (confined to the tree),
# nor a command in a container (only the tree is mounted), nor a command that cleans
# or rewrites its working folder reaches it.
TREE = "tree"
BASE_FILE = "base.json"
# More than a copy of `MAX_FILES` files ever writes there (a path and a digest each).
MAX_BASE_BYTES = MAX_FILES * 2048
# Beside the tree too: the bytes of each file as it was copied, at the same path, for a
# file of at most `MAX_BASE_TEXT` - what a line-by-line merge starts from. Believed only
# where its digest is the one `BASE_FILE` has for the file (`Copy.started_from`).
BASE = "base"
MAX_BASE_TEXT = 1024 * 1024
# Of the top names a copy of what git tracks left out (`Copy.left`), as many as are kept.
MAX_LEFT = 100
# Why a file is not taken, either way, when its path leaves the folder through a link.
OUTSIDE = "it leads out of the project folder, or of the copy, through a link"
# B-189: why a new file git ignores in the project is not offered (`Copy.ignored`).
IGNORED = "not offered: ignored by git - it is not kept"
# K-kopya-git: a file git ignores that the project has, which a copy of what git tracks did not
# hold, written in the copy by its agent (`Copy.state`: a conflict of whole files).
NOT_HELD = ("the copy did not hold this file (git ignores it): taking the agent's replaces the "
            "project's")
# Why a file of a copy that does not say what it was made from is not offered.
NOT_OFFERED = (
    "it differs from the project's and is not offered: what this copy started from is "
    "not known, and no change of the agent's to it is on record"
)
# K-buyuk-proje: a file a command made in a copy of one part, outside that part (`Copy.state`):
# shown, never taken - the copy is kept for the user to look at and discard.
NOT_IN_PART = "made outside this agent's part, in its copy: not taken into the project"


class TooBig(Exception):
    """The project has more files, or more bytes, than a copy is made of."""


def _user_data() -> Path:
    """The folder programs keep a user's data in."""
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def _clear(place: Path) -> bool:
    """Whether a folder is in nobody's repository and below nothing that tells a CLI
    what to do (`MARKS`, in it or in any folder above it). The `.claude` in the user's
    own home does not count: Claude Code reads that one wherever it is started."""
    home = Path(os.path.expanduser("~"))
    return not any(
        os.path.lexists(above / mark)
        for above in (place, *place.parents) for mark in MARKS
        if not (mark == ".claude" and above == home)
    )


def folder(runtime_root: Path) -> Path | None:
    """Where copies are made: `<runtime root>/copies` - or, where that is inside a
    repository or below a CLI's instructions (KOLONİ's own checkout is both), a folder
    of this runtime root's in the user's data folder. None where that is no better:
    then no copy is made."""
    return next((held for held in _both(runtime_root) if _clear(held)), None)


def _both(runtime_root: Path) -> tuple[Path, Path]:
    """The two folders a copy is ever in: the runtime root's own, and this runtime
    root's in the user's data folder."""
    of_root = os.path.normcase(str(Path(runtime_root).resolve())).encode("utf-8")
    return (
        Path(os.path.abspath(runtime_root)) / FOLDER,
        _user_data() / "KOLONI" / FOLDER / hashlib.sha256(of_root).hexdigest()[:12],
    )


def folders(runtime_root: Path) -> list[Path]:
    """Every folder a copy may be in: where they are made first, then the other of the
    two (`_both`) - a copy that was kept is still where it was made, whatever has been
    put above either folder, or taken away, since. Nothing is deleted anywhere else."""
    return list(dict.fromkeys(
        held for held in (folder(runtime_root), *_both(runtime_root)) if held
    ))


def ceiling(tree: Path) -> str:
    """GIT_CEILING_DIRECTORIES for whatever is started in a copy's tree: git looks for
    a repository no higher than the copies folder - never in one that folder is in."""
    return os.pathsep.join(
        [str(tree.parent.parent), *filter(None, [os.environ.get("GIT_CEILING_DIRECTORIES")])]
    )


def _key(path: str) -> str:
    """A path inside the project as it is compared: any case where the disk has none."""
    return path.casefold() if os.name == "nt" else path


def _is_link(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()


# B-383 (live): a Coder made a .venv in its copy; Take in left it out, as it should, and nobody
# said so - the Lead told the user the venv was there. Of the folders Take in leaves out, the ones
# an agent makes to install or build into (`__pycache__` and the tools' caches go unsaid: every
# run makes them), how each is made again in the project.
MADE_HOW = {".venv": "`python -m venv .venv`", "venv": "`python -m venv venv`",
            "node_modules": "`npm install`", "dist": "its build", "build": "its build"}
MADE_NAMED = 3
LEFT_IN_COPY = "The {names} made in the copy {stay} out of the project: make {it} there with {how}."


def left_in(tree: Path) -> str:
    """B-383: one line on the dependency and build folders at the top of a copy's tree that its
    agent made there (not the project's own, linked in), which Take in leaves out; "" for none.
    shortcut: the top of the tree only - a part's own node_modules below it goes unsaid; look one
    level down if that is missed."""
    try:
        made = sorted(entry.name for entry in os.scandir(tree)
                      if entry.name.casefold() in MADE_HOW and entry.is_dir(follow_symlinks=False)
                      and not _is_link(Path(entry.path)))[:MADE_NAMED]
    except OSError:
        return ""
    if not made:
        return ""
    one = len(made) == 1
    return LEFT_IN_COPY.format(
        names=", ".join(made), stay="stays" if one else "stay", it="it" if one else "them",
        how=" and ".join(dict.fromkeys(MADE_HOW[name.casefold()] for name in made)))


def digest(path: Path, follow: bool = False) -> str | None:
    """A digest of a file as it is on disk, text or not; None for one that is not there
    (a folder or - unless `follow` - a link is not a file). One that cannot be read is like
    no other."""
    try:
        if not follow and _is_link(path) or not path.is_file():
            return None
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return "unreadable"


def _bytes(path: Path) -> bytes | None:
    """What a file holds; None for one that is not there, or cannot be read."""
    try:
        return None if _is_link(path) or not path.is_file() else path.read_bytes()
    except OSError:
        return None


RUN_BITS = stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH


def keep_mode(source: Path, target: Path) -> None:
    """A file's run bits go with its bytes - `./gradlew` stays runnable - and only those, as
    git carries them: the target keeps its own read and write bits. Never through a link.
    POSIX only: Windows has none to carry."""
    if os.name == "nt" or target.is_symlink() or not (source.is_file() and target.is_file()):
        return
    had = stat.S_IMODE(target.stat().st_mode)
    wanted = had & ~RUN_BITS | stat.S_IMODE(source.stat().st_mode) & RUN_BITS
    if wanted != had:
        os.chmod(target, wanted)


def _inside(folder: Workspace, path: str) -> Path | None:
    """Where a path is in a folder itself; None for one that leads out of it - through a
    link or a junction at any part of it - so that nothing is read, written or deleted
    there."""
    try:
        return folder.resolve(path)
    except (WorkspaceError, OSError):
        return None


def under(parts: Sequence[str], names: frozenset[str]) -> str | None:
    """The folder of one of these names that a path is in, as its parts are written (any
    case, and with the dots and spaces Windows drops from the end of a name); None for
    a path in none. The names are folders': the path's last part is a file, and a file
    of such a name is a file like any other - but for git's own, a file too in a
    worktree, which is never a copy's."""
    *above, last = (part.rstrip(" .").casefold() for part in parts)
    found = next((part for part in above if part in names), None)
    return found or (last if last == ".git" and last in names else None)


def _apart(path: str, project: Workspace | None = None, tops: tuple[Path, ...] = ()) -> bool:
    """Whether a path is under a name that is left out of a copy or linked in it, so
    that nothing there is the copy's to take back - as the path is written and, with
    `project`, as it really leads there (a short name, a link): a kept copy has lost
    its links, and what it says of itself is not trusted. A path that itself has such
    a name is apart where it is a folder or a link in one of `tops`, not where it is a
    file (`under`)."""
    chains = [path.split("/")]
    if project is not None:
        with contextlib.suppress(WorkspaceError, ValueError, OSError):
            chains.append(list(project.resolve(path).relative_to(project.root).parts))
    names = NOT_COPIED | LINKED
    if any(under(chain, names) or "/".join(chain[:2]).casefold() == SHARED for chain in chains):
        return True
    return any(chain[-1].rstrip(" .").casefold() in names for chain in chains) and any(
        _is_link(top / path) or (top / path).is_dir() for top in tops
    )


def _git_listed(project: Path) -> list[str] | None:
    from app import git  # (here: git's executors import commands, which imports this)

    return git.listed(project)


def _holds(part: str | None, path: str, project: Path | None = None) -> bool:
    """K-buyuk-proje: whether a path from the project root is one a copy of this part holds: a
    file at the root, or one in the part's folder (as `_key` compares). No part: every path.
    With `project`: not a name at the root that is a folder there (another part's)."""
    if part is None:
        return True
    if "/" in path:
        return _key(path).startswith(_key(part))
    return project is None or not (project / path).is_dir()


def _held(project: Path, part: str | None, listed: list[str] | None) -> list[str] | None:
    """What `_scan` takes of a project (its `held`) for a copy of this part: the part and the
    root's own files - of `listed` only (`git.listed`), where given. No part: `listed`."""
    if part is None:
        return listed
    if listed is not None:
        # A folder is listed by its name where it is a submodule: the part itself, or one in
        # it, is held; one at the root is not a root file.
        return [path for path in listed if _key(path.rstrip("/") + "/").startswith(_key(part))
                or ("/" not in path and not (project / path).is_dir())]
    with os.scandir(project) as found:
        return [part, *(entry.name for entry in found if entry.is_file(follow_symlinks=False))]


def _scan(
    top: Path, avoid: Path | None = None, held: list[str] | None = None,
    left: list[str] | None = None, stop: bool = False,
) -> tuple[list[str], list[str], int]:
    """The files of a folder that belong in a copy, the folders that are linked instead,
    and the files' size - paths inside `top`, with forward slashes. No link is followed;
    a link that is not one of `LINKED` is left out, and so is one of them that leads out
    of `top` itself: through the copy it would be read, which in the project it is not.
    `avoid`: a folder not gone into. `held`: where given (`git.listed`), only the files it
    names and all of a folder it names (a submodule) - a folder none of them is in is not
    gone into; the top name of what is so left out goes into `left`, once. `stop`: TooBig
    as soon as the files are over `MAX_FILES` or `MAX_BYTES`, the rest not looked at."""
    files: list[str] = []
    links: list[str] = []
    size = 0
    keys = {_key(path.rstrip("/")) for path in held or ()}
    above = {_key(path[:at]) for path in keys for at, char in enumerate(path) if char == "/"}
    todo = [("", held is None)]
    whole = top.resolve()
    ours = Workspace(whole)  # (KOLONİ's own checkout or record in it: never copied)
    while todo:
        inside, every = todo.pop()
        with os.scandir(top / inside) as found:
            entries = sorted(found, key=lambda entry: entry.name)
        for entry in entries:
            name, path = entry.name, Path(entry.path)
            relative = f"{inside}{name}"
            link = _is_link(path)
            # A folder of such a name is left out - a file of it is a file like any
            # other (a `build` script), but for git's own.
            if name.casefold() == ".git" or relative.casefold() in (SHARED, SCRATCH) or (
                name.casefold() in NOT_COPIED and (link or entry.is_dir(follow_symlinks=False))
            ):
                continue
            # (A repository's code a knowledge keeps - thousands of files to read, never to
            # change - is linked as the dependencies are: its expert reads it from a copy too.)
            if (name.casefold() in LINKED or is_kept_code(relative.split("/"))) and (
                    link or entry.is_dir(follow_symlinks=False)):
                if path.is_dir() and path.resolve().is_relative_to(whole):
                    links.append(relative)
            elif link or (avoid is not None and path == avoid) or ours.koloni_s(whole / relative):
                continue
            elif not every and _key(relative) not in keys and _key(relative) not in above:
                first, _slash, below = relative.partition("/")
                shown = f"{first}/" if below or entry.is_dir(follow_symlinks=False) else first
                if left is not None and shown not in left:
                    left.append(shown)
            elif entry.is_dir(follow_symlinks=False):
                todo.append((f"{relative}/", every or _key(relative) in keys))
            elif entry.is_file(follow_symlinks=False):
                files.append(relative)
                size += entry.stat(follow_symlinks=False).st_size
                if stop and (len(files) > MAX_FILES or size > MAX_BYTES):
                    raise TooBig(f"over {MAX_FILES} files or {MAX_BYTES} bytes")
    return files, links, size


def _link(link: Path, target: Path) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        os.symlink(target, link, target_is_directory=True)


@dataclass
class Copy:
    """One working copy: where the project is, where the copy is, what each copied file
    held then (`base`, by `_key`; `names` has the path as it is written), and its links -
    where each stands in the copy, and the project folder it leads to. `two_way`: a
    kept copy with nothing to say what it was made from (`kept`) - its files are
    compared with the project's alone, and nothing vouches for any of them; `names`
    then has the paths its agents are on record as having changed in it.

    Both by the path as a card has it: `results` - of this process alone, not on disk -
    for a file both sides changed that was merged line by line and is not written into
    the copy yet: the digests of the two files the merge was made of ("shown"), the
    project's bytes ("there"), and the merged bytes ("merged") or, where the same lines
    clash, the bytes with either side's lines there ("agent", "project"); `joined` - the
    digest of each file that `join` wrote into the copy, written down with what the copy
    was made from (`save`): such a file is the two sides together after a restart too."""

    project: Path
    root: Path
    base: dict[str, str]
    names: dict[str, str]
    links: dict[str, Path]
    two_way: bool = False
    # Made of what the project's git would track (`git.listed`), the project being too big to
    # copy whole: what it ignores is not in it, and `behind` holds to the same; `left`, the top
    # names of what was so left out (kept with `BASE_FILE`, as said to its agents).
    git: bool = False
    left: tuple[str, ...] = field(default=(), repr=False, compare=False)
    # K-buyuk-proje: made for an agent in one part ("core/"): it holds that folder and the root's
    # own files (`holds`); `left` then names the other top folders too. None: the whole project.
    part: str | None = None
    results: dict[str, dict] = field(default_factory=dict, repr=False, compare=False)
    joined: dict[str, str] = field(default_factory=dict, repr=False, compare=False)
    # The secrets given on a card in its turn, as looked for (slice 91): a file holding one
    # is not taken. shortcut: none once the turn is over - a kept copy taken in later is not
    # looked at for one; keep a digest of each line if that is ever needed.
    secrets: Callable[[], Sequence[str]] = field(default=tuple, repr=False, compare=False)
    # The paths that held one when the copy was kept (`save`): refused after its turn too, after
    # a restart - their names alone are written down, never what they held.
    secret_held: tuple[str, ...] = field(default=(), repr=False, compare=False)
    # B-189: of each new file `changes` met, by `_key`, whether git ignores it in the project:
    # asked once a file (`git.ignored`), so a look again runs no git for it.
    ignores: dict[str, bool] = field(default_factory=dict, repr=False, compare=False)
    # Of this process alone, by path: what the project's file held just before and just after
    # it was taken (None: no file) - the agent's change, for its commit (`git.commit`).
    was: dict[str, tuple[bytes | None, bytes | None]] = field(
        default_factory=dict, repr=False, compare=False)
    # When it was made, in this process (None: loaded from disk): a change record of its line
    # from before then is another copy's (B-322: a stopped agent's kept one).
    # shortcut: a wall-clock time - the records' rowid is no sure order (a deleted
    # conversation's rows free theirs), and a clock set back while the copy is at work hides
    # its records from it; keep a counter of our own if that is ever seen.
    made_at: datetime | None = field(default=None, repr=False, compare=False)
    # K-dal-takim: the git branch whose worktree the tree is (`make_branch`); None: a copy. Of
    # this process alone: a kept one is loaded as a copy, and taken in file by file.
    branch: str | None = None
    # ... and the project's branch it was made from, with that one's commit then: what its merge
    # is held to (`git.branch_look`'s drift).
    start: tuple[str, str] | None = None

    def holds(self, path: str) -> bool:
        """Whether a path from the project root is one this copy holds (`part`): all that Take
        in, `behind` and `refresh` compare. A file of another part is not in it, and is never a
        deletion; nor is a name at the root that is another part's folder in the project."""
        return _holds(self.part, path, self.project)

    def ignored(self, path: str) -> bool:
        """B-189: a new file the project's git ignores (a generated data/clean.csv): not
        offered, nor kept - as `changes` has found it."""
        return self.ignores.get(_key(path), False)

    def left_out(self, target: Path) -> bool:
        """K-kopya-git: whether a place in the project, as it really leads, is one this copy of
        what git tracks (`git`) left out: not in the copy, ignored by the project's git, and
        neither in git's own folder nor under a name a copy leaves out or links - what its
        agents may read there (`AgentRunner._reads_left_out`) - and a top folder the copy holds
        only part of (`left`: `data/*` with `!data/.gitkeep`), to list and search there.
        K-buyuk-proje: so is, in a copy of one part (`part`), a place it does not hold - another
        part, read in the project.
        For a thread: git may be asked."""
        if not (self.git or self.part):
            return False
        try:
            real = Path(os.path.realpath(target))
            rel = real.relative_to(self.project)
        except ValueError:
            return False  # (out of the project, through a link or `..`)
        names = {".git", *NOT_COPIED, *LINKED}
        if not rel.parts or any(part.rstrip(" .").casefold() in names for part in rel.parts):
            return False
        path = rel.as_posix()
        if os.path.lexists(self.root / rel):
            return real.is_dir() and _key(f"{path}/") in {_key(name) for name in self.left}
        if not self.holds(path):
            return True
        if not self.git:
            return False
        if _key(path) not in self.ignores:
            from app import git  # (here: git's executors import commands, which imports this)

            self.ignores[_key(path)] = bool(git.ignored(self.project, [path], above=True))
        return self.ignores[_key(path)]

    @property
    def name(self) -> str:
        """The copy's folder in the copies folder: what it is removed by."""
        return self.root.parent.name

    def save(self) -> None:
        """Write down what the copy was made from, beside its tree (`BASE_FILE`): at
        once whole or not at all. OSError if it could not be written. Nothing for a
        copy that is compared two ways: what it was made from is not known, and is
        not made up from what was taken of it."""
        if self.two_way:
            return
        target = self.root.parent / BASE_FILE
        held = {self.names[key]: found for key, found in self.base.items()}
        new = target.with_suffix(".new")
        # A file of that name - which a command beside the tree could have made a link to
        # somewhere else - is taken away, and a new one made: never written through.
        new.unlink(missing_ok=True)
        with new.open("x", encoding="utf-8") as file:
            file.write(json.dumps({"files": held, "joined": self.joined, "git": self.git,
                                   "left": list(self.left[:MAX_LEFT]),
                                   "secret_held": list(self.secret_held)}))
        os.replace(new, target)

    def workspace(self) -> Workspace:
        """File access confined to the copy - and, to read, what its links lead to."""
        return Workspace(self.root, self.links)

    @cached_property
    def _own(self) -> Workspace:
        """The copy itself: through none of its links, not the linked folders either."""
        return Workspace(self.root)

    @cached_property
    def _projects(self) -> Workspace:
        return Workspace(self.project)

    @cached_property
    def _kept(self) -> Workspace:
        """Where the bytes each file was copied from are kept (`BASE`)."""
        return Workspace(self.root.parent / BASE)

    def started_from(self, path: str, base: dict[str, str] | None = None) -> bytes | None:
        """What a file held when the copy was made from it; None where that is not kept
        - a file over `MAX_BASE_TEXT`, a copy from before this was kept, a file the
        project did not have - or is not what the copy's record says the file was
        (`base`: instead of the copy's own): what stands beside the tree, where a
        command could reach it, is believed no further than its digest."""
        was = (self.base if base is None else base).get(_key(path))
        place = None if self.two_way or was is None else _inside(self._kept, path)
        try:
            if place is None or _is_link(place) or not place.is_file():
                return None
            data = place.read_bytes()
        except OSError:
            return None
        return data if hashlib.sha256(data).hexdigest() == was else None

    def _based(self, path: str, data: bytes | None) -> None:
        """What the copy was made from, for one file, is `data` from here on (None: no
        such file). Its bytes are kept for a later merge where they are few enough - and
        where they cannot be written, the file is one that is not merged line by line."""
        key = _key(path)
        if data is None:
            self.base.pop(key, None)
        else:
            self.base[key], self.names[key] = hashlib.sha256(data).hexdigest(), path
        place = None if self.two_way else _inside(self._kept, path)
        with contextlib.suppress(OSError):
            if place is None:
                return
            if data is None or len(data) > MAX_BASE_TEXT:
                place.unlink(missing_ok=True)
            else:
                place.parent.mkdir(parents=True, exist_ok=True)
                write_bytes(place, data)

    def here(self, path: str) -> Path | None:
        """A file's place in the copy itself; None where a link leads out of it."""
        return _inside(self._own, path)

    def there(self, path: str) -> Path | None:
        """A file's place in the project itself; None where a link leads out of it."""
        return _inside(self._projects, path)

    def sides(self, path: str) -> tuple[str | None, str | None]:
        """What the project holds of a file and what the copy does, as digests: what a
        card showed of it is compared by these."""
        there, here = self.there(path), self.here(path)
        return (digest(there) if there else OUTSIDE, digest(here) if here else OUTSIDE)

    def state(
        self, path: str, base: dict[str, str] | None = None,
        sides: tuple[str | None, str | None] | None = None,
    ) -> tuple[str, str] | None:
        """How one file of the copy stands against the project right now: its kind
        ("new", "changed", "deleted") and whether it can be taken ("ready": the project
        still holds what the copy was made from, or holds the same already; "conflict":
        the project's file changed meanwhile, and differently; "refused": the path
        leads out of the project, or out of the copy, through a link - `OUTSIDE`;
        "left_out": not offered at all - `NOT_OFFERED`, where `two_way`, a new file git
        ignores, `IGNORED`, or one outside a part copy's part, `NOT_IN_PART`).
        None for a file the copy has not changed. `base`: instead of the copy's own.
        `sides`: what the two hold (as `sides` gives it), where the caller has read
        them already - what it shows of the file and how it stands are of one read."""
        was = (self.base if base is None else base).get(_key(path))
        there, here = sides or self.sides(path)
        if not self.holds(path):
            # K-buyuk-proje: not this part copy's - a file a command made there is shown and
            # kept for the user (`NOT_IN_PART`); one it does not hold is no deletion, nor is a
            # root file it left as it was that the project has made a folder since.
            return None if here in (None, OUTSIDE, there, was) else (
                "new" if there is None else "changed", "left_out")
        if self.two_way:
            # Nothing says what the copy was made from: a file it holds that is not the
            # project's is shown against that, never "ready"; one it does not hold may
            # as well never have been copied, and is no deletion.
            if here in (None, OUTSIDE, there):
                return None
            if there is None:
                return "new", "left_out" if self.ignored(path) else "conflict"
            if there == OUTSIDE:
                return "changed", "refused"
            # The project has the file, and another: the agent's change - or the user's
            # own work since, which taking the copy's file would undo. Offered only
            # where a change of the agent's is on record.
            return "changed", "conflict" if _key(path) in self.names else "left_out"
        if here == OUTSIDE:
            # Behind a link a command made: not the copy's file, and not a deletion.
            return ("changed", "refused") if was is not None else None
        if here == was:
            return None
        kind = "deleted" if here is None else "new" if was is None else "changed"
        if there == OUTSIDE:
            return kind, "refused"
        if kind == "new" and (there is None or not self.git) and self.ignored(path):
            return kind, "left_out"  # (B-189: `changes`; `git`: one the project has, a conflict)
        return kind, "ready" if there in (was, here) else "conflict"

    def changes(
        self, base: dict[str, str] | None = None, names: dict[str, str] | None = None
    ) -> list[tuple[str, str, str]]:
        """Every file the copy has changed, as (path, kind, state), in path order.
        `base` and `names`: the copy's own as they were when the caller looked - a scan
        made in a thread is not made against records that another agent's taking in
        changes meanwhile (`refresh`).
        B-189 (live): a new file the project's git ignores (`ignored`: a generated
        data/clean.csv two teams each made) is "left_out" - not offered, never a conflict,
        not kept with the copy. One the project has (`.env`, `.vscode/settings.json`) goes
        through Take in as any other, with its cards - a conflict where the copy did not hold
        it (`git`).
        shortcut: git is asked once a new file (`ignores`), on whatever thread looks - on
        the event loop too, for a file not seen before; a .gitignore changed meanwhile is
        not seen for it."""
        base = self.base if base is None else base
        names = self.names if names is None else names
        files, _links, _size = _scan(self.root)
        now = {_key(path): path for path in files}
        found = []
        for key in sorted(set(base) | set(now)):
            path = now.get(key) or names[key]
            state = self.state(path, base)
            if state is not None and not _apart(path, self._projects, (self.project, self.root)):
                found.append((path, *state))
        unknown = [path for path, kind, _state in found
                   if kind == "new" and _key(path) not in self.ignores]
        if unknown:
            from app import git  # (here: git's executors import commands, which imports this)

            hit = (git.ignored(self.project, unknown, above=True) if self.git
                   else git.ignored(self.project, unknown))
            self.ignores.update({_key(path): path in hit for path in unknown})
        # (`git`: one the project has, which a copy of what git tracks did not hold, is a
        # conflict - "ready" is one it has not: the agent never saw it, and it is not lost.)
        return [(path, kind, "left_out" if kind == "new" and (state == "ready" or not self.git)
                 and self.ignored(path) else state) for path, kind, state in found]

    def taken(self, path: str) -> None:
        """The project now holds the copy's file: that is what the copy was made from,
        and what it does to the file from here on is a change of its own."""
        here = self.here(path)
        self._based(path, _bytes(here) if here else None)

    def join(self, path: str, result: bytes | None, project: bytes | None) -> None:
        """Both sides changed a file, and `result` is the two together: the copy's file
        becomes that (None: no file), and what the copy was made from becomes `project`
        - the project's file as it is now. From here on the copy's change to the file is
        the change from the project's own to the two together: what a command run in
        the copy sees is what the project is about to hold. OSError if not written, and
        for a path that leads out of the copy (`OUTSIDE`)."""
        target = self.here(path)
        if target is None:
            raise OSError(OUTSIDE)
        if result is None:
            target.unlink(missing_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            write_bytes(target, result)
        self._based(path, project)
        self.results.pop(path, None)
        if result is not None:
            self.joined[path] = hashlib.sha256(result).hexdigest()

    def give_up(self, path: str) -> None:
        """The project's file is kept, not the copy's: the copy gets the project's - its
        bytes, or gone - and no longer changes the file. OSError if not, and for a path
        that leads out of the project or of the copy (`OUTSIDE`)."""
        source = self.there(path)
        if source is None:
            raise OSError(OUTSIDE)
        data = _bytes(source)
        self.join(path, data, data)
        self.joined.pop(path, None)

    def behind(
        self, base: dict[str, str] | None = None, names: dict[str, str] | None = None
    ) -> list[str]:
        """The files the project has changed, got or lost since the copy was made from
        them, in path order: where the copy left such a file alone, `refresh` gives it
        the project's. Every file of the project is read: for a thread, with `base` and
        `names` as `changes` takes them."""
        base = self.base if base is None else base
        names = self.names if names is None else names
        # As the copy was made: of what git would track - and, where git does not answer now,
        # of the copy's own files alone, not of all that it ignores.
        listed = _git_listed(self.project) if self.git else None
        files = [] if self.git and listed is None else _scan(
            self.project, avoid=self.root.parent.parent.resolve(),
            held=_held(self.project, self.part, listed))[0]
        now = {_key(path): path for path in files}
        return [
            path for key in sorted(set(base) | set(now))
            if digest(self.project / (path := now.get(key) or names[key])) != base.get(key)
        ]

    def snapshot(
        self, keep: Iterable[str] = ()
    ) -> tuple[dict[str, str | None], dict[str, bytes | None]]:
        """The copy as it is, for `put_back`: every file of it with its digest, by its
        path, and what the files named in `keep` hold (None: no such file). The whole
        copy is read: for a thread."""
        files, _links, _size = _scan(self.root)
        kept = {path: _bytes(place) for path in keep if (place := self.here(path))}
        return {path: digest(self.root / path) for path in files}, kept

    def moved_since(self, was: dict[str, str | None]) -> list[str]:
        """The files of the copy that are not as a `snapshot` has them (`was`) - made,
        changed or gone since - in path order. The whole copy is read: for a thread."""
        files, _links, _size = _scan(self.root)
        return [
            path for path in sorted(set(was) | set(files))
            if (digest(place) if (place := self.here(path)) else OUTSIDE) != was.get(path)
        ]

    def put_back(
        self, paths: Iterable[str], was: dict[str, str | None], kept: dict[str, bytes | None]
    ) -> list[str]:
        """Undo what a command did to these files of the copy since `snapshot`: a file
        it made is deleted, and one it changed or deleted is what it was - its bytes of
        then (`kept`, by path; None: no file) where they were kept, else the project's
        file, which the copy had left alone and now leaves alone again (`give_up`).
        Returns the paths that could not be put back."""
        failed = []
        for path in paths:
            target = self.here(path)
            try:
                data = kept.get(path)
                if target is None:
                    raise OSError(OUTSIDE)
                if data is not None:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    write_bytes(target, data)
                elif path in kept or path not in was:
                    target.unlink(missing_ok=True)
                else:
                    self.give_up(path)
            except OSError:
                failed.append(path)
        return failed

    def put(self, path: str) -> None:
        """Make the project's file what the copy's is - its bytes, or gone. For what is
        not kept as a change record (not text, or too large for one); OSError if not,
        and for a path that leads out of the project or of the copy (`OUTSIDE`)."""
        source, target = self.here(path), self.there(path)
        if source is None or target is None:
            raise OSError(OUTSIDE)
        if source.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            write_bytes(target, source.read_bytes())
            keep_mode(source, target)
        else:
            target.unlink(missing_ok=True)

    def refresh(self, path: str) -> bool:
        """The project's file has just changed (another agent's changes were taken in):
        where this copy has not changed the file, it gets the new one and that is what
        the copy was made from. False where the copy has its own change: left as it is,
        and found to be a conflict when this copy is taken in."""
        # (Not a branch's worktree: the user's uncommitted work would go onto the branch.)
        if self.branch or not self.holds(path) or _apart(path, None, (self.project, self.root)):
            return False
        key, target, source = _key(path), self.here(path), self.there(path)
        # Not through a link a command made in this copy, nor one the project has.
        if target is None or source is None or digest(target) != self.base.get(key):
            return False
        try:
            if source.is_file():
                data = source.read_bytes()
                target.parent.mkdir(parents=True, exist_ok=True)
                write_bytes(target, data)
                keep_mode(source, target)
                self._based(path, data)
            else:
                target.unlink(missing_ok=True)
                self._based(path, None)
        except OSError:
            return False
        return True


def free(runtime_root: Path, name: str) -> str:
    """A name no copy has: `name` itself, or with a number after it where a folder of
    that name is still there (a copy whose command could not be killed, or one kept)."""
    held, found, count = folders(runtime_root), name, 1
    while any(os.path.lexists(one / found) for one in held):
        count += 1
        found = f"{name}-{count}"
    return found


def make(
    project: Path, runtime_root: Path, name: str, linked: bool = True, part: str | None = None
) -> Copy:
    """Copy a project into `<copies folder>/<name>` (`folder`). TooBig, with nothing
    made, for a copy over `MAX_FILES` or `MAX_BYTES`; OSError, with nothing left
    behind, when the copying fails - and where there is no place for a copy
    (`NO_PLACE`). Not `linked`: the dependency folders are not there at all.
    A project too big to copy whole, in a git repository, is copied as git would track it
    (`git.listed`; `Copy.git`): what git ignores (data, models, outputs) is neither copied nor
    linked - a command at work in the copy would write through a link into the project
    unasked. The dependency folders (`LINKED`) are linked all the same. The agent is told, and
    reads what was left out in the project (`AgentRunner._reads_left_out`). Where git does not
    answer, no copy, as before. `part` (K-buyuk-proje, "core/"): only that folder and the root's
    own files are copied - to the caps, and by git's list, as a whole project is (`Copy.part`)."""
    held = folder(runtime_root)
    if held is None:
        raise OSError(NO_PLACE)
    project, root = Path(project).resolve(), held / _plain(name) / TREE
    listed, left = None, []
    # A project that holds the copies folder does not copy the copies into themselves.
    try:
        files, links, _size = _scan(project, avoid=held.resolve(), held=_held(project, part, None),
                                    left=left, stop=True)
    except TooBig:
        listed, left = _git_listed(project), []
        if listed is None:
            raise
        files, links, _size = _scan(project, avoid=held.resolve(), held=_held(
            project, part, listed), left=left, stop=True)
    copy = Copy(project, root, {}, {}, {}, git=listed is not None, left=tuple(sorted(left)),
                part=part)
    root.mkdir(parents=True)
    try:
        for path in files:
            data = (project / path).read_bytes()
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            keep_mode(project / path, target)
            copy.base[_key(path)], copy.names[_key(path)] = hashlib.sha256(data).hexdigest(), path
            if len(data) <= MAX_BASE_TEXT:
                # Once more, beside the tree: what a merge of this file starts from.
                was = root.parent / BASE / path
                was.parent.mkdir(parents=True, exist_ok=True)
                was.write_bytes(data)
        for path in links if linked else ():
            _link(root / path, project / path)
            copy.links[path] = (project / path).resolve()
        copy.save()
    except Exception:
        # Whatever went wrong: what was made of it so far is not left behind.
        with contextlib.suppress(OSError, ValueError):
            remove(runtime_root, name)
        raise
    return copy


def seed(copy: Copy, source: Copy) -> list[str]:
    """K-evrim: a candidate's copy starts from its recipe's (`source`): each file `source`
    changed is written into `copy` as `source` holds it, or deleted there. Returns the paths
    that could not be. Reads both trees: for a thread."""
    return _carry(source, copy, [path for path, _kind, _state in source.changes()])


def bring(source: Copy, into: Copy, paths: Iterable[str], was: dict[str, str | None]) -> list[str]:
    """K-evrim: what the picked candidate changed (`paths`, in its copy `source`) into the
    recipe's copy (`into`) - but a file the recipe's copy itself changed since the candidate was
    seeded from it (`was`: its digests then, `Copy.snapshot`): that is never written over.
    Returns the paths not brought."""
    return _carry(source, into, paths, was)


def _carry(source: Copy, copy: Copy, paths: Iterable[str],
           was: dict[str, str | None] | None = None) -> list[str]:
    """Each of `paths` written into `copy` as `source` holds it, or deleted there - never
    through a link of either (`Copy.here`), nor over a file `copy` holds otherwise than `was`
    says. Returns the paths that could not be."""
    failed = []
    for path in paths:
        here, there = source.here(path), copy.here(path)
        try:
            if here is None or there is None:
                raise OSError(OUTSIDE)
            if was is not None and digest(there) != was.get(path):
                raise OSError("changed there since")
            if here.is_file():
                data = here.read_bytes()
                there.parent.mkdir(parents=True, exist_ok=True)
                write_bytes(there, data)
                keep_mode(here, there)
            else:
                there.unlink(missing_ok=True)
        except OSError:
            failed.append(path)
    return failed


def make_branch(
    project: Path, runtime_root: Path, name: str, short: str, linked: bool = True,
    start: Sequence[str] | None = None, tip: str | None = None,
) -> Copy:
    """K-dal-takim: a copy whose tree is a git worktree on a new branch `koloni/<short>`, made
    from where the project's branch is (`git.add_worktree`), in `<copies folder>/<name>` as a
    copy is. It holds what git tracks (`Copy.git`): what the project's git ignores is read in
    the project. The dependency folders are linked in as a copy's. `git.Refused` where git will
    not (no repository, HEAD on no branch); TooBig over a copy's caps - nothing left behind.
    shortcut: the worktree is checked out whole before the caps are counted; count `git
    ls-files` first if a project that big is ever put on a branch.
    `short` a branch of KOLONİ's own (`koloni/x`): that branch as it is, opened again for an agent
    that goes on (`git.reopen_worktree`, held to the `start` and `tip` on its record) - and never
    deleted here, which would take its work."""
    from app import git  # (here: git's executors import commands, which imports this)

    held = folder(runtime_root)
    if held is None:
        raise OSError(NO_PLACE)
    project, root = Path(project).resolve(), held / _plain(name) / TREE
    root.parent.mkdir(parents=True)
    branch, again = None, short.startswith(git.BRANCH_PREFIX)
    try:
        branch, into, sha = git.reopen_worktree(
            project, root, short, root.parent / "no-hooks", start, tip) if again else (
            git.add_worktree(project, root, short, root.parent / "no-hooks"))
        files, _links, _size = _scan(root, stop=True)
        listed = _git_listed(project)
        links = _scan(project, avoid=held.resolve(), held=listed)[1] if listed is not None else []
        copy = Copy(project, root, {}, {}, {}, git=True, branch=branch,
                    start=(into, sha))
        for path in files:
            copy.base[_key(path)] = hashlib.sha256((root / path).read_bytes()).hexdigest()
            copy.names[_key(path)] = path
        for path in links if linked else ():
            if not os.path.lexists(root / path):  # (a folder of that name the branch tracks)
                _link(root / path, project / path)
                copy.links[path] = (project / path).resolve()
        copy.save()
    except Exception:
        # Whatever went wrong: neither the folder nor the branch is left behind - but a branch
        # opened again keeps its earlier work (git's record of the worktree goes).
        with contextlib.suppress(OSError, ValueError):
            remove(runtime_root, name)
        if branch is not None:
            with contextlib.suppress(git.Refused):
                git.drop_branch(project, root, branch, Path(runtime_root) / "no-hooks",
                                force=True, keep=again)
        raise
    return copy


def load(project: Path, runtime_root: Path, name: str, part: str | None = None) -> Copy:
    """A copy a process that is gone left on disk, as it was made - without its links,
    which a kept copy has lost. `project`: where its files go, as the caller's own
    records have it; nothing in the copy's folder says where anything is written.
    OSError or ValueError where what it was made from cannot be read (`BASE_FILE`):
    nothing is made up for it, and nothing of such a copy can be compared.

    That file is in the copy's folder, where a command of its agent's could rewrite it:
    it is read as what somebody else wrote. Nothing is read through a link, a path that
    is not a plain one inside the project is not taken from it, nor one under a name a
    copy leaves out or links - a kept copy reaches what a copy at work could. Which
    files it says hold both sides together (`Copy.joined`) changes only how such a file
    is put on record when it is taken, and only while the file has that digest.
    `part`: the part the copy was made for, as the caller's records have it (K-buyuk-proje): the
    file says nothing of it - what an agent can rewrite would hide its own work, or another
    part's files would be "deleted"."""
    held = place(runtime_root, name)
    said = f"{held / BASE_FILE} does not say what the copy was made from"
    if _is_link(held / TREE) or _is_link(held / BASE_FILE) or not (held / TREE).is_dir():
        raise ValueError(said)
    if (held / BASE_FILE).stat().st_size > MAX_BASE_BYTES:
        raise ValueError(said)
    try:
        found = json.loads((held / BASE_FILE).read_text(encoding="utf-8"))
    except RecursionError:
        raise ValueError(said) from None
    files = found.get("files") if isinstance(found, dict) else None
    if not isinstance(files, dict) or not all(
        isinstance(path, str) and isinstance(was, str) for path, was in files.items()
    ):
        raise ValueError(said)
    files = {
        path: was for path, was in files.items()
        if _holds(part, path, Path(project)) and "\\" not in path and ":" not in path
        and not any(part in ("", ".", "..") for part in path.split("/"))
        and not _apart(path, None, (Path(project), held / TREE))
    }
    joined = found.get("joined")  # not there in a copy from before it was written down
    left = found.get("left")  # (said to agents: plain short names only)
    secret = found.get("secret_held")
    return Copy(
        Path(project).resolve(), held / TREE,
        {_key(path): was for path, was in files.items()},
        {_key(path): path for path in files}, {}, git=found.get("git") is True, part=part,
        left=tuple(name for name in (left if isinstance(left, list) else [])[:MAX_LEFT]
                   if isinstance(name, str) and 0 < len(name) <= 255 and name.isprintable()),
        joined={
            path: was for path, was in (joined.items() if isinstance(joined, dict) else ())
            if path in files and isinstance(was, str)
        },
        secret_held=tuple(path for path in (secret if isinstance(secret, list) else [])
                          if isinstance(path, str)),
    )


def kept(
    project: Path, runtime_root: Path, name: str, tree: Path | None = None,
    recorded: Iterable[str] = (), part: str | None = None,
) -> Copy:
    """A copy left on disk as it can be compared: by what it was made from (`load`) or,
    where that cannot be read - or the copy is from before it was written down - with
    the project alone (`Copy.two_way`). `tree`: where its files are as the caller's
    records have it - the tree in its folder, or (a copy from before there were trees)
    the folder itself; what the folder happens to hold does not say which. `recorded`:
    the paths its agents are on record as having changed in it. `part`: the part it was made
    for, as the records have it (`load`). OSError or ValueError
    for one that is not read at all: no record says where its files are, or its
    folder, or its tree, is a link."""
    try:
        return load(project, runtime_root, name, part)
    except (OSError, ValueError):
        held = place(runtime_root, name)
        if tree is None or tree not in (held, held / TREE) or not tree.is_dir() or any(
            _is_link(one) for one in (held.parent, held, held / TREE)
        ):
            raise
        # The note of what a copy was made from is KOLONİ's own, not a file of the
        # copy's: a folder that holds one is no copy from before there were trees.
        notes = (BASE_FILE, Path(BASE_FILE).with_suffix(".new").name)
        if tree == held and any(os.path.lexists(held / note) for note in notes):
            raise
        on_record = {_key(path): path for path in recorded}
        return Copy(Path(project).resolve(), tree, {}, on_record, {}, two_way=True, part=part)


def forget(runtime_root: Path, name: str) -> None:
    """A copy is thrown away: what it was made from goes first, so that a folder that
    cannot be deleted right now is never taken for work that was kept."""
    with contextlib.suppress(OSError, ValueError):
        os.unlink(place(runtime_root, name) / BASE_FILE)


# --- deleting -------------------------------------------------------------------------


def _plain(name: str) -> str:
    """A copy's name as it is, where it is one: ValueError for a name that would lead
    anywhere but to a folder directly inside a copies folder."""
    if not name or name in (".", "..") or Path(name).name != name or ":" in name:
        raise ValueError(f"{name!r} is not the name of a working copy")
    return name


def place(runtime_root: Path, name: str) -> Path:
    """Where the copy of that name is: a folder directly inside one of the copies
    folders (`folders`: the one that has it, else where copies are made), and nothing
    else - ValueError for a name that would lead anywhere else."""
    held = folders(runtime_root)
    return next((one for one in held if os.path.lexists(one / _plain(name))), held[0]) / name


def named(runtime_root: Path, kept_in: str) -> str:
    """The name of the copy a folder on record is, or is the tree of. ValueError for a
    folder that is not in one of the copies folders: nothing is done with it."""
    for held in folders(runtime_root):
        with contextlib.suppress(ValueError, IndexError):
            return _plain(Path(kept_in).relative_to(held).parts[0])
    raise ValueError(f"{kept_in} is not a working copy's folder")


def _unlink(link: Path) -> None:
    """Remove a link itself. What it leads to is not touched: a junction, and on Windows
    a link to a folder, is removed as the empty folder it is."""
    if os.name == "nt" and (link.is_junction() or os.path.isdir(link)):
        os.rmdir(link)
    else:
        os.unlink(link)


def _unlink_file(path: Path) -> None:
    try:
        os.unlink(path)
    except PermissionError:
        os.chmod(path, stat.S_IWRITE)  # a file written read-only
        os.unlink(path)


def _entries(top: Path) -> list[os.DirEntry]:
    with os.scandir(top) as found:
        return list(found)


def _delete(top: Path) -> None:
    """Delete a folder and what is in it, following no link: one found is removed as a
    link (also one made since the links were removed). Each entry is looked at when it
    is reached, and so is the folder itself: a command still alive may have put a link
    where a folder was a moment ago."""
    if _is_link(top):
        _unlink(top)
        return
    for entry in _entries(top):
        path = Path(entry.path)
        if _is_link(path):
            _unlink(path)
        elif entry.is_dir(follow_symlinks=False):
            _delete(path)
        else:
            _unlink_file(path)
    os.rmdir(top)


def remove(runtime_root: Path, name: str) -> None:
    """Delete one working copy. Only ever a folder directly inside a copies folder
    (`place`); its links are removed first, each as a link, so that whatever happens
    afterwards nothing in the copy leads into the project any more; then its own
    files. OSError when something could not be deleted: what is left is deleted at the
    next start (`clear`)."""
    _remove(place(runtime_root, name))


def _remove(copy: Path) -> None:
    held = copy.parent
    if _is_link(held):
        raise ValueError(f"{held} is a link: nothing is deleted through it")
    if _is_link(copy):
        _unlink(copy)
        return
    if not copy.is_dir():
        return
    _unlink_links(copy)
    _delete(copy)


def unlink(runtime_root: Path, name: str) -> None:
    """Remove the links of a copy that is kept: its folder stays, and leads nowhere."""
    copy = place(runtime_root, name)
    if not _is_link(copy.parent) and not _is_link(copy) and copy.is_dir():
        _unlink_links(copy)


def relink(copy: Copy) -> None:
    """B-322: a kept copy given back to its agent gets the links `unlink` took away. A
    place something else holds now is left as it is."""
    for path, target in copy.links.items():
        if not os.path.lexists(copy.root / path):
            _link(copy.root / path, target)


def _unlink_links(copy: Path) -> None:
    """Remove every link in a copy, each as a link: nothing in it leads anywhere else
    afterwards, whatever is then done with the folder."""
    todo = [copy]
    while todo:
        for entry in _entries(todo.pop()):
            path = Path(entry.path)
            if _is_link(path):
                _unlink(path)
            elif entry.is_dir(follow_symlinks=False):
                todo.append(path)


def clear(runtime_root: Path, keep: Callable[[str], bool] = lambda name: False) -> None:
    """Delete every copy there is: at the start nothing is running, so each is left over
    from a process that is gone. One that cannot be deleted does not keep the rest.
    `keep`: asked for each copy by its name; one it says yes to holds work that never
    reached the project and stays - without its links, so that deleting the folder by
    hand cannot reach the project through one."""
    for held in folders(runtime_root):
        if _is_link(held) or not held.is_dir():
            continue
        for entry in _entries(held):
            with contextlib.suppress(OSError, ValueError):
                if _is_link(Path(entry.path)) or not keep(entry.name):
                    _remove(Path(entry.path))
                else:
                    _unlink_links(Path(entry.path))
