import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.deps import get_session, require_own_origin
from app.db.models import Question, Run, now
from app.schemas import AnswerIn, QuestionOut
from app.serialize import question_out

# An answer is the user's word - and where a question asks leave for a tool, their yes: it
# is taken only from the app's own page, not from a command an agent runs against the
# app's address.
router = APIRouter(prefix="/api", tags=["questions"], dependencies=[Depends(require_own_origin)])

DECISION_TIMEOUT = 5.0


@router.post("/questions/{question_id}/answer", response_model=QuestionOut)
async def answer(
    question_id: str, body: AnswerIn, request: Request, session: Session = Depends(get_session)
):
    question = session.get(Question, question_id)
    if question is None:
        raise HTTPException(404, "question not found")
    text = body.answer.strip()
    if not text:
        raise HTTPException(422, "the answer is empty")
    # B-326: a card of KOLONİ's own (`leave`) takes one of its options, as written there, and
    # nothing else - a step failed card asked again at once for any other word - but where it
    # offers Ask for changes, the user's own words are that (B-112; the page sends "Ask for
    # changes: <words>"). shortcut: the "Who checks?" card's names past its six buttons ("Or
    # write one of") are refused here too; put them in its options when a team has that many.
    if question.leave and question.options and "Ask for changes" not in question.options:
        text = next((one for one in question.options if one.casefold() == text.casefold()), "")
        if not text:
            raise HTTPException(
                422, f"answer with one of its options: {', '.join(question.options)}")
    # (Its record says first: one no longer current - its turn over, asked again - takes none.)
    if question.status != "pending" or not request.app.state.runner.answer_question(
            question_id, text):
        raise HTTPException(409, "this question is no longer waiting for an answer")
    # The agent task records the answer; reply once it has.
    deadline = asyncio.get_running_loop().time() + DECISION_TIMEOUT
    while True:
        await asyncio.sleep(0.01)
        session.refresh(question)
        if question.status != "pending" or asyncio.get_running_loop().time() > deadline:
            break
    # (Superseded: heard, and its card asked again at once - G5.4.)
    if question.status not in ("answered", "superseded"):
        # Stop got there first: the agent never saw the answer.
        raise HTTPException(409, "this question is no longer waiting for an answer")
    return question_out(question)


# "Decided for you" (K-vekil-karar): what the Lead answered for the user while they were away.
def _decided(session: Session, question_id: str) -> Question:
    question = session.get(Question, question_id)
    if question is None or question.lead_why is None:
        raise HTTPException(404, "the Lead decided nothing by that id")
    if question.seen_at is not None:
        raise HTTPException(409, "you looked at this decision already")
    return question


def _seen(request: Request, session: Session, question: Question) -> dict:
    """It leaves "Decided for you": said to whoever watches its chat."""
    question.seen_at = now()
    session.commit()
    payload = question_out(question)
    request.app.state.bus.emit(session.get_one(Run, question.run_id).conversation_id,
                               question.run_id, "question.updated", payload)
    return payload


# (async: the bus and the runner are the event loop's, not a worker thread's)
@router.post("/questions/{question_id}/ok", response_model=QuestionOut)
async def ok(question_id: str, request: Request, session: Session = Depends(get_session)):
    return _seen(request, session, _decided(session, question_id))


@router.post("/questions/{question_id}/change", response_model=QuestionOut)
async def change(
    question_id: str, body: AnswerIn, request: Request, session: Session = Depends(get_session)
):
    """The user's own answer in place of the Lead's, to the agent that asked while it is at
    work; on record as the user's (the next turn's Lead reads it so), and looked at, as with OK."""
    question = _decided(session, question_id)
    text = body.answer.strip()
    if not text or text == question.answer or (question.options and text not in question.options):
        raise HTTPException(422, "change it to another of its options")
    if why := await request.app.state.runner.change_lead_answer(question, text):
        raise HTTPException(409, why)
    question.answer, question.lead_why = text, None
    return _seen(request, session, question)
