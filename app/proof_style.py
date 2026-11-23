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
from collections.abc import Iterable, Mapping
from pathlib import Path, PurePosixPath
from typing import NamedTuple

from app.proof import Row, row

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
# A path put in a command line as it is - no quoting needed in PowerShell or sh; another is said.
_PLAIN = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_./@+-]*")
_ESLINT_CONFIGS = (
    *(f"eslint.config.{one}" for one in ("js", "mjs", "cjs", "ts", "mts", "cts")),
    *(f".eslintrc{one}" for one in ("", ".js", ".cjs", ".json", ".yml", ".yaml")),
)
NOT_INSTALLED = "{tool}: not checked - set up in this project, not installed here"
NOT_PLAIN = "Code style not checked: {named} - a name KOLONİ does not put in a command line"
TOO_MANY = "{tool}: {n} more files not checked - at most {most} a run"
CLEAN = "{tool}: no problems on the lines this turn changed ({n} files)"
ELSEWHERE = "{tool}: {n} problems on lines this turn did not change"
MORE = "{tool}: +{n} more problems on the lines this turn changed"
UNREAD = "{tool}: not checked - its output was not read ({why})"
BY_THEIRS = (
    "{tool}: not run here - the project's own check runs it (its CI lines, its test command)"
)
DECLINED = "declined on its card this turn"
WROTE_IT = "this turn wrote in {folder}: no install of the project's"
NEEDS_LEAVE = "{tool}: not checked - it needs your leave once ({why})"
PAST = "past the {seconds} s of Code style and types"
NO_ANSWER = "Code style not checked: the Orchestrator's answer is not on record"


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
    settings and their own `node_modules/.bin`.
    shortcut: mypy's settings only at the root; a `.venv` only at the root, not `venv/`; eslint's
    settings in package.json are not looked for - add them if a project is met with them."""
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
        ("mypy", "--no-error-summary --no-pretty", py if _mypy_set(root) else []),
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
        ("tsc", "--noEmit --pretty false -p tsconfig.json", None, TS),
    ):
        by_home: dict[str, list[str]] = {}
        for one in paths:
            if one.casefold().endswith(kinds):
                found = set_up or (lambda at: (at / "tsconfig.json").is_file())
                home = _home(root, one, found)
                if home is not None:
                    by_home.setdefault(home, []).append(one)
        for home, ours in by_home.items():
            program = _node(root / home, tool)
            if program is None:
                notes.append(NOT_INSTALLED.format(tool=tool))
                continue
            files, more = _capped(tool, ours)
            inside = [str(PurePosixPath(one).relative_to(home or ".")) for one in files]
            line = _line(program, words, inside if tool == "eslint" else [])
            runs.append(Run(tool, line, home or ".", tuple(files)))
            notes += more
    return runs, notes


def _on_path(tool: str) -> bool:
    return shutil.which(tool) is not None


def runs_tool(line: str, tool: str) -> bool:
    """Whether a check line of the project's (its CI's, its check command) does what this tool's
    run does - `ruff format --check` is not `ruff check`."""
    words = line.split()
    if tool == "ruff":
        return "ruff" in words and "format" not in words
    return any(word == tool or word.endswith(f"/{tool}") for word in words)


# --- what a tool said ----------------------------------------------------------------------------

# ruff (concise) and mypy: `path:line:col: said`, `path:line: said`; tsc: `path(line,col): said`;
# eslint (stylish): the file on a line of its own, each problem under it, indented.
_COLON = re.compile(r"^(?P<path>[^\n]+?):(?P<line>\d+):(?:\d+:)?\s+(?P<said>\S.*)$")
_TSC = re.compile(r"^(?P<path>[^\n(]+?)\((?P<line>\d+),\d+\):\s+(?P<said>\S.*)$")
_ESLINT = re.compile(r"^\s+(?P<line>\d+):\d+\s+(?P<said>\S.*)$")
_RUFF = re.compile(r"^(?P<code>[A-Z]+\d+)\s+(?:\[\*\]\s+)?(?P<message>.+)$")
_MYPY = re.compile(r"^error:\s+(?P<message>.+?)(?:\s+\[(?P<code>[\w-]+)\])?$")
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
        found = _RUFF.match(said)
        return (f"ruff {found['code']} - {found['message']}", True) if found else None
    if tool == "mypy":
        found = _MYPY.match(said)
        code = f" {found['code']}" if found and found["code"] else ""
        return (f"mypy{code} - {found['message']}", True) if found else None
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
    """What `tool` said, line by line - whatever else its output holds (a warning, a summary)."""
    folder, found, current = root / cwd, [], None
    for raw in output.splitlines():
        text = raw.rstrip("\r")
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


def rows_of(
    run: Run, code: int | None, output: str, root: Path, added: Mapping[str, Iterable[int]]
) -> list[Row]:
    """A run's lines: each error on a line the turn added or changed in a file it changed is
    failed (at most MOST_FAILED, the rest counted); the others one note; none, a pass. An exit
    with nothing read from its output is said, never failed."""
    found = problems(run.tool, output, root, run.cwd)
    if code is None:
        return [row(STYLE, "note", UNREAD.format(tool=run.tool, why="it did not end"))]
    if code != 0 and not found:
        return [row(STYLE, "note", UNREAD.format(tool=run.tool, why=f"exit {code}"))]
    lines = {path: set(numbers) for path, numbers in added.items()}
    mine = [one for one in found if one.error and one.line in lines.get(one.path, ())]
    rows = [
        row(STYLE, "failed", _one_line(f"{one.path}:{one.line}: {one.said}"))
        for one in mine[:MOST_FAILED]
    ]
    if len(mine) > MOST_FAILED:
        rows.append(row(STYLE, "note", MORE.format(tool=run.tool, n=len(mine) - MOST_FAILED)))
    if elsewhere := len(found) - len(mine):
        rows.append(row(STYLE, "note", ELSEWHERE.format(tool=run.tool, n=elsewhere)))
    return rows or [row(STYLE, "passed", CLEAN.format(tool=run.tool, n=len(run.files)))]
