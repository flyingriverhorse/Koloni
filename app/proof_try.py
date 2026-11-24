"""Kanıtlı bitiş S5b (plan decision 14c): what the live try at a turn's end runs - read off the
project's own files, never a model's word: the command-line tools the turn changed (a script in
`bin/`, a `bin` of package.json, a console script of pyproject.toml) that read their arguments,
under plain names, each asked for its `--help` alone; and the dev server that serves its screens
(package.json's `dev`, else `start`).
Each file is read inside the project only (`Workspace`), with what is read capped."""

import json
import posixpath
import re
import tomllib
from pathlib import Path, PurePosixPath

from app.workspace import Workspace, WorkspaceError

MOST_BYTES = 2**20  # of a package.json, a pyproject.toml or a script read
MOST_TOOLS = 2  # tools tried a turn
# A script in bin/ by its suffix, else by its first line's interpreter.
BY_SUFFIX = {".py": "python", ".js": "node", ".mjs": "node", ".cjs": "node", ".sh": "sh"}
SHEBANG = {"python": "python", "python3": "python", "node": "node", "sh": "sh", "bash": "sh"}
NO_MAIN = 'its module {module} has no `if __name__ == "__main__"` to run'
UNUSUAL = "an unusual name - KOLONİ runs only plain names"
NO_ARGUMENTS = "it does not answer --help - asked, it would do its work"
_PATH = re.compile(r"[A-Za-z0-9_./-]{1,200}")
_MODULE = re.compile(r"[A-Za-z0-9_.]{1,200}")
# What answers `--help` by itself, by runner (review of S5b, round 2: a word in a comment, a
# default for `$1` or a variable called `arg` is no such thing - a deploy script ran with `--help`
# as its target): Python's parsers imported, Node's required or imported, sh's own case for it.
_PARSERS_PY = "argparse|click|typer|docopt|fire|optparse"
_PARSERS_JS = "commander|yargs|meow|cac"
ANSWERS_HELP = {
    "python": re.compile(
        rf"^[ \t]*(?:from[ \t]+(?:{_PARSERS_PY})\b|import[ \t]+(?:[\w.]+[ \t]*,[ \t]*)*"
        rf"(?:{_PARSERS_PY})\b)",
        re.MULTILINE,
    ),
    "node": re.compile(
        rf"""\brequire\([ \t]*['"](?:{_PARSERS_JS})(?:/[\w./-]*)?['"][ \t]*\)|"""
        rf"""^[ \t]*import\b[^\n]*?['"](?:{_PARSERS_JS})(?:/[\w./-]*)?['"]""",
        re.MULTILINE,
    ),
    "sh": re.compile(r"""(?:-h[ \t]*\|[ \t]*)?--help[ \t]*\)|['"]--help['"]"""),
}
# A whole line that is a comment, by runner; and sh's comment after a word.
_COMMENT = {
    "python": re.compile(r"^[ \t]*#[^\n]*", re.MULTILINE),
    "node": re.compile(r"^[ \t]*(?://|/?\*)[^\n]*", re.MULTILINE),
    "sh": re.compile(r"(?:^|[ \t])#[^\n]*", re.MULTILINE),
}


def _read(ws: Workspace, rel: str) -> str | None:
    """A file of the project as text; None where it is not there, out of it, or too big."""
    try:
        path = ws.resolve(rel)
        if not ws.is_own(path) or not path.is_file() or path.stat().st_size > MOST_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except (OSError, WorkspaceError):
        return None


def _package(ws: Workspace, folder: str = ".") -> dict:
    text = _read(ws, posixpath.join(folder, "package.json"))
    try:
        found = json.loads(text) if text else {}
    except (ValueError, RecursionError):
        return {}
    return found if isinstance(found, dict) else {}


def _shebang(ws: Workspace, rel: str) -> str | None:
    first = (_read(ws, rel) or "").split("\n", 1)[0]
    if not first.startswith("#!"):
        return None
    words = first[2:].split()
    name = PurePosixPath(
        words[1]
        if words and words[0].endswith("/env") and len(words) > 1
        else (words[0] if words else "")
    ).name
    return SHEBANG.get(name)


def _scripts(ws: Workspace) -> dict[str, str]:
    text = _read(ws, "pyproject.toml")
    try:
        found = tomllib.loads(text).get("project", {}).get("scripts", {}) if text else {}
    except tomllib.TOMLDecodeError:
        return {}
    return {str(name): str(spec) for name, spec in found.items()} if isinstance(found, dict) else {}


