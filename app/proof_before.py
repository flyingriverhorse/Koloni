"""Kanıtlı bitiş S7 (plan decisions 14b, 19), what needs no model: which tests a failing run names,
the line that runs those alone again (a flaky test fails in the full run and passes alone), whether
a turn is a bug fix, which of its new files are tests, and the project's last green state - the
counts of a whole suite that passed, against which a drop in tests or a rise in skipped ones is
said. The runner's part: `BeforeMixin`."""

import re
from collections import Counter
from collections.abc import Collection, Iterable
from pathlib import Path

from app import ledger

# A bug-fix turn, by the user's words (S7; or a Bugfix recipe of the turn).
BUGFIX = re.compile(
    r"\b(fix|bug|broken|regress\w*|crash\w*|error|hata\w*|düzelt\w*|bozuk|çök\w*)\b", re.IGNORECASE
)
_PYTEST = re.compile(r"^(?:FAILED|ERROR) (\S+?)(?: - .*)?$", re.MULTILINE)
# vitest's " FAIL  src/a.test.ts > adds" and jest's "FAIL src/a.test.js": the file.
_FILE_FAIL = re.compile(r"^\s*FAIL\s+(\S+)", re.MULTILINE)
_FILE_TOOLS = frozenset({"vitest", "jest", "npm test", "pnpm test", "yarn test", "bun test"})
# A test file by its name: test_x.py, x_test.py / .go, x.test.ts, x.spec.js, ...
TEST_FILE = re.compile(
    r"(?:^|/)(?:test_[^/]+\.py|[^/]+_test\.(?:py|go)|[^/]+\.(?:test|spec)\.[cm]?[jt]sx?)$"
)
# The passes a run lists: pytest's "<id> PASSED" (with -v / -rA), jest's "PASS <file>", vitest's
# " ✓ <file>". A run that lists none keeps only its counts.
# (a node id is a word with `::` inside it, kept by `passed_ids`: `\S+::\S+` split a long word
# every way)
_PYTEST_PASSED = re.compile(r"^(\S+) PASSED", re.MULTILINE)
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
# CL-336 M: a lint, format or type check's findings by the file each names where a finding
# starts - `path:3`, `path:3:1`, `path(3,1)` (ruff, flake8, pylint, mypy, tsc), ruff's / ty's
# `--> path:3:1` (with the line above it), a path alone or after "would reformat" / "[warn]" (ruff
# format, black, prettier; eslint's and pyright's file above its lines) and eslint's
# `  3:1  error ...` under it. (Not inside a line: ruff quotes the code, `np.zeros(3,4)`.)
_AT = re.compile(r"^\s*(?:-->\s*)?([^\s:()\"'<>\[\]`]+\.[A-Za-z0-9]{1,8})(?::\d+|\(\d+,\d+\))")
_BARE = re.compile(
    r"^\s*(?:would reformat:?\s+|\[warn\]\s+)?([^\s:]+\.[A-Za-z0-9]{1,8})\s*$", re.IGNORECASE
)
_UNDER = re.compile(r"^\s+\d+:\d+\s")
# (review of CL-336 M) ...and every other line that reads like a problem - an error, a warning, a
# failure, a code (`E501`, `TS5023`) - or names a file of the project anywhere (`mypy.ini: [mypy]:
# Unrecognized option`); not a summary line, whose counts move with what was checked.
_PROBLEM = re.compile(r"(?i:\b(?:error|errors|warning|failed|fatal)\b)|\b[A-Z]{1,6}\d{3,5}\b")
_SUMMARY = re.compile(
    r"^(?:found\s+)?\d+\s+(?:source\s+)?"
    r"(?:files?|errors?|problems?|warnings?|fixable)\b|^\[\*\]\s+\d+\s+fixable|^[✖✗]\s+\d+\s+problems?|^success:"
    r"|^all checks passed",
    re.IGNORECASE,
)
_TOKEN = re.compile(r"[^\s:()\"'<>\[\]`,;=]+\.[A-Za-z0-9]{1,8}")
MOST_LINT_CHARS = 100_000  # (of the output's end, its colours off)


