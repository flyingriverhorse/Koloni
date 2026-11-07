"""While the user is away (slice 106), for the user: the Lead's card, changed and started -
or put away - only from the app's own page (`require_own_origin`), so that no agent, trigger
or page of an agent's starts a night; the night's state for the To-do page, the top bar and
the morning's node; Stop all, and Try again for a job that could not be done."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import away, backlog
from app.agent import announce
from app.api.deps import get_session, require_own_origin
from app.db.models import AwayRun, BacklogTask, Conversation, Project, Run, now
from app.schemas import AwayIn, AwayOut

router = APIRouter(prefix="/api", tags=["away"])
OWN = [Depends(require_own_origin)]


def _away(session: Session, away_id: str) -> AwayRun:
    found = session.get(AwayRun, away_id)
    if found is None:
        raise HTTPException(404, "no such card")
    return found


def _told(request: Request, project_id: str) -> None:
    announce(request.app.state.session_factory, request.app.state.bus, project_id,
             "backlog.changed")


@router.get("/projects/{project_id}/away", response_model=AwayOut | None)
async def read_night(project_id: str, session: Session = Depends(get_session)):
    """The project's night that runs, else its last one; null: it never had one."""
    if session.get(Project, project_id) is None:
        raise HTTPException(404, "project not found")
    night = away.running(session, project_id) or session.scalar(
        select(AwayRun).where(AwayRun.project_id == project_id, AwayRun.status == "ended")
        .order_by(AwayRun.started_at.desc()).limit(1))
    return away.report(session, night) if night else None


@router.get("/conversations/{cid}/away", response_model=list[AwayOut])
async def read_cards(cid: str, session: Session = Depends(get_session)):
    """The cards the Lead put in this chat, oldest first - with their nights."""
    if session.get(Conversation, cid) is None:
        raise HTTPException(404, "conversation not found")
    return [away.report(session, one) for one in session.scalars(
        select(AwayRun).where(AwayRun.conversation_id == cid).order_by(AwayRun.created_at))]


@router.patch("/away/{away_id}", response_model=AwayOut, dependencies=OWN)
async def change_card(away_id: str, body: AwayIn, request: Request,
                      session: Session = Depends(get_session)):
    card = _away(session, away_id)
    fields = body.model_dump(exclude_unset=True)
    try:
        away.change(session, card, fields)
    except away.Refused as exc:
        raise HTTPException(409, str(exc)) from None
    session.commit()
    return away.report(session, card)


@router.post("/away/{away_id}/start", response_model=AwayOut, dependencies=OWN)
async def start(away_id: str, request: Request, session: Session = Depends(get_session)):
    """The user's Start: the only way a night begins."""
    card = _away(session, away_id)
    try:
        away.start(session, card, request.app.state.runner)
    except away.Refused as exc:
        raise HTTPException(409, str(exc)) from None
    _told(request, card.project_id)
    session.refresh(card)
    return away.report(session, card)


@router.post("/away/{away_id}/dismiss", response_model=AwayOut, dependencies=OWN)
async def dismiss(away_id: str, request: Request, session: Session = Depends(get_session)):
    """Not now: the card is put away, nothing started."""
    card = _away(session, away_id)
    if card.status != "planned":
        raise HTTPException(409, "only a card not started yet is put away")
    card.status = "dismissed"
    session.commit()
    return away.report(session, card)


@router.post("/away/{away_id}/stop", response_model=AwayOut, dependencies=OWN)
async def stop_all(away_id: str, request: Request, session: Session = Depends(get_session)):
    """Stop all: the job at work stops, its copy kept, and no other starts. One that waits for
    the user's word waits on."""
    card = _away(session, away_id)
    if card.status != "running":
        raise HTTPException(409, "this card's jobs are not running")
    away.stop(session, card, "Stopped by you.", request.app.state.runner)
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
async def try_again(away_id: str, task_id: str, request: Request,
                    session: Session = Depends(get_session)):
    """Try again: a job that could not be done or was stopped, worked on in its chat again - a
    turn of the user's own, the night over."""
    card = _away(session, away_id)
    task = session.get(BacklogTask, task_id)
    if task is None or task.away_run_id != card.id or task.conversation_id is None:
        raise HTTPException(404, "no such job of this card")
    if card.status == "running" or task.away_state not in ("failed", "stopped"):
        raise HTTPException(409, "only a job that could not be done or stopped, once its run "
                                 "is over")
    if session.scalar(select(Run.id).where(Run.conversation_id == task.conversation_id,
                                           Run.status.not_in(backlog.ENDED)).limit(1)):
        raise HTTPException(409, "a turn of its chat is at work: try again once it is over")
    runner = request.app.state.runner
    task.status, task.away_state, task.away_why = "doing", None, None
    backlog.say(session, session.get_one(Conversation, task.conversation_id), away.AGAIN,
                runner.bus, runner.start)
    _told(request, card.project_id)
    return away.report(session, card)
