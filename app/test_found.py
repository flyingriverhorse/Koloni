"""S1b (kanıtlı bitiş, plan decisions 9 and 11), what needs no model: the counts a test runner's
summary gives, which line of an agent's or a model's may be tried as a project's test command, and
what the one look for one is told of the project - its layout, its test files, its notes - and how
its answer is read. The runner's part: `FoundMixin`."""

import json
import os
import re
import sys
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import NamedTuple

from app import ledger
from app.commands import plain
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

    @property
    def ran(self) -> bool:
        """Whether it really ran tests: some passed or failed (skipped alone is none)."""
        return self.passed + self.failed > 0


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


# go: a package that did not build or set up ran no test; one with "[no tests to run]" ran none.
_GO_NONE = re.compile(r"\[(?:build failed|setup failed|no tests to run)\]")


def _go(text: str) -> Counts | None:
    tests = tuple(len(re.findall(rf"^\s*--- {word}", text, re.M))
                  for word in ("PASS", "FAIL", "SKIP"))
    if any(tests):
        return Counts(tests[0], tests[1], tests[2])
    lines = [line for line in text.splitlines() if not _GO_NONE.search(line)]
    packages = (sum(bool(re.match(r"ok\s+\S", line)) for line in lines),
                sum(bool(re.match(r"FAIL\s+\S+\s", line)) for line in lines))
    return Counts(*packages, 0, "packages") if any(packages) else None


def _cargo(text: str) -> Counts | None:
    found = re.findall(r"test result: \w+\. (\d+) passed; (\d+) failed; (\d+) ignored", text)
    if not found:
        return None
    passed, failed, skipped = (sum(int(one[at]) for one in found) for at in range(3))
    return Counts(passed, failed, skipped)


def _phpunit(text: str) -> Counts | None:
    """PHPUnit's "Tests: 5, Assertions: 7, Warnings: 1, Failures: 1, Skipped: 2." - by its words."""
    lines = re.findall(r"^Tests: \d+, Assertions: \d+.*$", text, re.M)
    if not lines:
        return None
    said = {word.casefold(): int(n) for word, n in re.findall(r"(\w+): (\d+)", lines[-1])}
    failed = said.get("failures", 0) + said.get("errors", 0)
    skipped = said.get("skipped", 0) + said.get("incomplete", 0)
    return Counts(said["tests"] - failed - skipped, failed, skipped)


def _unittest(text: str) -> Counts | None:
    """unittest's "Ran 6 tests in 0.1s" and, after it, "OK (skipped=1)" or "FAILED (failures=1,
    errors=1)"."""
    found = re.search(r"^Ran (\d+) tests? in [\d.]+s\s+(?:OK|FAILED)(?: \(([^)]*)\))?", text, re.M)
    if not found:
        return None
    said = {word: int(n) for word, n in re.findall(r"([a-z][a-z ]*)=(\d+)", found.group(2) or "")}
    failed = said.get("failures", 0) + said.get("errors", 0)
    skipped = said.get("skipped", 0) + said.get("expected failures", 0)
    return Counts(int(found.group(1)) - failed - skipped, failed, skipped)


def _last(pattern: str, make: Callable[[re.Match], Counts]) -> Callable[[str], Counts | None]:
    def read(text: str) -> Counts | None:
        found = list(re.finditer(pattern, text))
        return make(found[-1]) if found else None
    return read


