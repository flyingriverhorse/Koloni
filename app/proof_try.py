"""Kanıtlı bitiş S5b (plan decision 14c): what the live try at a turn's end runs - read off the
project's own files, never a model's word: the command-line tools the turn changed (a script in
`bin/`, a `bin` of package.json, a console script of pyproject.toml), each run once with `--help`
and once plain; and the dev server that serves its screens (package.json's `dev`, else `start`).
Each file is read inside the project only (`Workspace`), with what is read capped."""

import json
import posixpath
import tomllib
from pathlib import Path, PurePosixPath

from app.workspace import Workspace, WorkspaceError

MOST_BYTES = 2**20  # of a package.json, a pyproject.toml or a script read
MOST_TOOLS = 2  # tools tried a turn
# A script in bin/ by its suffix, else by its first line's interpreter.
BY_SUFFIX = {".py": "python", ".js": "node", ".mjs": "node", ".cjs": "node", ".sh": "sh"}
SHEBANG = {"python": "python", "python3": "python", "node": "node", "sh": "sh", "bash": "sh"}
NO_MAIN = 'its module {module} has no `if __name__ == "__main__"` to run'


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
    name = PurePosixPath(words[1] if words and words[0].endswith("/env") and len(words) > 1
                         else (words[0] if words else "")).name
    return SHEBANG.get(name)


def _scripts(ws: Workspace) -> dict[str, str]:
    text = _read(ws, "pyproject.toml")
    try:
        found = tomllib.loads(text).get("project", {}).get("scripts", {}) if text else {}
    except tomllib.TOMLDecodeError:
        return {}
    return {str(name): str(spec) for name, spec in found.items()} if isinstance(found, dict) else {}


def cli_tools(root: Path | Workspace, changed: list[str]) -> list[tuple[str, str | None]]:
    """The command-line tools the turn changed, each as (the line that runs it, None) - or
    (its name, why it is not tried). At most MOST_TOOLS. A console script of pyproject.toml is
    run as `python -m module` only where that module runs itself (`__main__`)."""
    ws = root if isinstance(root, Workspace) else Workspace(str(root))
    paths = {posixpath.normpath(one.replace("\\", "/")) for one in changed}
    found: list[tuple[str, str | None]] = []
    for path in sorted(paths):
        if PurePosixPath(path).parent == PurePosixPath("bin"):
            runner = BY_SUFFIX.get(PurePosixPath(path).suffix) or _shebang(ws, path)
            if runner:
                found.append((f"{runner} {path}", None))
    bins = _package(ws).get("bin")
    for target in (bins.values() if isinstance(bins, dict) else [bins] if bins else []):
        rel = posixpath.normpath(str(target))
        if rel in paths and not any(line.endswith(f" {rel}") for line, _why in found):
            found.append((f"node {rel}", None))
    for name, spec in _scripts(ws).items():
        module = spec.split(":", 1)[0].strip()
        dotted = module.replace(".", "/")
        hit = next((one for one in (f"{dotted}.py", f"src/{dotted}.py", f"{dotted}/__main__.py",
                                    f"src/{dotted}/__main__.py") if one in paths), None)
        if hit is None:
            continue
        text = _read(ws, hit) or ""
        runs = hit.endswith("__main__.py") or ("__name__" in text and "__main__" in text)
        found.append((f"python -m {module}", None) if runs else (
            name, NO_MAIN.format(module=module)))
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
