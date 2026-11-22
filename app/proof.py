"""Kanıtlı bitiş (proven finish), what needs no model: the kind of each file a turn changed, the
project's test command(s), the turn's changes on record, whether a test run on record stands for
this turn's, and the rows of the Checked section KOLONİ writes under the answer (`ProofMixin`)."""

import fnmatch
import re
from collections.abc import Collection, Iterable
from datetime import datetime
from pathlib import PurePosixPath
from typing import NamedTuple, TypedDict

from sqlalchemy import literal_column, or_, select
from sqlalchemy.orm import Session

from app import finish_tests, ledger, project_map, test_found
from app.commands import only_reads
from app.db.models import Command, Conversation, FileChange, Flag, Message, Project, Run, ToolCall
from app.tools import MAX_TIMEOUT
from app.workspace import in_scratch, unified_diff

# KOLONİ's own end-of-turn test run: its call's id starts so (`ProofMixin`).
PROOF_CALL = "koloni_proof_"

# Project.after_change: Check it, Tests only, Nothing.
AFTER_CHANGE = ("check", "tests", "nothing")
# Conversation.after_change (S10): None the project's; this chat's "off" or "on".
CHAT_AFTER_CHANGE = ("off", "on")

# By the file's name, casefolded (a name wins over an extension).
KIND_BY_NAME: dict[str, str] = {
    **dict.fromkeys((
        "requirements*.txt", "constraints*.txt", "pyproject.toml", "setup.py", "setup.cfg",
        "tox.ini", "pytest.ini", "conftest.py", "package.json", "package-lock.json",
        "pnpm-lock.yaml", "yarn.lock", "tsconfig*.json", "vite.config.*", "vitest.config.*",
        "makefile", "dockerfile", "docker-compose*.yml", ".env*"), "config"),
    "*.drawio.xml": "diagram",
}
KIND_BY_EXT: dict[str, str] = {
    **dict.fromkeys((".md", ".markdown", ".rst", ".adoc", ".txt", ".docx", ".odt"), "docs"),
    **dict.fromkeys((".pptx", ".odp", ".key"), "slides"),
    **dict.fromkeys((".drawio", ".dio", ".mmd", ".mermaid", ".puml", ".plantuml", ".svg"),
                    "diagram"),
    **dict.fromkeys((".csv", ".tsv", ".ipynb", ".parquet", ".xlsx", ".xls"), "data"),
    **dict.fromkeys((".html", ".htm", ".css", ".scss", ".sass", ".less", ".vue", ".svelte",
                     ".tsx", ".jsx"), "ui"),
    **dict.fromkeys((".toml", ".yaml", ".yml", ".json", ".ini", ".cfg", ".lock"), "config"),
}
# What changes nothing a test reads: only such a turn runs no test.
NO_TESTS = frozenset({"docs", "slides", "diagram", "data"})
# A branch turn's work once merged at its end (`_drop_copy`): still the turn's, made when it was
# made - not at the merge.
MERGED = "merged"


def kind_of(path: str) -> str:
    """"code", "config", "docs", "slides", "diagram", "data" or "ui"; what no table names: code."""
    posix = path.replace("\\", "/").casefold()
    if "/.github/workflows/" in f"/{posix}":
        return "config"
    name = posix.rsplit("/", 1)[-1]
    named = next((kind for pattern, kind in KIND_BY_NAME.items()
                  if fnmatch.fnmatchcase(name, pattern)), None)
    return named or KIND_BY_EXT.get(PurePosixPath(name).suffix, "code")


def needs_tests(paths: Iterable[str]) -> bool:
    """False only for changes that are all documents, slides, diagrams or data."""
    kinds = {kind_of(path) for path in paths}
    return bool(kinds - NO_TESTS)


class TestRun(NamedTuple):
    """A test command, the folder it runs in (project-relative POSIX, "." the root), and whether
    it is the user's own (else KOLONİ's guess from the project's files)."""
    command: str
    cwd: str
    yours: bool


