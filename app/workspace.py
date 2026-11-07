"""File access confined to one project folder, and to the folders outside it the user opens."""

import codecs
import contextlib
import difflib
import fnmatch
import functools
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import threading
import time
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath

MAX_READ_BYTES = 256 * 1024
MAX_READ_LINES = 2000
READ_CHUNK = 64 * 1024
MAX_WRITE_BYTES = 1024 * 1024
MAX_MATCHES = 200
SEARCH_SECONDS = 20.0  # what Settings.search_seconds is unless KOLONI_SEARCH_SECONDS says
TOO_LONG = (
    "the search took too long - more than {:g} s; search a smaller path or a simpler pattern"
)
STOPPED = "the search was stopped"
SKIP_DIRS = frozenset({".git", "node_modules", ".venv", "__pycache__"})


# What a turn nobody is watching never writes, though its trigger lets it change files:
# a file that tells a later turn what it may do, or that runs by itself, is not an
# ordinary file - and nobody is there to look at it. A path with one of these names in
# it, at any depth and in any case; each with why it is here. A turn somebody watches
# writes one only on the user's word, at every level.
# A command that names one is asked the same way (`commands.names_standing`, B-79).
# shortcut: a command by the names written in it - a wildcard, a variable or a script that
# writes one is not seen; what it writes is put back after it (K-yazma-denetimi,
# `project_view.standing`).
NOT_WRITTEN_UNATTENDED = {
    ".claude": "Claude Code's settings, hooks, agents and commands: what it may do unasked",
    ".codex": "Codex's settings: what it may run without asking",
    ".qoder": "Qoder's settings and rules: what it may do without asking",
    ".agy": "agy's settings and permission rules: what it may do without asking",
    ".agents": "agy's hooks, skills and plugins for the project: commands it runs by itself",
    ".agent": "agy's hooks, skills and plugins for the project (another name it reads)",
    "_agents": "agy's hooks, skills and plugins for the project (another name it reads)",
    "_agent": "agy's hooks, skills and plugins for the project (another name it reads)",
    ".git": "git's hooks and config: programs that run by themselves at the next git command",
    ".github": "workflows and actions: they run by themselves once pushed",
    ".vscode": "the editor's tasks and settings: they can run when the folder is opened",
    ".husky": "git hooks kept in the project: they run by themselves at the next commit",
    **dict.fromkeys(
        (".pre-commit-config.yaml", "lefthook.yml", "lefthook.yaml", ".lefthook.yml",
         ".lefthook.yaml", "lefthook-local.yml", ".lintstagedrc",
         *(f".lintstagedrc.{ext}" for ext in ("json", "yaml", "yml", "js", "cjs", "mjs")),
         *(f"lint-staged.config.{ext}" for ext in ("js", "cjs", "mjs", "ts", "mts", "cts")),
         *(f"{dot}simple-git-hooks.{ext}" for dot in ("", ".")
           for ext in ("json", "js", "cjs", "mjs"))),
        "the commands a commit hook runs: they run by themselves at the next commit"),
    ".mcp.json": "the tool servers a CLI starts in this project, and then trusts",
    ".claude.json": "Claude Code's own state: the tools and servers it holds to be allowed",
    "agents.md": "instructions every later agent reads as the user's own",
    "claude.md": "instructions every later Claude Code agent reads as the user's own",
    "gemini.md": "instructions every later Gemini or agy agent reads as the user's own",
    ".gemini": "Gemini's and agy's settings, hooks and MCP servers: what they may do unasked",
    ".copilot": "GitHub Copilot's settings and MCP servers: what it may do without asking",
    ".koloni": "KOLONİ's rules and settings for the folder: what later agents are told, and "
               "where their commands run",
}
# A Python environment's `.pth` files run at every start of its Python (user, 29 Oct). Bounded:
# one environment folder deep in the project, never a walk of it. (Not node_modules/.bin: every
# npm install rewrites it, and it runs only when the user runs an npm script.) A write of one is
# asked as one of `NOT_WRITTEN_UNATTENDED` is, by the name "*.pth" (`stands_over_later_turns`).
PTH_GLOBS = ("*/Lib/site-packages/*.pth", "*/lib/python*/site-packages/*.pth")
# K-fullauto-sorma: of those, the instruction files alone - read by later agents as the user's
# words, running nothing by themselves - are not asked about at Full auto in a turn the user
# watches (a command naming one, KOLONİ's own write); every other name asks there too.
INSTRUCTION_FILES = frozenset({"agents.md", "claude.md", "gemini.md"})


class WorkspaceError(Exception):
    """A file operation was refused; the message is written for the model and the user."""


class Outside(WorkspaceError):
    """A path outside the project and the folders it also works in: one the user may
    open, once or for its whole `folder`."""

    def __init__(self, rel: str, folder: Path):
        super().__init__(f"{rel!r} is outside the project folder")
        self.folder = folder


class CliHome(WorkspaceError):
    """A file in a CLI's own folder in the home folder (`CLI_HOMES`): opened by KOLONİ's file
    tools on the user's word, one call at a time, at every level - never where nobody watches.
    `real` is where it really leads, `card` why it is asked (`CLI_HOME_CARD`)."""

    def __init__(self, rel: str, real: Path, cli: str):
        super().__init__(
            f"{rel!r} is in {CLI_HOMES[cli]}'s own folder: read_file, write_file and edit_file "
            "open one file there, on the user's word each time")
        self.real = real
        self.card = CLI_HOME_CARD.format(cli=CLI_HOMES[cli])


# The CLIs' own folders in the home folder (K-ev-klasoru): still never a project, a listed
# folder or a CLI's own --add-dir (`_places`), but a file in one is opened on a card (`CliHome`).
# shortcut: by these names under the home folder only - CODEX_HOME, CLAUDE_CONFIG_DIR or
# COPILOT_HOME pointing elsewhere is not followed; add them the day a user sets one.
CLI_HOMES = {".claude": "Claude Code", ".codex": "Codex", ".copilot": "GitHub Copilot",
             ".gemini": "Gemini and agy"}
