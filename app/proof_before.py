"""Kanıtlı bitiş S7 (plan decisions 14b, 19), what needs no model: which tests a failing run names,
the line that runs those alone again (a flaky test fails in the full run and passes alone), whether
a turn is a bug fix, which of its new files are tests, and the project's last green state - the
counts of a whole suite that passed, against which a drop in tests or a rise in skipped ones is
said. The runner's part: `BeforeMixin`."""

import re
import shlex
import sys
from collections.abc import Iterable

from app import ledger

# A bug-fix turn, by the user's words (S7; or a Bugfix recipe of the turn).
BUGFIX = re.compile(
    r"\b(fix|bug|broken|regress\w*|crash\w*|error|hata\w*|düzelt\w*|bozuk|çök\w*)\b",
    re.IGNORECASE)
_PYTEST = re.compile(r"^(?:FAILED|ERROR) (\S+?)(?: - .*)?$", re.MULTILINE)
# vitest's " FAIL  src/a.test.ts > adds" and jest's "FAIL src/a.test.js": the file.
_FILE_FAIL = re.compile(r"^\s*FAIL\s+(\S+)", re.MULTILINE)
_FILE_TOOLS = frozenset({"vitest", "jest", "npm test", "pnpm test", "yarn test", "bun test"})
# A test file by its name: test_x.py, x_test.py / .go, x.test.ts, x.spec.js, ...
TEST_FILE = re.compile(
    r"(?:^|/)(?:test_[^/]+\.py|[^/]+_test\.(?:py|go)|[^/]+\.(?:test|spec)\.[cm]?[jt]sx?)$")
# The passes a run lists: pytest's "<id> PASSED" (with -v / -rA), jest's "PASS <file>", vitest's
# " ✓ <file>". A run that lists none keeps only its counts.
_PYTEST_PASSED = re.compile(r"^(\S+::\S+) PASSED", re.MULTILINE)
_FILE_PASS = re.compile(r"^\s*(?:PASS|✓)\s+(\S+)", re.MULTILINE)
# shortcut: at most this many passed ids are kept of a green run - a regression past them is said
# by file; keep more if a project that big is seen naming one wrong.
MOST_IDS = 5000
# What an agent's answer says when it took tests away or skipped them on purpose.
SAID_WHY = re.compile(r"\b(?:remov|delet|skip|xfail|drop|retir)\w*", re.IGNORECASE)


def failed_ids(command: str, output: str) -> list[str]:
    """The tests a failing run names: pytest's `FAILED <id>` / `ERROR <id>` (its reason cut), a
    vitest's or jest's `FAIL <file>` - the file; [] where its tool names none KOLONİ reads."""
    read = ledger.read_test(command)
    tool = read[0] if read else ""
    text = ledger.tail(output, 20_000)
    found = _PYTEST.findall(text) if tool == "pytest" else _FILE_FAIL.findall(text) if (
        tool in _FILE_TOOLS) else []
    return list(dict.fromkeys(found))


def passed_ids(command: str, output: str) -> list[str] | None:
    """The tests a passing run lists as passed (pytest node ids; vitest's / jest's files), at
    most MOST_IDS; None where its output lists none - nothing more is run to know."""
    read = ledger.read_test(command)
    tool = read[0] if read else ""
    text = ledger.tail(output, max(len(output), 1))
    found = _PYTEST_PASSED.findall(text) if tool == "pytest" else _FILE_PASS.findall(text) if (
        tool in _FILE_TOOLS) else []
    return list(dict.fromkeys(found))[:MOST_IDS] or None


def regressions(failing: list[str], green: dict, mine: set[str]) -> list[tuple[str, bool]]:
    """Decision 14b: of a run's failing tests, those that passed at the last green run - by
    its passed ids where it kept them (a test added since is never one); else by file, any not
    of a file this turn added (True: said "by file")."""
    ids = green.get("ids")
    if ids:
        kept = set(ids)
        return [(one, False) for one in failing if one in kept or one.split("::")[0] in kept]
    return [(one, True) for one in failing if one.split("::")[0] not in mine]


def _quoted(one: str) -> str:
    """For the shell the host runs a line in: POSIX quoting, or double quotes on Windows."""
    return f'"{one}"' if sys.platform == "win32" else shlex.quote(one)


def alone(command: str, ids: list[str]) -> str | None:
    """The line that runs only `ids` of `command` again: pytest's ids after it, npm's test
    script's files after `--`, vitest's / jest's files after it; None: no such line (another
    tool, an exit masked, an id with a quote or a line break in it)."""
    read = ledger.read_test(command)
    if not ids or read is None or read[1] or any(c in one for one in ids for c in "'\"\r\n"):
        return None
    named = " ".join(map(_quoted, ids))
    if read[0] == "pytest" or read[0] in ("vitest", "jest"):
        return f"{command} {named}"
    return f"{command} -- {named}" if read[0] in _FILE_TOOLS else None


def new_tests(created: Iterable[str]) -> list[str]:
    """The test files among a turn's new files (S2's `proof.new_tests` takes its place once in:
    shortcut, a test written into an existing file is not counted here)."""
    return [path for path in created if TEST_FILE.search(path.replace("\\", "/"))]


def green_said(was: dict | None, ran: int, skipped: int) -> list[str]:
    """Decision 14b: what a whole suite that passed says against the project's last green run -
    fewer tests that ran, more skipped. [] where it holds or none is known yet."""
    if not was:
        return []
    said = []
    if ran < was["ran"]:
        said.append(f"Tests went from {was['ran']} to {ran} ({was['ran'] - ran} removed)")
    if skipped > was["skipped"]:
        said.append(f"Skipped rose from {was['skipped']} to {skipped}")
    return said