# Each runner's summary, tried in this order (`counts`): the end of a run's output - its whole for
# go's and cargo's, whose counts are spread over it.
# shortcut: as each prints by default with its quiet flags left out - none measured here but
# pytest's, jest's and vitest's; a summary seen worded otherwise is "no count", never invented.
PARSERS: tuple[tuple[Callable[[str], Counts | None], bool], ...] = (
    (_cargo, True),
    (_last(r"Failed:\s+(?P<f>\d+), Passed:\s+(?P<p>\d+), Skipped:\s+(?P<s>\d+)",  # dotnet
           lambda m: Counts(_n(m, "p"), _n(m, "f"), _n(m, "s"))), False),
    (_last(r"Test summary: total: \d+, failed: (?P<f>\d+), succeeded: (?P<p>\d+), "  # dotnet 9
           r"skipped: (?P<s>\d+)", lambda m: Counts(_n(m, "p"), _n(m, "f"), _n(m, "s"))), False),
    (_last(r"Tests run: (?P<r>\d+), Failures: (?P<f>\d+), Errors: (?P<e>\d+), "  # maven
           r"Skipped: (?P<s>\d+)", lambda m: Counts(
               _n(m, "r") - _n(m, "f") - _n(m, "e") - _n(m, "s"), _n(m, "f") + _n(m, "e"),
               _n(m, "s"))), False),
    (_last(r"(?P<r>\d+) tests completed(?:, (?P<f>\d+) failed)?(?:, (?P<s>\d+) skipped)?",  # gradle
           lambda m: Counts(_n(m, "r") - _n(m, "f") - _n(m, "s"), _n(m, "f"), _n(m, "s"))), False),
    (_last(r"(?P<r>\d+) examples?, (?P<f>\d+) failures?(?:, (?P<s>\d+) pending)?",  # rspec
           lambda m: Counts(_n(m, "r") - _n(m, "f") - _n(m, "s"), _n(m, "f"), _n(m, "s"))), False),
    (_unittest, False),
    (_last(r"OK \((?P<r>\d+) tests?, \d+ assertions?\)",  # phpunit, passing
           lambda m: Counts(_n(m, "r"), 0, 0)), False),
    (_phpunit, False),
    (_last(r"Tests:\s+(?P<line>.*\d+ total)",  # jest
           lambda m: Counts(_words(m["line"], "passed"), _words(m["line"], "failed"),
                            _words(m["line"], "skipped"))), False),
    (_vitest, False),
    (_go, True),
    (_pytest_like, False),
)


def counts(output: str, command: str = "") -> Counts | None:
    """What a run's output counts, by the first runner whose summary it holds - pytest's own first
    where the command is pytest's; None: none known - the run is judged by its exit code alone,
    and says so. Its colours aside (`commands.plain`: CL-316)."""
    output = plain(output)
    tail = output[-4000:]
    read = ledger.read_test(command) if command else None
    if read is not None and read[0] == "pytest" and (own := _pytest_like(tail)) is not None:
        return own
    return next((found for parse, whole in PARSERS
                 if (found := parse(output if whole else tail)) is not None), None)


MOST_LINE = 200  # characters of a command line tried
# Plan decision 11 / review of S1b: the only lines of an agent's or the look's that are tried as the
# project's test command - the forms KOLONİ's own guesses take, each with at most `-q` or `-v`.
# Nothing else: no prefix, no shell, no option with a value, no path, no file of tests.
TRIED = frozenset({
    "pytest", "python -m pytest", "npx vitest run", "npx jest", "npm test",
    "yarn test", "pnpm test", "bun test", "tox", "nox", "go test ./...", "cargo test",
    "dotnet test", "mvn test", "gradle test", "./gradlew test", "bundle exec rspec",
    "composer test", "vendor/bin/phpunit", "mix test", "swift test", "ctest",
    "ctest --test-dir build", "make test",
})


def tryable(command: str) -> bool:
    """Whether a line that is not the user's may be tried, and saved, as the project's test
    command: exactly one of `TRIED`, at most `-q` or `-v` after it - single-spaced (a newline
    or a tab would make it two commands, or another, where it is run as saved)."""
    words = command.split()
    if len(command) > MOST_LINE or len(words) > 6 or command != " ".join(words):
        return False
    if words and words[-1] in ("-q", "-v"):
        words = words[:-1]
    return " ".join(words) in TRIED


MOST_SAID = 5


def said_runs(said: str, root: Path) -> tuple[list[tuple[str, str]], int]:
    """The look's answer as data: `{"tests": [{"command", "folder"}]}` (in a code fence or not) -
    each a tryable line in a folder inside the project that is there, at most MOST_SAID; and how
    many more it named that are not (never tried: not one of `TRIED`, or not in the project)."""
    found = re.search(r"\{.*\}", said, re.S)
    try:
        given = json.loads(found.group(0)) if found else {}
    except ValueError:
        return [], 0
    tests = given.get("tests") if isinstance(given, dict) else None
    out: list[tuple[str, str]] = []
    named = 0
    for one in tests if isinstance(tests, list) else []:
        command = one.get("command") if isinstance(one, dict) else None
        folder = one.get("folder", ".") if isinstance(one, dict) else None
        named += isinstance(command, str)
        if isinstance(command, str) and isinstance(folder, str) and tryable(command.strip()) and (
                (place := inside(root, folder)) is not None):
            out.append((" ".join(command.split()), place))
    return out[:MOST_SAID], named - len(out[:MOST_SAID])