CLI_HOME_CARD = (
    "This folder is {cli}'s settings for this whole computer: changing it affects every "
    "project. It may hold API keys: those KOLONİ knows by their shape are hidden from the "
    "model, the rest of what is read here goes to the model's provider."
)
# Why such a folder is in `_places`: what the list of places never opened says of it too.
CLI_PLACE = "it is {cli}'s settings for this whole computer: a file there is opened on a card"
CLI_PLACES = {CLI_PLACE.format(cli=cli): name for name, cli in CLI_HOMES.items()}
# Never opened in them, not even on a card: logins and past conversations - by any part of the
# path below the folder, as `_name` gives it. Names only, no real home folder was looked into:
# those with a note are in tasarim/specs/2026-10-23-cli-denetim-protokolleri-design.md.
# shortcut: the other names are from memory of each CLI's layout, not checked against its
# docs here; check them (and new ones a CLI adds) against each CLI's documentation.
CLI_NEVER = {
    ".claude": {".credentials.json", "projects",  # (projects: the note's transcript_path)
                "history.jsonl", "todos", "shell-snapshots", "file-history", "session-env",
                "paste-cache", "debug",
                "backups", "ide"},  # (copies of ~/.claude.json; an IDE's lock holds its token)
    ".codex": {"auth.json", "sessions", "archived_sessions", "history.jsonl", "log"},
    # config.json: Copilot keeps its logged-in users there, and the token where no keychain is
    ".copilot": {"config.json", "session-state",  # (session-state: the note's workspacePath)
                 "history-session-state", "command-history-state.json", "logs"},
    ".gemini": {"oauth_creds.json", "google_accounts.json", "tmp", "history",
                "brain", "cli.log", "conversations"},  # (brain, cli.log: the note, agy's)
}
# Any other login, token or account file, or a session's or history's record, by its name.
CLI_LOGIN = re.compile(r".*(auth|cred|token|account|login|cookie|session|histor).*")
CLI_NEVER_WHY = "it is a CLI's login or a record of its past conversations"


def _cli_home(path: Path) -> tuple[str, tuple[str, ...]] | None:
    """The CLI folder (`CLI_HOMES`) that holds this absolute path and the path's parts below
    it - where no other place KOLONİ never opens holds it too (a `.codex` that leads into
    `.ssh`) - or None."""
    cased, found = _cased(path), None
    for place, why in _never_places():
        if cased.is_relative_to(_cased(place)):
            if why not in CLI_PLACES:
                return None
            found = found or (CLI_PLACES[why], cased.relative_to(_cased(place)).parts)
    return found


def _cli_never(cli: str, parts: tuple[str, ...]) -> bool:
    return any(_name(part) in CLI_NEVER[cli] or CLI_LOGIN.fullmatch(_name(part)) for part in parts)


NETWORK = ("\\\\", "//")
# Where WSL mounts Windows' drives (/mnt/c): under WSL each is a drive's root, in any case.
# shortcut: Windows' own programs run from WSL (`cmd.exe /c type C:\Users\...`) are not
# seen by this guard - they open Windows' paths themselves; hold interop if an agent uses it.
WSL_DRIVES = Path("/mnt")


@functools.cache
def _interop() -> bool:
    return os.path.exists("/proc/sys/fs/binfmt_misc/WSLInterop")


def _wsl() -> bool:
    """Whether KOLONİ runs in WSL - its shell sets WSL_DISTRO_NAME; one started by systemd
    has none, but the kernel still runs Windows' programs (`_interop`)."""
    return bool(os.environ.get("WSL_DISTRO_NAME")) or sys.platform == "linux" and _interop()


def _on_drive(path: PurePath) -> bool:
    """Whether a path is on one of WSL's mounts of Windows' drives (/mnt/c/...)."""
    parts = PurePosixPath(path.as_posix()).parts
    at = len(WSL_DRIVES.parts)
    return (len(parts) > at and PurePosixPath(*parts[:at]) == PurePosixPath(WSL_DRIVES.as_posix())
            and len(parts[at]) == 1 and parts[at].isalpha())


def _drive_root(path: Path) -> bool:
    return path == Path(path.anchor) or _wsl() and (
        path.parent == WSL_DRIVES and len(path.name) == 1 and path.name.isalpha())


def _home() -> Path:
    # The user's own, from the environment: not what a test (or a library) made of
    # Path.home() - a secret is where it really is.
    return Path(os.path.expanduser("~"))


def home_of(named: str) -> str:
    """A path with "~" for the home folder, as Claude Code reads one ("~", "~/", "~\\"), or
    with %USERPROFILE%, written out; any other as it is."""
    if named == "~" or named.startswith(("~/", "~\\")):
        return str(_home()) + named[1:]
    if named[:13].upper() == "%USERPROFILE%" and named[13:14] in ("", "/", "\\"):
        return str(_home()) + named[13:]
    return named


def _never_places() -> tuple[tuple[Path, str], ...]:
    names = ("APPDATA", "LOCALAPPDATA", "KOLONI_RUNTIME_ROOT", "SYSTEMROOT", "ProgramFiles",
             "ProgramFiles(x86)", "ProgramW6432")
    environ = ("wsl" if _wsl() else "", *(os.environ.get(name, "") for name in names))
    # And Path.home()'s, where something made it another: more places, never fewer.
    homes = dict.fromkeys((str(_home()), str(Path.home())))
    return tuple(dict.fromkeys(found for home in homes for found in _places(home, environ)))


# What a home folder holds that is never opened - the user's on Linux, macOS and Windows, and
# under WSL each Windows home on its drives too.
HOME_SECRETS = (
    ".ssh", ".agents", ".aws", ".config/gh", ".config/gcloud", ".config/github-copilot",
    ".config/rclone", ".qoder", ".kaggle", ".docker", ".azure",
    # (B-65: Databricks' token cache, Cline's and Continue's API keys, LM Studio's)
    ".databricks", ".cline", ".continue", ".lmstudio",
    # (B-94: Ollama's private key; other agents' and tools' homes, never looked into)
    ".ollama", ".qoder-cli", ".qodersec", ".lingma", ".cagent", ".claude-server-commander")
# KOLONİ's own places: the only ones a listed folder may hold (`_kept_out`).
OWN_RECORD = "it is KOLONİ's own record"
OWN_CODE = "it is KOLONİ's own code and settings"