def test_runs(project: Project, found: dict | None) -> list[TestRun]:
    """The project's whole test command(s): the user's check command; else each part's test of
    its map (the user's, or the map's guess); else the guess from its files; else none."""
    if project.check_command and project.check_command.strip():
        return [TestRun(project.check_command.strip(), ".", True)]
    parts = project_map.edited(found, project.test_commands or {})["parts"] if found else []
    runs = [TestRun(part["test"], part["path"].removeprefix("./").rstrip("/") or ".",
                    bool(part["edited"])) for part in parts if part["test"]]
    guess = None if runs else finish_tests.command_of(project.root_path, None)
    return runs or ([TestRun(guess, ".", False)] if guess else [])


class Change(NamedTuple):
    """One path a turn changed: its kind, lines added and removed (first before to last after),
    whether it is gone, who changed it last, and whether it is where the tests run."""
    path: str
    kind: str
    added: int
    removed: int
    deleted: bool
    agent_id: str
    in_project: bool


def changes(session: Session, run_id: str, lead_id: str,
            sharing: Collection[str] = ()) -> list[Change]:
    """The turn's kept changes, one a path. Not in the project: a copy's (`in_copy`) of an agent
    other than the Lead, waiting in Ready for you - but where that agent works in the Lead's own
    copy (`sharing`: an Away job's, a branch turn's), where the tests run."""
    rows: dict[str, list[FileChange]] = {}
    for row in session.scalars(
            select(FileChange).where(FileChange.run_id == run_id,
                                     FileChange.status.in_((*ledger.KEPT, MERGED)))
            .order_by(FileChange.created_at, literal_column("file_changes.rowid"))):
        if not in_scratch(row.path):
            rows.setdefault(row.path, []).append(row)
    here = {lead_id, *sharing}
    found = []
    for path, made in rows.items():
        last = made[-1]
        _diff, added, removed = unified_diff(made[0].before_content, last.after_content or "",
                                             path, context=0)
        found.append(Change(path, kind_of(path), added, removed, last.kind == "delete",
                            last.agent_id, last.status in ("applied", MERGED)
                            or last.agent_id in here))
    return found


def last_change(session: Session, run_id: str, made_there: Collection[str] = ()
                ) -> datetime | None:
    """When the turn's newest kept change was made or taken in: a test run that started before
    it did not see it. (A merged branch's: when it was made - the gate ran on the branch. And,
    for a run where `made_there`'s agents worked, theirs: their copy held it when it was made.)"""
    times = session.execute(select(FileChange.created_at, FileChange.decided_at,
                                   FileChange.status, FileChange.agent_id).where(
        FileChange.run_id == run_id, FileChange.status.in_((*ledger.KEPT, MERGED)))).all()
    return max((one for made, decided, status, agent in times for one in (
        made, None if status == MERGED or agent in made_there else decided) if one is not None),
        default=None)


def _folded(command: str) -> str:
    return " ".join(command.split())


def fresh(session: Session, run_id: str, lead_id: str, run: TestRun, since: datetime | None,
          sharing: Collection[str] = (), made: datetime | None = None) -> Command | None:
    """The newest run of exactly `run`'s command in its folder that ran to its end with an exit
    code and stands for the work as it is: the Lead's (or KOLONİ's, on its record) started after
    `since`; or one of `sharing`'s - the agents that worked where the Lead does, a recipe's Tester
    in its copy - started after `made` (`last_change` with them: what their copy held, Take in
    brought in as it was; plan decision 13, no second run). Never one after which a command of
    that place's agents started that may have changed files - a formatter, a codegen, a sed: no
    FileChange records what it rewrote (`_rewritten_after`). None: run it. (Claude Code's pass,
    exit code None, is never reused; nor a sub-agent's in a copy of its own.)
    shortcut: a Take-in check that ran the same command on what then went in is not counted - the
    project may hold more by then; count it when its `checked` files equal what was taken, if the
    double run is felt."""
    wanted, by, looked = _folded(run.command), {lead_id, *sharing}, set()
    for one in session.scalars(
            select(Command).where(Command.run_id == run_id, Command.agent_id.in_(by),
                                  Command.status == "exited", Command.exit_code.is_not(None),
                                  Command.cwd == run.cwd, Command.started_at.is_not(None))
            .order_by(Command.started_at.desc(), literal_column("commands.rowid").desc())):
        mine = one.agent_id == lead_id  # (the newest of each place's runs is its word)
        if _folded(one.command) != wanted or mine in looked:
            continue
        looked.add(mine)
        after = since if mine else made
        if (after is None or (one.started_at or after) > after) and not _rewritten_after(
                session, run_id, by, one, wanted):
            return one
    return None


