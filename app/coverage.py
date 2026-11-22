"""Kanıtlı bitiş S9, what needs no model: where a project already measures coverage (pytest-cov,
Vitest's coverage, c8), the report flags its whole-suite run gets - nothing installed, nothing but
report flags added, the report written under the project's scratch - and what share of the turn's
changed lines that report says the tests ran. The runner's part: `CoverageMixin`."""

import json
import re
import shlex
import sys
from pathlib import Path
from typing import NamedTuple

from app import ledger
from app.workspace import SCRATCH

# A report this big is not read (a project's whole coverage, its every file).
MOST_REPORT = 20 * 1024 * 1024
REPORT = {"pytest-cov": "coverage.json", "vitest": "coverage-final.json",
          "c8": "coverage-final.json"}
# What a runner says of an option it does not know: the flags failed, not the tests.
FLAGS_FAILED = re.compile(r"unrecognized arguments|unknown option|no such option|"
                          r"Unknown (?:argument|option)|error: unexpected argument", re.IGNORECASE)


class Covered(NamedTuple):
    """Of the changed lines a test could run: the share run (None: none could be), and the ones
    no test ran, by path."""
    percent: int | None
    uncovered: dict[str, list[int]]


def _text(path: Path) -> str:
    try:
        with path.open("rb") as handle:
            return handle.read(256 * 1024).decode("utf-8", errors="replace")
    except OSError:
        return ""


def _package(folder: Path) -> tuple[dict, str]:
    """A package.json's dependencies (and dev ones), and its test script."""
    try:
        data = json.loads(_text(folder / "package.json") or "{}")
    except ValueError:
        return {}, ""
    if not isinstance(data, dict):
        return {}, ""
    return ({**(data.get("dependencies") or {}), **(data.get("devDependencies") or {})},
            str((data.get("scripts") or {}).get("test") or ""))


def tool_of(folder: Path, command: str) -> str | None:
    """The coverage tool a whole-suite run in `folder` may use, as the project already has it:
    pytest-cov named in its pyproject.toml / setup.cfg / requirements*.txt for a pytest run;
    Vitest's coverage package for a vitest run (or `npm test` running vitest); c8, its local bin
    there, for a node run; None: none - nothing is installed."""
    read = ledger.read_test(command)
    tool = read[0] if read else ""
    if read is None or read[1]:
        return None
    if tool == "pytest":
        named = [folder / "pyproject.toml", folder / "setup.cfg", *folder.glob("requirements*.txt")]
        return "pytest-cov" if any("pytest-cov" in _text(one) for one in named) else None
    deps, script = _package(folder)
    vitest = tool == "vitest" or tool.endswith(" test") and "vitest" in script
    if vitest and ({"@vitest/coverage-v8", "@vitest/coverage-istanbul"} & set(deps)):
        return "vitest"
    if "c8" in deps and (folder / "node_modules" / ".bin" / ("c8.cmd" if sys.platform == "win32"
                                                             else "c8")).exists():
        return "c8"
    return None


def _quoted(path: str) -> str:
    return f'"{path}"' if sys.platform == "win32" else shlex.quote(path)


def with_coverage(command: str, tool: str, out: str) -> str:
    """The run's line with only report flags added, the report written to `out` (the project's
    scratch): pytest-cov's JSON; Vitest's json reporter (after `--` through a package script);
    c8 through the project's own bin (`npx --no`: never a download)."""
    where = _quoted(out)
    if tool == "pytest-cov":
        return f"{command} --cov=. --cov-report=json:{_quoted(f'{out}/coverage.json')}"
    if tool == "vitest":
        flags = f"--coverage --coverage.reporter=json --coverage.reportsDirectory={where}"
        read = ledger.read_test(command)
        through = read and read[0] != "vitest" and not re.search(r"(?:^|\s)--(?:\s|$)", command)
        return f"{command} -- {flags}" if through else f"{command} {flags}"
    return f"npx --no c8 --reporter=json --report-dir {where} {command}"


# KOLONİ's own report flags (`with_coverage`), told by their folder in the project's scratch.
_OUT = r"(?:\"[^\"]*\"|'[^']*'|\S+)"
_AT = r"(?=\"[^\"]*coverage-|'[^']*coverage-|\S*coverage-)"
_ADDED = re.compile(
    rf"^npx --no c8 --reporter=json --report-dir {_AT}{_OUT} "
    rf"| --cov=\. --cov-report=json:{_AT}{_OUT}"
    rf"|(?: --)? --coverage --coverage\.reporter=json --coverage\.reportsDirectory={_AT}{_OUT}")


def unflagged(line: str) -> str:
    """A run's line without the report flags KOLONİ added: the command it is known by (reuse,
    the green state, how long it takes)."""
    return _ADDED.sub("", line) if ".koloni" in line and "coverage-" in line else line


def report(root: Path, out: Path, tool: str) -> dict | None:
    """A run's coverage report: only one under the project's scratch, at most MOST_REPORT bytes;
    None: none there, too big, outside, or not JSON."""
    place = (out / REPORT[tool]).resolve()
    scratch = (root / SCRATCH).resolve()
    if not place.is_relative_to(scratch) or not place.is_file():
        return None
    if place.stat().st_size > MOST_REPORT:
        return None
    try:
        return json.loads(place.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _rel(root: Path, name: str) -> str:
    path = Path(name)
    if path.is_absolute():
        try:
            path = path.resolve().relative_to(root.resolve())
        except (OSError, ValueError):
            return ""
    return path.as_posix().removeprefix("./")


def _lines(root: Path, data: dict, tool: str) -> dict[str, tuple[set[int], set[int]]]:
    """By project path: the lines a test could run, and those it ran."""
    out: dict[str, tuple[set[int], set[int]]] = {}
    if tool == "pytest-cov":
        for name, one in (data.get("files") or {}).items():
            ran = set(one.get("executed_lines") or [])
            out[_rel(root, name)] = (ran | set(one.get("missing_lines") or []), ran)
        return out
    for name, one in data.items():
        if not isinstance(one, dict):
            continue
        could, ran = set(), set()
        for key, span in (one.get("statementMap") or {}).items():
            line = (span.get("start") or {}).get("line")
            if isinstance(line, int):
                could.add(line)
                if (one.get("s") or {}).get(key):
                    ran.add(line)
        out[_rel(root, one.get("path") or name)] = (could, ran)
    return out


def changed_lines_covered(root: Path, data: dict, tool: str,
                          added: dict[str, list[int]]) -> Covered:
    """Of the turn's added lines a test could run (the report's), the share it ran, and those
    it did not, by path."""
    lines = _lines(root, data, tool)
    could = ran = 0
    uncovered: dict[str, list[int]] = {}
    for path, numbers in added.items():
        known = lines.get(path)
        if known is None:
            continue
        here = sorted(set(numbers) & known[0])
        missed = [one for one in here if one not in known[1]]
        could, ran = could + len(here), ran + len(here) - len(missed)
        if missed:
            uncovered[path] = missed
    return Covered(round(100 * ran / could) if could else None, uncovered)


def ranges(numbers: list[int]) -> str:
    """12-14, 20: lines as their runs."""
    out: list[list[int]] = []
    for one in sorted(set(numbers)):
        if out and one == out[-1][-1] + 1:
            out[-1].append(one)
        else:
            out.append([one])
    return ", ".join(f"{run[0]}-{run[-1]}" if len(run) > 1 else str(run[0]) for run in out)
