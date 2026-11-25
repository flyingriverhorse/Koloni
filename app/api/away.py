"""☾ Away (slice 106), for the user: Go away and I'm back only from the app's own page
(`require_own_origin`), so that no agent, trigger or page of an agent's starts it; its state for
the chat, the To-do page, the top bar and the morning's node; Stop all, and Try again for a job
that could not be done. Waiting for you (§10): what the jobs parked for the user, decided only from
the app's own page - Run, Reject, an answer, Stop this task."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import away, backlog, parked
from app.agent import announce
from app.api.deps import get_session, require_own_origin
from app.db.models import AwayRun, BacklogTask, Conversation, Project, Run, now
from app.schemas import AwayGoIn, AwayOut
from app.serialize import message_out

router = APIRouter(prefix="/api", tags=["away"])
OWN = [Depends(require_own_origin)]


class WaitingOut(BaseModel):
    """A row of Waiting for you (`parked.waiting`): what a job parked, why in KOLONİ's words alone,
    and - not decided yet - why it cannot be now (`closed`; None: it can)."""

    id: str
    kind: str  # `parked.KINDS`: "command", "question"...
    task_id: str
    task: str
    conversation_id: str | None
    what: str  # the line or the question, whole: data
    cwd: str | None
    why: str
    warn: str | None  # (`injection.NOTE` where it reads like orders)
    options: list[str]
    decision: str | None
    answer: str | None
    result: str | None
    closed: str | None
    seq: int


class DecideIn(BaseModel):
    word: Literal["run", "reject", "answer"]
    answer: str | None = Field(default=None, max_length=4000)


def _away(session: Session, away_id: str) -> AwayRun:
    found = session.get(AwayRun, away_id)
    if found is None:
        raise HTTPException(404, "no such card")
    return found


def _told(request: Request, project_id: str) -> None:
    announce(
        request.app.state.session_factory, request.app.state.bus, project_id, "backlog.changed"
    )


@router.get("/projects/{project_id}/away", response_model=AwayOut | None)
async def read_night(project_id: str, session: Session = Depends(get_session)):
    """The project's night that runs, else its last one; null: it never had one."""
    if session.get(Project, project_id) is None:
        raise HTTPException(404, "project not found")
    night = away.running(session, project_id) or session.scalar(
        select(AwayRun)
        .where(AwayRun.project_id == project_id, AwayRun.status == "ended")
        .order_by(AwayRun.started_at.desc())
        .limit(1)
    )
    return away.report(session, night) if night else None


@router.get("/conversations/{cid}/away", response_model=list[AwayOut])
async def read_cards(cid: str, session: Session = Depends(get_session)):
    """The cards the Lead put in this chat, oldest first - with their nights."""
    if session.get(Conversation, cid) is None:
        raise HTTPException(404, "conversation not found")
    return [
        away.report(session, one)
        for one in session.scalars(
            select(AwayRun).where(AwayRun.conversation_id == cid).order_by(AwayRun.created_at)
        )
    ]


@router.post("/conversations/{cid}/away", response_model=AwayOut, dependencies=OWN)
async def go_away(
    cid: str, body: AwayGoIn, request: Request, session: Session = Depends(get_session)
):
    """The user's Go away from this chat: the only way Away begins."""
    conversation = session.get(Conversation, cid)
    if conversation is None:
        raise HTTPException(404, "conversation not found")
    try:
        night = away.go(session, conversation, body.model_dump(), request.app.state.runner)
    except away.Refused as exc:
        raise HTTPException(409, str(exc)) from None
    _told(request, night.project_id)
    session.refresh(night)
    return away.report(session, night)


@router.post("/away/{away_id}/back", response_model=AwayOut, dependencies=OWN)
async def come_back(away_id: str, request: Request, session: Session = Depends(get_session)):
    """I'm back: Away ends, its summary in the chat; the job at work finishes."""
    card = _away(session, away_id)
    if card.status != "running":
        raise HTTPException(409, "you're not away from this project")
    said = away.back(session, card.project_id)
    if said is not None:
        request.app.state.bus.emit(card.conversation_id, None, "message.created", message_out(said))
    state = request.app.state  # (the chats' To-do queues waited while the user was away)
    backlog.go_on(session, card.project_id, state.bus, state.runner.start)
    _told(request, card.project_id)
    session.refresh(card)
    return away.report(session, card)


