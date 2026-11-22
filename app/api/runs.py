from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import literal_column, select
from sqlalchemy.orm import Session

from app import away, backlog
from app.agent import TERMINAL
from app.api.conversations import new_turn, queue_or_start
from app.api.deps import get_session, require_origin, require_own_origin
from app.api.usage import over_budget
from app.db.models import Conversation, Message, Run, now, project_of
from app.schemas import (
    BoardPostIn,
    BoardPostOut,
    PlanApproveIn,
    PlanRejectIn,
    PostMessageOut,
    SendIn,
)
from app.serialize import conversation_out, message_out, run_out
from app.tools import ToolError

router = APIRouter(prefix="/api/runs", tags=["runs"])


@router.post("/{run_id}/cancel", status_code=202, dependencies=[Depends(require_origin)])
async def cancel_run(run_id: str, request: Request, session: Session = Depends(get_session)):
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    if run.status in TERMINAL:
        raise HTTPException(409, "run already finished")
    stop(session, request, run)
    return {}


@router.post("/{run_id}/check/stop", dependencies=[Depends(require_own_origin)])
async def stop_check(run_id: str, request: Request, session: Session = Depends(get_session)):
    """"Stop this check" (kanıtlı bitiş S6): the turn's test run that runs now - its related
    tests while the answer waits, or its whole suite gone on after the answer - is stopped; what
    finished stays. The user's, from the app's own page, at every level."""
    if session.get(Run, run_id) is None:
        raise HTTPException(404, "run not found")
    if not request.app.state.runner.stop_check(run_id):
        raise HTTPException(409, "no check of this turn is running")
    return {}


def stop(session: Session, request: Request, run: Run) -> None:
    """The user's Stop on a turn that has not ended (also Stop everything's, `app.api.hold`)."""
    runner = request.app.state.runner
    if run.status != "queued" and runner.cancel(run.id):
        return
    # Never started, or its task is gone (the server restarted): settle it here.
    was_queued = run.status == "queued"
    run.status = "cancelled" if was_queued else "interrupted"
    run.ended_at = now()
    if not was_queued:  # (a queued one is not the turn a backlog task is worked in)
        backlog.turn_ended(session, run, run.status)
        away.turn_ended(session, run, run.status)
    session.commit()
    request.app.state.bus.emit(run.conversation_id, run.id, "run.finished", run_out(run))
    if not was_queued:
        runner.start_next(run.conversation_id)


def _over(session: Session, conversation: Conversation, go_on: bool) -> None:
    """Held back as a message's turn is over the budget (`post_message`), unless the user said
    to go on over it - already their word, from the app's own page."""
    project = project_of(session, conversation)
    if (over := over_budget(session, project, conversation)) and not go_on:
        raise HTTPException(409, f"this {'project' if project else 'chat'} is {over}: say to "
                                 "go on over it")


# Sent on the user's word, from the app's own page: an agent's request starts no turn.
@router.post("/{run_id}/send", response_model=PostMessageOut,
             dependencies=[Depends(require_own_origin)])
async def send_again(run_id: str, request: Request, body: SendIn | None = None,
                     session: Session = Depends(get_session)):
    """A message of the user's still queued when KOLONİ restarted, sent now: its turn runs, or
    waits behind one at work, as the newest - nothing is ever sent again by itself."""
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    message = session.scalar(select(Message).where(Message.run_id == run.id,
                                                   Message.role == "user").limit(1))
    if message is None or run.status != "interrupted" or run.started_at is not None or (
            not run.by_user or run.unattended or run.compare_id is not None):
        raise HTTPException(409, "only a message of yours that was never sent can be sent")
    conversation = session.get_one(Conversation, run.conversation_id)
    _over(session, conversation, bool(body and body.over_budget))
    queue_or_start(session, run)
    # The newest turn: last in the chat, in what its Lead is given and in the queue.
    run.ended_at, run.created_at = None, now()
    message.created_at = conversation.updated_at = run.created_at
    conversation.archived_at = None  # (the user writes in it again: it is back, as on a message)
    session.commit()
    bus = request.app.state.bus
    bus.emit(run.conversation_id, run.id, "run.updated", run_out(run))
    bus.emit(run.conversation_id, run.id, "message.created", message_out(message))
    bus.emit(run.conversation_id, None, "conversation.updated", conversation_out(conversation))
    if run.status == "running":
        request.app.state.runner.start(run.id)
    return {"message": message_out(message), "run": run_out(run)}