def _rewritten_after(session: Session, run_id: str, by: Collection[str], ran: Command,
                     wanted: str) -> bool:
    """Whether a command of `by` started after `ran` that may have changed files, or ran the same
    test command again and did not pass: any but one that only reads (`commands.only_reads`) or
    a clean pass of exactly the end check's command. A test tool on a line is no sign it only
    tested - `fmt && pytest`, `jest -u`, `--snapshot-update` write. Re-running is the safe way."""
    return any(
        not only_reads(one.command) and not (
            _folded(one.command) == wanted and one.status == "exited" and one.exit_code == 0)
        for one in session.scalars(select(Command).where(
            Command.run_id == run_id, Command.agent_id.in_(by), Command.id != ran.id,
            # (`>=`: a later line in the same tick of Windows' clock is no proof it came first)
            Command.started_at.is_not(None), Command.started_at >= ran.started_at)))



def after_change_of(session: Session, conversation: Conversation, run: Run | None = None) -> str:
    """After a change for a turn of this chat (S10, plan decision 17): the project's ("check",
    "tests", "nothing") unless the chat says otherwise - "off" (its switch off: nothing checked),
    or on: the project's, Check it where that is Nothing. A recipe's turn (`run.teams`) follows
    the recipe, never the chat's switch: today the project's (shortcut: S5c gives a recipe its own
    Checks step)."""
    project = session.get(Project, conversation.project_id) if conversation.project_id else None
    own = project.after_change if project is not None else "nothing"
    if run is not None and run.teams:
        return own
    if conversation.after_change == "off":
        return "off"
    return "check" if conversation.after_change == "on" and own == "nothing" else own


def too_slow(session: Session, project_id: str, run: TestRun, seconds: int) -> str | None:
    """Why `run` is not run where a turn's end waits at most `seconds` for it: the newest run of
    it in the project (any chat's, anyone's) ran longer, or was stopped at a limit of that wait or
    more (the limit it really had, as its record keeps it - not one the wait for the machine ate
    into) - said as when; None: run it. A quicker run since (an agent's, the user's) lets it run
    again."""
    wanted = _folded(run.command)
    for one in session.scalars(
            select(Command).join(Run, Run.id == Command.run_id)
            .join(Conversation, Conversation.id == Run.conversation_id)
            .where(Conversation.project_id == project_id, Command.cwd == run.cwd,
                   Command.status.in_(("exited", "timed_out")),
                   Command.started_at.is_not(None), Command.ended_at.is_not(None))
            .order_by(Command.ended_at.desc(), literal_column("commands.rowid").desc())):
        if _folded(one.command) != wanted or one.ended_at is None or one.started_at is None:
            continue
        took = (one.ended_at - one.started_at).total_seconds()
        if took > seconds or one.status == "timed_out" and one.timeout_seconds >= seconds and (
                took >= one.timeout_seconds - 1):  # (it ran its whole limit: a second's slack)
            return f"they ran past {clock(seconds)} on {one.ended_at:%d %b %H:%M}"
        return None
    return None


class Row(TypedDict):
    kind: str
    state: str
    text: str
    command: str | None
    guessed: bool
    started_at: str | None
    # S1b: what its runner's summary counted ({"passed", "failed", "skipped", "unit"}); None:
    # no count known (never made up).
    counts: dict | None
