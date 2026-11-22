"""Kanıtlı bitiş S7 (plan decisions 14b, 19), what needs no model: which tests a failing run names,
the line that runs those alone again (a flaky test fails in the full run and passes alone), whether
a turn is a bug fix, which of its new files are tests, and the project's last green state - the
counts of a whole suite that passed, against which a drop in tests or a rise in skipped ones is
said. The runner's part: `BeforeMixin`."""

import re
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
# What an agent's answer says when it took tests away or skipped them on purpose - in a sentence
# that names tests (`excuse`): "Removed a stray debug print." excuses nothing.
SAID_WHY = re.compile(r"\b(?:remov|delet|skip|xfail|drop|retir)\w*", re.IGNORECASE)
_NAMES_TESTS = re.compile(r"\b(?:test|skip|xfail)|\bspecs?\b", re.IGNORECASE)
_SKIPS = re.compile(r"\b(?:skip|xfail)", re.IGNORECASE)
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
MOST_SAID = 120  # characters of the sentence quoted
# A test id KOLONİ runs again alone, unasked, from what a run PRINTED (review of S7): plain
# characters only - letters of any alphabet (`test_düzelt`), digits, `_ - . / \ : [ ]`; none a
# shell reads (`$ ( ) ; % ^ & | < >`, a backtick, a quote - PowerShell's curly ones too - a space).
_PLAIN_ID = re.compile(r"[\w\-./\\:\[\]]{1,500}")


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


def plain_id(one: str) -> bool:
    """Whether a test id (a run printed it) may go on a line KOLONİ runs unasked: plain
    characters, relative - no leading `-` (an option), `/` or `\\`, no drive, no `..` part."""
    if not _PLAIN_ID.fullmatch(one) or one.startswith(("-", "/", "\\")):
        return False
    parts = re.split(r"::|[/\\]", one)
    return not re.match(r"[A-Za-z]:(?!:)", one) and ".." not in parts


def _quoted(one: str) -> str:
    """In single quotes on both platforms: literal to sh and to PowerShell alike (a plain id
    holds no quote: `plain_id`)."""
    return f"'{one}'"


def alone(command: str, ids: list[str]) -> str | None:
    """The line that runs only `ids` of `command` again: pytest's ids after it, npm's test
    script's files after `--`, vitest's / jest's files after it; None: no such line (another
    tool, an exit masked, an id that is no plain one: `plain_id`)."""
    read = ledger.read_test(command)
    if not ids or read is None or read[1] or not all(map(plain_id, ids)):
        return None
    named = " ".join(map(_quoted, ids))
    if read[0] == "pytest" or read[0] in ("vitest", "jest"):
        return f"{command} {named}"
    return f"{command} -- {named}" if read[0] in _FILE_TOOLS else None


def reproduces(output: str, wrote: dict[str, str]) -> bool:
    """R4: whether a failing run's output names a failing TEST of a test file the agent wrote
    (`wrote`: its project-relative path to its text) - by the file the id names (pytest's
    `x::t`, vitest's `file > name`; from a sub-folder, the end of the path), or where the tool
    names no file (jest's `suite › name`, go's `--- FAIL: TestX`) by its name in that file. A
    collection or syntax error names no failing test (review of S7): no reproduction.
    shortcut: a failing name `ledger.failing_named` does not read - a jest test outside a
    `describe` (`● adds two`), mocha's, node:test's - is none: such a run never reproduces (the
    step is held); read those forms there if a Bugfix on such a project is seen held."""
    for one in ledger.failing_named(ledger.tail(output)):
        if "::" in one or " > " in one:
            head = re.split(r"::| > ", one)[0].strip().replace("\\", "/").removeprefix("./")
            if any(path == head or path.endswith(f"/{head}") for path in wrote):
                return True
        elif (bare := ledger._bare(one)) and any(bare in text for text in wrote.values()):
            return True
    return False


def new_tests(created: Iterable[str]) -> list[str]:
    """The test files among a turn's new files (S2's `proof.new_tests` takes its place once in:
    shortcut, a test written into an existing file is not counted here)."""
    return [path for path in created if TEST_FILE.search(path.replace("\\", "/"))]


def excuse(answer: str, said: str) -> str | None:
    """The sentence of the agent's answer that says why the tests changed as `said` says: for a
    drop, one that says it removed / skipped / dropped them and names tests; for a rise in
    skipped ones, one that names skip or xfail. None: the answer says no why."""
    skips = said.startswith("Skipped rose")
    for sentence in (one.strip() for one in _SENTENCE.split(answer)):
        if skips and _SKIPS.search(sentence) or not skips and SAID_WHY.search(
                sentence) and _NAMES_TESTS.search(sentence):
            return sentence if len(sentence) <= MOST_SAID else sentence[:MOST_SAID - 1] + "…"
    return None


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
