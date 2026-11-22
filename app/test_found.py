"""S1b (kanıtlı bitiş, plan decisions 9 and 11), what needs no model: the counts a test runner's
summary gives, which line of an agent's or a model's may be tried as a project's test command, and
what the one look for one is told of the project - its layout, its test files, its notes - and how
its answer is read. The runner's part: `FoundMixin`."""

import json
import re
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import NamedTuple

from app import ledger
from app.commands import is_plain
from app.workspace import secret_in_project


class Counts(NamedTuple):
    """What a run's summary says: passed, failed (errors with them), skipped - of `unit`."""
    passed: int
    failed: int
    skipped: int
    unit: str = "tests"

    @property
    def total(self) -> int:
        return self.passed + self.failed + self.skipped


def _n(found: re.Match, name: str) -> int:
    return int(found.group(name) or 0)


def _words(text: str, word: str) -> int:
    """pytest's / jest's "3 failed, 11 passed": the number before `word`, 0 where none."""
    found = re.search(rf"(\d+) {word}", text)
    return int(found.group(1)) if found else 0


def _pytest_like(text: str) -> Counts | None:
    lines = [line for line in text.splitlines() if ledger.SUMS_UP.search(line)]
    if not lines:
        return None
    last = lines[-1]
    return Counts(_words(last, "passed"), _words(last, "failed") + _words(last, "errors?"),
                  _words(last, "skipped"))


def _vitest(text: str) -> Counts | None:
    found = [line for line in text.splitlines() if re.match(r"\s*Tests\s{2,}\d", line)]
    return None if not found else Counts(_words(found[-1], "passed"), _words(found[-1], "failed"),
                                         _words(found[-1], "skipped"))


def _go(text: str) -> Counts | None:
    tests = (len(re.findall(r"^--- PASS", text, re.M)), len(re.findall(r"^--- FAIL", text, re.M)),
             len(re.findall(r"^--- SKIP", text, re.M)))
    if any(tests):
        return Counts(*tests)
    packages = (len(re.findall(r"^ok\s+\S", text, re.M)),
                len(re.findall(r"^FAIL\s+\S+\s", text, re.M)))
    return Counts(*packages, 0, "packages") if any(packages) else None


def _cargo(text: str) -> Counts | None:
    found = re.findall(r"test result: \w+\. (\d+) passed; (\d+) failed; (\d+) ignored", text)
    return Counts(*(sum(int(one[at]) for one in found) for at in range(3))) if found else None


def _last(pattern: str, make: Callable[[re.Match], Counts]) -> Callable[[str], Counts | None]:
    def read(text: str) -> Counts | None:
        found = list(re.finditer(pattern, text))
        return make(found[-1]) if found else None
    return read


# Each runner's summary, tried in this order on the end of a run's output (`counts`).
# shortcut: as each prints by default with its quiet flags left out - none measured here but
# pytest's, jest's and vitest's; a summary seen worded otherwise is "no count", never invented.
PARSERS: tuple[Callable[[str], Counts | None], ...] = (
    _cargo,
    _last(r"Failed:\s+(?P<f>\d+), Passed:\s+(?P<p>\d+), Skipped:\s+(?P<s>\d+)",  # dotnet
          lambda m: Counts(_n(m, "p"), _n(m, "f"), _n(m, "s"))),
    _last(r"Tests run: (?P<r>\d+), Failures: (?P<f>\d+), Errors: (?P<e>\d+), "  # maven
          r"Skipped: (?P<s>\d+)", lambda m: Counts(
              _n(m, "r") - _n(m, "f") - _n(m, "e") - _n(m, "s"), _n(m, "f") + _n(m, "e"),
              _n(m, "s"))),
    _last(r"(?P<r>\d+) tests completed(?:, (?P<f>\d+) failed)?(?:, (?P<s>\d+) skipped)?",  # gradle
          lambda m: Counts(_n(m, "r") - _n(m, "f") - _n(m, "s"), _n(m, "f"), _n(m, "s"))),
    _last(r"(?P<r>\d+) examples?, (?P<f>\d+) failures?(?:, (?P<s>\d+) pending)?",  # rspec
          lambda m: Counts(_n(m, "r") - _n(m, "f") - _n(m, "s"), _n(m, "f"), _n(m, "s"))),
    _last(r"OK \((?P<r>\d+) tests?, \d+ assertions?\)",  # phpunit, passing
          lambda m: Counts(_n(m, "r"), 0, 0)),
    _last(r"Tests: (?P<r>\d+), Assertions: \d+(?:, Errors: (?P<e>\d+))?(?:, Failures: "  # phpunit
          r"(?P<f>\d+))?(?:, Errors: (?P<e2>\d+))?(?:, Skipped: (?P<s>\d+))?", lambda m: Counts(
              _n(m, "r") - _n(m, "f") - _n(m, "e") - _n(m, "e2") - _n(m, "s"),
              _n(m, "f") + _n(m, "e") + _n(m, "e2"), _n(m, "s"))),
    _last(r"Tests:\s+(?P<line>.*\d+ total)",  # jest
          lambda m: Counts(_words(m["line"], "passed"), _words(m["line"], "failed"),
                           _words(m["line"], "skipped"))),
    _vitest,
    _go,
    _pytest_like,
)