ICONS = {"passed": "✓ ", "failed": "✗ ", "running": "… "}

PASSED_ROW = "Tests passed: {command}{guessed} - {summary}"
# A runner KOLONİ reads no count of (an `npm test` that prints none): its exit code alone, said.
BY_CODE = "Tests passed (by exit code, no count): {command}{guessed}"
SKIPPED_ONLY = "Tests skipped only: {command} - {summary}"
# A test line whose exit is not the tests' (`ledger.read_test`: `| tail -1`, `|| true`).
NO_VERDICT = "Tests gave no verdict: {command} masks its exit"
FAILED_ROW = "Tests failed: {command}{guessed} - {summary}"
RAN_NONE = "Tests ran none: {command} collected no test"
TIMED_OUT = "Tests timed out after {minutes} min: {command}"
# A turn the user watches waits at most so long for them (S1, until they can run on in the
# background): stopped then, and said so - never passed or failed.
NOT_WAITED = ("Tests not waited for: still running at {clock}, so KOLONİ stopped them rather "
              "than hold the answer - {command}")
NOT_RUN = "Tests not run: {why}"
# (A change made after the last run: that run did not see it.)
NOT_AGAIN = "Tests not run on the last change: {why}"
NOT_STARTED = "Tests could not start: {first}"
STOPPED = "Tests not finished: stopped"
NO_COMMAND = ("No test command: nothing was run (set one in Settings › This project › Checks "
              "and git)")
NO_TESTS_ROW = "No tests: only documents, slides, diagrams or data changed"
SENT_BACK = "Sent back to fix: {n} of {most} rounds"
STILL_FAILING = "Still failing after {most} fix rounds: you decide (Fix it)"
RECIPE_SPENT = "Still failing after the recipe's fix rounds: you decide (Fix it)"
WAITING = "Not in this run: {name}'s work waits in Ready for you"
RUN_BY = "Tests passed: {command} - run by {who} after the last change"
NOT_CHECKED = "Not checked: After a change is set to Nothing"
OFF_FOR_CHAT = "Not checked: off for this chat"
LAST_RUN = "An agent ran {command} {when} the last change: {how}"


def row(kind: str, state: str, text: str, command: str | None = None,
        guessed: bool = False) -> Row:
    return {"kind": kind, "state": state, "text": text, "command": command, "guessed": guessed,
            "started_at": None, "counts": None}


def clock(seconds: int) -> str:
    return f"{seconds // 60}:{seconds % 60:02d}"


# What a runner says where it ran no test: unittest's "Ran 0 tests", jest's "No tests found",
# vitest's "No test files found", pytest's "no tests ran" (its exit 5 too).
RAN_NO_TEST = re.compile(r"\bRan 0 tests\b|\bNo tests found\b|\bNo test files found\b|"
                         r"\bno tests ran\b", re.IGNORECASE)
SKIPPED = re.compile(r"\b[1-9]\d* skipped\b", re.IGNORECASE)


def _summary(output: str, counts: re.Pattern = ledger.SUMS_UP) -> str | None:
    lines = [line.strip(" =-") for line in output[-4000:].splitlines() if counts.search(line)]
    return lines[-1] if lines else None


def _ran_none(run: TestRun, code: int, output: str) -> bool:
    """pytest's or unittest's exit 5, or a runner's own words that it ran no test - where its
    output counts none that passed or failed."""
    named = run.command.casefold()
    return (code == 5 and ("pytest" in named or "unittest" in named)) or (
        _summary(output) is None and bool(RAN_NO_TEST.search(output[-4000:])))


def _counted(found: "test_found.Counts | None") -> str | None:
    """A runner's counts in words, where its summary is not pytest's own line: "11 passed, 1
    failed, 2 skipped" (of packages, for go's)."""
    if found is None or not found.total:
        return None
    unit = "" if found.unit == "tests" else f" {found.unit}"
    return ", ".join(f"{n}{unit} {word}" for n, word in zip(found[:3], (
        "passed", "failed", "skipped"), strict=True) if n or word == "passed")


