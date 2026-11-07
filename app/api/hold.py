"""Stop everything (K-hepsini-durdur): one Stop for every turn of every chat, each as its own
Stop does (`runs.stop`) - a night's job as its Stop all cuts it (`away.stop`); and what
starts by itself - triggers, a backlog that works itself, a night's next job - waits until
Resume (`backlog.held`). The user's own messages are not held: what the user sends still starts.
The hold is a row of `flags`, so it outlives a restart with no table of its own.
shortcut: KOLONİ's own model calls after a turn that ended (a task's assessment, the note of
what it found, the summary of its older part) are not stopped, and a turn of the user's that
ends while held still makes them; skip them while held if that is ever in the way."""

import asyncio
import contextlib
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app import away, backlog
from app.agent import TERMINAL, announce
from app.api.deps import get_session, require_own_origin
from app.api.runs import stop
from app.db.models import AwayRun, BacklogTask, Conversation, Flag, Project, Run, Trigger, now
from app.schemas import HoldOut

router = APIRouter(prefix="/api", tags=["hold"])
OWN = [Depends(require_own_origin)]
NIGHT_STOPPED = "Stopped by you: Stop everything."
# How long Stop waits for the turns it stopped to end, so that its answer lists them.
WAIT_SECONDS = 10
# shortcut: the list shows the newest 50 turns stopped; page it if a hold ever stops more.
SHOWN = 50
# R147: Resume lets go of what starts by itself; a turn it stopped goes on only by a message.
STAY_STOPPED = "{n} stopped {turns} stopped - send a message to go on."


def _stay(stopped: int) -> str | None:
    return STAY_STOPPED.format(n=stopped, turns="turn stays" if stopped == 1 else "turns stay"
                               ) if stopped else None


def _told(request: Request, project_id: str) -> None:
    announce(request.app.state.session_factory, request.app.state.bus, project_id,
             "backlog.changed")


def _state(session: Session) -> dict:
    flag = session.get(Flag, backlog.HOLD)
    since = datetime.fromisoformat(flag.value) if flag else None
    stopped, stopping = [], 0
    if since is not None:
        # What it stopped: the turns there were as it began that ended stopped since.
        stopped = [
            {"run_id": run_id, "conversation_id": cid, "title": title, "project": project,
             "created_at": created_at}
            for run_id, cid, title, project, created_at in session.execute(
                select(Run.id, Run.conversation_id, Conversation.title, Project.name,
                       Run.created_at)
                .join(Conversation, Conversation.id == Run.conversation_id)
                .outerjoin(Project, Project.id == Conversation.project_id)
                .where(Run.created_at <= since, Run.ended_at >= since,
                       Run.status.in_(("cancelled", "interrupted")))
                .order_by(Run.ended_at.desc()).limit(SHOWN))
        ]
        # ...and those it stopped that have not ended yet (a CLI's that takes its time).
        stopping = session.scalar(select(func.count()).select_from(Run).where(
            Run.created_at <= since, Run.status.not_in(TERMINAL)))
    return {
        "held": since is not None,
        "since": since,
        "running": session.scalar(
            select(func.count()).select_from(Run).where(Run.status.not_in(TERMINAL))),
        "triggers": session.scalar(
            select(func.count()).select_from(Trigger).where(Trigger.enabled)),
        "backlogs": list(session.scalars(select(Project.name).where(Project.backlog_auto))),
        "nights": list(session.scalars(
            select(Project.name).join(AwayRun, AwayRun.project_id == Project.id)
            .where(AwayRun.status == "running"))),
        "stopped": stopped,
        "stopping": stopping,
        "stays_stopped": _stay(len(stopped)),
    }


@router.get("/hold", response_model=HoldOut)
async def read_hold(session: Session = Depends(get_session)):
    return _state(session)


@router.post("/hold", response_model=HoldOut, dependencies=OWN)
async def stop_everything(request: Request, session: Session = Depends(get_session)):
    """Hold first - a turn that ends starts no next task, no night's job - then stop."""
    if not backlog.held(session):
        session.add(Flag(name=backlog.HOLD, value=now().isoformat()))
        session.commit()
    runner = request.app.state.runner
    for night in session.scalars(select(AwayRun).where(AwayRun.status == "running")).all():
        away.stop(session, night, NIGHT_STOPPED, runner, ends=False)
        _told(request, night.project_id)
    runs = session.scalars(select(Run).where(Run.status.not_in(TERMINAL))).all()
    ids = [run.id for run in runs]
    # Queued first: a turn that stops starts the one queued behind it (`start_next`).
    for run in sorted(runs, key=lambda run: run.status != "queued"):
        if run.status not in TERMINAL:  # (read again: it may have ended meanwhile)
            stop(session, request, run)
    session.commit()  # (nothing held open while the turns end)
    # Shielded: given up at the time, the wait must not cancel the turns a second time - in
    # the middle of their own cleanup (a copy's folder, a CLI's processes).
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(asyncio.shield(asyncio.gather(
            *(runner.wait(run_id) for run_id in ids))), WAIT_SECONDS)
    return _state(session)


@router.post("/hold/resume", response_model=HoldOut, dependencies=OWN)
async def resume(request: Request, session: Session = Depends(get_session)):
    """What was held goes on: each trigger from its next time, each backlog that works
    itself with its next task, each night with its next job. What was stopped stays stopped,
    and the answer says so (`stays_stopped`, read before the hold that lists them goes)."""
    flag = session.get(Flag, backlog.HOLD)
    stays = _state(session)["stays_stopped"]
    if flag is not None:
        session.delete(flag)
        session.commit()
        state = request.app.state
        state.triggers.resumed(now())
        # (A run of the backlog: by itself, or what Run the backlog queued, or a fix round due.)
        for project_id in session.scalars(select(Project.id).where(or_(
                Project.backlog_auto, Project.id.in_(select(BacklogTask.project_id).where(
                    BacklogTask.status.in_(("todo", "doing"))))))).all():
            if backlog.chain(session, project_id, state.bus, state.runner.start):
                _told(request, project_id)
        for project_id in session.scalars(
                select(AwayRun.project_id).where(AwayRun.status == "running")).all():
            if away.go_on(session, project_id, state.runner):
                _told(request, project_id)
    return {**_state(session), "stays_stopped": stays}