@router.post(
    "/{run_id}/notes", response_model=BoardPostOut, status_code=201,
    dependencies=[Depends(require_origin)],
)
async def write_note(
    run_id: str, body: BoardPostIn, request: Request, session: Session = Depends(get_session)
):
    """The user writes on a turn's shared notebook; every agent at work reads it."""
    if session.get(Run, run_id) is None:
        raise HTTPException(404, "run not found")
    text = body.content.strip()
    if not text:
        raise HTTPException(422, "the note is empty")
    try:
        note = request.app.state.runner.note_from_user(run_id, text)
    except ToolError as exc:
        raise HTTPException(422, str(exc)) from None
    if isinstance(note, str):
        raise HTTPException(409, note)
    return note


# What the work turn of an approved plan is told; the plan follows it, word for word.
APPROVED = "Go ahead: carry out the approved plan below.\n\nThe approved plan:\n"


def _proposed(session: Session, run_id: str) -> Run:
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    if not run.plan or run.plan["status"] != "proposed":
        raise HTTPException(409, "this turn has no plan waiting for a decision")
    return run


# The decision is the user's, from the app's own page: an agent's command against the
# app's address neither starts the work nor turns it down.
@router.post("/{run_id}/plan/approve", dependencies=[Depends(require_own_origin)])
async def approve_plan(
    run_id: str, body: PlanApproveIn, request: Request, session: Session = Depends(get_session)
):
    """The plan, as it was or as the user edited it, is approved: the work starts in a new
    turn of the same topic that carries it, with the conversation's own model and tools."""
    run = _proposed(session, run_id)
    newest = session.scalar(
        select(Run.id).where(Run.conversation_id == run.conversation_id)
        .order_by(Run.created_at.desc(), literal_column("runs.rowid").desc()).limit(1)
    )
    if newest != run.id:
        # The user wrote again instead: the work of an older plan would run beside, or
        # after, what came of that. It can still be turned down.
        raise HTTPException(
            409, "a later turn has started since this plan; reject it or ask again")
    conversation = session.get_one(Conversation, run.conversation_id)
    # The work spends as a message's turn does: held back the same way, the plan still
    # proposed.
    _over(session, conversation, body.over_budget)
    proposed = run.plan or {}  # (never empty: `_proposed` saw a plan)
    plan = (body.text or "").strip() or proposed["text"]
    run.plan = {**proposed, "text": plan, "status": "approved"}  # (a new dict: JSON is saved so)
    work, message = new_turn(session, run.conversation_id, run.topic_id, APPROVED + plan)
    conversation.updated_at = now()  # (activity, as a message is)
    session.commit()
    bus = request.app.state.bus
    bus.emit(run.conversation_id, run.id, "run.updated", run_out(run))
    bus.emit(run.conversation_id, work.id, "run.started", run_out(work))
    bus.emit(run.conversation_id, work.id, "message.created", message_out(message))
    bus.emit(run.conversation_id, None, "conversation.updated", conversation_out(conversation))
    if work.status == "running":
        request.app.state.runner.start(work.id)
    return {"run_id": work.id}


@router.post("/{run_id}/plan/reject", dependencies=[Depends(require_own_origin)])
async def reject_plan(
    run_id: str, body: PlanRejectIn, request: Request, session: Session = Depends(get_session)
):
    """The plan is turned down, with why if the user said: nothing more runs of it."""
    run = _proposed(session, run_id)
    run.plan = {**(run.plan or {}), "status": "rejected", "why": (body.why or "").strip() or None}
    session.commit()
    request.app.state.bus.emit(run.conversation_id, run.id, "run.updated", run_out(run))
    return {}
