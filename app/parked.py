"""☾ Away, park and continue (§10): in a job while the user is away, a command's card or a question
the Orchestrator cannot answer does not stop the job - KOLONİ parks it (`Parked`), tells the agent
it did not run, and the job goes on. In the morning the user decides each under Waiting for you.

Every word here is KOLONİ's; what is parked - a line, a question - is data, quoted where it is said
to a model, never read as an instruction."""

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import away, backlog, injection
from app.cards import REASONS
from app.commands import _BLOCKS, _parts, _program
from app.copies import NOT_COPIED
from app.db.away_models import Parked
from app.db.models import (
    AwayRun,
    BacklogTask,
    Command,
    Conversation,
    Merge,
    Project,
    Question,
    Run,
    now,
)
from app.team import quoted

# To the agent whose command was parked (CLI: `deny(text, fixed=True)`).
PARKED = (
    "KOLONİ parked this for the user, who is away: {what}. It did not run. Do what you can "
    "without it, and say in your summary what waits."
)
# ...whose question was.
PARKED_ASKED = (
    "KOLONİ parked this for the user, who is away: {what}. Do what you can without their answer, "
    "and say in your summary what waits."
)
WHY = "{n} parked"  # (a job's reason to wait, `away.turn_ended`)
# Why a question was parked where the Orchestrator gave no answer that counts.
COULD_NOT_ANSWER = "The Orchestrator could not answer it"
# What a package manager's `run` is followed by: a script's name, not a folder.
_RUNNERS = frozenset({"npm", "pnpm", "yarn", "bun"})


def said(line: str, cwd: str | None) -> str:
    """What the agent is told of its parked command."""
    at = f" in {cwd}" if cwd and cwd != "." else ""
    return PARKED.format(what=f"run {quoted(line)}{at}")


def needs_project(line: str) -> bool:
    """Whether a command needs the project itself, not a copy of it: a stage of it runs git (a
    copy has no `.git`), or a word of it names a folder a copy leaves out (`copies.NOT_COPIED`:
    `build`, `dist`...), split as `away.kept_out` splits words - not `npm run build`'s script.
    shortcut: a script named by its runner without `run` (`yarn build`) counts as a folder; read
    the runner's own scripts if that keeps a line closed that need not be."""
    for words in _parts(line, _BLOCKS):
        if words and _program(words[0]) == "git":
            return True
        if words and _program(words[0]) in _RUNNERS and words[1:2] == ["run"]:
            words = words[:2] + words[3:]  # (its script's name is no folder)
        if any(
            part.casefold() in NOT_COPIED
            for word in words
            for piece in re.split(r"[=,;:<>|&()]+", word.strip("'\""))
            for part in re.split(r"[\\/]", piece)
        ):
            return True
    return False


def park(
    session: Session, task: BacklogTask, kind: str, ref_id: str | None, what: str, data: dict
) -> Parked:
    """A row parked for task `task` (a job of an Away) - or the one parked already: the same kind,
    the same line or question and folder, not decided yet. Not committed."""
    for one in session.scalars(
        select(Parked).where(
            Parked.task_id == task.id,
            Parked.kind == kind,
            Parked.what == what,
            Parked.decision.is_(None),
        )
    ):
        if one.data.get("cwd") == data.get("cwd"):
            return one
    seq = session.scalar(select(func.max(Parked.seq)).where(Parked.away_run_id == task.away_run_id))
    row = Parked(
        away_run_id=task.away_run_id,
        task_id=task.id,
        seq=(seq or 0) + 1,
        kind=kind,
        ref_id=ref_id,
        what=what,
        data=data,
    )
    session.add(row)
    session.flush()
    return row


# --- Waiting for you: the list, a decision, Stop this task --------------------------------------

# Why a row's decision waits (`closed`): all of them...
AT_WORK = "Its job is at work: decide once its turn is over"
LAST = "Waits for this task's other decisions and its going-on turn"
# ...and a command's Run (its Reject stays open).
GONE = "Its copy is gone: there is nothing to run it in"
NEEDS = "Needs the project itself: Take in first"
NOWHERE = "Where it would run is not known: Reject it, or run it yourself"
ELSEWHERE = "The project runs commands elsewhere now: Reject it, or set that back"
STOPPED = "Stopped by you."


class Refused(ValueError):
    """A decision not taken, with its HTTP status: 404 no such row, 409 not now, 422 not so."""

    def __init__(self, status: int, why: str):
        super().__init__(why)
        self.status = status