def counts(output: str) -> Counts | None:
    """What the end of a run's output counts, by the first runner whose summary it holds; None:
    none known - the run is judged by its exit code alone, and says so."""
    tail = output[-4000:]
    return next((found for parse in PARSERS if (found := parse(tail)) is not None), None)


MOST_LINE = 200  # characters of a command line tried


def tryable(command: str) -> bool:
    """Whether a line that is not the user's may be tried as the project's test command: one
    plain invocation of a test tool (`ledger.read_test`), its exit not masked, nothing chained."""
    if len(command) > MOST_LINE or "\n" in command or not is_plain(command):
        return False
    read = ledger.read_test(command)
    return read is not None and not read[1]


MOST_SAID = 5


def said_runs(said: str, root: Path) -> list[tuple[str, str]]:
    """The look's answer as data: `{"tests": [{"command", "folder"}]}` (in a code fence or not) -
    each a tryable line in a folder inside the project that is there; at most MOST_SAID. Never a
    command it said that is not one plain test line."""
    found = re.search(r"\{.*\}", said, re.S)
    try:
        given = json.loads(found.group(0)) if found else {}
    except ValueError:
        return []
    tests = given.get("tests") if isinstance(given, dict) else None
    out: list[tuple[str, str]] = []
    for one in tests if isinstance(tests, list) else []:
        command = one.get("command") if isinstance(one, dict) else None
        folder = one.get("folder", ".") if isinstance(one, dict) else None
        if isinstance(command, str) and isinstance(folder, str) and tryable(command.strip()) and (
                (place := _inside(root, folder)) is not None):
            out.append((command.strip(), place))
    return out[:MOST_SAID]


def _inside(root: Path, folder: str) -> str | None:
    """A folder the look named, as the project's relative POSIX path ("." the root) - where it is
    a folder inside the project; None: not."""
    rel = PurePosixPath(folder.replace("\\", "/").strip() or ".")
    if rel.is_absolute() or ".." in rel.parts:
        return None
    return str(rel) if (root / rel).is_dir() else None


# What the look is shown of the project: its test files by these names, and the head of these notes.
TEST_FILES = ("test_*.py", "*_test.py", "*_test.go", "*.test.[jt]s", "*.test.[jt]sx",
              "*.spec.[jt]s", "*.spec.[jt]sx", "*Test.java", "*Tests.cs", "*_spec.rb",
              "*Test.php", "*_test.exs", "*Tests.swift")
NOTES = ("README.md", "README.rst", "README", "CONTRIBUTING.md", "Makefile", "justfile",
         "tox.ini", "noxfile.py")
SKIP = {".git", ".venv", "venv", "node_modules", "dist", "build", "target", ".koloni"}
MOST_FILES, MOST_NOTE = 40, 1500


def digest(root: Path, found: dict | None) -> str:
    """The project as the look reads it - its parts and languages (the map's), the test files it
    has (`TEST_FILES`, up to MOST_FILES), and the head of its notes (`NOTES`): KOLONİ reads, the
    model reads only this. No secret file is named or read (`secret_in_project`).
    shortcut: a walk by name, not git's view of the folder; skip what git ignores if that is met."""
    parts = [f"- {part['path']} ({part.get('language') or 'no language known'}, "
             f"{part.get('files', '?')} files)" for part in (found or {}).get("parts", [])]
    tests: list[str] = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if len(tests) >= MOST_FILES or SKIP & set(path.relative_to(root).parts):
            continue
        if path.is_file() and not secret_in_project(rel) and any(
                path.match(pattern) for pattern in TEST_FILES):
            tests.append(f"- {rel}")
    notes = []
    for name in NOTES:
        try:
            text = (root / name).read_text(encoding="utf-8", errors="replace")[:MOST_NOTE]
        except OSError:
            continue
        notes.append(f"--- {name} ---\n{text}")
    return "\n".join(["Parts of the project:", *(parts or ["- none found"]),
                      "Test files:", *(tests or ["- none found"]), *notes])


def fingerprint(found: dict | None) -> str:
    """The map's parts and languages, as one line: the look is not asked again while they stand."""
    return json.dumps(sorted((part.get("path"), part.get("language"))
                             for part in (found or {}).get("parts", [])))