def failed_ids(command: str, output: str) -> list[str]:
    """The tests a failing run names: pytest's `FAILED <id>` / `ERROR <id>` (its reason cut), a
    vitest's or jest's `FAIL <file>` - the file; [] where its tool names none KOLONİ reads."""
    read = ledger.read_test(command)
    tool = read[0] if read else ""
    text = ledger.tail(output, 20_000)
    found = (
        _PYTEST.findall(text)
        if tool == "pytest"
        else _FILE_FAIL.findall(text)
        if (tool in _FILE_TOOLS)
        else []
    )
    return list(dict.fromkeys(found))


def passed_ids(command: str, output: str) -> list[str] | None:
    """The tests a passing run lists as passed (pytest node ids; vitest's / jest's files), at
    most MOST_IDS; None where its output lists none - nothing more is run to know."""
    read = ledger.read_test(command)
    tool = read[0] if read else ""
    text = ledger.tail(output, max(len(output), 1))
    found = (
        [one for one in _PYTEST_PASSED.findall(text) if "::" in one[1:-1]]
        if (tool == "pytest")
        else _FILE_PASS.findall(text)
        if tool in _FILE_TOOLS
        else []
    )
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


def lint_findings(
    output: str, root: Path, cwd: str, mine: Collection[str] = ()
) -> tuple[frozenset[str], Counter[str]] | None:
    """CL-336 M: a failed lint, format or type check's (`ci_commands.checks_files`) files - each
    project-relative, named where a finding starts - and findings, counted: each line that names
    a file there, or reads like a problem anywhere (`_PROBLEM`, a project file in it), its
    folder's path taken off (one copy's output reads as another's). None - not to be told
    apart: none named, a name there that is no file of the project (gone, outside it, a word
    that only looks like one), or a file of `mine` (the turn's) anywhere in it."""
    folder = (root / cwd).resolve()
    text = ledger.tail(output, MOST_LINT_CHARS)
    for prefix in {str(folder), folder.as_posix()}:
        text = text.replace(prefix + "\\", "").replace(prefix + "/", "")
    if _names_any(text.replace("\\", "/").casefold(), mine, cwd):
        return None
    files: set[str] = set()
    found: Counter[str] = Counter()
    header, last = None, ""
    for line in text.splitlines():
        said = line.strip().replace("\\", "/")
        bare = _BARE.match(line)
        named = bare[1] if bare else at[1] if (at := _AT.match(line)) else None
        if named:
            rel = _project_file(named, folder, root)
            if rel is None:
                return None
            files.add(rel)
            header = rel if bare else header
            found[f"{last} {said}" if said.startswith("-->") else said] += 1
        elif header and _UNDER.match(line):
            found[f"{header} {said}"] += 1
        elif (
            said
            and not _SUMMARY.match(said)
            and (
                _PROBLEM.search(said)
                or any(_project_file(one, folder, root) for one in _TOKEN.findall(said))
            )
        ):
            found[said] += 1
        last = said or last
    return (frozenset(files), found) if files else None


def _names_any(text: str, mine: Collection[str], cwd: str) -> bool:
    """Whether `text` (casefolded, `/`) names any of `mine` (project-relative): as it is, or from
    the run's folder `cwd`."""
    at = "" if cwd in ("", ".") else cwd.casefold().strip("/") + "/"
    forms = {
        form for one in mine for form in (one.casefold(), one.casefold().removeprefix(at)) if form
    }
    return any(re.search(rf"(?<![\w.-]){re.escape(form)}(?!\w)", text) for form in forms)


def _project_file(said: str, folder: Path, root: Path) -> str | None:
    try:
        path = (folder / said.replace("\\", "/")).resolve()
        return path.relative_to(root.resolve()).as_posix() if path.is_file() else None
    except (OSError, ValueError):
        return None


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
        if (
            skips
            and _SKIPS.search(sentence)
            or not skips
            and SAID_WHY.search(sentence)
            and _NAMES_TESTS.search(sentence)
        ):
            return sentence if len(sentence) <= MOST_SAID else sentence[: MOST_SAID - 1] + "…"
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
