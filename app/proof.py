"""Kanıtlı bitiş (proven finish), what needs no model: the kind of each file a turn changed, the
project's test command(s), the turn's changes on record, whether a test run on record stands for
this turn's, and the rows of the Checked section KOLONİ writes under the answer (`ProofMixin`)."""

import fnmatch
from collections.abc import Collection, Iterable
from datetime import datetime
from pathlib import PurePosixPath
from typing import NamedTuple, TypedDict

from sqlalchemy import literal_column, select
from sqlalchemy.orm import Session

from app import finish_tests, ledger, project_map
from app.db.models import Command, Conversation, FileChange, Project, Run
from app.tools import MAX_TIMEOUT
from app.workspace import in_scratch, unified_diff

# Project.after_change: Check it, Tests only, Nothing.
AFTER_CHANGE = ("check", "tests", "nothing")

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
                                     FileChange.status.in_(ledger.KEPT))
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
                            last.agent_id, last.status == "applied" or last.agent_id in here))
    return found


def last_change(session: Session, run_id: str) -> datetime | None:
    """When the turn's newest kept change was made or taken in: a test run before it did not
    see it."""
    times = session.execute(select(FileChange.created_at, FileChange.decided_at).where(
        FileChange.run_id == run_id, FileChange.status.in_(ledger.KEPT))).all()
    return max((one for pair in times for one in pair if one is not None), default=None)


def _folded(command: str) -> str:
    return " ".join(command.split())


def fresh(session: Session, run_id: str, lead_id: str, run: TestRun,
          since: datetime | None) -> Command | None:
    """The newest run of exactly `run`'s command in its folder, by the Lead or KOLONİ (the Lead's
    record: where the gate runs it - never a sub-agent's, which may be in its copy), that ran to
    its end with an exit code after `since`; None: run it. (Claude Code's pass, exit code None,
    is never reused.)
    shortcut: a Take-in check that ran the same command on what then went in is not counted - the
    project may hold more by then; count it when its `checked` files equal what was taken, if the
    double run is felt.
    shortcut: by the Lead's record alone - a Lead whose place moved within the turn (a recipe's
    copy taken in) ran it elsewhere; the take-in is a newer change then, so it runs again."""
    wanted = _folded(run.command)
    for one in session.scalars(
            select(Command).where(Command.run_id == run_id, Command.agent_id == lead_id,
                                  Command.status == "exited", Command.exit_code.is_not(None),
                                  Command.cwd == run.cwd, Command.ended_at.is_not(None))
            .order_by(Command.ended_at.desc(), literal_column("commands.rowid").desc())):
        if _folded(one.command) == wanted:
            return one if since is None or (one.ended_at or since) > since else None
    return None


def too_slow(session: Session, project_id: str, run: TestRun, seconds: int) -> str | None:
    """Why `run` is not run where a turn's end waits at most `seconds` for it: the newest run of
    it in the project (any chat's, anyone's) took longer, or was stopped at that wait - said as
    when; None: run it. A quicker run since (an agent's, the user's) lets it run again."""
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
        if one.status == "timed_out" and one.timeout_seconds >= seconds or took > seconds:
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
ICONS = {"passed": "✓ ", "failed": "✗ ", "running": "… "}

PASSED_ROW = "Tests passed: {command}{guessed} - {summary}"
FAILED_ROW = "Tests failed: {command}{guessed} - {summary}"
RAN_NONE = "Tests ran none: {command} collected no test"
TIMED_OUT = "Tests timed out after {minutes} min: {command}"
# A turn the user watches waits at most so long for them (S1, until they can run on in the
# background): stopped then, and said so - never passed or failed.
NOT_WAITED = ("Tests not waited for: still running at {clock}, so KOLONİ stopped them rather "
              "than hold the answer - {command}")
NOT_RUN = "Tests not run: {why}"
NOT_STARTED = "Tests could not start: {first}"
STOPPED = "Tests not finished: stopped"
NO_COMMAND = ("No test command: nothing was run (set one in Settings › This project › Checks "
              "and git)")
NO_TESTS_ROW = "No tests: only documents, slides, diagrams or data changed"
SENT_BACK = "Sent back to fix: {n} of {most} rounds"
STILL_FAILING = "Still failing after {most} fix rounds: you decide (Fix it)"
WAITING = "Not in this run: {name}'s work waits in Ready for you"
RUN_BY = "Tests passed: {command} - run by {who} after the last change"
NOT_CHECKED = "Not checked: After a change is set to Nothing"
LAST_RUN = "An agent ran {command} {when} the last change: {how}"


def row(kind: str, state: str, text: str, command: str | None = None,
        guessed: bool = False) -> Row:
    return {"kind": kind, "state": state, "text": text, "command": command, "guessed": guessed,
            "started_at": None}


def clock(seconds: int) -> str:
    return f"{seconds // 60}:{seconds % 60:02d}"


def _summary(output: str) -> str | None:
    lines = [line.strip(" =-") for line in output[-4000:].splitlines()
             if ledger.SUMS_UP.search(line)]
    return lines[-1] if lines else None


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

    def made(state: str, text: str) -> Row:
        return row("tests", state, text, run.command, not run.yours)
    if ended in (None, "failed_to_start") or finish_tests.did_not_start(code, output):
        return made("not_run", NOT_STARTED.format(first=_first(said, output)))
    if ended == "timed_out":
        return made("timed_out", TIMED_OUT.format(minutes=seconds // 60, command=run.command)
                    if seconds >= MAX_TIMEOUT else
                    NOT_WAITED.format(clock=clock(seconds), command=run.command))
    if ended != "exited" or code is None:
        return made("not_run", STOPPED)
    if code == 5 and "pytest" in run.command.casefold():
        return made("not_run", RAN_NONE.format(command=run.command))
    summary = _summary(output) or f"exit {code}"
    failed = code != 0 or bool(ledger.FAILED.search(output[-4000:]))
    return made("failed" if failed else "passed", (FAILED_ROW if failed else PASSED_ROW).format(
        command=run.command, guessed=guessed, summary=summary))


def checked_text(rows: list[Row]) -> str:
    """The Checked section as text: one line a row, its state's mark first."""
    return "\n".join(ICONS.get(one["state"], "– ") + one["text"] for one in rows)
