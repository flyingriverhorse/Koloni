"""MCP servers the user connects: KOLONİ as their client.

A server is a program on this machine that speaks MCP over stdio: JSON-RPC, one message a
line. KOLONİ asks it three things - `initialize`, `tools/list`, `tools/call` - one at a
time, and gives it nothing: whatever it asks of KOLONİ (a model's answer, the folders, a
question to the user) is refused, and what it announces is passed over. It runs with the
user's own rights, outside every rule KOLONİ holds its own tools to; what it says is data.

Its tools are read once and kept as the user saw them (`kept`); agents are offered the
kept list (`usable`, `schema`), whatever the server lists later.
"""

import asyncio
import contextlib
import hashlib
import json
import locale
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from collections.abc import Iterable
from pathlib import Path, PureWindowsPath

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import raw, web
from app.db.models import Conversation, Project
from app.model_cli import CMD_ACTS_ON, ERROR_CHARS, MAX_SHIM_LINE, CliStepClient, complaints
from app.model_client import OwnStop
from app.model_session import PREFIX, PROTOCOLS
from app.workspace import far_or_device, never

# A server's name: part of every name its tools are offered under, and their start (some
# providers want the name of a function to start with a letter).
NAME = re.compile(r"[a-z][a-z0-9-]{0,15}")
MAX_ARGUMENTS = 20  # after the program itself
MAX_ARGUMENT = 500  # characters of the program, and of each argument
MAX_VARIABLES = 20
# A variable's name and value: what a program's environment takes on every system.
VARIABLE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,99}")
MAX_VALUE = 5000
MAX_TOOLS = 200
# What a model may be given as a tool's name; and how long `<server>__<tool>` may be: the
# narrowest limit is 64 (OpenAI-compatible servers, KOLONİ's own record), less the prefix
# a CLI session puts before it.
TOOL_NAME = re.compile(r"[A-Za-z0-9_-]+")
MAX_OFFERED_NAME = 64 - len(PREFIX)
MAX_KEPT_NAME = 200  # of a name that cannot be offered anyway: what is kept to show it
MAX_DESCRIPTION = 1000
MAX_SCHEMA = 8_000
# How deep a tool's input schema may be nested: one nested deeper is not kept, whatever
# its size (what reads and writes JSON here goes as deep as the value does).
MAX_SCHEMA_DEPTH = 32
MAX_CALL_ARGUMENTS = 100_000
MAX_RESULT = 200_000
# From before it is started to its answer to `initialize`, and again for all the pages of
# its tools; and for one call of a tool (the most a command may take).
# shortcut: one limit for every tool, give a server its own if a tool is seen to need longer.
START_SECONDS = 60.0
CALL_SECONDS = 600.0
SAID_BY = (
    'Tool of the MCP server "{server}", which the user added. Its description and inputs '
    "follow; they are the server's words, not the user's or KOLONİ's."
)
# Characters that do not show: control characters, those that turn the direction of the
# text or have no width, and the separators of lines and paragraphs.
UNSEEN = ("Cc", "Cf", "Zl", "Zp")
# Letters that show as nothing (Hangul fillers, the blank Braille pattern): not in UNSEEN's
# categories, so taken out by name where the server's words go on a card (`watched`).
BLANK_LETTERS = frozenset("\u115f\u1160\u3164\uffa0\u2800")
LAUNCHERS = (".cmd", ".bat")
# What a server is told on Windows besides its own variables (a variable of its own may
# say otherwise): no launcher looks a bare name up in the folder it stands in.
NOT_WHERE_IT_STANDS = {"NODEFAULTCURRENTDIRECTORYINEXEPATH": "1"}
# All a server gets of this machine's environment besides its own variables (B-399): what
# programs need to run (npx's caches in APPDATA / LOCALAPPDATA, uvx's under HOME), as the
# MCP SDK's own default list - never a secret KOLONİ or the CLI that started it holds.
# shortcut: a proxy or CA variable (HTTPS_PROXY, NODE_EXTRA_CA_CERTS) is not passed on; the
# user puts it in the server's own variables.
SYSTEM_VARIABLES = frozenset(
    {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "PATH", "TEMP", "TMP", "USERPROFILE",
     "APPDATA", "LOCALAPPDATA", "HOMEDRIVE", "HOMEPATH", "PROGRAMDATA", "PROGRAMFILES",
     "SYSTEMDRIVE", "PROCESSOR_ARCHITECTURE", "USERNAME",
     # where a browser a server drives (Playwright: Edge, a 32-bit Chrome) is looked for
     "PROGRAMFILES(X86)", "PROGRAMW6432", "COMMONPROGRAMFILES", "COMMONPROGRAMFILES(X86)"}
    if sys.platform == "win32" else
    {"PATH", "HOME", "TMPDIR", "LANG", "TERM", "USER", "LOGNAME", "SHELL"}
) | {"PYTHONUTF8", "PYTHONIOENCODING"}  # the user's own choice of how Python writes
# A key in a command's argument as it is shown: the shapes frontend/src/tools/paste.ts has.
# shortcut: the same shapes in two places, change both together; make them one if a third
# place needs them.
MASK = "••••••••"
KEY_LIKE = re.compile(r"(?:sk-|gh[pousr]_|github_pat_|xox[a-z]-)\S{6,}|[0-9a-f]{32,}"
                      r"|(?=.*\d)(?=.*[a-z])[\w+-]{40,}={0,2}", re.I | re.A)