def _plain(path: str, module: bool = False) -> bool:
    """Whether a name may go on a line KOLONİ runs (S7's `plain_id` rule): plain characters
    (a module's: no `/`), relative - no part that starts with `-` (an option), no `..` part. A
    name the agent chose is never a way to a command of its own under KOLONİ's call (review of
    S5b: `bin/$(...).py` ran)."""
    parts = path.split("." if module else "/")
    return (
        bool((_MODULE if module else _PATH).fullmatch(path))
        and not path.startswith("/")
        and (".." not in parts and not any(part.startswith("-") for part in parts))
    )


def _answers_help(text: str, runner: str) -> bool:
    """Whether a script answers `--help` itself - a parser it imports (Python, Node), or its own
    case for it (sh) - read outside its comments: so that `--help` asks it for its help, never
    to do its work (a deploy or a sync script that ignores it is never run: review of S5b)."""
    kind = runner if runner in ANSWERS_HELP else "python"
    return bool(ANSWERS_HELP[kind].search(_COMMENT[kind].sub("", text)))


def _quoted(path: str) -> str:
    """In single quotes on both platforms: literal to sh and to PowerShell alike (a plain name
    holds no quote: `_plain`)."""
    return f"'{path}'"


def cli_tools(root: Path | Workspace, changed: list[str]) -> list[tuple[str, str | None]]:
    """The command-line tools the turn changed, each as (the line that asks it for its help -
    `--help` is added by the caller - None), or (its name, why it is not tried): a name that is
    not plain, a script that reads no arguments, a console script whose module does not run
    itself (`__main__`). At most MOST_TOOLS."""
    ws = root if isinstance(root, Workspace) else Workspace(str(root))
    paths = {posixpath.normpath(one.replace("\\", "/")) for one in changed}
    found: list[tuple[str, str | None]] = []
    seen: set[str] = set()

    def tool(runner: str, path: str) -> None:
        seen.add(path)
        if not _plain(path):
            found.append((path, UNUSUAL))
        elif not _answers_help(_read(ws, path) or "", runner):
            found.append((path, NO_ARGUMENTS))
        else:
            found.append((f"{runner} {_quoted(path)}", None))

    for path in sorted(paths):
        if PurePosixPath(path).parent == PurePosixPath("bin"):
            runner = BY_SUFFIX.get(PurePosixPath(path).suffix) or _shebang(ws, path)
            if runner:
                tool(runner, path)
    bins = _package(ws).get("bin")
    for target in bins.values() if isinstance(bins, dict) else [bins] if bins else []:
        rel = posixpath.normpath(str(target))
        if rel in paths and rel not in seen:
            tool("node", rel)
    for name, spec in _scripts(ws).items():
        module = spec.split(":", 1)[0].strip()
        if not _plain(module, module=True):
            found.append((name, UNUSUAL))
            continue
        dotted = module.replace(".", "/")
        hit = next(
            (
                one
                for one in (
                    f"{dotted}.py",
                    f"src/{dotted}.py",
                    f"{dotted}/__main__.py",
                    f"src/{dotted}/__main__.py",
                )
                if one in paths
            ),
            None,
        )
        if hit is None:
            continue
        text = _read(ws, hit) or ""
        runs = hit.endswith("__main__.py") or ("__name__" in text and "__main__" in text)
        found.append(
            (name, NO_MAIN.format(module=module))
            if not runs
            else (
                (name, NO_ARGUMENTS)
                if not _answers_help(text, "python")
                else (f"python -m {module}", None)
            )
        )
    return found[:MOST_TOOLS]


def dev_command(root: Path | Workspace, changed: list[str]) -> tuple[str, str] | None:
    """The line that starts the dev server of the turn's screens, and its folder: package.json's
    `dev` (else `start`) script of the nearest folder above a changed screen, else of the root.
    shortcut: always npm's line - a pnpm or yarn project's scripts run under npm too; read the
    lockfile if a project is seen that does not."""
    ws = root if isinstance(root, Workspace) else Workspace(str(root))
    folders: list[str] = []
    for one in changed:
        for parent in PurePosixPath(one.replace("\\", "/")).parents:
            folder = str(parent)
            if folder not in folders:
                folders.append(folder)
    folders.sort(key=lambda folder: (-len(PurePosixPath(folder).parts), folder))
    for folder in [*(one for one in folders if one != "."), "."]:
        scripts = _package(ws, folder).get("scripts")
        if not isinstance(scripts, dict):
            continue
        if isinstance(scripts.get("dev"), str):
            return "npm run dev", folder
        if isinstance(scripts.get("start"), str):
            return "npm start", folder
    return None