@functools.cache
def _places(home_name: str, environ: tuple[str, ...]) -> tuple[tuple[Path, str], ...]:
    """Each place by its name and by where it really leads (a link leads elsewhere):
    worked out once for the environment it is asked in."""
    from app.config import REPO_ROOT, load_settings, mcp_base  # (it imports nothing of ours)

    home, (wsl, appdata, localdata, _runtime, system_root, *programs) = Path(home_name), environ
    secret = "it holds the user's settings and secrets"
    places = [(home / name, CLI_PLACE.format(cli=cli)) for name, cli in CLI_HOMES.items()]
    places += [(home / name, secret) for name in HOME_SECRETS]
    roaming = Path(appdata or home / "AppData/Roaming")
    places += [(roaming / "agent-grid", secret), (roaming / "GitHub CLI", secret)]
    # Browsers' profiles (passwords, cookies) and Windows' own keys and saved logins. Not all
    # of AppData\Local: its Temp and KOLONİ's own copies are there.
    local = Path(localdata or home / "AppData/Local")
    places += [(place, secret) for place in (
        local / "Google/Chrome/User Data", local / "Microsoft/Edge/User Data",
        local / "BraveSoftware", local / "Vivaldi/User Data", roaming / "Mozilla/Firefox",
        roaming / "Opera Software", local / "Microsoft/Credentials",
        roaming / "Microsoft/Credentials", roaming / "Microsoft/Protect")]
    # The same on macOS and Linux: browsers' profiles, keychains and keyrings.
    mac = home / "Library/Application Support"
    places += [(place, secret) for place in (
        mac / "Google/Chrome", mac / "Microsoft Edge", mac / "BraveSoftware", mac / "Firefox",
        home / ".mozilla/firefox", home / ".config/google-chrome", home / ".config/chromium",
        home / ".config/microsoft-edge", home / ".config/BraveSoftware",
        home / "Library/Keychains", home / ".gnupg", home / ".local/share/keyrings")]
    places += [(REPO_ROOT / "runtime", OWN_RECORD), (load_settings().runtime_root, OWN_RECORD)]
    places.append((mcp_base().parent, OWN_RECORD))  # where MCP servers start (97)
    # KOLONİ's own checkout: its code, the instructions its agents read, its settings and
    # keys (.env). A folder listed for agents may hold it (slice 75), never open it.
    places.append((REPO_ROOT, OWN_CODE))
    system = "it is the system's own"
    if sys.platform == "win32":
        places.append((Path(system_root or "C:/Windows"), system))
        places += [(Path(name or "C:/Program Files"), system) for name in programs]
    else:  # macOS's and Linux's; a link (/etc on macOS, /bin on Linux) by where it leads too
        # /usr's own folders, not /usr: /usr/local is where the user's own may lie.
        # (/proc, /sys, /dev, /run: the running system's - /proc/self/environ holds KOLONİ's
        # own keys, /run the user's sockets; /var holds /var/run, so it is not listed either)
        places += [(Path(name), system) for name in (
            "/etc", "/System", "/usr/bin", "/usr/sbin", "/usr/lib", "/usr/lib64", "/usr/share",
            "/usr/libexec", "/bin", "/sbin", "/Library", "/proc", "/sys", "/dev", "/run",
            "/var/run", "/boot")]
        if not home.is_relative_to("/root"):  # (KOLONİ run as root works in its home)
            places.append((Path("/root"), system))
    if wsl:  # WSL: Windows' own homes, under its drives, as the home's places on Windows
        for windows in sorted(WSL_DRIVES.glob("?/Users/*")):
            places += [(windows / name, CLI_PLACE.format(cli=cli))
                       for name, cli in CLI_HOMES.items()]
            places += [(windows / name, secret) for name in (*HOME_SECRETS, "AppData")]
    both = ((found, why) for place, why in places for found in (place, place.resolve()))
    return tuple(dict.fromkeys(both))


def _cased(path: PurePath) -> PurePath:
    """A path as places are compared: on macOS in any case, as its disk (APFS) has none - and
    so under WSL one on Windows' drives (/mnt/c/users is /mnt/c/Users); a Windows path
    compares so by itself.
    shortcut: a Linux folder made case-blind (ext4 `chattr +F`) is compared case by case; add
    it here if KOLONİ is ever run in one."""
    if sys.platform == "darwin" or _wsl() and _on_drive(path):
        return PurePosixPath(path.as_posix().casefold())
    return path


def never(path: Path) -> str | None:
    """Why KOLONİ never opens this absolute path, or None: in such a place, or a folder
    that holds one (the home folder itself, say). (On Windows and macOS paths compare in
    any case.) `opened` judges where a path really leads, and its folder."""
    if str(path).startswith(NETWORK):
        return "it is a network path: KOLONİ works in this machine's own folders only"
    if _drive_root(path):  # (first: it holds the user's places too - B-73)
        return "it is a drive's root"
    cased = _cased(path)
    for place, why in _never_places():
        if cased.is_relative_to(_cased(place)):
            return why
        if _cased(place).is_relative_to(cased):
            return f"it holds {place}, which KOLONİ never opens"
    return None


NUL_IN_PATH = "a path can't hold a NUL character"
# Names Windows opens as a device, whatever comes after a dot.
DEVICES = re.compile(r"(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?", re.IGNORECASE)


def not_written_as_named(rel: str) -> str | None:
    """Why Windows would write a path somewhere else than a file of that name: a part of it
    is a device (`CON`, `com1.txt`) or names a file's stream (`a.txt:evil` - one can strip a
    download's mark); None for a plain one, and anywhere but on Windows."""
    if sys.platform != "win32":
        return None
    path = PureWindowsPath(rel)
    for part in path.parts[1 if path.anchor else 0:]:
        if ":" in part:
            return "it names a stream of a file (a colon after the drive)"
        if DEVICES.fullmatch(_name(part)):
            return "it names a device"
    return None


def opened(raw: str) -> Path:
    """Where an absolute path outside the project really leads - through `..`, any case,
    a short name or a link - or WorkspaceError with why KOLONİ never opens it. Its folder
    (the path itself, or the file's) is judged too. A secret is refused by its name
    first, before anything of it is looked at on disk; a network path likewise."""
    if "\x00" in raw:  # (3.13+ resolve() no longer raises on one)
        raise WorkspaceError(NUL_IN_PATH)
    try:
        why = never(Path(raw)) if raw.startswith(NETWORK) else never(Path(os.path.abspath(raw)))
        real = Path(raw).resolve() if why is None else None
        if real is not None:
            folder = real if real.is_dir() else real.parent
            why = never(real)
            if why is None and (held := never(folder)):  # B-194: "it holds" is the folder's
                why = f"its folder {folder}{held.removeprefix('it')}"
    except (ValueError, OSError) as exc:  # a NUL in it, or too long a path
        raise WorkspaceError(f"{raw[:200]!r} is not a path KOLONİ opens: {exc}") from None
    if why or real is None or not real.is_absolute():  # a root with no drive is no place
        raise WorkspaceError(f"{raw!r} is never opened: {why or 'not a full path'}")
    return real


def _kept_out(path: Path) -> str | None:
    """Why a folder is on no list of folders to work in, and a path in a listed one is not
    opened (`listed_folder`, `Workspace._in_listed`): a network path, a place KOLONİ never
    opens or a path in one, the home folder or a folder that holds it, a drive's root, a
    folder that holds the user's or the system's places. One that holds only KOLONİ's own
    places may be listed (slice 75: the Desktop holding KOLONİ): every path a tool names
    there is judged by itself, and a walk passes those places by (`_walk`)."""
    if str(path).startswith(NETWORK) or _drive_root(path):
        return never(path)
    cased = _cased(path)
    for place, why in _never_places():
        if cased.is_relative_to(_cased(place)):
            return why
    for place, why in _never_places():
        if _cased(place).is_relative_to(cased) and why not in (OWN_RECORD, OWN_CODE):
            return f"it holds {place}, which KOLONİ never opens"
    if any(_cased(home).is_relative_to(cased) for home in (_home(), Path.home())):
        return "it is, or holds, the home folder, which holds the user's settings and secrets"
    return None