PLACEHOLDER = re.compile(r"\$\{.*\}|<.*>|\$[A-Za-z_]\w*|x{3,}|your[\W_].*|.*[\W_]here",
                         re.I | re.S | re.A)
# An address in an argument, the user (and password) before its host, a field of its query.
URL = re.compile(r"[a-z][a-z0-9+.-]*://[^\s\"'<>]+", re.I)
USERINFO = re.compile(r"^([a-z][a-z0-9+.-]*://)([^/?#@]+)@", re.I)
FIELD = re.compile(r"([?&])([^=&#]+)=([^&#]*)")
AUTHORIZATION = re.compile(r"(authorization:\s*(?:(?:bearer|basic|token)\s+)?)(\S.*)",
                           re.I | re.S)
# NAME=VALUE: a flag's (--token=…) or a variable's (docker's -e GITHUB_TOKEN=…); a flag alone.
NAMED = re.compile(r"(-{0,2}[\w.-]+)=(.*)", re.S | re.A)
FLAG = re.compile(r"-{1,2}([\w-]+)", re.A)
# A drive with a path but no root after it (D:proj\s.js): read from that drive's own folder
# (`not_startable`). Not a bare drive (D:), nor a number after one (a:1, 8:80: not paths).
DRIVE_RELATIVE = re.compile(r"[A-Za-z]:(?![\\/])(?!\d+$)[\w.-]", re.A)
# What a server runs from a project (97, `in_project`): a folder after one of these flags
# (uv --directory, npm --prefix, ...) or as an interpreter's first argument is its code.
RUN_FROM = {"--directory", "--project", "--cwd", "--prefix", "--dir", "-C", "--from",
            "--with-editable"}
INTERPRETERS = {"python", "pythonw", "py", "node", "deno", "bun"}
# Not hashed with a script's folder: what tools make, and packages (`_held`'s shortcut).
SKIPPED = {".git", ".venv", "node_modules", "__pycache__", "dist", "build"}
MAX_TREE_FILES = 2000
MAX_TREE_BYTES = 50_000_000
# The start folder's own settings: npm and uv look no further up than these (97).
# shortcut: not measured with a real npm or uv; check that they stop here.
STUBS = {"package.json": '{"private": true}\n', "uv.toml": ""}


class McpError(Exception):
    """A server could not be started, did not answer, or answered what cannot be read.
    Said so that it follows the server's name: "could not be started: ..."."""


class _Refused(Exception):
    """The server answered a request with an error of its own: its words."""


def found(program: str) -> str | None:
    """A program's full path as it is found from here: on PATH, or where its own full
    path says. None for one that is not found - and for one found only by a path that is
    not full: on Windows a bare name is looked for first in the folder KOLONİ itself
    stands in, and what lies there is not what the user named. (And made whole: a path
    that names no drive can count as full there.)"""
    at = shutil.which(program)
    return os.path.abspath(at) if at and os.path.isabs(at) else None


def _launcher(program: str) -> bool:
    """Whether a program is one the Windows command interpreter runs: a .cmd or .bat
    file, on Windows - elsewhere a file so named is a program like any other."""
    return sys.platform == "win32" and program.lower().endswith(LAUNCHERS)


def not_startable(argv: list[str]) -> str | None:
    """Why a command cannot be started as it is, its program given by its full path; None:
    it can. On Windows an argument from a drive's own folder (`D:proj\\server.js`, or a
    NAME=value's value): the server would run the file on that drive's root, which
    `in_project` does not pin. And a program that is a .cmd or .bat file: the Windows
    command interpreter runs it, reads the whole line itself first, and would act on
    some characters - in the program's own path as in an argument."""
    if sys.platform == "win32" and any(
        DRIVE_RELATIVE.match(part) or (named := NAMED.fullmatch(part))
        and DRIVE_RELATIVE.match(named[2]) for part in argv[1:]
    ):
        return ("an argument names a drive without a folder from its root (D:proj): write "
                "it in full (D:\\proj)")
    if not _launcher(argv[0]):
        return None
    if any(CMD_ACTS_ON.search(part) for part in argv):
        return ("its program is a .cmd or .bat file, which the Windows command interpreter "
                "runs: the characters % ! ^ & | < > cannot be in its path or in an argument")
    if len(subprocess.list2cmdline(argv)) > MAX_SHIM_LINE:
        return ("its program is a .cmd or .bat file, and its command line is too long for "
                f"one on Windows ({MAX_SHIM_LINE} characters at most)")
    return None


