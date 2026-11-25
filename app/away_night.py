"""The night on Ready for you (karar defteri, Part B; §3.4): what `away.report` adds to each job
of a night that ended, for its strip and its Markdown - when its turns of the night began and
ended, what was decided for the user in its chat, and what KOLONİ's checks did not do. From the
records alone: a time no record holds is None - never the night's own, nor now - and so is what
was not checked where no record says."""

from datetime import datetime

from sqlalchemy import ColumnElement, select
from sqlalchemy.orm import Session

from app.db.away_models import Parked
from app.db.models import AwayRun, BacklogTask, Message, Run
from app.proof import TESTS_OFF
from app.schemas_decisions import Decision

# A Checked note's rows that say a check was not done (`proof.row`), by their kind and state: any
# that did not run ("not_run": the tests - no command, a guessed one while away, none collected, a
# masked exit -, a kind's check, the Reviewer, a stronger model), the live or browser try's notes
# (not tried: no preview, nobody watching, the tests still failing; no verdict), the notes that
# nothing was - After a change set to Nothing, off for this chat, a recipe's Checks step that checks
# nothing - and its tests off there (a "tests" note, by its sentence: the other such notes say what
# was found, not what was skipped).
NOTHING_CHECKED = frozenset({"not_checked", "chat_off", "recipe_off"})
# shortcut: KOLONİ waits for no check of GitHub's on a push yet (`wait_for_ci`, 0.1.10): a job whose
# push you said Run says so; read the record of that wait once there is one.
GITHUB = "GitHub's checks on its push were not waited for"


def _night(away: AwayRun, ended: datetime) -> list[ColumnElement[bool]]:
    """A turn of the night: started between its start and its end."""
    began = (away.started_at or ended).replace(tzinfo=None)
    return [Run.created_at >= began, Run.created_at <= ended.replace(tzinfo=None)]


def times(
    session: Session, away: AwayRun, ended: datetime, cid: str
) -> tuple[datetime | None, datetime | None]:
    """When a job's turns of the night began - the first's start - and ended - the last's end; no
    end while one of them is still open.
    shortcut: one span - a going-on turn of the morning after your decisions (§10) moves the
    night's end to its own (`away.after_the_night`; Change and redo's does not), and the bar runs
    over the hours between; give each turn its span if that misleads."""
    found = session.execute(
        select(Run.created_at, Run.started_at, Run.ended_at).where(
            Run.conversation_id == cid, *_night(away, ended)
        )
    ).all()
    if not found:
        return None, None
    ends = [end for _created, _started, end in found if end is not None]
    began = min(started or created for created, started, _end in found)
    return began, max(ends) if len(ends) == len(found) else None


def _not_done(row: dict) -> bool:
    """Whether a Checked note's row says a check was not done (`NOTHING_CHECKED`)."""
    kind, state = row.get("kind"), row.get("state")
    return (
        state == "not_run"
        or kind in NOTHING_CHECKED
        or (kind == "try" and state == "note")
        or (kind == "tests" and row.get("text") == TESTS_OFF)
    )


def not_checked(
    session: Session, away: AwayRun, ended: datetime, task: BacklogTask, cid: str
) -> list[str] | None:
    """What KOLONİ's checks did not do on a job's work, in their own sentences: the rows of its last
    Checked note of the night that say so - and, its push gone, that GitHub's were not waited for.
    None where the night left no Checked note in its chat (none says what was checked)."""
    note = session.execute(
        select(Message.blocks)
        .join(Run, Run.id == Message.run_id)
        .where(Message.role == "checked", Run.conversation_id == cid, *_night(away, ended))
        .order_by(Run.created_at.desc(), Message.created_at.desc())  # (its last turn's)
        .limit(1)
    ).first()
    if note is None:
        return None
    said = [
        str(row.get("text") or "")
        for row in (note.blocks or {}).get("rows") or []
        if _not_done(row)
    ]
    pushed = session.scalar(
        select(Parked.id)
        .where(Parked.task_id == task.id, Parked.kind == "push", Parked.decision == "run")
        .limit(1)
    )
    return said + ([GITHUB] if pushed else [])


def add(session: Session, away: AwayRun, jobs: list[dict], tasks: dict[str, BacklogTask]) -> None:
    """Each started job of `away`'s report (`jobs`, as `away.report` made them) with its times, the
    night's decisions in its chat and what was not checked - where the night ended (one at work is
    not drawn: nothing of it is over). A decision of no job's chat is on no job."""
    from app import decisions  # (here: `app.decisions` reaches `app.away` through `app.agent`)

    ended = away.ended_at
    if away.status != "ended" or away.started_at is None or ended is None:
        return
    # (Nothing of what undoes a row is asked: the strip and its Markdown show none - and a report
    # is read for every night of a chat, after each decision of the morning.)
    log = decisions.of(session, away.project_id, away.started_at, ended, undo=False)
    by_chat: dict[str, list[Decision]] = {}
    for row in log.rows:
        if row.conversation_id is not None:
            by_chat.setdefault(row.conversation_id, []).append(row)
    for one in jobs:
        task = tasks.get(one.get("task_id") or "")
        cid = one.get("conversation_id")
        if task is None or not cid:
            continue
        one["started_at"], one["ended_at"] = times(session, away, ended, cid)
        one["decisions"] = by_chat.get(cid, [])
        one["not_checked"] = not_checked(session, away, ended, task, cid)