def far_or_device(raw: str) -> bool:
    """Whether a path names a network share or a device (`\\\\?\\`, `\\\\.\\`) in any spelling
    of its slashes: such a one is never looked at on disk - a share would be dialled."""
    return raw.startswith(NETWORK) or str(PureWindowsPath(raw)).startswith("\\\\")


def not_a_project(path: Path) -> str | None:
    """Why a folder is not opened as a project, the one every agent of its chats works in
    (slice 86a): as `_kept_out` says - the home folder, a drive's root, KOLONİ's own code
    and record or a folder in them, a place never opened.
    shortcut: but the one folder KOLONİ's e2e works in (frontend/e2e/paths.mjs); take this
    out once the e2e keeps its project outside the checkout."""
    from app.config import REPO_ROOT  # (app.config imports nothing of ours)

    why = _kept_out(path)
    if why in (OWN_RECORD, OWN_CODE) and _cased(path) == _cased(
            REPO_ROOT / "runtime" / "e2e" / "project"):
        return None
    return why


def listed_folder(raw: str) -> Path:
    """A folder for a list of folders to work in besides a project, as it really is:
    absolute, local and existing, and not one `_kept_out` - or WorkspaceError, saying why
    not. A folder that holds a place KOLONİ never opens (the Desktop holding KOLONİ's own
    runtime) may be one."""
    try:
        if not Path(raw).is_absolute():
            raise WorkspaceError(f"{raw} is not an absolute path")
        why = _kept_out(Path(raw) if raw.startswith(NETWORK) else Path(os.path.abspath(raw)))
        real = None if why else Path(raw).resolve()
        why = why or (_kept_out(real) if real else None)
        # (The path as it is written, not as Python quotes it: B-73.)
        if why or real is None:
            raise WorkspaceError(f"{raw} is never opened: {why}")
        if not real.is_dir():
            raise WorkspaceError(f"{raw} is not an existing folder")
    except (ValueError, OSError) as exc:  # a NUL in it, or too long a path
        raise WorkspaceError(f"{raw[:200]} is not a folder KOLONİ opens: {exc}") from None
    return real


def outside_folder(raw: str) -> Path:
    """A folder to work in besides the project, as it really is: absolute, local and
    existing, and none KOLONİ never opens - or WorkspaceError, saying why not."""
    if not Path(raw).is_absolute():
        raise WorkspaceError(f"{raw!r} is not an absolute path")
    real = opened(raw)
    if not real.is_dir():
        raise WorkspaceError(f"{raw!r} is not an existing folder")
    return real


# An absolute path in the user's own words; in quotes or backticks it may hold spaces. On
# Windows one with a drive; elsewhere one from the root - not a URL's (https://x/y), nor a
# part of a relative one (a/b, ./x, ../x, ~/x).
NAMED = re.compile(
    r"""["'`]([A-Za-z]:[\\/][^"'`\n]*)["'`]|(?<![\w/\\])([A-Za-z]:[\\/][^\s"'`<>|*?]*)"""
    if os.name == "nt" else
    r"""["'`](/[^"'`\n]*)["'`]|(?<![\w/\\:.~])(/(?![/\s])[^\s"'`<>|*?]*)""")


def named_folders(text: str) -> list[Path]:
    """The folders a message names - a folder itself, or a file's - that may be listed
    (`listed_folder`)."""
    found: list[Path] = []
    for quoted, bare in NAMED.findall(text):
        named = quoted or bare.rstrip(".,;:!?)")
        try:
            try:
                folder = listed_folder(named)
            except WorkspaceError:
                folder = listed_folder(str(Path(named).parent))  # a file's
        except (WorkspaceError, OSError):
            continue
        if folder not in found:
            found.append(folder)
    return found


def for_change(root: str | Path, path: str) -> "Workspace":
    """Where a recorded change is: the project, or - for a file outside it, on record by
    its full path - that file's folder too."""
    return Workspace(root, also=[Path(path).parent] if Path(path).is_absolute() else [])


