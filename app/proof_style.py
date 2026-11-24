"""0.1.7's fourth kind of work, Code style and types: the project's own ruff, eslint, tsc and mypy
on the files a turn changed - each only where the project sets it up AND has it installed here,
never a download (no npx, uvx or pip). Running one runs the project's code (an eslint.config.js is
JavaScript, a mypy plugin Python): it goes as the project's test command goes - a card where no
rule covers it (`KindsMixin._style`). Here, what needs no process: which tools and their lines,
and what their output says - a problem on a line the turn wrote is the turn's.

The tools' output is text from the project's code: each line it gives is cut short, on one line,
and goes to the Orchestrator only as data (`proof_kinds.KINDS_TO_FIX`)."""

import os
import re
import shutil
import sys
import time
from collections import Counter
from collections.abc import Iterable, Mapping
from pathlib import Path, PurePosixPath
from typing import NamedTuple

from app import proof
from app.commands import _program
from app.proof import Row, row
from app.proof_kinds import _json
from app.workspace import WorkspaceError, sha256_text

STYLE = "style"
PY = (".py", ".pyi")
JS = (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts", ".vue")
TS = (".ts", ".tsx", ".mts", ".cts")
STYLE_FILES = (*PY, *JS)
MOST_FILES = 50  # a command's
STYLE_SECONDS = 120  # the kind's, every command of it
MOST_SAID = 160  # characters of one problem
MOST_FAILED = 20  # problems a tool fails the turn with, then counted
MOST_CONFIG = 256 * 1024  # of a pyproject.toml or setup.cfg read
# A line of a tool's output is read this far (B2: a regex over a long run of spaces held the GIL).
MOST_LINE = 2048
# A path put in a command line as it is - no quoting needed in PowerShell or sh; another is said.
_PLAIN = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_./@+-]*")
# Colour codes a tool may write all the same (FORCE_COLOR set: NO_COLOR is not enough for ruff),
# and its links around a rule's code (OSC 8: `ESC ] 8 ;; url ESC \`).
_COLOUR = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
_ESLINT_CONFIGS = (
    *(f"eslint.config.{one}" for one in ("js", "mjs", "cjs", "ts", "mts", "cts")),
    *(f".eslintrc{one}" for one in ("", ".js", ".cjs", ".json", ".yml", ".yaml")),
)
NOT_INSTALLED = "{tool}: not checked - set up in this project, not installed here"
NOT_PLAIN = "Code style not checked: {named} - a name KOLONİ does not put in a command line"
TOO_MANY = "{tool}: {n} more files not checked - at most {most} a run"
CLEAN = "{tool}: no problems on the lines this turn changed ({n} files)"
ELSEWHERE = "{tool}: {n} problems on lines this turn did not change"
WARNED = "{tool}: {n} warnings on the lines this turn changed"
MORE = "{tool}: +{n} more problems on the lines this turn changed"
UNREAD = "{tool}: not checked - its output was not read ({why})"
BY_THEIRS = (
    "{tool}: not run here - the project's own check runs it (its CI lines, its test command)"
)
DECLINED = "declined on its card this turn"
WROTE_IT = "this turn wrote in {folder}: no install of the project's"
WROTE_BARE = "this turn wrote {name} in the folder it runs in"
OUTSIDE = "its program is not in the project ({program})"
NEEDS_LEAVE = "{tool}: not checked - it needs your leave once ({why})"
NO_FILES = "tsc: not checked - its tsconfig names no files (references)"
COMPOSITE = "tsc: not checked - its tsconfig is composite: tsc would write its build info"
NO_TSCONFIG = "tsc: not checked - its tsconfig.json could not be read"
PAST = "past the {seconds} s of Code style and types"
NO_ANSWER = "Code style not checked: the Orchestrator's answer is not on record"
NOT_JUDGED = "{tool}: {n} problems not judged - too large to compare in time: {paths}"
CHECKED_NONE = "{tool}: not checked - it found none of the turn's files to check ({said})"
IGNORED = "{tool}: {n} of the turn's files not checked - its settings leave them out"
SETTINGS_CHANGED = "{tool}'s settings changed this turn ({path}) - the check runs by them"