@dataclass(frozen=True)
class Kind:
    """A kind of parked row: the words it is decided with, why its doing word is closed now
    (`closed`: None, open), and - `act` - what its own click does at once (a push); without one,
    a row is decided with the task's others, then one going-on turn (`ready`). `last`: closed
    while another row of its task waits for a decision, or its going-on turn runs."""

    words: frozenset[str]
    closed: Callable[[Session, Parked, BacklogTask], str | None]
    act: Callable[..., Awaitable[str]] | None = None
    last: bool = False


def where(session: Session, row: Parked) -> tuple[Literal["copy", "project", "gone"], Merge | None]:
    """Where a parked command would run now: in the job's copy, kept and untouched ("copy"); in
    the project, some of the copy taken in ("project" - B-122's way); nowhere, the copy thrown
    away or never made ("gone"). With the copy's Merge."""
    copy = row.data.get("copy")
    merge = session.scalar(select(Merge).where(Merge.kept_in == copy).limit(1)) if copy else None
    if merge is not None:
        taken = any(one.get("state") == "applied" for one in merge.files)
        return ("project" if taken else "copy"), merge
    command = session.get(Command, row.ref_id or "") if copy else None
    # (A Take in or a Discard that ended the copy takes its folder off its Merge: by its turn.)
    merge = (
        session.scalar(
            select(Merge)
            .where(Merge.run_id == command.run_id, Merge.kept_in.is_(None))
            .order_by(Merge.decided_at.desc())
            .limit(1)
        )
        if command is not None
        else None
    )
    return ("project" if merge is not None and merge.status == "applied" else "gone"), merge


def _command_closed(session: Session, row: Parked, task: BacklogTask) -> str | None:
    """Why a parked command's Run is closed now - it runs only as it was recorded."""
    place, _merge = where(session, row)
    if place == "gone":
        return GONE
    if row.data.get("needs_project") and place != "project":
        return NEEDS
    if row.data.get("cwd") is None:  # (a CLI that did not say where its shell stood)
        return NOWHERE
    project = session.get(Project, task.project_id)
    image = project.docker_image if project and project.exec_location == "docker" else None
    recorded = (row.data.get("location"), row.data.get("image"))
    if project is None or (project.exec_location, image) != recorded:
        return ELSEWHERE
    return None


KINDS: dict[str, Kind] = {
    "command": Kind(frozenset({"run", "reject"}), _command_closed),
    "question": Kind(frozenset({"answer"}), lambda _session, _row, _task: None),
}


def at_work(session: Session, task: BacklogTask) -> bool:
    return task.conversation_id is not None and (
        session.scalar(
            select(Run.id)
            .where(Run.conversation_id == task.conversation_id, Run.status.not_in(backlog.ENDED))
            .limit(1)
        )
        is not None
    )


def _undecided(session: Session, task: BacklogTask, but: str = "") -> list[Parked]:
    return list(
        session.scalars(
            select(Parked).where(
                Parked.task_id == task.id, Parked.decision.is_(None), Parked.id != but
            )
        )
    )


def _held(session: Session, night: AwayRun, row: Parked, task: BacklogTask) -> str | None:
    """Why no decision of the row is taken now: the user is away (one at a time: a going-on
    turn would be a second job), its job's turn is at work - and, of a `last` kind, its task's
    other rows wait, or its going-on turn runs."""
    if away.running(session, night.project_id) is not None:
        return away.AWAY_NOW
    kind = KINDS.get(row.kind)
    if (
        kind is not None
        and kind.last
        and (
            at_work(session, task)
            or any(not KINDS[one.kind].last for one in _undecided(session, task, row.id))
        )
    ):
        return LAST
    return AT_WORK if at_work(session, task) else None


def closed(session: Session, night: AwayRun, row: Parked, task: BacklogTask) -> str | None:
    """What the list says of a row not decided: why it cannot be (Run) now; None: it can."""
    kind = KINDS.get(row.kind)
    return _held(session, night, row, task) or (kind.closed(session, row, task) if kind else None)


def _why(row: Parked) -> str:
    """Why it was parked, in KOLONİ's words alone: the card's family (`cards.REASONS`), the
    judge's own sentence; a question's reason, the Orchestrator's, quoted."""
    if row.kind != "command":
        said = row.data.get("why") or COULD_NOT_ANSWER
        return said if said == COULD_NOT_ANSWER else f"The Orchestrator: {quoted(said)}"
    return row.data.get("judge") or REASONS.get(row.data.get("reason") or "", REASONS["other"])


