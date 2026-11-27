"""The decision log (karar defteri) of a project, for Today's Decisions: read only - there is no
way here to add, change or delete one of its rows (the Orchestrator's note_decision only adds one
of its own). The user's OK and Change on a decision it noted (0.1.11) are theirs alone, from the
app's own page."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import away, decisions, masking
from app.agent.words import KOLONIS
from app.api.conversations import post_message, queue_or_start
from app.api.deps import get_session, require_origin, require_own_origin
from app.api.usage import over_budget
from app.db.models import Conversation, Message, Project, Run, now, project_of
from app.db.turn_models import NotedDecision
from app.schemas_at_work import MessageIn, PostMessageOut
from app.schemas_decisions import DecisionLog
from app.serialize import message_out, run_out
from app.team import quoted

router = APIRouter(prefix="/api/projects", tags=["decisions"])


# (Not async: it reads the database for as long as a long night takes - in a worker thread, not on
# the event loop.)
@router.get("/{project_id}/decisions", response_model=DecisionLog)
def read(
    project_id: str,
    since: datetime | None = None,
    until: datetime | None = None,
    unseen: bool = False,
    session: Session = Depends(get_session),
):
    """What was decided for the user in the project from `since` until `until` (each where
    given), newest first, and how many commands the judge found fine meanwhile. `unseen`: only
    those that wait for your OK, of any age."""
    if session.get(Project, project_id) is None:
        raise HTTPException(404, "project not found")
    try:
        since, until = (None if at is None else decisions.utc(at) for at in (since, until))
    except OverflowError:
        raise HTTPException(422, "since and until must be times UTC can hold") from None
    return decisions.of(session, project_id, since, until, unseen)


# --- Task 10 (0.1.11): the user's OK and Change on a decision the Orchestrator noted ----------

noted_router = APIRouter(
    prefix="/api/decisions",
    tags=["decisions"],
    # (the user's own word on it, from the app's own page: never an agent's command)
    dependencies=[Depends(require_origin), Depends(require_own_origin)],
)
# The user's Change, into the decision's own turn while it takes a word (Send now): KOLONİ's id of
# the decision, which the Orchestrator's note_decision answer named, and the user's words - no word
# of the Orchestrator's in a message of the user's (Check what I said first reads those).
CHANGE_NOW = "I change your decision {id}: {words}"
# ...and, its turn over, in a turn of KOLONİ's of its chat, as Change and redo's (`app.redo`): its
# words and the user's quoted, as data.
CHANGE_LATER = (
    KOLONIS + ": the user changed your decision {what} (decision {id}): {words}. Take it into "
    "account and go on with the task."
)
JOB_CHAT = "it was decided in a job's chat while you were away: write your change in that chat"


class NotedChangeIn(BaseModel):
    words: str = Field(min_length=1, max_length=1000)


def _noted(session: Session, decision_id: str) -> tuple[NotedDecision, Run]:
    row = session.get(NotedDecision, decision_id)
    if row is None:
        raise HTTPException(404, "the Orchestrator noted no decision by that id")
    return row, session.get_one(Run, row.run_id)


@noted_router.post("/{decision_id}/ok", status_code=204)
def noted_ok(decision_id: str, session: Session = Depends(get_session)):
    """The user's OK on a noted decision: it stays in the log, seen."""
    row, _turn = _noted(session, decision_id)
    row.seen_at = row.seen_at or now()
    session.commit()


@noted_router.post("/{decision_id}/change", response_model=PostMessageOut, status_code=201)
async def noted_change(
    decision_id: str, body: NotedChangeIn, request: Request, session: Session = Depends(get_session)
):
    """The user's Change on a noted decision, in their own words: into its turn while that one is
    at work and takes a word - Send now's own way (`post_message`); else in a turn of KOLONİ's of
    its chat, queued behind one at work - not a job's chat (`JOB_CHAT`). Seen once sent."""
    row, turn = _noted(session, decision_id)
    words = " ".join(body.words.split())
    if not words:
        raise HTTPException(422, "say what you decide instead")
    cid = turn.conversation_id
    project = project_of(session, session.get_one(Conversation, cid))
    if project is not None and away.running(session, project.id) is not None:
        raise HTTPException(409, away.AWAY_NOW)
    if over := over_budget(session, project, session.get_one(Conversation, cid)):
        raise HTTPException(409, f"The project is {over}.")
    into, _why = request.app.state.runner.takes_word(cid, turn.topic_id)
    if into == turn.id:
        said = MessageIn(
            content=CHANGE_NOW.format(id=row.id, words=words), now=True, topic_id=turn.topic_id
        )
        posted = await post_message(cid, said, request, session)
        row.seen_at = row.seen_at or now()  # (once the word is on record)
        session.commit()
        return posted
    if away.job_of(session, cid) is not None:
        # shortcut: a job's chat goes on in a job's turn - its branch, its work kept for Take in
        # (`app.redo`'s); a plain turn there would be none. Refused, said why; go on as redo does
        # if a Change of a job's noted decision is seen wanted.
        raise HTTPException(409, JOB_CHAT)
    row.seen_at = row.seen_at or now()
    run = Run(conversation_id=cid, topic_id=turn.topic_id)
    queue_or_start(session, run)
    session.add(run)
    session.flush()
    told = CHANGE_LATER.format(
        what=quoted(decisions.said(row.what) or ""), id=row.id, words=quoted(masking.masked(words))
    )
    message = Message(conversation_id=cid, run_id=run.id, role="user", content=told)
    session.add(message)
    session.commit()
    bus = request.app.state.bus
    bus.emit(cid, run.id, "run.started", run_out(run))
    bus.emit(cid, run.id, "message.created", message_out(message))
    if run.status == "running":
        request.app.state.runner.start(run.id)
    return {"message": message_out(message), "run": run_out(run), "queued_why": None}