class Run(NamedTuple):
    """One command of a tool: its line, the folder it runs in (from the root, "." the root), and
    the turn's files it reads (from the root)."""

    tool: str
    command: str
    cwd: str
    files: tuple[str, ...]


def _read(path: Path) -> str:
    try:
        with path.open("rb") as file:
            return file.read(MOST_CONFIG).decode("utf-8", "replace")
    except OSError:
        return ""


def _has_table(path: Path, table: str) -> bool:
    """Whether a TOML or INI file has `[table]` (or a table under it)."""
    return bool(re.search(rf"(?m)^[ \t]*\[{re.escape(table)}[\].]", _read(path)))


def _ruff_set(folder: Path) -> bool:
    return (
        (folder / "ruff.toml").is_file()
        or (folder / ".ruff.toml").is_file()
        or _has_table(folder / "pyproject.toml", "tool.ruff")
    )


def _mypy_set(folder: Path) -> bool:
    return (
        (folder / "mypy.ini").is_file()
        or (folder / ".mypy.ini").is_file()
        or _has_table(folder / "pyproject.toml", "tool.mypy")
        or _has_table(folder / "setup.cfg", "mypy")
    )


def _venv(root: Path, tool: str) -> str | None:
    """The project's own `.venv` program, as a command line names it from the root."""
    rel = f".venv/Scripts/{tool}.exe" if sys.platform == "win32" else f".venv/bin/{tool}"
    return rel if (root / rel).is_file() else None


def _node(home: Path, tool: str) -> str | None:
    """The folder's own `node_modules/.bin` program (on Windows its .cmd: PowerShell may refuse a
    .ps1 and would open the bare file with another program), as named from that folder."""
    rel = (
        f"node_modules/.bin/{tool}.cmd" if sys.platform == "win32" else f"node_modules/.bin/{tool}"
    )
    return rel if (home / rel).is_file() else None


def _homes(root: Path, rel: str) -> Iterable[str]:
    """The folders from a file's own up to the root, as paths from the root ("" the root)."""
    for parent in PurePosixPath(rel).parents:
        yield "" if str(parent) == "." else str(parent)


def _home(root: Path, rel: str, found) -> str | None:
    return next((home for home in _homes(root, rel) if found(root / home)), None)


def _line(program: str, words: str, files: Iterable[str]) -> str:
    return " ".join([program, words, *(f"./{one}" for one in files)]).strip()


def _capped(tool: str, files: list[str]) -> tuple[list[str], list[str]]:
    more = len(files) - MOST_FILES
    return files[:MOST_FILES], (
        [TOO_MANY.format(tool=tool, n=more, most=MOST_FILES)] if more > 0 else []
    )


def configured(root: Path, paths: list[str]) -> bool:
    """Whether a tool is set up for any of these files - else the kind says nothing at all."""
    py = [one for one in paths if one.casefold().endswith(PY)]
    js = [one for one in paths if one.casefold().endswith(JS)]
    return (
        any(_home(root, one, _ruff_set) is not None for one in py)
        or (bool(py) and _mypy_set(root))
        or any(_home(root, one, _eslint_set) is not None for one in js)
        or any(
            _home(root, one, lambda at: (at / "tsconfig.json").is_file()) is not None
            for one in js
            if one.casefold().endswith(TS)
        )
    )


def _eslint_set(folder: Path) -> bool:
    return any((folder / one).is_file() for one in _ESLINT_CONFIGS)