class Workspace:
    def __init__(self, root: str | Path, links: dict[str, Path] | None = None,
                 also: Iterable[str | Path] = (), granted: Path | None = None):
        self.root = Path(root).resolve()
        # For a working copy (`app.copies`): the folders in it that are links to the
        # project's own - where each stands, and where it leads. What they lead to may
        # be read through them; every other way out of the folder stays closed.
        self.links = links or {}
        # The folders outside the project it also works in (slice 41).
        self.also = [Path(folder) for folder in also]
        # The one file in a CLI's own folder the user said yes to, for one call (`CliHome`).
        self.granted = granted

    def resolve(self, rel: str) -> Path:  # noqa: C901
        """Turn a path into an absolute one: one relative to the project, or an absolute
        one in the project or in a folder it also works in. Any other is `Outside`, and
        one KOLONİ never opens (`never`) a plain WorkspaceError."""
        if not isinstance(rel, str) or not rel.strip():
            raise WorkspaceError("empty path")
        if "\x00" in rel:  # (3.13+ resolve() no longer raises on one)
            raise WorkspaceError(NUL_IN_PATH)
        windows = PureWindowsPath(rel)
        absolute = windows.is_absolute() if sys.platform == "win32" else rel.startswith("/")
        if not absolute and (windows.drive or windows.root or PurePosixPath(rel).is_absolute()):
            raise WorkspaceError(
                f"{rel!r} is outside the project folder; use a path relative to it"
            )
        lexical = Path(os.path.abspath(self.root / rel))
        inside = lexical == self.root or lexical.is_relative_to(self.root)
        # resolve() follows symlinks and junctions, so a link that points out of the
        # project is caught by the containment check below. (Out of it by its name, a
        # path is judged by `opened` before anything of it is looked at.)
        if inside:
            candidate = (self.root / rel).resolve()
        else:
            try:
                candidate = opened(str(lexical))
            except WorkspaceError:
                # In a listed folder that holds a place never opened (slice 75) a path is
                # judged by itself and its own folder.
                listed = self._in_listed(lexical) or self._cli_file(rel, lexical)
                if listed is None:
                    raise
                candidate = listed
        if self.is_own(candidate) and (why := self.koloni_s(candidate)):
            raise WorkspaceError(f"{rel!r} is never opened: {why}")
        if self.is_own(candidate) or any(
            candidate == target or candidate.is_relative_to(target)
            for target in self.links.values()
        ):
            return candidate
        if inside:
            try:
                opened(str(candidate))  # led out of the project by a link
            except WorkspaceError:
                if self._cli_file(rel, candidate) is None:
                    raise
        # Out of the project a secret (.env, a key) is never opened, nobody asked: by the
        # name it was given or the one it really has.
        if is_secret(rel) or is_secret(str(candidate)):
            raise WorkspaceError(f"{rel!r} is never opened: it is a secret")
        if candidate == self.granted or any(
                candidate == folder or candidate.is_relative_to(folder) for folder in self.also):
            return candidate
        raise Outside(rel, candidate if candidate.is_dir() else candidate.parent)

    def _in_listed(self, named: Path) -> Path | None:
        """Where a path outside the project really leads, where that is in a folder it also
        works in and neither the path nor its own folder is `_kept_out` - by its name, and
        then where it leads; else None."""
        def kept_out(path: Path) -> bool:
            return bool(_kept_out(path) or _kept_out(path if path.is_dir() else path.parent))

        try:
            if kept_out(named):
                return None
            real = named.resolve()
            if kept_out(real) or not any(real == f or real.is_relative_to(f) for f in self.also):
                return None
        except (ValueError, OSError):  # a NUL in it, or too long a path
            return None
        return real

    def _cli_file(self, rel: str, named: Path) -> Path | None:
        """Where a path that really leads into a CLI's own folder (`CLI_HOMES`) leads - when it
        is the file this Workspace was `granted` - or None, for a path that leads into none.
        CliHome while it waits for the user's yes; a login or a past conversation
        (`CLI_NEVER`), by the name it was given or the one it has, is never opened."""
        if never(named) and _cli_home(named) is None:
            return None  # (refused by its name, as `opened` has it: not looked at on disk)
        try:
            real = named.resolve()
        except (ValueError, OSError):
            return None
        found = _cli_home(real)
        if found is None:
            return None
        given = _cli_home(named)
        if is_secret(str(real)) or given and is_secret(str(named)):
            raise WorkspaceError(f"{rel!r} is never opened: it is a secret")
        if any(_cli_never(*one) for one in (found, given) if one):
            raise WorkspaceError(f"{rel!r} is never opened: {CLI_NEVER_WHY}")
        if real != self.granted:
            raise CliHome(rel, real, found[0])
        return real

    def is_own(self, path: Path) -> bool:
        """Whether a resolved path is in the folder itself, not in what a link leads to."""
        return path == self.root or path.is_relative_to(self.root)

    @functools.cached_property
    def _koloni_inside(self) -> list[tuple[PurePath, str, str]]:
        """KOLONİ's own places the project holds (`_kept_out` lets it: the Desktop holding
        KOLONİ) - not one the project is in itself (its e2e project, a working copy) - each
        compared as `_cased`, with its path in the project in its own case: on macOS a search
        told to leave it out (`rg -g '!name'`) matches case by case. (By parts, not letters:
        casefold makes "İ" two.)
        shortcut: "its own case" is the case KOLONİ's own path was given in (REPO_ROOT, the
        runtime root), not always the disk's; read the name off the disk if one is seen
        started from a path in another case."""
        at = _cased(self.root)
        return [(_cased(place), why, PurePosixPath(*place.parts[len(at.parts):]).as_posix())
                for place, why in _never_places()
                if why in (OWN_RECORD, OWN_CODE) and _cased(place) != at
                and _cased(place).is_relative_to(at)]

    def koloni_s(self, path: Path) -> str | None:
        """Why a resolved path in the project is never opened all the same: it is in
        KOLONİ's own code or record (`_koloni_inside`) - or None."""
        cased = _cased(path)
        return next((why for place, why, _rel in self._koloni_inside
                     if cased.is_relative_to(place)), None)

    def koloni_under(self, folder: Path) -> str | None:
        """The first of `koloni_places` a resolved folder holds, or is - or None."""
        cased = _cased(folder)
        return next((rel for place, _why, rel in self._koloni_inside
                     if place.is_relative_to(cased)), None)

    def koloni_places(self) -> list[str]:
        """`_koloni_inside`, by their paths in the project."""
        return list(dict.fromkeys(rel for _place, _why, rel in self._koloni_inside))

    def rel(self, path: Path) -> str:
        if not self.is_own(path):
            for at, target in self.links.items():
                if path == target or path.is_relative_to(target):
                    return (PurePosixPath(at) / path.relative_to(target)).as_posix()
            return str(path)  # outside the project: by where it is
        return path.relative_to(self.root).as_posix()

    def list_dir(self, rel: str = ".") -> list[tuple[str, str, int | None]]:
        target = self.resolve(rel)
        if not target.is_dir():
            raise WorkspaceError(f"{rel!r} is not a folder")
        entries: list[tuple[str, str, int | None]] = []
        for child in target.iterdir():
            # (Out of the project, a place KOLONİ never opens is not shown either; in it,
            # KOLONİ's own.)
            if child.name in SKIP_DIRS or self.koloni_s(child) or not self.is_own(child) and (
                _kept_out(child) or is_secret(str(child))
            ):
                continue
            if child.is_dir():
                entries.append((child.name, "dir", None))
            else:
                entries.append((child.name, "file", child.stat().st_size))
        return sorted(entries, key=lambda e: (e[1] != "dir", e[0].lower()))

    def _file(self, rel: str) -> Path:
        target = self.resolve(rel)
        if not target.exists():
            raise WorkspaceError(f"{rel!r} does not exist")
        if not target.is_file():
            raise WorkspaceError(f"{rel!r} is not a file")
        if self._hidden(target):
            raise WorkspaceError(f"{rel!r} is not read: {LINKED_ELSEWHERE}")
        return target

    def _hidden(self, path: Path) -> bool:
        """A file outside the project that is a hard link: its other name may be in a
        place KOLONİ never opens, and no path tells. (In the project such a file is read
        as before, and never written: `write_bytes`.)"""
        return not self.is_own(path) and has_other_names(path)

    def read_text(self, rel: str) -> str:
        target = self._file(rel)
        try:
            # Bytes in, bytes out: no newline translation, so edits keep CRLF/LF as found.
            return target.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            raise WorkspaceError(f"{rel!r} is not UTF-8 text") from None
        except OSError as exc:
            raise WorkspaceError(f"could not read {rel!r}: {exc.strerror or exc}") from None

    def lines(self, rel: str, keep: int) -> Iterator[tuple[str, int]]:
        """A UTF-8 file's lines, one at a time and split as `str.splitlines` splits the
        whole text (the way read_file has always numbered them): the first `keep`
        characters of each, and its length. A piece of the file is held at a time, never
        the file - nor the whole of a long line."""
        target = self._file(rel)
        decoder = codecs.getincrementaldecoder("utf-8")()
        head, length, cr = "", 0, ""
        try:
            with target.open("rb") as file:
                while True:
                    data = file.read(READ_CHUNK)
                    text = cr + decoder.decode(data, final=not data)
                    # A "\r" at the end may be half of a "\r\n": it waits for the next piece.
                    cr = "\r" if data and text.endswith("\r") else ""
                    for piece in text[: len(text) - len(cr)].splitlines(keepends=True):
                        (body,) = piece.splitlines()
                        head += body[: keep - len(head)]
                        length += len(body)
                        if len(body) < len(piece):  # the line ends here
                            yield head, length
                            head, length = "", 0
                    if not data:
                        break
        except UnicodeDecodeError:
            raise WorkspaceError(f"{rel!r} is not UTF-8 text") from None
        except OSError as exc:
            raise WorkspaceError(f"could not read {rel!r}: {exc.strerror or exc}") from None
        if length:  # the last line, with no line end after it
            yield head, length

    def endings(self, rel: str) -> tuple[int, int, bool]:
        """A file's CRLF and lone LF line ends, counted a piece at a time, and whether its
        last byte ends a line: what read_file says of its form (B-162)."""
        crlf = lf = 0
        last = b""
        try:
            with self._file(rel).open("rb") as file:
                while data := file.read(READ_CHUNK):
                    crlf += (last[-1:] + data).count(b"\r\n")  # (one across two pieces too)
                    lf += data.count(b"\n")
                    last = data
        except OSError as exc:
            raise WorkspaceError(f"could not read {rel!r}: {exc.strerror or exc}") from None
        return crlf, lf - crlf, last.endswith(b"\n")  # (a lone CR at the end: none)

    def read_text_or_none(self, rel: str) -> str | None:
        return self.read_text(rel) if self.resolve(rel).exists() else None

    def search(
        self, pattern: str, rel: str = ".", glob: str | None = None,
        seconds: float = SEARCH_SECONDS, stop: threading.Event | None = None,
    ) -> tuple[list[tuple[str, int, str]], bool, int, list[str]]:
        """Regex search; returns (path, line number, line) matches, whether it hit the cap,
        how many secret files (`secret_in_project`; `is_secret` out of it) it did not
        look into, and the text files over MAX_READ_BYTES it did not read.

        Made in a process of its own (`_search_here`, there): Python's re holds the whole
        interpreter while it matches, and a pattern that backtracks would hold the app -
        Stop too - for as long as it runs. That process is ended once it has run for
        `seconds` (TOO_LONG), or as soon as `stop` is set."""
        asked: bytes | None = json.dumps({
            "root": str(self.root), "links": {at: str(to) for at, to in self.links.items()},
            "also": [str(folder) for folder in self.also],
            "pattern": pattern, "rel": rel, "glob": glob,
        }).encode()
        try:
            # Started from KOLONİ's own folder: nothing of the project's can be imported.
            process = subprocess.Popen(
                [sys.executable, "-m", "app.workspace"], cwd=Path(__file__).parent.parent,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            why = exc.strerror or exc
            raise WorkspaceError(f"the search could not be started: {why}") from None
        job = None
        if sys.platform == "win32":
            # In a job of its own, as a command is: ended with it, and with this process
            # should it die. (Imported here: the search's own process does not need it.)
            from app.executors.winjob import Job

            job = Job.for_process(int(getattr(process, "_handle")))  # noqa: B009
        deadline = time.monotonic() + seconds
        try:
            while True:
                try:
                    out, _ = process.communicate(asked, timeout=0.05)
                    break
                except subprocess.TimeoutExpired:
                    asked = None  # (handed over with the first call)
                    late = time.monotonic() > deadline
                    if late or (stop is not None and stop.is_set()):
                        if job is not None:
                            job.terminate()
                        process.kill()
                        process.communicate()
                        raise WorkspaceError(
                            TOO_LONG.format(seconds) if late else STOPPED) from None
        finally:
            if job is not None:
                job.terminate()  # nothing of it is left; the job is released
        try:
            said = json.loads(out)
            if "error" in said:
                raise WorkspaceError(said["error"])
            matches = [tuple(match) for match in said["matches"]]
            return matches, said["truncated"], said["secrets"], said["big"]
        except (ValueError, TypeError, KeyError):
            raise WorkspaceError("the search failed") from None

    def _search_here(
        self, pattern: str, rel: str = ".", glob: str | None = None
    ) -> tuple[list[tuple[str, int, str]], bool, int, list[str]]:
        try:
            regex = re.compile(pattern)
        except re.error as exc:
            raise WorkspaceError(f"invalid regular expression: {exc}") from None
        start = self.resolve(rel)
        if not start.exists():
            raise WorkspaceError(f"{rel!r} does not exist")
        files = [start] if start.is_file() else self._walk(start)
        matches: list[tuple[str, int, str]] = []
        secrets, big = 0, []
        for path in files:
            if glob and not fnmatch.fnmatch(path.name, glob) or self._hidden(path):
                continue
            # A secret in the project is read only on the user's word (read_file): never here.
            if (secret_in_project if self.is_own(path) else is_secret)(self.rel(path)):
                secrets += 1
                continue
            try:
                if path.stat().st_size > MAX_READ_BYTES:
                    with path.open("rb") as file:  # (a big binary would never match: unsaid)
                        if b"\0" not in file.read(1024):
                            big.append(self.rel(path))
                    continue
                text = path.read_bytes().decode("utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for number, line in enumerate(text.splitlines(), 1):
                if regex.search(line):
                    if len(matches) == MAX_MATCHES:
                        return matches, True, secrets, big
                    matches.append((self.rel(path), number, line.strip()[:300]))
        return matches, False, secrets, big

    def _walk(self, folder: Path) -> Iterator[Path]:
        for child in sorted(folder.iterdir(), key=lambda p: p.name.lower()):
            # Links and junctions are not followed: they may lead out of the project. Out
            # of it, a place KOLONİ never opens is not walked into either.
            if child.name in SKIP_DIRS or child.is_symlink() or child.is_junction() or (
                not self.is_own(child) and (_kept_out(child) or is_secret(str(child)))
            ) or self.koloni_s(child) or self.is_own(child) and is_kept_code(
                    child.relative_to(self.root).parts):
                continue
            if child.is_dir():
                yield from self._walk(child)
            elif child.is_file():
                yield child

    def to_write(self, rel: str) -> Path:
        """`resolve`, for a path to be written: never one Windows writes elsewhere
        (`not_written_as_named`)."""
        if why := not_written_as_named(rel):
            raise WorkspaceError(f"{rel!r} is not written: {why}")
        return self.resolve(rel)

    def write_text(self, rel: str, content: str) -> None:
        target = self.to_write(rel)
        data = content.encode("utf-8")
        if len(data) > MAX_WRITE_BYTES:
            raise WorkspaceError(f"{rel!r} would be larger than 1 MiB")
        if target.is_dir():
            raise WorkspaceError(f"{rel!r} is a folder")
        try:
            held = target.read_bytes() if target.is_file() else None
        except OSError as exc:
            raise WorkspaceError(f"could not write {rel}: {exc.strerror or exc}") from None
        try:
            self._write_bytes(target, data)
            # Read back (G4.1): what is said to be written is what the file holds.
            if target.read_bytes() == data:
                return
            why = f"{rel} was written but does not read back as written"
        except OSError as exc:
            why = f"could not write {rel}: {exc.strerror or exc}"
        # A write cut short, or changed on its way, does not leave the file half written.
        try:
            if held is None:
                target.unlink(missing_ok=True)
            elif target.read_bytes() != held:
                self._write_bytes(target, held)
            back = held is None or target.read_bytes() == held
        except OSError:
            back = False
        if back:
            raise WorkspaceError(f"{why}; the file is as it was")
        raise WorkspaceError(f"{why}; it may be partly written - what it held before is on "
                             "this change's record")

    def _write_bytes(self, target: Path, data: bytes) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        write_bytes(target, data)

    def write_new(self, rel: str, data: bytes) -> None:
        """A new file (a user's attached one, slice 85b): never written over one that is
        there - made between a look and this write too (O_EXCL)."""
        target = self.to_write(rel)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with os.fdopen(os.open(target, flags, 0o666), "wb") as file:
                file.write(data)
        except FileExistsError:
            raise WorkspaceError(f"{rel} is there already: nothing was written over it") from None
        except OSError as exc:
            raise WorkspaceError(f"could not write {rel}: {exc.strerror or exc}") from None

    def delete(self, rel: str) -> None:
        try:
            self.to_write(rel).unlink(missing_ok=True)  # (a stream: a mark)
        except OSError as exc:
            raise WorkspaceError(f"could not delete {rel}: {exc.strerror or exc}") from None


LINKED_ELSEWHERE = (
    "it is a hard link: the same file has another name, perhaps in a folder KOLONİ "
    "never opens"
)
HARD_LINK = (
    "it is a hard link: the same file has another name, perhaps outside the project, "
    "and what is written here would be written there too"
)


def has_other_names(target: Path) -> bool:
    """Whether a file has more than one name (a hard link). No check of a path can tell
    which of them is "inside": such a file is not written at all. One that cannot be
    looked at is taken to have them."""
    try:
        status = target.stat()
    except (FileNotFoundError, NotADirectoryError):
        return False  # no such file: a new one has one name
    except (OSError, ValueError):  # (ValueError: a NUL in it)
        return True
    return stat.S_ISREG(status.st_mode) and status.st_nlink > 1


def write_bytes(target: Path, data: bytes) -> None:
    """Write a file - never one with another name (`HARD_LINK`): OSError says so. Every
    write KOLONİ makes into a project, or into a working copy, goes through here. The
    file is opened without being emptied and its names are counted on that very handle,
    so that a link made between a look and the write is not written through either."""
    flags = os.O_WRONLY | os.O_CREAT | getattr(os, "O_BINARY", 0)
    # A new file is 0o666 less the umask (0644), not 0o777's runnable; one there keeps its mode.
    with os.fdopen(os.open(target, flags, 0o666), "wb") as file:
        if os.fstat(file.fileno()).st_nlink > 1:
            raise OSError(HARD_LINK)
        file.truncate(0)
        file.write(data)


def _name(part: str) -> str:
    """One part of a path as Windows would open it: any case, with the dots and spaces
    at its end dropped, and without a stream's name after a colon."""
    return part.split(":")[0].rstrip(" .").casefold()


# shortcut: secrets known by their name only - with slice 45's (`app/skills.py`) and those
# of the cloud CLIs, browsers and wallets; widen it when another kind turns up. Any part of
# a path counts, a folder's too: the safe way round.
SECRET_NAMES = re.compile(
    r"\.env(\..*)?|.*\.env|\.envrc|[._]netrc|\.git-credentials|\.pgpass|\.npmrc|\.pypirc"
    r"|\.?credentials(\..*)?|id_(rsa|dsa|ecdsa|ed25519)|\.ssh|\.aws|\.gnupg|.*\.tfvars"
    r"|.*\.(pem|key|p12|pfx|jks|keystore|ppk|kdbx|keytab)"
    r"|secrets?\.(json|ya?ml|toml)|service-account.*\.json|auth\.json|\.htpasswd|\.my\.cnf"
    r"|token\.txt|api_?keys?(\..*)?|wallet\.dat|kubeconfig|.*\.tfstate(\..*)?"
    r"|application_default_credentials\.json|accesstokens\.json|login data"
    # any KOLONİ's database: one run from a worktree never reads the main install's
    r"|koloni\.db(-wal|-shm|-journal)?"
    # the providers' own sign-in folders (`limits.cli_home`): a command naming one is asked
    # at every level. shortcut: by the name, as every secret here; a wildcard or a short name
    # (`CLI-HO~1`) is not seen - KOLONİ's file tools never open the runtime at all.
    r"|cli-homes"
)
# Why reading one in the project waits on the user's word, every time (slice 88).
SECRET_CARD = (
    "This is a secret file (keys, passwords): reading it sends what it holds to the "
    "model's provider."
)
# A file named as any other but for the folder it is in.
SECRET_PAIRS = ([".git", "config"], [".kube", "config"], [".docker", "config.json"])


def is_secret(rel: str) -> bool:
    """Whether any part of a path is named as a secret is (`.env`, a key file), as Windows
    would open the name (`_name`: `.env.` and `.env::$DATA` are `.env`) - or it is a
    repository's `.git/config`, whose remotes can hold `https://user:token@...`. A short
    name (`ENV~1`) is not seen here: ask with the path resolved too."""
    parts = [_name(part) for part in re.split(r"[\\/]", rel)]
    return parts[-2:] in SECRET_PAIRS or any(SECRET_NAMES.fullmatch(p) for p in parts)


# In the project a file is a secret by its own name and the folder it is in, not by any part
# of its path: these hold work there.
SECRET_FOLDERS = frozenset({".ssh", ".aws", ".gnupg"})
NOT_SECRET_IN_PROJECT = re.compile(
    r".+\.(example|sample|template)"  # .env.example: a file to copy, with no values
    r"|(credentials|api_?keys?|token)"
    r"\.(py|ts|tsx|js|jsx|mjs|cjs|go|rs|java|cs|rb|php|md|txt|json|ya?ml|toml)"
)
# What a package manager put there: a venv by any name has its site-packages.
INSTALLED = frozenset({".venv", "venv", "node_modules", "site-packages"})


def secret_in_project(rel: str) -> bool:
    """`is_secret`, for a path in the project (relative to it): by the file's own name, a
    secret folder (.ssh) or a pair (.git/config) - not an example of one (.env.example), a
    source or text file named credentials, api_keys or token, nor anything installed
    (`INSTALLED`). (Out of the project `is_secret` judges every part.)"""
    parts = [_name(part) for part in re.split(r"[\\/]", rel)]
    if INSTALLED.intersection(parts[:-1]):
        return False
    if parts[-2:] in SECRET_PAIRS or SECRET_FOLDERS.intersection(parts[:-1]):
        return True
    return not NOT_SECRET_IN_PROJECT.fullmatch(parts[-1]) and bool(
        SECRET_NAMES.fullmatch(parts[-1]))


def secret_named(given: str, rel: str) -> bool:
    """Whether a file of the project is a secret: by `rel`, where it really is in the
    project - or by the name it was `given`, where that is relative: a full one also names
    the folders above the project, which do not make its files secrets."""
    return secret_in_project(rel) or not Path(given).is_absolute() and secret_in_project(given)


# The agents' scratch in a project (K-koloni-klasor, `koloni.scratch`).
SCRATCH = ".koloni/tmp"


def in_scratch(rel: str) -> bool:
    """Whether a path in the project (as KOLONİ records it: posix, from its root) is in the
    agents' scratch. Its changes stay on record for their card and undo, but no list of what a
    turn changed shows them - to the user or to an agent."""
    return rel.replace("\\", "/").removeprefix("./").casefold().startswith(f"{SCRATCH}/")


def is_kept_code(parts: Sequence[str]) -> bool:
    """Whether a folder of the project, by its path's parts, is a repository's code a knowledge
    keeps as text (`knowledge.KEPT`: `.koloni/knowledge/<topic>/code`) - another project's files,
    thousands of them: no look of this project's goes in (its changes, its standing files, a
    working copy, its git status, a search of it, its map or its triggers)."""
    return len(parts) == 4 and _name(parts[0]) == ".koloni" and _name(
        parts[1]) == "knowledge" and _name(parts[3]) == "code"


# KOLONİ's own in `.koloni/`, kept in git with the folder: its rules and settings (86c), recipes,
# experts' guides, shared notes, and the scratch's ignore file.
KOLONI_KEPT = ("rules.md", "settings.json", ".gitignore", "recipes/", "knowledge/", "shared/")


def stray_in_koloni(rel: str) -> bool:
    """Whether a path in the project is in `.koloni/` and none of KOLONİ's own there
    (`KOLONI_KEPT`): no change of the project's to list (R125: a Chrome profile a CLI left in
    `.koloni/browser-smoke/` filled Workspace → Changes) - nor a repository's code a knowledge
    keeps (`is_kept_code`), whatever its folder's .gitignore says."""
    path = rel.replace("\\", "/").removeprefix("./")
    if not path.casefold().startswith(".koloni/"):
        return False
    if is_kept_code(path.split("/")[:4]):
        return True
    rest = path[len(".koloni/"):].casefold()  # (`Rules.md` is the rules file on Windows)
    return not any(rest == kept or kept.endswith("/") and rest.startswith(kept)
                   for kept in KOLONI_KEPT)


def standing_names(parts: Sequence[str]) -> list[str]:
    """The names of `NOT_WRITTEN_UNATTENDED` among a path's parts (as `_name` gives them), in
    order - but not `.koloni` where `tmp` follows it: `.koloni/tmp/` is the agents' scratch in
    the project (K-koloni-klasor), no standing name; what is under it is judged as any path."""
    return [_name(part) for at, part in enumerate(parts) if _name(part) in NOT_WRITTEN_UNATTENDED
            and not (_name(part) == ".koloni" and at + 1 < len(parts)
                     and _name(parts[at + 1]) == "tmp")]


def stands_over_later_turns(ws: Workspace, rel: object) -> str | None:
    """The name in a project path that makes it one of `NOT_WRITTEN_UNATTENDED`, or
    None. Looked for in the path as it was given and in where it really leads - through
    `..`, a link or a junction - so that no other way round is an ordinary file."""
    if not isinstance(rel, str):
        return None
    chains = [re.split(r"[\\/]", rel)]
    # (A path that is not inside the project is refused as that, by whoever writes it.)
    with contextlib.suppress(WorkspaceError, ValueError, OSError):
        real = ws.resolve(rel)
        # (Outside the project, in a folder it also works in: the whole of where it is.)
        chains.append(list(real.relative_to(ws.root).parts if ws.is_own(real) else real.parts))
    found = [name for chain in chains for name in standing_names(chain)]
    if not found and any(fnmatch.fnmatchcase("/".join(map(_name, chain)), glob.casefold())
                         for chain in chains for glob in PTH_GLOBS):
        return "*.pth"
    # An instruction file only where nothing else stands in either chain: the path
    # `AGENTS.md/../.claude/settings.json` is `.claude`'s (review of K-fullauto-sorma 2).
    return next((one for one in found if one not in INSTRUCTION_FILES), found[0] if found else None)


def standing_asks(standing: str | None, level: str) -> bool:
    """Whether a write of a file that `stands_over_later_turns` (`standing`, its name) is asked
    at `level`: every one, at every level - but an instruction file alone at Full auto
    (K-fullauto-sorma, `INSTRUCTION_FILES`): later agents read it as the user's words, it runs
    nothing by itself."""
    return bool(standing) and (level != "full_auto" or standing not in INSTRUCTION_FILES)


def sha256_text(text: str | None) -> str | None:
    return None if text is None else hashlib.sha256(text.encode("utf-8")).hexdigest()


def unified_diff(
    before: str | None, after: str, path: str, context: int = 3
) -> tuple[str, int, int]:
    """Unified diff of a text change plus its added and removed line counts."""
    lines = list(
        difflib.unified_diff(
            (before or "").splitlines(), after.splitlines(), f"a/{path}", f"b/{path}",
            n=context, lineterm=""
        )
    )
    body = lines[2:]  # skip the ---/+++ header so content like "+++ x" is not miscounted
    added = sum(1 for line in body if line.startswith("+"))
    removed = sum(1 for line in body if line.startswith("-"))
    return "\n".join(lines), added, removed


def _search_apart() -> None:
    """The process a search is made in (`Workspace.search`): what to look for comes in,
    as JSON, and what was found - or why nothing could be - goes out."""
    asked = json.loads(sys.stdin.buffer.read())
    ws = Workspace(asked["root"], {at: Path(to) for at, to in asked["links"].items()},
                   [Path(folder) for folder in asked["also"]])
    try:
        matches, truncated, secrets, big = ws._search_here(
            asked["pattern"], asked["rel"], asked["glob"])
        said: dict = {"matches": matches, "truncated": truncated, "secrets": secrets, "big": big}
    except WorkspaceError as exc:
        said = {"error": str(exc)}
    except OSError as exc:
        said = {"error": f"file system error: {exc.strerror or exc}"}
    sys.stdout.buffer.write(json.dumps(said).encode())


if __name__ == "__main__":
    _search_apart()