def waiting(session: Session, night: AwayRun) -> list[dict]:
    """Waiting for you (`WaitingOut`): what an Away parked, its jobs in the card's order, each
    job's in the order parked - not a task's whose chat was deleted."""
    order = {job["task_id"]: at for at, job in enumerate(night.jobs) if job.get("task_id")}
    rows = list(session.scalars(select(Parked).where(Parked.away_run_id == night.id)))
    tasks = {
        task.id: task
        for task in session.scalars(
            select(BacklogTask).where(BacklogTask.id.in_({row.task_id for row in rows}))
        )
    }
    found = []
    for row in sorted(rows, key=lambda one: (order.get(one.task_id, len(order)), one.seq)):
        task = tasks.get(row.task_id)
        if task is None or session.get(Conversation, task.conversation_id or "") is None:
            continue
        found.append(
            {
                "id": row.id,
                "kind": row.kind,
                "task_id": task.id,
                "task": task.title,
                "conversation_id": task.conversation_id,
                "what": row.what,
                "cwd": row.data.get("cwd"),
                "why": _why(row),
                "warn": injection.NOTE if injection.scan(row.what) else None,
                "options": row.data.get("options") or [],
                "decision": row.decision,
                "answer": row.answer,
                "result": row.result,
                "closed": None if row.decision else closed(session, night, row, task),
                "seq": row.seq,
            }
        )
    return found


def ready(session: Session, task: BacklogTask) -> bool:
    """Every row of a task decided that goes on in its going-on turn (no `act` of its own), and
    one such not gone on yet: the turn may start."""
    rows = [
        one
        for one in session.scalars(select(Parked).where(Parked.task_id == task.id))
        if (kind := KINDS.get(one.kind)) is not None and kind.act is None
    ]
    return all(one.decision for one in rows) and any(
        one.decision != "stop" and one.went_on is None for one in rows
    )


def _answered(row: Parked, word: str, answer: str | None) -> str:
    """A question's answer as the user gave it - one of its options where it has some."""
    given, options = (answer or "").strip(), row.data.get("options") or []
    if word == "answer" and (not given or (options and given not in options)):
        raise Refused(422, "answer with one of its options" if options else "an answer, please")
    return given


async def decide(
    session: Session, night: AwayRun, item_id: str, word: str, answer: str | None
) -> BacklogTask | None:
    """The user's word on a parked row (`Refused`: why not). A row with an `act` does its work
    at once; else the task, where this was its last decision (`ready`) - its going-on turn may
    start - or None. Committed."""
    row = session.get(Parked, item_id)
    task = session.get(BacklogTask, row.task_id) if row is not None else None
    kind = KINDS.get(row.kind) if row is not None else None
    if row is None or row.away_run_id != night.id or task is None or kind is None:
        raise Refused(404, "no such item of this card")
    if row.decision is not None:
        raise Refused(409, "decided already")
    if word not in kind.words:
        raise Refused(422, f"a {row.kind} is decided with {', '.join(sorted(kind.words))}")
    if why := _held(session, night, row, task) or (
        kind.closed(session, row, task) if word != "reject" else None
    ):
        raise Refused(409, why)
    given = _answered(row, word, answer)
    row.decision, row.answer, row.decided_at = word, given or None, now()
    if row.kind == "question" and (question := session.get(Question, row.ref_id or "")):
        question.status, question.answer, question.answered_at = "answered", given, now()
    if kind.act is not None:
        row.result = await kind.act(session, row, task)
        session.commit()
        return None
    session.commit()
    return task if ready(session, task) else None


def close_rows(session: Session, task: BacklogTask) -> None:
    """A task's rows not decided are closed - Stop this task, Try again: nothing of them runs,
    no going-on turn; its parked questions are cancelled. Not committed."""
    for row in _undecided(session, task):
        row.decision, row.decided_at = "stop", now()
        if row.kind == "question" and (question := session.get(Question, row.ref_id or "")):
            question.status = "cancelled"


def stop(session: Session, night: AwayRun, task: BacklogTask) -> None:
    """Stop this task: what waits of it is closed, it is stopped by the user. Committed."""
    if task.away_run_id != night.id:
        raise Refused(404, "no such job of this card")
    close_rows(session, task)
    task.away_state, task.away_why = "stopped", STOPPED
    session.commit()