def planned(root: Path, paths: list[str]) -> tuple[list[Run], list[str]]:
    """The commands for the turn's `paths` (from the root), and what is said instead of one: a
    tool set up but not installed, a name not put in a command line, more files than a run reads.
    ruff and mypy run at the root with the root's `.venv` (ruff: else one on PATH; mypy: its
    settings at the root) - eslint and tsc in the nearest folder up from a file with their
    settings and their own `node_modules/.bin`. What they would write goes nowhere but the work's
    folder: mypy's cache in its `.mypy_cache`, tsc not incremental (`_tsconfig_says`).
    shortcut: mypy's settings only at the root; a `.venv` only at the root, not `venv/`; eslint's
    settings in package.json are not looked for - add them if a project is met with them.
    shortcut: mypy's cache is put in the folder by `--cache-dir` - what `--no-incremental` alone
    writes is not measured here (no mypy on this machine)."""
    odd = [one for one in paths if not _PLAIN.fullmatch(one)]
    paths = [one for one in paths if _PLAIN.fullmatch(one)]
    notes = []
    if odd:
        notes.append(NOT_PLAIN.format(named=", ".join(odd[:5]) + (" …" if len(odd) > 5 else "")))
    py = [one for one in paths if one.casefold().endswith(PY)]
    runs: list[Run] = []
    for tool, words, ours in (
        ("ruff", "check --no-cache --output-format=concise", [
            one for one in py if _home(root, one, _ruff_set) is not None
        ]),
        ("mypy", "--no-error-summary --no-pretty --cache-dir=.mypy_cache", (
            py if _mypy_set(root) else []
        )),
    ):  # fmt: skip
        if not ours:
            continue
        program = _venv(root, tool) or ("ruff" if tool == "ruff" and _on_path("ruff") else None)
        if program is None:
            notes.append(NOT_INSTALLED.format(tool=tool))
            continue
        files, more = _capped(tool, ours)
        runs.append(Run(tool, _line(program, words, files), ".", tuple(files)))
        notes += more
    for tool, words, set_up, kinds in (
        ("eslint", "--format stylish --no-color", _eslint_set, JS),
        ("tsc", "--noEmit --pretty false --incremental false -p tsconfig.json", _tsconfig, TS),
    ):
        _node_runs(root, paths, (tool, words, set_up, kinds), runs, notes)
    return runs, notes


def _tsconfig(folder: Path) -> bool:
    return (folder / "tsconfig.json").is_file()


def _node_runs(root: Path, paths: list[str], how: tuple, runs: list[Run], notes: list[str]) -> None:
    """`planned`'s eslint or tsc (`how`: its name, its words, where it is set up, the endings it
    reads): one run in each nearest folder with its settings and its program."""
    tool, words, set_up, kinds = how
    by_home: dict[str, list[str]] = {}
    for one in paths:
        if one.casefold().endswith(kinds) and (home := _home(root, one, set_up)) is not None:
            by_home.setdefault(home, []).append(one)
    for home, ours in by_home.items():
        program = _node(root / home, tool)
        if program is None:
            notes.append(NOT_INSTALLED.format(tool=tool))
            continue
        if tool == "tsc" and (why := _tsconfig_says(root / home)):
            notes.append(why)
            continue
        files, more = _capped(tool, ours)
        inside = [str(PurePosixPath(one).relative_to(home or ".")) for one in files]
        line = _line(program, words, inside if tool == "eslint" else [])
        runs.append(Run(tool, line, home or ".", tuple(files)))
        notes += more


def _tsconfig_says(folder: Path) -> str | None:
    """Why tsc is not run on this folder's tsconfig.json - None: it checks files and writes
    nothing. One that names no files (a solution's `files: []` with its `references`, as
    create-vite writes it) checks nothing: never a pass for that. A composite one makes tsc write
    its build info whatever it is told (tsc 5.9, measured: `--incremental false` is refused there,
    exit 2, and the file is written all the same). One that cannot be read is said too.
    shortcut: this file alone, not what it `extends` - a base that is composite is not seen; read
    the chain if a project is met with one."""
    try:
        found, said = _json(_read(folder / "tsconfig.json"), "tsconfig.json")
    except WorkspaceError:
        return NO_TSCONFIG
    if said is not None or not isinstance(found, dict):
        return NO_TSCONFIG
    options = found.get("compilerOptions")
    if isinstance(options, dict) and options.get("composite") is True:
        return COMPOSITE
    return NO_FILES if found.get("files") == [] and "include" not in found else None


def _real(path: Path) -> str:
    return os.path.normcase(os.path.realpath(path)).casefold()


def _within(path: str, folder: str) -> bool:
    return path == folder or path.startswith(folder.rstrip("\\/") + os.sep)