def folder_key(folder: str) -> str:
    """A folder of the project as the key a saved test command is kept under
    (`Project.tests_found`): POSIX, "." the root - in one case where the file system has one
    (CL-316: on Windows and macOS `SUB` and `sub` are one folder, never two saves)."""
    key = str(PurePosixPath(folder.replace("\\", "/").strip() or "."))
    return key.casefold() if sys.platform in ("win32", "darwin") else key


def inside(root: Path, folder: str) -> str | None:
    """A folder named as the project's relative POSIX path ("." the root) - where it is a folder
    inside the project, through no link; None: not."""
    rel = PurePosixPath(folder.replace("\\", "/").strip() or ".")
    if rel.is_absolute() or ".." in rel.parts or ":" in folder:
        return None
    place = root / rel
    if not place.is_dir() or not _within(root, place):
        return None
    return str(rel)


def _within(root: Path, place: Path) -> bool:
    try:
        return place.resolve().is_relative_to(root.resolve())
    except OSError:
        return False


def _linked(place: Path) -> bool:
    """A link or (on Windows) a junction: not walked, not read."""
    return place.is_symlink() or bool(getattr(os.path, "isjunction", lambda _p: False)(place))


# What the look is shown of the project: its test files by these names, and the head of these notes.
TEST_FILES = ("test_*.py", "*_test.py", "*_test.go", "*.test.[jt]s", "*.test.[jt]sx",
              "*.spec.[jt]s", "*.spec.[jt]sx", "*Test.java", "*Tests.cs", "*_spec.rb",
              "*Test.php", "*_test.exs", "*Tests.swift")
NOTES = ("README.md", "README.rst", "README", "CONTRIBUTING.md", "Makefile", "justfile",
         "tox.ini", "noxfile.py")
SKIP = {".git", ".venv", "venv", "node_modules", "dist", "build", "target", ".koloni",
        "__pycache__", ".tox", ".nox"}
MOST_FILES, MOST_NOTE, MOST_FOLDERS = 40, 1500, 2000


def _test_files(root: Path) -> list[str]:
    """The project's test files by name (`TEST_FILES`), up to MOST_FILES - walked through no link
    or junction, past `SKIP`, MOST_FOLDERS folders at most; no secret file named."""
    found: list[str] = []
    for walked, (top, folders, files) in enumerate(os.walk(root), 1):
        folders[:] = sorted(name for name in folders
                            if name not in SKIP and not _linked(Path(top) / name))
        for name in sorted(files):
            rel = (Path(top) / name).relative_to(root).as_posix()
            if not secret_in_project(rel) and any(
                    PurePosixPath(name).match(pattern) for pattern in TEST_FILES):
                found.append(f"- {rel}")
        if len(found) >= MOST_FILES or walked >= MOST_FOLDERS:
            break
    return found[:MOST_FILES]


def _note(root: Path, name: str) -> str | None:
    """The head of a note, MOST_NOTE bytes - not one that is a link or a junction, lies outside
    the project, is a secret file by its name, or has another name too (a hard link: its other
    name may be anywhere)."""
    place = root / name
    if _linked(place) or not place.is_file() or not _within(root, place) or (
            secret_in_project(name)):
        return None
    try:
        if place.stat().st_nlink > 1:
            return None
        with place.open("rb") as handle:
            return handle.read(MOST_NOTE).decode("utf-8", errors="replace")
    except OSError:
        return None


def digest(root: Path, found: dict | None) -> str:
    """The project as the look reads it - its parts and languages (the map's), the test files it
    has, and the head of its notes (`NOTES`): KOLONİ reads, the model reads only this.
    shortcut: a walk by name, not git's view of the folder; skip what git ignores if that is met."""
    parts = [f"- {part['path']} ({part.get('language') or 'no language known'}, "
             f"{part.get('files', '?')} files)" for part in (found or {}).get("parts", [])]
    notes = [f"--- {name} ---\n{text}" for name in NOTES
             if (text := _note(root, name)) is not None]
    return "\n".join(["Parts of the project:", *(parts or ["- none found"]),
                      "Test files:", *(_test_files(root) or ["- none found"]), *notes])


def fingerprint(found: dict | None) -> str:
    """The map's parts and languages, as one line: the look is not asked again while they stand."""
    return json.dumps(sorted((part.get("path"), part.get("language"))
                             for part in (found or {}).get("parts", [])))
