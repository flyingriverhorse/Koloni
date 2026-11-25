"""Change and redo (karar defteri, Part B; §3.3, the user's Q7 (a)): on a card the Orchestrator
answered for the user, its agent finished since, the user's own answer in its place - and a
going-on turn of its chat, as §10's after a parked command (`AwayMixin._go_on_parked`): KOLONİ's
message, never the user's; the turn's kept copy gone on in; in a job's chat a job's turn (a
`Parked` row of kind "redo" it went on from: `away.going_on` - its work kept for Take in, on its
branch, held to the job's ceiling). The question and both answers are agents' and models' words:
masked, cut, marked where they read like orders and quoted - data, never an instruction. Only from
the app's own page (`api.questions`); not while the project is away, nor twice for one decision."""

from typing import cast

from sqlalchemy import CursorResult, func, select, update
from sqlalchemy.orm import Session

from app import away, backlog, decisions
from app.agent.words import AGENT_TERMINAL, KOLONIS
from app.api.usage import over_budget
from app.db.away_models import Parked
from app.db.models import Agent, Conversation, Message, Project, Question, Run, now
from app.serialize import conversation_out, message_out, question_out, run_out
from app.team import quoted

REDO = (
    KOLONIS
    + ": the user changed your answer to {question}: {new} (was {old}). Go on with the task."
)
NOTHING = "the Orchestrator decided nothing by that id in this project"
CHANGED = "you changed this decision already"
AGENT_AT_WORK = "the agent that asked is at work: Change it instead"
CHAT_AT_WORK = "a turn of its chat is at work: try again once it is over"
NOT_AN_OPTION = "change it to another of its options"
# (§10: a going-on turn now would be its job's second one - what it parked waits for it, then the
# rows' own turn; once decided, Change and redo goes on after it.)
PARKED_FIRST = "decide what its job parked first"


class Refused(ValueError):
    """Change and redo not taken, with its HTTP status: 404 no such decision of the project's, 409
    not now (or not any more), 422 not one of its options."""

    def __init__(self, status: int, why: str):
        super().__init__(why)
        self.status = status


def told(question: str, old: str | None, new: str) -> str:
    """KOLONİ's message to the chat: what the user changed - each word of the card's as the log
    shows it (`decisions.said`: masked, cut, marked) and quoted: none passes for KOLONİ's."""

    def data(text: str | None) -> str:
        return quoted(decisions.said(text) or "")

    return REDO.format(question=data(question), new=data(new), old=data(old))


def _decision(session: Session, project_id: str, question_id: str) -> tuple[Question, Run]:
    """The card the Orchestrator answered in project `project_id`, and the turn it was asked in."""
    question = session.get(Question, question_id)
    turn = session.get(Run, question.run_id) if question is not None else None
    chat = session.get(Conversation, turn.conversation_id) if turn is not None else None
    if (
        question is None
        or turn is None
        or chat is None
        or chat.project_id != project_id
        or question.status != "answered"
    ):
        raise Refused(404, NOTHING)
    if question.lead_why is None:
        # (Change and Change and redo clear the Orchestrator's why, and mark it looked at.)
        raise Refused(409, CHANGED) if question.seen_at is not None else Refused(404, NOTHING)
    return question, turn


def _allowed(
    session: Session, project_id: str, question: Question, chat: str, new: str
) -> str | None:
    """The kept copy the going-on turn goes on in, by its Merge's id (None: a fresh one), where
    Change and redo may be done now - else `Refused`, why not."""
    if away.running(session, project_id) is not None:
        raise Refused(409, away.AWAY_NOW)
    if new not in decisions.offered(question):
        raise Refused(422, NOT_AN_OPTION)
    asker = session.get(Agent, question.agent_id)
    merge, gone = decisions.work(session, question)
    at_work = asker is not None and asker.status not in AGENT_TERMINAL
    undo, why = decisions.card_undo(question, at_work, lambda: gone)
    if undo != "change_and_redo":
        raise Refused(409, AGENT_AT_WORK if undo == "change" else why or NOTHING)
    if session.scalar(
        select(Run.id).where(Run.conversation_id == chat, Run.status.not_in(backlog.ENDED)).limit(1)
    ):
        raise Refused(409, CHAT_AT_WORK)
    if (job := away.job_of(session, chat)) is not None and away.parked_left(session, job.id):
        raise Refused(409, PARKED_FIRST)
    if over := over_budget(
        session, session.get(Project, project_id), session.get(Conversation, chat)
    ):
        raise Refused(409, f"The project is {over}.")
    return merge


def redo(session: Session, project_id: str, question_id: str, answer: str, runner) -> str:
    """The user's Change and redo: their answer on record in place of the Orchestrator's - looked
    at, as Change leaves it - and a going-on turn of its chat on KOLONİ's message, started. Its
    run's id; `Refused`: why not. Nothing awaited between the last look and the commit: a second
    click finds it changed (and the record's own condition holds it besides)."""
    question, turn = _decision(session, project_id, question_id)
    cid, new, old = turn.conversation_id, answer.strip(), question.answer
    merge = _allowed(session, project_id, question, cid, new)
    marked = session.execute(
        update(Question)
        .where(
            Question.id == question.id,
            Question.lead_why.is_not(None),
            Question.seen_at.is_(None),
            Question.answer == old,
        )
        .values(answer=new, lead_why=None, seen_at=now())
    )
    if cast(CursorResult, marked).rowcount != 1:
        session.rollback()
        raise Refused(409, CHANGED)
    task = away.job_of(session, cid)
    run = Run(
        conversation_id=cid,
        topic_id=turn.topic_id,
        status="running",
        started_at=now(),
        task_id=task.id if task is not None else None,
    )
    session.add(run)
    session.flush()
    message = Message(
        conversation_id=cid, run_id=run.id, role="user", content=told(question.question, old, new)
    )
    session.add(message)
    chat = session.get_one(Conversation, cid)
    chat.archived_at = (
        None  # (written in again, by the user's own click: it is back, as on a message)
    )
    if task is not None and task.away_run_id is not None:  # (a job's chat: a job's turn, §10)
        seq = session.scalar(
            select(func.max(Parked.seq)).where(Parked.away_run_id == task.away_run_id)
        )
        session.add(
            Parked(
                away_run_id=task.away_run_id,
                task_id=task.id,
                seq=(seq or 0) + 1,
                kind="redo",
                ref_id=question.id,
                what=question.question,
                decision="answer",
                answer=new,
                went_on=run.id,
                decided_at=now(),
            )
        )
        task.status, task.away_state, task.away_why = "doing", None, None
    session.commit()
    session.refresh(question)
    runner.bus.emit(cid, question.run_id, "question.updated", question_out(question))
    runner.bus.emit(cid, run.id, "run.started", run_out(run))
    runner.bus.emit(cid, run.id, "message.created", message_out(message))
    runner.bus.emit(cid, None, "conversation.updated", conversation_out(chat))
    if merge is not None:  # (its kept copy, none of it taken in: `decisions.work`)
        runner.resume_on(run.id, merge)
    runner.start(run.id)
    return run.id