def planted(work: Path, project: Path, run: Run, written: Iterable[str]) -> str | None:
    """B1: why `run`'s program is not run - None: it may be. Its real place is in neither the
    work's folder nor the project (a link leading out: a copy's `node_modules` and `.venv` are
    links into the project, so both are its places); or a file the turn wrote (`written`, from the
    root) is that program, or in the folder it is installed in (`wrote_program`): a program
    planted by the turn, whatever case its folder was written in (Windows' and macOS's file
    systems ignore it) and through any link; or (W1) a `node.cmd`, a `python.exe` - a name a shim
    runs bare - in the folder it runs in. By real paths, casefolded on every system. A program on
    PATH (ruff's) is no file of the project's.
    shortcut: what the turn wrote on record only - a file a command made unrecorded is not seen;
    `proof.unrecorded` says a turn had such a command."""
    written = list(written)
    here = _real(work / run.cwd)
    for rel in written:
        stem, ext = os.path.splitext(PurePosixPath(rel).name.casefold())
        if stem in _BARE and ext in RUNNABLE and _real((work / rel).parent) == here:
            return WROTE_BARE.format(name=PurePosixPath(rel).name)
    program = run.command.split()[0]
    if "/" not in program:
        return None
    if not any(_within(_real(work / run.cwd / program), _real(root)) for root in (work, project)):
        return OUTSIDE.format(program=program)
    place = wrote_program(work, run.cwd, program, written)
    return WROTE_IT.format(folder=place) if place else None


# The folders a tool's program is installed in: an agent's write under one is a program planted.
INSTALLS = ("node_modules", ".venv", "site-packages")
# W1: the names a program's shim runs bare (npm's `.cmd` runs `node`) - cmd.exe looked for them
# in the folder it runs in first (`host.no_cwd_search` stops that where KOLONİ starts it) -, and
# the endings Windows runs a file by (PATHEXT's, and none).
_BARE = ("node", "python", "python3", "pythonw", "py")
RUNNABLE = (
    *("", ".exe", ".cmd", ".bat", ".com", ".ps1", ".vbs", ".vbe", ".js", ".jse", ".wsf", ".wsh"),
    ".msc",
)


def wrote_program(work: Path, cwd: str, program: str, written: Iterable[str]) -> str | None:
    """B1, W2: where a file of `written` (from the work's root) plants `program`, named by its path
    and run in `cwd` - said from the root: the install folder it is in (the first of its folders
    named in INSTALLS: what its `.cmd` shim runs is there too), else the program itself, written
    as it is named or as a file Windows runs by that name (`check.cmd` for `check`). None: no
    such write. By real paths, casefolded, through any link."""
    parts = PurePosixPath(program.replace("\\", "/")).parts
    at = next((n for n, part in enumerate(parts) if part.casefold() in INSTALLS), None)
    named = PurePosixPath(*(parts if at is None else parts[: at + 1]))
    real, place = _real(work / cwd / str(named)), PurePosixPath(cwd, named)
    for rel in written:
        mine = _real(work / rel)
        stem, ext = os.path.splitext(mine)
        if (
            _within(mine, real)
            if at is not None
            else mine == real or (stem == real and ext in RUNNABLE)
        ):
            return place.as_posix()
    return None


def still_written(work: Path, records: Iterable[tuple[str, str]]) -> list[str]:
    """Of an earlier turn's writes under an install folder (`records`: path from the root, the
    digest of what the agent wrote), those whose file still holds it in the work's folder - a
    program planted then and run by a rule now (B1 across turns: an Always rule matches by its
    text, in any folder). One the user's install wrote over since is theirs again."""
    held = []
    for rel, digest in records:
        try:
            text = (work / rel).read_bytes().decode("utf-8", "replace")
        except OSError:
            continue
        if digest in (sha256_text(text), sha256_text(text.replace("\r\n", "\n"))):
            held.append(rel)
    return held


def _on_path(tool: str) -> bool:
    return shutil.which(tool) is not None


# A check line's commands, and the words before a tool's own in one: a runner of the project's
# installs (`uv run ruff`, `npx tsc`, `python -m mypy`), its options, a variable set for it.
_COMMANDS = re.compile(r"&&|\|\||[;|\n]")
_RUNNERS = frozenset(
    {"uv", "uvx", "run", "npx", "bunx", "pnpx", "pnpm", "yarn", "npm", "exec", "poetry", "pdm"}
    | {"hatch", "pipenv", "python", "python3", "py", "-m", "--", "&"}
)
_ASKS_ONLY = frozenset({"--version", "-V", "--help", "-h"})
_NOT_CHECK = frozenset({"format", "rule", "config", "linter", "clean", "version", "help"})


