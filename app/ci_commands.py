"""Kanıtlı bitiş S8 (plan decision 3), what needs no model: the lint, typecheck and test commands
a project's GitHub Actions workflows run (`.github/workflows/*.yml`), as the end check may run them
once the user approved the list - each line one the CI runs, in its working directory; never an
e2e step, nor one with an expression, a secret or an install in it; and a fingerprint of the
workflow files: a change asks again."""

import hashlib
import re
from pathlib import Path
from typing import NamedTuple

import yaml

from app import ledger

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


class CiRun(NamedTuple):
    """A command a workflow runs, the folder it runs in ("." the root), and its step's name."""
    command: str
    cwd: str
    step: str


def _kept_line(line: str) -> bool:
    return bool(LINTS.match(line) or TYPECHECKS.match(line) or ledger.read_test(line))


def _steps(data: object) -> list[dict]:
    jobs = data.get("jobs") if isinstance(data, dict) else None
    return [step for job in (jobs or {}).values() if isinstance(job, dict)
            for step in job.get("steps") or [] if isinstance(step, dict)]


def _skipped(step: dict, lines: list[str]) -> str | None:
    """Why a step's lines are not run: an e2e step, an expression or a secret, an install."""
    text = "\n".join(lines)
    if E2E.search(text) or E2E.search(str(step.get("name") or "")):
        return "e2e not run"
    if "${{" in text or "secrets." in text:
        return "not run: it reads the workflow's expressions or secrets"
    if INSTALL.search(text):
        return "not run: it installs"
    return None


def ci_runs(root: Path) -> tuple[list[CiRun], list[str]]:
    """The lint / typecheck / test lines of the project's workflows - each step whose every line
    is one, in its `working-directory`, once across jobs and the matrix, at most MOST_RUNS; and
    what was left out and why (an e2e step, an expression or secret, an install, a file that does
    not parse). `uses:` steps run no line of theirs."""
    runs: list[CiRun] = []
    said: list[str] = []
    for path in sorted((root / WORKFLOWS).glob("*.y*ml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, yaml.YAMLError):
            said.append(f"CI file not read: {path.name} does not parse")
            continue
        for step in _steps(data):
            run = step.get("run")
            if not isinstance(run, str):
                continue
            lines = [one.strip() for one in run.splitlines() if one.strip()]
            name = str(step.get("name") or (lines[0] if lines else ""))
            why = _skipped(step, lines)
            if why is not None:
                said.append(f"{why}: {name}" if why == "e2e not run" else f"CI step {name}: {why}")
                continue
            if not lines or not all(_kept_line(one) for one in lines):
                continue
            cwd = str(step.get("working-directory") or ".").strip().removeprefix("./").rstrip(
                "/") or "."
            for line in lines:
                if (line, cwd) not in {(one.command, one.cwd) for one in runs}:
                    runs.append(CiRun(line, cwd, name))
    return runs[:MOST_RUNS], said


def fingerprint(root: Path) -> str:
    """The workflow files as they are now: a change to any of them asks again."""
    digest = hashlib.sha256()
    for path in sorted((root / WORKFLOWS).glob("*.y*ml")):
        try:
            digest.update(path.name.encode() + b"\0" + path.read_bytes() + b"\0")
        except OSError:
            digest.update(path.name.encode() + b"\0?\0")
    return digest.hexdigest()
