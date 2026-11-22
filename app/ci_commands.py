"""Kanıtlı bitiş S8 (plan decision 3), what needs no model: the lint, typecheck and test commands
a project's GitHub Actions workflows run (`.github/workflows/*.yml`), as the end check may run them
once the user approved the list - each line one plain command the CI runs, in its working
directory; never an e2e step, nor one with an expression, a secret or an install in it; and a
fingerprint of the workflow files: a change asks again. The files are repository text: read
bounded (their number, each one's size, regular files only), without YAML aliases, and a file
that breaks the parser is said, never raised."""

import hashlib
import json
import os
import re
import stat
from collections.abc import Iterator
from pathlib import Path, PurePosixPath
from typing import NamedTuple

import yaml

from app import ledger
from app.commands import is_plain

WORKFLOWS = ".github/workflows"
# Lint and typecheck commands, by their start; a test is `ledger.read_test`'s.
LINTS = re.compile(r"^(?:uv run |python -m |npx |pnpm |yarn |npm run )?"
                   r"(?:ruff\b|flake8\b|eslint\b|oxlint\b|lint\b|pylint\b|black --check\b)")
TYPECHECKS = re.compile(r"^(?:uv run |python -m |npx |pnpm |yarn |npm run )?"
                        r"(?:mypy\b|ty check\b|pyright\b|tsc\b|typecheck\b)")
E2E = re.compile(r"\b(?:playwright|cypress|e2e)\b", re.IGNORECASE)
INSTALL = re.compile(r"\b(?:pip install|npm ci|npm install|pnpm install|yarn install|uv sync|"
                     r"apt-get|brew install|poetry install)\b")
MOST_RUNS = 12
# What of the workflow folder is read: so many files, each at most so big, so much in all.
MOST_FILES = 50
MOST_BYTES = 256 * 1024
MOST_ALL = 1024 * 1024
# The shells a step's lines may run in (GitHub's default too): another (python, a template of
# its own) runs them as its own language.
SHELLS = frozenset({"bash", "sh", "pwsh", "powershell", "cmd"})
NOT_PLAIN = "not a plain command"


class CiRun(NamedTuple):
    """A command a workflow runs, the folder it runs in ("." the root), and its step's name."""
    command: str
    cwd: str
    step: str


class Found(NamedTuple):
    """The project's CI lines, what was left out and why, and the files' fingerprint - of the
    same bytes."""
    runs: list[CiRun]
    said: list[str]
    mark: str


class _Alias(yaml.YAMLError):
    pass


class _NoAliases(yaml.SafeLoader):
    """YAML without aliases: one alias may stand for millions of nodes (a billion laughs)."""

    def compose_node(self, parent, index):
        if self.check_event(yaml.AliasEvent):
            raise _Alias("aliases are not read")
        return super().compose_node(parent, index)


def kept(line: str) -> bool:
    """A line the end check may run as the CI does: one plain command (`commands.is_plain` - no
    chain, pipe, redirect or substitution) that lints, typechecks or tests."""
    return is_plain(line) and _checks(line)


def _checks(line: str) -> bool:
    return bool(LINTS.match(line) or TYPECHECKS.match(line) or ledger.read_test(line))


def _files(root: Path) -> Iterator[tuple[str, bytes | None, str]]:
    """Each workflow file by name: its bytes, or None and why it is not read (a link or no
    regular file, too big, past the count or the whole budget)."""
    try:
        paths = sorted((root / WORKFLOWS).glob("*.y*ml"))
    except OSError:
        return
    left = MOST_ALL
    for number, path in enumerate(paths):
        if number >= MOST_FILES:
            yield path.name, None, f"more than {MOST_FILES} workflow files"
            continue
        try:
            mode = os.lstat(path)
        except OSError:
            yield path.name, None, "it cannot be read"
            continue
        if not stat.S_ISREG(mode.st_mode):
            yield path.name, None, "not a regular file"
        elif mode.st_size > MOST_BYTES:
            yield path.name, None, f"over {MOST_BYTES // 1024} KB"
        elif mode.st_size > left:
            yield path.name, None, f"past {MOST_ALL // 1024} KB of workflows in all"
        else:
            try:
                with path.open("rb") as handle:  # (bounded: it may have changed since)
                    data = handle.read(MOST_BYTES + 1)
            except OSError:
                yield path.name, None, "it cannot be read"
                continue
            if len(data) > MOST_BYTES:
                yield path.name, None, f"over {MOST_BYTES // 1024} KB"
                continue
            left -= len(data)
            yield path.name, data, ""


def _mark(files: list[tuple[str, bytes | None, str]]) -> str:
    digest = hashlib.sha256()
    for name, data, why in files:
        digest.update(name.encode() + b"\0" + (data if data is not None else why.encode()) + b"\0")
    return digest.hexdigest()


def fingerprint(root: Path) -> str:
    """The workflow files as they are now: a change to any of them asks again."""
    return _mark(list(_files(root)))


NONE = _mark([])  # (no workflow file at all)