def runs_tool(line: str, tool: str) -> bool:
    """Whether a check line of the project's (its CI's, its check command) does what this tool's
    run does: the tool as a command's program, after a runner (`uv run`, `npx`, `python -m`) -
    never a word of another's (`pip install ruff`, `pytest -k mypy`), nor its `--version`;
    `ruff format --check` is not `ruff check`. Unsure: no - KOLONİ then runs its own."""
    return any(_runs(command.split(), tool) for command in _COMMANDS.split(line))


def _runs(words: list[str], tool: str) -> bool:
    at = 0
    while at < len(words) and _program(words[at]) != tool:
        if not (words[at] in _RUNNERS or words[at].startswith("-") or "=" in words[at]):
            return False
        at += 1
    rest = words[at + 1 :]
    if at == len(words) or _ASKS_ONLY & {*rest} or (tool in ("eslint", "tsc") and "-v" in rest):
        return False
    first = next((word for word in rest if not word.startswith("-")), None)
    return tool != "ruff" or (first is not None and first not in _NOT_CHECK)


# --- what a tool said ----------------------------------------------------------------------------

# ruff (concise) and mypy: `path:line:col: said`, `path:line: said`; tsc: `path(line,col): said`;
# eslint (stylish): the file on a line of its own, each problem under it, indented. (B2: no lazy
# part before an optional one - mypy's `[code]` is read off the end by `_mypy`; each line is cut
# at MOST_LINE first.)
_COLON = re.compile(r"^(?P<path>[^\n]+?):(?P<line>\d+):(?:\d+:)?\s+(?P<said>\S.*)$")
_TSC = re.compile(r"^(?P<path>[^\n(]+?)\((?P<line>\d+),\d+\):\s+(?P<said>\S.*)$")
_ESLINT = re.compile(r"^\s+(?P<line>\d+):\d+\s+(?P<said>\S.*)$")
_RUFF = re.compile(r"^(?P<code>[A-Z]+\d+)\s+(?:\[\*\]\s+)?(?P<message>.+)$")
# (W3: a file it cannot parse - `invalid-syntax:` now, `SyntaxError:` before ruff 0.6)
_RUFF_SYNTAX = re.compile(r"^(?:invalid-syntax|SyntaxError):\s*(?P<message>\S.*)$")
_MYPY = re.compile(r"^error:\s+(?P<message>\S.*)$")
_MYPY_CODE = re.compile(r"[\w-]+")
_TS = re.compile(r"^(?P<level>error|warning)\s+(?P<code>TS\d+):\s+(?P<message>.+)$")


class Problem(NamedTuple):
    path: str  # from the root
    line: int
    said: str  # "ruff F401 - `os` imported but unused"
    error: bool  # (a warning is said, never failed)


def _one_line(text: str) -> str:
    said = " ".join(text.split())
    return said if len(said) <= MOST_SAID else said[: MOST_SAID - 1] + "…"


def _said(tool: str, said: str) -> tuple[str, bool] | None:
    """A tool's words on one problem, as said here ("ruff F401 - ..."), and whether it is an
    error; None: not a problem's line (a note of mypy's, a summary)."""
    if tool == "ruff":
        if found := _RUFF.match(said):
            return f"ruff {found['code']} - {found['message']}", True
        found = _RUFF_SYNTAX.match(said)
        return (f"ruff invalid-syntax - {found['message']}", True) if found else None
    if tool == "mypy":
        found = _MYPY.match(said)
        return _mypy(found["message"]) if found else None
    if tool == "tsc":
        found = _TS.match(said)
        return (
            (f"tsc {found['code']} - {found['message']}", found["level"] == "error")
            if found
            else None
        )
    # (eslint: "error  'x' is never used  no-unused-vars" - its rule last, after two spaces)
    level, _gap, rest = said.partition(" ")
    if level not in ("error", "warning"):
        return None
    message, _sep, rule = rest.strip().rpartition("  ")
    message, rule = (message, rule) if message else (rule, "")
    return f"eslint{f' {rule.strip()}' if rule else ''} - {message.strip()}", level == "error"