def _is_value(value: str) -> bool:
    return value not in ("", MASK) and not PLACEHOLDER.fullmatch(value)


def _secret_name(name: str) -> bool:
    return name == "k" or bool(web._SECRET.search(name))


def _part_shown(command: list[str], at: int) -> tuple[str, list[str]]:
    """An argument (not the program) as it may be shown, and the values put away from it."""
    part, away = command[at], []

    def put_away(value: str) -> str:
        away.append(value)
        return MASK

    def in_url(url: re.Match) -> str:
        bare = USERINFO.sub(lambda m: m[1] + put_away(m[2]) + "@", url[0])
        return FIELD.sub(lambda m: f"{m[1]}{m[2]}={put_away(m[3])}" if _secret_name(m[2])
                         and _is_value(m[3]) else m[0], bare)

    shown = AUTHORIZATION.sub(lambda m: m[1] + put_away(m[2]), URL.sub(in_url, part))
    if shown != part:
        return shown, away
    named = NAMED.fullmatch(part)
    name, value = (named[1], named[2]) if named else (None, part)
    flag = FLAG.fullmatch(command[at - 1]) if at > 1 else None
    secret = _secret_name(name.lstrip("-")) if name else (
        flag is not None and _secret_name(flag[1]) and not part.startswith("-"))
    if (secret and _is_value(value)) or KEY_LIKE.fullmatch(value):
        shown = f"{name}={put_away(value)}" if name else put_away(value)
    return shown, away


def command_shown(command: list[str]) -> list[str]:
    """A command as it may be shown: a key in an argument is MASK - a value named like a
    secret (`web._SECRET`: after such a flag, spaced or with =, or as a variable's NAME=),
    after "Authorization:", the user and password or a secret field of an address, or one
    that is KEY_LIKE. The program itself is never a key; a value left to the reader
    (<YOUR_TOKEN>, $VAR) is not one."""
    return command[:1] + [_part_shown(command, at)[0] for at in range(1, len(command))]


def keys_in(command: list[str]) -> list[str]:
    """The values `command_shown` puts away: secrets, hidden in whatever the server says."""
    return [value for at in range(1, len(command)) for value in _part_shown(command, at)[1]]


def visible(text: str) -> str:
    """Text as the user is shown it where they give leave: a character that does not show
    is written out as its escape, so that what is seen is what is sent."""
    return "".join(
        ch if unicodedata.category(ch) not in UNSEEN
        else f"\\u{ord(ch):04x}" if ord(ch) < 0x10000 else f"\\U{ord(ch):08x}"
        for ch in text
    )


def agents_folders(session: Session) -> list[Path]:
    """Every folder agents write in without asking (97): each project, and each folder a
    project or a conversation also works in.
    shortcut: not a folder lent on an ask_folder card, a path outside allowed on a card, or
    one a command at Full auto writes in (any folder of the user's); add those if a server
    is seen to be started from one."""
    rows = session.execute(select(Project.root_path, Project.also_in)).all()
    listed = [folder for root, also in rows for folder in (root, *also)]
    listed += [folder for also in session.scalars(select(Conversation.also_in)) for folder in also]
    return [Path(folder) for folder in dict.fromkeys(listed)]