def _skipped_only(output: str, found: "test_found.Counts | None") -> str | None:
    """Where a passing run ran no test but skipped some: its summary; None: not so."""
    if found is not None:
        return _counted(found) if found.skipped and not found.passed + found.failed else None
    return _summary(output, SKIPPED) if _summary(output) is None else None


def _first(*said: str) -> str:
    for text in said:
        if line := next((one.strip() for one in text.splitlines() if one.strip()), ""):
            return line.removeprefix("error: ")
    return "no word of why"


def tests_row(run: TestRun, code: int | None, output: str, ended: str | None, said: str,
              seconds: int = MAX_TIMEOUT) -> Row:
    """A test run as its Checked row: failed is any exit but 0 (pytest's 5, nothing collected,
    aside) or a failure its output counts; never passed without exit code 0. `ended`: its
    record's status (None: none - it never started); `seconds`: the wait it was given."""
    guessed = "" if run.yours else " (guessed)"
    found = test_found.counts(output, run.command)

    def made(state: str, text: str) -> Row:
        return {**row("tests", state, text, run.command, not run.yours),
                "counts": found._asdict() if found else None}
    if ended in (None, "failed_to_start") or code not in (0, None) and (
            finish_tests.did_not_start(code, output)):
        return made("not_run", NOT_STARTED.format(first=_first(said, output)))
    if ended == "timed_out":
        return made("timed_out", TIMED_OUT.format(minutes=seconds // 60, command=run.command)
                    if seconds >= MAX_TIMEOUT else
                    NOT_WAITED.format(clock=clock(seconds), command=run.command))
    if ended != "exited" or code is None:
        return made("not_run", STOPPED)
    counted = bool(ledger.FAILED.search(output[-4000:]))
    if (read := ledger.read_test(run.command)) is not None and read[1] and not counted:
        return made("not_run", NO_VERDICT.format(command=run.command))
    if _ran_none(run, code, output):
        return made("not_run", RAN_NONE.format(command=run.command))
    summary = _summary(output) or _counted(found)
    if code != 0 or counted:
        return made("failed", FAILED_ROW.format(command=run.command, guessed=guessed,
                                                summary=summary or f"exit {code}"))
    if (skipped := _skipped_only(output, found)) is not None:
        return made("not_run", SKIPPED_ONLY.format(command=run.command, summary=skipped))
    return made("passed", PASSED_ROW.format(command=run.command, guessed=guessed, summary=summary)
                if summary else BY_CODE.format(command=run.command, guessed=guessed))


def checked_text(rows: list[Row]) -> str:
    """The Checked section as text: one line a row, its state's mark first."""
    return "\n".join(ICONS.get(one["state"], "– ") + one["text"] for one in rows)


# --- S6: related tests first, the whole suite in the background; the machine's load ----------

# A whole suite that goes on after the answer (`running`): waiting for another of KOLONİ's runs
# to end (no `started_at`), then running (`started_at` set: the page ticks its clock).
FULL_QUEUED = "Full tests waiting for another test run to end: {command}"
FULL_RUNNING = "Full tests running: {command}"
FULL_HELD = "Full tests not run: the related tests fail"
SUPERSEDED = "Tests not finished: the project changed, and a newer run took their place"
RESTARTED = "Tests not finished: KOLONİ restarted"
# A result that came after the project changed beneath it: it stands for no state of the work.
CHANGED_WHILE = " - the project changed while they ran"

# Settings › The app: KOLONİ's own test runs at once, and the test processes each may start
# (pytest-xdist's `-n auto` reads it). Cautious: this machine once failed under test load.
TEST_RUNS_FLAG, TEST_RUNS_RANGE, TEST_RUNS = "test_runs_at_once", (1, 4), 1
TEST_WORKERS_FLAG, TEST_WORKERS_RANGE, TEST_WORKERS = "test_workers", (1, 16), 2


def related_said(text: str) -> str:
    """A related run's row: "Related tests passed: …" - not to be read as the whole suite's."""
    return f"Related t{text[1:]}" if text.startswith("Tests ") else text


def load_of(session: Session) -> tuple[int, int]:
    """KOLONİ's test runs at once, and the test processes each may start, as Settings › The app
    has them; a value out of its range is held to it, one that is no whole number is the
    default."""
    def read(name: str, low_high: tuple[int, int], default: int) -> int:
        value = session.scalar(select(Flag.value).where(Flag.name == name))
        try:
            return default if value is None else min(low_high[1], max(low_high[0], int(value)))
        except ValueError:
            return default
    return (read(TEST_RUNS_FLAG, TEST_RUNS_RANGE, TEST_RUNS),
            read(TEST_WORKERS_FLAG, TEST_WORKERS_RANGE, TEST_WORKERS))


def written_since(session: Session, project_id: str,
                  since: datetime) -> dict[str, list[tuple[datetime, str | None]]]:
    """The project's paths a recorded change wrote after `since` - written there, taken in from a
    copy, or taken back (Undo), by any chat's turn - each with when, and what those changes
    left there (None: no file)."""
    left: dict[str, list[tuple[datetime, str | None]]] = {}
    for change in session.scalars(
            select(FileChange).join(Run, Run.id == FileChange.run_id)
            .join(Conversation, Conversation.id == Run.conversation_id)
            .where(Conversation.project_id == project_id,
                   FileChange.status.in_(("applied", MERGED, "reverted")),
                   or_(FileChange.created_at > since, FileChange.decided_at > since))):
        # (Undo puts back what it replaced - nothing where it made the file: `revert_change`.)
        held = (None if change.kind == "create" else change.before_content or "") if (
            change.status == "reverted") else (
            None if change.kind == "delete" else change.after_content)
        left.setdefault(change.path, []).append((change.decided_at or change.created_at, held))
    return left


def changed_since(session: Session, project_id: str, since: datetime,
                  ran: Command | None = None) -> bool:
    """Whether the project changed after `since` beneath `ran` (a test run of KOLONİ's): a
    recorded change (`written_since`), or a command of any turn in it that may have changed
    files - `_rewritten_after`'s rule, the same as for a pass that stands.
    shortcut: what the user changes outside KOLONİ is not on record; read the files' times if a
    background result is seen to stand for an edit it never ran on."""
    if written_since(session, project_id, since):
        return True
    if ran is None or ran.started_at is None:
        return False
    # (Not KOLONİ's own test runs - another suite of the same turn, say: they change nothing the
    # tests read, and a standing file they write is put back as they end.)
    proofs = select(ToolCall.id).where(ToolCall.provider_call_id.startswith(PROOF_CALL))
    agents: dict[str, set[str]] = {}
    for run_id, agent_id in session.execute(
            select(Command.run_id, Command.agent_id).join(Run, Run.id == Command.run_id)
            .join(Conversation, Conversation.id == Run.conversation_id)
            .where(Conversation.project_id == project_id, Command.id != ran.id,
                   Command.started_at.is_not(None), Command.started_at >= since,
                   or_(Command.tool_call_id.is_(None), Command.tool_call_id.not_in(proofs)))):
        agents.setdefault(run_id, set()).add(agent_id)
    return any(_rewritten_after(session, run_id, by, ran, _folded(ran.command))
               for run_id, by in agents.items())


def settle_running(session: Session) -> None:
    """At start-up: a test run that went on after its turn ended with the process that ran it -
    its row says so, never "running" on (`recover_interrupted`)."""
    for note in session.scalars(select(Message).where(
            Message.role == "checked", Message.content.contains(ICONS["running"]))):
        rows = [row("tests", "not_run", RESTARTED, one["command"], one["guessed"])
                if one["state"] == "running" else one
                for one in (note.blocks or {}).get("rows", [])]
        note.blocks, note.content = {"rows": rows}, checked_text(rows)