def _mypy(message: str) -> tuple[str, bool]:
    """mypy's error, its `[code]` read off the end (`... [attr-defined]`) - by `rpartition`, never
    a lazy match before an optional group (B2: quadratic over a long run of spaces)."""
    head, sep, tail = message.rstrip().rpartition(" [")
    if sep and tail.endswith("]") and _MYPY_CODE.fullmatch(tail[:-1]):
        return f"mypy {tail[:-1]} - {head.rstrip()}", True
    return f"mypy - {message.rstrip()}", True


def _from_root(root: Path, cwd: Path, path: str) -> str | None:
    """A tool's path as a path from the root (None: outside it) - by its real place, any case on
    Windows."""
    full = Path(os.path.realpath(cwd / path.strip()))
    base = Path(os.path.realpath(root))
    try:
        rel = full.relative_to(base)
    except ValueError:
        if sys.platform != "win32":
            return None
        try:
            rel = Path(str(full).casefold()).relative_to(str(base).casefold())
        except ValueError:
            return None
    return rel.as_posix()


def problems(tool: str, output: str, root: Path, cwd: str) -> list[Problem]:
    """What `tool` said, line by line - whatever else its output holds (a warning, a summary, its
    colour codes) - each line read to MOST_LINE."""
    folder, found, current = root / cwd, [], None
    for raw in _COLOUR.sub("", output).splitlines():
        text = raw.rstrip("\r")[:MOST_LINE]
        if tool == "eslint":
            if (at := _ESLINT.match(text)) and current is not None:
                said = _said(tool, at["said"])
                if said is not None:
                    found.append(Problem(current, int(at["line"]), *said))
            elif text.strip() and not text[0].isspace() and not text.startswith("✖"):
                current = _from_root(root, folder, text)
            continue
        at = (_TSC if tool == "tsc" else _COLON).match(text)
        said = _said(tool, at["said"]) if at else None
        rel = _from_root(root, folder, at["path"]) if at else None
        if at and said is not None and rel is not None:
            found.append(Problem(rel, int(at["line"]), *said))
    return found


class Changed:
    """The lines the turn added or changed in each file it changed (`proof.changed_lines`), each
    file's worked out once and only when asked - for a file a tool said a problem in (W4: a
    large file's diff is long work) - while `until` (`time.monotonic`'s) is not past. None: not
    judged, too large to compare in time."""

    def __init__(self, texts: Mapping[str, tuple[str, str]], until: float) -> None:
        self.texts, self.until = texts, until
        self._lines: dict[str, frozenset[int] | None] = {}

    def get(self, path: str, default: Iterable[int] = ()) -> Iterable[int] | None:
        if path not in self.texts:
            return default
        if path not in self._lines:
            said = proof.changed_lines(*self.texts[path]) if time.monotonic() < self.until else None
            self._lines[path] = None if said is None else frozenset(said)
        return self._lines[path]


# ruff's word that it found nothing to check (its settings left the files out: `force-exclude`)
_NONE_FOUND = re.compile(r"^warning: (No Python files found[^\n]*)", re.M)