def _linked(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()


def _editable(pth: Path, roots: list[Path]) -> list[Path]:
    """The folders in `roots` a site-packages .pth file adds to Python's path: an editable
    install (`uv sync`, `pip install -e`) runs the project's own source from there. Each
    line as `site` reads it: joined onto the .pth file's folder (a relative one, and `/x`
    on that folder's drive, which 3.13's isabs no longer calls whole on Windows) - but a
    comment and an `import` line, which `site` runs instead. Read as UTF-8, else in the
    locale's encoding, as 3.13's `site` does (setuptools writes it so)."""
    held = pth.read_bytes()
    try:
        text = held.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = held.decode(locale.getencoding(), errors="replace")
    lines = text.splitlines()
    return [path for line in lines
            if line.strip() and not line.startswith(("#", "import ", "import\t"))
            and not far_or_device(joined := os.path.join(pth.parent, line.rstrip()))
            and (path := Path(os.path.abspath(joined))).is_dir()
            and any(path.resolve().is_relative_to(r) for r in roots)]


def _held(entry: Path, roots: list[Path]) -> str | None:
    """One sha256 of what decides what an entry of a command runs (97): the files below
    its folder - a script's own folder, as it imports its neighbours (tools.py, ./lib) - but
    in SKIPPED folders, and of a link where it leads, not what is behind it; for a
    project's own python (.venv/Scripts) its pyvenv.cfg and site-packages' .pth files too,
    and the folders in `roots` those add (an editable install's source). None past
    MAX_TREE_FILES or MAX_TREE_BYTES, or for what could not all be read: asked about every
    time.
    shortcut: not the packages a project's python or a node_modules/.bin shim then loads
    (SKIPPED), nor what a script imports from above its folder (require('../shared')), nor
    a PYTHONPATH or NODE_OPTIONS in the server's variables; hash them too if such a server
    is seen to be changed by an agent."""
    folder = entry if entry.is_dir() else entry.parent
    parts = [folder]
    venv = folder.parent / "pyvenv.cfg"
    digest, count, size = hashlib.sha256(), 0, 0
    try:
        if entry.is_file() and venv.is_file():
            pths = [*sorted(folder.parent.glob("Lib/site-packages/*.pth")),
                    *sorted(folder.parent.glob("lib/python*/site-packages/*.pth"))]
            parts += [venv, *pths, *(source for pth in pths for source in _editable(pth, roots))]
        for part in parts:
            walked = os.walk(part) if part.is_dir() else [(str(part.parent), [], [part.name])]
            for root, dirs, names in walked:
                for linked in sorted(Path(root, d) for d in dirs if _linked(Path(root, d))):
                    digest.update(f"{linked}->{os.readlink(linked)}\0".encode())
                dirs[:] = sorted(d for d in dirs if d not in SKIPPED and not _linked(Path(root, d)))
                count += len(dirs)  # (a folder counts as a file: no walk of endless empty ones)
                for name in sorted(names):
                    path = Path(root, name)
                    count, size = count + 1, size + path.stat().st_size
                    if count > MAX_TREE_FILES or size > MAX_TREE_BYTES:
                        return None
                    with path.open("rb") as held:
                        one = hashlib.file_digest(held, "sha256").digest()
                    digest.update(f"{path}\0".encode() + one)
    except (OSError, ValueError):  # (a NUL in a .pth line, too long a path)
        return None
    return digest.hexdigest()


def in_project(command: list[str], folders: list[Path]) -> dict[str, str | None]:
    """What a command runs from one of `folders`, which agents can change (97), each by
    its full path with `_held`'s hash: its program as it is found, each argument (or a
    NAME=value's value) that is a full path to a file, and one to a folder where it is
    code - after a flag that says where a runner runs from (uv --directory), or the first
    argument of an interpreter (node ./mcp). In a folder by the path as given or by where a
    link makes it lead: either is enough. Another folder is the server's data; a relative
    path is read from the server's own folder, never a project's; a network or device path
    is never looked at; and what is KOLONİ's own (its .venv), as given or where it leads,
    is not the project's: no file tool writes there. (`D:proj` is refused: `not_startable`.)
    shortcut: `/x` is read on KOLONİ's own drive, the server reads it on `mcp_home`'s; read
    it there if the two are ever seen to differ."""
    roots = [*folders, *(folder.resolve() for folder in folders)]
    program = found(command[0]) or command[0]
    interpreter = Path(program).stem.lower().rstrip("0123456789.") in INTERPRETERS
    first = next((at for at in range(1, len(command)) if not command[at].startswith("-")), None)
    entries = [(program, False)]
    for at in range(1, len(command)):
        named = NAMED.fullmatch(command[at])
        entries.append((command[at], command[at - 1] in RUN_FROM or (interpreter and at == first)))
        if named:
            entries.append((named[2], named[1] in RUN_FROM))
    files: dict[str, str | None] = {}
    for part, code in entries:
        try:
            # (`/x` too, which 3.13's isabs no longer calls whole on Windows: on its drive.)
            if far_or_device(part) or not (os.path.isabs(part) or PureWindowsPath(part).root):
                continue
            given = Path(os.path.abspath(part))
            real = given.resolve()
            inside = [p for p in (given, real) if any(p.is_relative_to(r) for r in roots)]
            if (not inside or never(given) or never(real)
                    or not (real.is_file() or (code and real.is_dir()))):
                continue
            files[str(inside[0])] = _held(real, roots)
        except (OSError, ValueError):  # gone meanwhile, a NUL in it, too long a path
            continue
    return files


def trusted(kept: dict[str, str], files: dict[str, str | None]) -> bool:
    """Whether the user said to start each of these as it is now (one too big to hash is
    asked about every time)."""
    return all(digest is not None and kept.get(path) == digest for path, digest in files.items())


def runs(files: dict[str, str | None], shown: int = 3) -> str:
    """What a server runs from a project, as a card says it: the first few, written out
    as they are seen (`visible`), and why it is asked every time where it is - well within
    a question's characters (`tools.MAX_QUESTION_CHARS`)."""
    named = ", ".join(map(visible, list(files)[:shown]))
    if len(named) > 1200:
        named = f"{named[:1200]}…"
    if len(files) > shown:
        named += f" and {len(files) - shown} more"
    if None in files.values():
        named += (f" (a folder of it holds more than {MAX_TREE_FILES} files or "
                  f"{MAX_TREE_BYTES // 1_000_000} MB, or what could not be read: you are "
                  "asked every time it starts)")
    return named


def _message(line: bytes) -> object:
    """A line a server wrote, as JSON. Half of a character's pair - which JSON can spell,
    and nothing can store or send - reads as "?", as in a model's arguments
    (`tools.parse_arguments`). ValueError for what is not JSON; RecursionError for JSON
    nested deeper than can be read."""
    text = line.decode("utf-8", errors="replace")
    if web.too_deep(text):  # (json.loads alone reads deeper on some Pythons than others)
        raise RecursionError("nested deeper than is read")
    value = json.loads(text)
    if "\\u" in text:
        value = json.loads(json.dumps(value, ensure_ascii=False).encode("utf-8", "replace"))
    return value


def _last(words: str) -> str:
    """A server's last words, as they are added to why it failed - in quotes: its own."""
    return f"; its last words: {json.dumps(words, ensure_ascii=False)}" if words else ""


def said(result: dict) -> tuple[bool, str]:
    """Whether a tool's result says it failed, and its text: the text parts, and for each
    part that is not text a line that names it."""
    parts = []
    content = result.get("content")
    for part in content if isinstance(content, list) else []:
        kind = part.get("type") if isinstance(part, dict) else None
        if kind == "text" and isinstance(part.get("text"), str):
            parts.append(part["text"])
        else:
            named = isinstance(kind, str) and re.fullmatch(r"[a-z_]{1,20}", kind)
            parts.append(f"[{kind if named else 'content'}: not shown]")
    return result.get("isError") is True, "\n".join(parts)


class _Starter(CliStepClient):
    """How a server is started: as a CLI is, with this machine's SYSTEM_VARIABLES only."""

    label = "this server"

    def _inherited(self, pass_env: str | None = None) -> dict[str, str]:
        return {name: value for name, value in os.environ.items()
                if name.upper() in SYSTEM_VARIABLES or name.startswith("LC_")}


class Client:
    """A server that was started and said hello, asked one thing at a time (an agent's
    calls run in order). Whatever goes wrong between a request and its answer ends it."""

    # The command and variables it was started with, as the server's record had them.
    started_as: tuple[list[str], dict[str, str]] | None = None

    def __init__(self, process: asyncio.subprocess.Process, job, secrets: list[str],
                 folder: Path):
        self._process, self._job, self._folder = process, job, folder
        # Its variables' values and its arguments' keys, as they are looked for in whatever
        # it says (`raw.spellings`).
        self._secrets = secrets
        self._asked = 0
        self._ended: str | None = None  # (`end`: what it said, once it is ended)
        assert process.stderr is not None  # piped
        with raw.of(None):  # its error output is no agent's CLI's
            self._errors = asyncio.ensure_future(complaints(process.stderr))

    @classmethod
    async def start(cls, command: list[str], env: dict[str, str], home: Path) -> "Client":
        """Start the program and say hello: in an empty folder made for it in `home`
        (`Settings.mcp_home`: no folder above it can be a project), which is gone when it
        is ended - never in the project, a working copy or the system's temp folder, whose
        files could then decide what is run (a launcher looks a bare name up in the folder
        it stands in; npx and `python -m` take what they find there, npm and uv in the
        folders above it too - 97). With its own variables and SYSTEM_VARIABLES only.
        McpError says why it could not be.
        shortcut: a server that reads ./config.json or keeps its state in its own folder
        finds an empty one at each start, as before 97; give it a folder that is kept if a
        server is seen to need one."""
        started_as = (list(command), dict(env))
        hidden = raw.spellings([*env.values(), *keys_in(command)])
        at = found(command[0])
        if at is None:
            raise McpError(raw.hide(
                f"could not be started: the program {command[0]} was not found (a name is "
                "looked for on PATH; a program in a folder is given by its full path)", hidden))
        argv = [at, *command[1:]]
        why = not_startable(argv)
        if why:
            raise McpError(f"could not be started: {why}")
        if sys.platform == "win32":
            # One name there, however it is written: its own value takes this machine's
            # place.
            env = {**NOT_WHERE_IT_STANDS, **{name.upper(): value for name, value in env.items()}}
        starter = _Starter(env=env)
        folder: Path | None = None
        try:
            home.mkdir(parents=True, exist_ok=True)
            for name, stub in STUBS.items():
                if not (home / name).exists():
                    (home / name).write_text(stub, encoding="utf-8")
            folder = Path(tempfile.mkdtemp(prefix="koloni-mcp-", dir=home))
            process, job = await starter._start(argv, _launcher(at), folder)
        except BaseException as exc:
            if folder is not None:
                shutil.rmtree(folder, ignore_errors=True)
            if isinstance(exc, OSError):
                raise McpError(
                    f"could not be started: {raw.hide(str(exc.strerror or exc), hidden)}"
                ) from None
            if isinstance(exc, OwnStop):
                raise McpError(f"could not be started: {raw.hide(str(exc), hidden)}") from None
            raise
        client = cls(process, job, hidden, folder)
        client.started_as = started_as
        await client._within(START_SECONDS, "initialize", {
            "protocolVersion": PROTOCOLS[0],
            "capabilities": {},  # none: nothing is to be asked of KOLONİ
            "clientInfo": {"name": "koloni", "version": "1"},
        })
        try:
            await client._say({"method": "notifications/initialized"})
        except BaseException:  # a Stop too: nobody else has it yet to end it
            await client.end()
            raise
        return client

    @property
    def alive(self) -> bool:
        return self._process.returncode is None

    def _write(self, message: dict) -> asyncio.StreamWriter:
        stdin = self._process.stdin
        assert stdin is not None  # piped
        stdin.write((json.dumps({"jsonrpc": "2.0", **message}) + "\n").encode())
        return stdin

    async def _say(self, message: dict) -> None:
        try:
            await self._write(message).drain()
        except (BrokenPipeError, ConnectionResetError):
            raise McpError("ended without an answer") from None

    async def _ask(self, method: str, params: dict) -> dict:
        """One request and the server's answer to it. What it writes in between is not
        an answer: a request of its own is refused, and a notification, a line that is
        not JSON and an answer to something else are passed over."""
        stdout = self._process.stdout
        assert stdout is not None  # piped
        self._asked += 1
        await self._say({"id": self._asked, "method": method, "params": params})
        while True:
            try:
                line = await stdout.readline()
            except ValueError:
                raise McpError("sent a line too long to read") from None
            if not line:
                raise McpError("ended without an answer")
            try:
                told = _message(line)
            except ValueError:
                continue
            except RecursionError:
                raise McpError(f"answered {method} with what cannot be read") from None
            if not isinstance(told, dict):
                continue
            if "method" in told:
                if told.get("id") is not None:
                    # `ping` asks nothing of KOLONİ: the protocol has it answered.
                    await self._say({"id": told["id"], **(
                        {"result": {}} if told["method"] == "ping" else {"error": {
                            "code": -32601, "message": "KOLONİ answers no request of a server's",
                        }}
                    )})
                continue
            if told.get("id") != self._asked:
                continue
            result, error = told.get("result"), told.get("error")
            if isinstance(result, dict):
                return result
            if isinstance(error, dict) and isinstance(error.get("message"), str):
                raise _Refused(raw.hide(error["message"], self._secrets)[:ERROR_CHARS])
            raise McpError(f"answered {method} with what cannot be read")

    async def _within(self, seconds: float, method: str, params: dict) -> dict:
        """The answer to a request, within `seconds`. If it does not come - the time is
        up, the server is gone, it wrote what cannot be read, the turn is stopped - the
        server is ended here, told first that a call of a tool is given up; McpError
        says why, with its last words. Whatever a server does ends its call and no more:
        only a stop of the turn passes through. An error it answers with fails a call of
        a tool and leaves the server running; a server that refuses anything else is of
        no use, and is ended too."""
        try:
            async with asyncio.timeout(seconds):
                return await self._ask(method, params)
        except _Refused as exc:
            if method == "tools/call":
                raise
            raise McpError(f"refused {method}: {exc}" + _last(await self.end())) from None
        except BaseException as exc:
            try:
                if method == "tools/call" and not isinstance(exc, McpError):
                    # Written, and not waited for: a server that reads nothing any more
                    # is ended all the same, and at once.
                    with contextlib.suppress(Exception):
                        self._write({"method": "notifications/cancelled", "params": {
                            "requestId": self._asked, "reason": "the call was given up"}})
            finally:
                last = await self.end()
            if isinstance(exc, TimeoutError):
                why = f"did not answer within {seconds:g} seconds"
            elif isinstance(exc, McpError):
                why = str(exc)
            elif isinstance(exc, Exception):
                why = f"answered {method} with what cannot be read"
            else:
                raise  # Stop
            raise McpError(why + _last(last)) from None

    async def tools(self) -> list:
        """What the server lists as its tools now: every page, up to MAX_TOOLS of them,
        all of them within START_SECONDS."""
        listed: list = []
        cursor = None
        try:
            async with asyncio.timeout(START_SECONDS):
                while len(listed) < MAX_TOOLS:
                    page = await self._within(
                        START_SECONDS, "tools/list", {"cursor": cursor} if cursor else {})
                    tools = page.get("tools")
                    listed += tools if isinstance(tools, list) else []
                    cursor = page.get("nextCursor")
                    # (A page with nothing on it is the last: a cursor alone is not followed.)
                    if not tools or not isinstance(cursor, str) or not cursor:
                        break
        except TimeoutError:
            raise McpError(
                f"did not list its tools within {START_SECONDS:g} seconds"
                + _last(await self.end())) from None
        return listed[:MAX_TOOLS]

    async def call(self, tool: str, arguments: dict) -> tuple[bool, str]:
        """Call one tool: whether it failed, and what it said - its secrets hidden.
        McpError when no answer came: the server is ended, and the next call needs
        another."""
        try:
            result = await self._within(
                CALL_SECONDS, "tools/call", {"name": tool, "arguments": arguments})
        except _Refused as exc:
            return True, str(exc)
        failed, text = said(result)
        return failed, raw.hide(text, self._secrets)

    async def end(self) -> str:
        """End the server and everything it started, and take its folder away; safe to do
        again. Returns the last line of its error output, its secrets hidden: why it
        failed, where it did."""
        if self._ended is not None:
            return self._ended
        self._ended = ""  # (another end while this one works is no second one)
        if self._process.stdin is not None:
            with contextlib.suppress(Exception):
                self._process.stdin.close()
        # (Its group only while it runs: a server that crashed may have done so hours ago.)
        await CliStepClient._end(self._process, self._job, exited_now=False)
        errors = b""
        if not self._errors.cancelled():
            with contextlib.suppress(Exception):
                errors = await asyncio.wait_for(asyncio.shield(self._errors), 2)
            self._errors.cancel()
        await asyncio.to_thread(shutil.rmtree, self._folder, True)
        # Hidden first, cut after: a secret across the cut would be left half in sight.
        lines = raw.hide(errors.decode("utf-8", errors="replace"), self._secrets).split("\n")
        self._ended = next(
            (line.strip()[-ERROR_CHARS:] for line in reversed(lines) if line.strip()), "")
        return self._ended


async def read_tools(command: list[str], env: dict[str, str], home: Path) -> list:
    """A server's tools as it lists them now: it is started, asked, and ended. McpError
    says why they could not be read - that it did not start, where it did not."""
    client = await Client.start(command, env, home)
    try:
        return await client.tools()
    finally:
        await client.end()


def sweep(home: Path) -> None:
    """Take away the start folders a KOLONİ that did not end well left in `home`: at the
    start, before any server of this one's runs (the folder is this runtime's alone)."""
    for left in home.glob("koloni-mcp-*"):
        shutil.rmtree(left, ignore_errors=True)


def _depth(value: object) -> int:
    """How deep a JSON value is nested - found level by level, not by going as deep, and
    no further than the first level past MAX_SCHEMA_DEPTH."""
    deep, level = 0, [value]
    while level and deep <= MAX_SCHEMA_DEPTH:
        deep += 1
        level = [inner for one in level if isinstance(one, dict | list)
                 for inner in (one.values() if isinstance(one, dict) else one)]
    return deep


def _as_read(server: str, listed: object) -> dict | None:
    """One tool as it is kept from a reading: its name, the server's description of it
    and its input schema, and why it cannot be offered to an agent (`unusable`; None: it
    can). None for what has no name to keep it under."""
    if not isinstance(listed, dict) or not isinstance(listed.get("name"), str):
        return None
    name, described, schema = listed["name"], listed.get("description"), listed.get("inputSchema")
    if not name:
        return None
    listed_one = isinstance(schema, dict)
    # Why its schema is not kept as the server gave it, whatever else is said of the tool.
    not_kept = None
    if listed_one and _depth(schema) > MAX_SCHEMA_DEPTH:
        not_kept = f"its input schema is nested deeper than {MAX_SCHEMA_DEPTH} levels"
    elif listed_one:
        try:
            written = json.dumps(schema, ensure_ascii=False, allow_nan=False)
        except ValueError:
            # Python reads 1e999 and NaN as numbers; what a model is sent cannot hold them.
            not_kept = "its input schema holds a number that is not finite (NaN, Infinity)"
        else:
            if len(written) > MAX_SCHEMA:
                not_kept = f"its input schema has {len(written)} characters ({MAX_SCHEMA} at most)"
            elif any(unicodedata.category(ch) in UNSEEN for ch in written):
                # Not cleaned as a description is: that would rewrite its keys. As it
                # is written here it is shown on the page, where they cannot be seen.
                not_kept = "its inputs hold characters that do not show"
    if not TOOL_NAME.fullmatch(name):
        why = "its name has characters other than letters, digits, _ and -"
    elif len(f"{server}__{name}") > MAX_OFFERED_NAME:
        why = (f"with the server's name before it, its name has {len(server) + 2 + len(name)} "
               f"characters ({MAX_OFFERED_NAME} at most)")
    elif not listed_one or schema.get("type") != "object":
        why = "it lists no input schema of an object"
    else:
        why = not_kept
    # The server's words, without what does not show (a line end and a tab do).
    plain = "".join(
        ch for ch in described if ch in "\n\t" or unicodedata.category(ch) not in UNSEEN
    ) if isinstance(described, str) else ""
    return {
        "name": name[:MAX_KEPT_NAME],
        "description": plain[:MAX_DESCRIPTION],
        # Kept as the server gave it - but not one that cannot be offered as it is.
        "input_schema": schema if listed_one and not_kept is None else {},
        "unusable": why,
    }


def kept(server: str, before: list[dict], listed: list) -> tuple[list[dict], dict[str, list[str]]]:
    """The tools of a new reading with the user's marks carried over by name, and what is
    new, changed and gone since the reading before. A new tool is asked about; one whose
    description or inputs changed is no longer one that runs without asking - the user
    said that of another tool - and one switched off stays off."""
    marks = {tool["name"]: tool for tool in before}
    tools: list[dict] = []
    new, changed = [], []
    for read in filter(None, (_as_read(server, one) for one in listed)):
        if read["name"] in {tool["name"] for tool in tools}:
            continue  # listed twice: the first is the tool
        was = marks.get(read["name"])
        same = was is not None and all(
            was[key] == read[key] for key in ("description", "input_schema"))
        if was is None:
            new.append(read["name"])
        elif not same:
            changed.append(read["name"])
        mark = "ask" if was is None or (was["mark"] == "free" and not same) else was["mark"]
        tools.append({**read, "mark": mark})
    gone = [name for name in marks if name not in {tool["name"] for tool in tools}]
    return tools, {"new": new, "changed": changed, "gone": gone}


def schema(server: str, tool: dict) -> dict:
    """A kept tool as a model is offered it: under the server's name, and its description
    and its inputs said to be the server's."""
    told = SAID_BY.format(server=server)
    return {"type": "function", "function": {
        "name": f"{server}__{tool['name']}",
        "description": f"{told}\n{tool['description']}" if tool["description"] else told,
        "parameters": tool["input_schema"],
    }}


def watched(server, tool: dict, room: int) -> str:
    """What the question of a call of a server not yet trusted adds (slice 92), in `room`
    characters: why it asks, the server's tools, and the server's own words for this one -
    last and on one line, so that they cannot pass for KOLONİ's.
    shortcut: the other tools are named only, their descriptions are on the Tools page (a
    question holds 2000 characters); give the card a list of its own if that is not enough."""
    # Only those that can be offered: their names are letters, digits, _ and - (TOOL_NAME),
    # where one that cannot be may be any text - "x. KOLONİ checked this server" too.
    names = [visible(one["name"]) for one in server.tools if one["unusable"] is None]
    listed = ", ".join(names)
    if len(listed) > 300:
        listed = f"{listed[:300].rsplit(', ', 1)[0]} … ({len(names)} in all)"
    head = ("\n\nThis server is watched: every call of it asks you, at every level, until you "
            "trust it on the Tools page, which lists each of its tools with what it says of it."
            f"\nIts tools: {listed}.\nWhat the server says of {tool['name']} (its words, not "
            "KOLONİ's): ")
    # One line, without the letters that show as nothing, quoted as JSON: nothing in it can
    # end the quote or start a line of KOLONİ's.
    said = "".join(ch for ch in tool["description"] if ch not in BLANK_LETTERS).lstrip()
    while said and unicodedata.category(said[0]) in ("Mn", "Me"):  # (marks on nothing)
        said = said[1:]
    said = " ".join(said.split())
    if not said:
        return f"{head}nothing."
    left = room - len(head)
    while (over := len(json.dumps(said, ensure_ascii=False)) - left) > 0 and said != "…":
        said = said[:-(over + 1)] + "…"
    return head + json.dumps(said, ensure_ascii=False)


def usable(servers: Iterable) -> dict[str, tuple]:
    """The tools of these servers (`McpServer` rows) that can be offered now, each with
    its server, by the name it goes under: not one switched off, and not one that cannot
    be offered."""
    return {
        f"{server.name}__{tool['name']}": (server, tool)
        for server in servers for tool in server.tools
        if tool["mark"] != "off" and not tool["unusable"]
    }