def offer_id(mark: str, runs: list[dict]) -> str:
    """An offer's own name: the files' fingerprint and the very lines it offers."""
    return hashlib.sha256(f"{mark}\0{json.dumps(runs, sort_keys=True)}".encode()).hexdigest()


def _text(node: object) -> str:
    return node if isinstance(node, str) else ""  # (never `str()` of a node: it may be huge)


def _run_defaults(node: object) -> dict:
    defaults = node.get("defaults") if isinstance(node, dict) else None
    run = defaults.get("run") if isinstance(defaults, dict) else None
    return run if isinstance(run, dict) else {}


def _steps(data: object) -> Iterator[tuple[dict, dict]]:
    """Each step of each job, with its job's `defaults.run` over the workflow's."""
    jobs = data.get("jobs") if isinstance(data, dict) else None
    top = _run_defaults(data)
    for job in jobs.values() if isinstance(jobs, dict) else ():
        if not isinstance(job, dict):
            continue
        defaults = {**top, **_run_defaults(job)}
        steps = job.get("steps")
        for step in steps if isinstance(steps, list) else ():
            if isinstance(step, dict):
                yield step, defaults


def _folder(step: dict, defaults: dict) -> str | None:
    """The step's working directory from the root ("."); None: one it may not run in (outside
    the project, an expression, not a string)."""
    given = step.get("working-directory", defaults.get("working-directory"))
    if given is None:
        return "."
    if not isinstance(given, str) or "${{" in given:
        return None
    path = PurePosixPath(given.strip().replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or re.match(r"^[A-Za-z]:", given.strip()):
        return None
    return path.as_posix().removeprefix("./") or "."


def _skipped(step: dict, defaults: dict, lines: list[str], name: str) -> str | None:
    """Why a step's lines are not run: an e2e step, an expression or a secret, an install, a
    shell of another language, a folder outside the project."""
    text = "\n".join(lines)
    if E2E.search(text) or E2E.search(name):
        return "e2e not run"
    if "${{" in text or "secrets." in text:
        return "not run: it reads the workflow's expressions or secrets"
    if INSTALL.search(text):
        return "not run: it installs"
    shell = step.get("shell", defaults.get("shell"))
    if shell is not None and not (isinstance(shell, str) and shell.split()[:1] and (
            shell.split()[0] in SHELLS)):
        return "not run: its shell is not a shell"
    if _folder(step, defaults) is None:
        return "not run: its working directory is not a folder of the project"
    return None


def _read_one(name: str, data: bytes, runs: list[CiRun], said: list[str],
              seen: set[tuple[str, str]]) -> None:
    try:
        parsed = yaml.load(data.decode("utf-8"), Loader=_NoAliases)  # noqa: S506 (SafeLoader's)
    except _Alias:
        said.append(f"CI file not read: {name} - it uses YAML aliases, which are not read")
        return
    except (ValueError, yaml.YAMLError, RecursionError, MemoryError):
        said.append(f"CI file not read: {name} does not parse")
        return
    for step, defaults in _steps(parsed):
        if len(runs) >= MOST_RUNS:
            return
        lines = [one.strip() for one in _text(step.get("run")).splitlines() if one.strip()]
        if not lines:
            continue
        name_of = _text(step.get("name")) or lines[0]
        why = _skipped(step, defaults, lines, name_of)
        if why is None and not all(kept(one) for one in lines):
            # (a test or lint line chained with another, piped, redirected: said; an unrelated
            # line beside: the step is none of the CI's checks, left out unsaid)
            why = f"not run: {NOT_PLAIN}" if any(
                _checks(one) and not is_plain(one) for one in lines) else ""
        if why:
            said.append(f"{why}: {name_of}" if why == "e2e not run" else (
                f"CI step {name_of}: {why}"))
        if why is not None:
            continue
        cwd = _folder(step, defaults) or "."
        for line in lines:
            if (line, cwd) not in seen and len(runs) < MOST_RUNS:
                seen.add((line, cwd))
                runs.append(CiRun(line, cwd, name_of))


def found(root: Path) -> Found:
    """The lint / typecheck / test lines of the project's workflows - each step whose every line
    is one, in its working directory (`defaults.run`'s where the step names none), once across
    jobs and the matrix, at most MOST_RUNS; what was left out and why (an e2e step, an expression
    or secret, an install, another shell, a line not plain, a file not read); and the
    fingerprint of the very bytes read. `uses:` steps run no line of theirs."""
    files = list(_files(root))
    runs: list[CiRun] = []
    said: list[str] = []
    seen: set[tuple[str, str]] = set()
    for name, data, why in files:
        if data is None:
            said.append(f"CI file not read: {name} - {why}")
        else:
            _read_one(name, data, runs, said, seen)
    if len(said) > MOST_RUNS:  # (a workflow of thousands of steps: not a row each)
        said[MOST_RUNS:] = [f"and {len(said) - MOST_RUNS} more CI steps left out"]
    return Found(runs, said, _mark(files))


def ci_runs(root: Path) -> tuple[list[CiRun], list[str]]:
    """`found`'s lines and what was left out."""
    one = found(root)
    return one.runs, one.said