def rows_of(
    run: Run,
    code: int | None,
    output: str,
    root: Path,
    added: Changed | Mapping[str, Iterable[int] | None],
) -> list[Row]:
    """A run's lines: each error on a line the turn added or changed in a file it changed is
    failed (at most MOST_FAILED, the rest counted); its warnings there one note, what is on other
    lines another, what is in a file too large to compare (`Changed`) another; none, a pass. An
    exit with nothing read from its output is said, never failed; nor is a run that checked none
    of the files (W5) a pass."""
    if code is None:
        return [row(STYLE, "note", UNREAD.format(tool=run.tool, why="it did not end"))]
    if none := _NONE_FOUND.search(_COLOUR.sub("", output)[: MOST_LINE * 8]):
        said = _one_line(CHECKED_NONE.format(tool=run.tool, said=none[1]))
        return [row(STYLE, "note", said)]
    found = problems(run.tool, output, root, run.cwd)
    ignored = sum(one.said.startswith("eslint - File ignored") for one in found)
    found = [one for one in found if not one.said.startswith("eslint - File ignored")]
    if code != 0 and not found:
        return [row(STYLE, "note", UNREAD.format(tool=run.tool, why=f"exit {code}"))]
    ours, unjudged = [], Counter[str]()
    for one in found:
        if (lines := added.get(one.path, ())) is None:
            unjudged[one.path] += 1
        elif one.line in lines:
            ours.append(one)
    mine = [one for one in ours if one.error]
    rows = [
        row(STYLE, "failed", _one_line(f"{one.path}:{one.line}: {one.said}"))
        for one in mine[:MOST_FAILED]
    ]
    if len(mine) > MOST_FAILED:
        rows.append(row(STYLE, "note", MORE.format(tool=run.tool, n=len(mine) - MOST_FAILED)))
    if warned := len(ours) - len(mine):
        rows.append(row(STYLE, "note", WARNED.format(tool=run.tool, n=warned)))
    if elsewhere := len(found) - len(ours) - sum(unjudged.values()):
        rows.append(row(STYLE, "note", ELSEWHERE.format(tool=run.tool, n=elsewhere)))
    if unjudged:
        paths = ", ".join(sorted(unjudged))
        said = NOT_JUDGED.format(tool=run.tool, n=sum(unjudged.values()), paths=paths)
        rows.append(row(STYLE, "note", _one_line(said)))
    if ignored:
        rows.append(row(STYLE, "note", IGNORED.format(tool=run.tool, n=ignored)))
    return rows or [row(STYLE, "passed", CLEAN.format(tool=run.tool, n=len(run.files)))]


# W5: a tool's settings files - one the turn changed where the run is or above it (or above a
# file it checks) changes what it checks: said beside what it found. In a file other tools
# share, its own part: pyproject's [tool.ruff] and [tool.ruff.*] tables, setup.cfg's [mypy].
# shortcut: by its tables' lines - a dotted key outside them (`tool.ruff.x = 1` under [tool])
# is not seen; read the TOML if such a key is met.
_SETTINGS = {
    "ruff": ("ruff.toml", ".ruff.toml", "pyproject.toml"),
    "mypy": ("mypy.ini", ".mypy.ini", "pyproject.toml", "setup.cfg"),
    "eslint": (*_ESLINT_CONFIGS, "package.json"),
    "tsc": ("tsconfig.json", "jsconfig.json"),
}
_PART = {"pyproject.toml": "tool.{tool}", "setup.cfg": "{tool}", "package.json": "eslintConfig"}


def settings_changed(
    run: Run, texts: Mapping[str, tuple[str, str]], gone: Iterable[str] = ()
) -> str | None:
    """W5: the note that `run`'s tool's settings changed this turn (`texts`: each file the turn
    changed, its first before and last after; `gone`: those it deleted) - None: they did not."""
    places = [PurePosixPath(run.cwd), *(PurePosixPath(one).parent for one in run.files)]
    places = [PurePosixPath(place.as_posix().casefold()) for place in places]
    for path in sorted({*texts, *gone}):
        named = PurePosixPath(path.casefold())
        if not (
            named.name in _SETTINGS[run.tool]
            or run.tool == "tsc"
            and named.name.startswith("tsconfig.")
            and named.suffix == ".json"
        ):
            continue
        if not any(named.parent == place or named.parent in place.parents for place in places):
            continue
        part = _PART.get(named.name, "").format(tool=run.tool)
        if part and path in texts and _part(texts[path][0], part) == _part(texts[path][1], part):
            continue
        return SETTINGS_CHANGED.format(tool=run.tool, path=path)
    return None


def _part(text: str, name: str) -> list[str]:
    """The lines of `text`'s [name] and [name.*] tables, [name-*] sections (INI: `[mypy-x.*]`) -
    or, in JSON, every line where `name` is a key's (package.json's `eslintConfig`: all of it
    from there on, its end unread)."""
    out, inside = [], False
    for line in text.splitlines():
        head = line.strip()
        if head.startswith("["):
            title = head.lstrip("[").split("]")[0].strip()
            inside = title == name or title.startswith((f"{name}.", f"{name}-"))
        elif f'"{name}"' in head:
            inside = True
        if inside:
            out.append(line)
    return out