@router.post("/away/{away_id}/stop", response_model=AwayOut, dependencies=OWN)
async def stop_all(away_id: str, request: Request, session: Session = Depends(get_session)):
    """Stop all: the job at work stops, its copy kept, and no other starts - one that waits for
    the user's word too, and the chat gone from's turn."""
    card = _away(session, away_id)
    if card.status != "running":
        raise HTTPException(409, "this card's jobs are not running")
    away.stop(session, card, "Stopped by you.", request.app.state.runner, waiting=True)
    _told(request, card.project_id)
    session.refresh(card)
    return away.report(session, card)


@router.post("/away/{away_id}/seen", status_code=204, dependencies=OWN)
async def seen(away_id: str, session: Session = Depends(get_session)):
    """The night's report was on the user's screen: KOLONİ opened from now on does not go to it."""
    card = _away(session, away_id)
    if card.status == "ended" and card.seen_at is None:
        card.seen_at = now()
        session.commit()
    return Response(status_code=204)


@router.post("/away/{away_id}/jobs/{task_id}/again", response_model=AwayOut, dependencies=OWN)
async def try_again(
    away_id: str, task_id: str, request: Request, session: Session = Depends(get_session)
):
    """Try again: a job that could not be done or was stopped, worked on in its chat again - a
    turn of the user's own, the night over."""
    card = _away(session, away_id)
    if card.status == "running":
        raise HTTPException(409, away.AWAY_NOW)
    task = session.get(BacklogTask, task_id)
    if task is None or task.away_run_id != card.id or task.conversation_id is None:
        raise HTTPException(404, "no such job of this card")
    if task.away_state not in ("failed", "stopped"):
        raise HTTPException(409, "only a job that could not be done or stopped")
    if session.scalar(
        select(Run.id)
        .where(Run.conversation_id == task.conversation_id, Run.status.not_in(backlog.ENDED))
        .limit(1)
    ):
        raise HTTPException(409, "a turn of its chat is at work: try again once it is over")
    runner = request.app.state.runner
    parked.close_rows(session, task)  # (§10: what it parked is not decided now)
    task.status, task.away_state, task.away_why = "doing", None, None
    backlog.say(
        session,
        session.get_one(Conversation, task.conversation_id),
        away.AGAIN,
        runner.bus,
        runner.start,
        task_id=task.id,
    )
    _told(request, card.project_id)
    return away.report(session, card)


@router.get("/away/{away_id}/waiting", response_model=list[WaitingOut])
async def read_waiting(away_id: str, session: Session = Depends(get_session)):
    """Waiting for you: what the card's jobs parked, its jobs in order, each in the order parked."""
    return parked.waiting(session, _away(session, away_id))


@router.post("/away/{away_id}/waiting/{item_id}", response_model=list[WaitingOut], dependencies=OWN)
async def decide_waiting(
    away_id: str,
    item_id: str,
    body: DecideIn,
    request: Request,
    session: Session = Depends(get_session),
):
    """The user's Run, Reject or answer of a parked row - only from the app's own page."""
    card = _away(session, away_id)
    try:
        await parked.decide(session, card, item_id, body.word, body.answer)
    except parked.Refused as exc:
        raise HTTPException(exc.status, str(exc)) from None
    _told(request, card.project_id)
    return parked.waiting(session, card)


@router.post("/away/{away_id}/jobs/{task_id}/stop", response_model=AwayOut, dependencies=OWN)
async def stop_task(
    away_id: str, task_id: str, request: Request, session: Session = Depends(get_session)
):
    """Stop this task: what it parked is closed, it is stopped - no going-on turn."""
    card = _away(session, away_id)
    if card.status == "running":
        raise HTTPException(409, away.AWAY_NOW)
    task = session.get(BacklogTask, task_id)
    if task is None or task.away_run_id != card.id:
        raise HTTPException(404, "no such job of this card")
    if task.away_state != "waits":
        raise HTTPException(409, "only a job that waits for you")
    parked.stop(session, card, task)
    _told(request, card.project_id)
    return away.report(session, card)
