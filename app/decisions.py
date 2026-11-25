"""The decision log (karar defteri, Part A): what was decided for the user in one project, by whom
and why - by the Orchestrator (the cards it answered, the sub-agents it opened or not, the Scout's
To-do proposals it took or turned down), by KOLONİ's judge (a command refused, or found risky) and
by the user's own words (Check what I said first). Read from the records that keep each of them: no
table of its own, no model asked, and nothing writes here - no row is added, changed or hidden by an
agent. The judge's "fine" is counted, not listed. Agents' and models' words are masked, cut and
marked where they read like orders (`said`); they are shown, never given to an agent as orders.
shortcut: read from the records, a row leaves the log where its record changes - the user's own
Change clears the Orchestrator's why (`api.questions.change`), and an added task turned down is
deleted; give decisions a table of their own (approach B) if the log must keep those."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import InstrumentedAttribute, Session

from app import injection, raw
from app.agent.spawn_mixin import SPAWN_WORDS
from app.agent.words import AGENT_TERMINAL
from app.db.models import Agent, BacklogTask, Command, Conversation, Question, Run
from app.schemas_decisions import Decision, DecisionLink, DecisionLog

SAID_MOST = 300  # characters of an agent's or a model's words a row shows
# (`spawn_mixin._spawn_word`'s card: the one of KOLONİ's cards with these two options)
SPAWN = list(SPAWN_WORDS)
FROM = {
    "preferences": "your preferences",
    "rules": "this project's rules",
    "message": "your message",
}

When = ColumnElement[datetime] | InstrumentedAttribute[datetime]
Window = Callable[[When], list[ColumnElement[bool]]]


def said(text: str | None) -> str | None:
    """An agent's or a model's words as a row shows them: every secret KOLONİ knows masked - before
    the cut, which could leave half of one -, on one line, cut, and after `injection.NOTE` where the
    whole reads like orders. None for none."""
    if not text:
        return None
    shown = " ".join(raw.hidden(text).split())
    cut = shown if len(shown) <= SAID_MOST else shown[: SAID_MOST - 1] + "…"
    return f"{injection.NOTE} {cut}" if injection.scan(shown) else cut


def _utc(at: datetime) -> datetime:
    return at.astimezone(UTC) if at.tzinfo else at.replace(tzinfo=UTC)


def _card_undo(leave: bool, seen: bool, at_work: bool, others: bool) -> str | None:
    """Why today's Change no longer works on a card's answer (`api.questions.change`); None: it
    does. shortcut: not where its agent is a CLI that hears nothing more (`steer`) - known only to
    the runner at work; the Change says so when pressed."""
    if leave:
        return "the next step ran"
    if seen:
        return "you said OK to it"
    if not at_work:
        return "the agent that asked has finished"
    return None if others else "it has no other answer to change to"


def _cards(session: Session, project_id: str, window: Window) -> list[Decision]:
    """The cards the Orchestrator answered for the user - a sub-agent to open among them."""
    at = func.coalesce(Question.answered_at, Question.created_at)
    found = session.execute(
        select(Question, at, Run.conversation_id, Agent.status)
        .join(Run, Run.id == Question.run_id)
        .join(Conversation, Conversation.id == Run.conversation_id)
        .join(Agent, Agent.id == Question.agent_id)
        .where(
            Conversation.project_id == project_id,
            Question.status == "answered",
            Question.lead_why.is_not(None),
            *window(at),
        )
    ).all()
    calls = [q.tool_call_id for q, *_ in found if q.tool_call_id]
    opened = {
        (parent, call): agent_id
        for agent_id, parent, call in session.execute(
            select(Agent.id, Agent.parent_agent_id, Agent.tool_call_id).where(
                Agent.tool_call_id.in_(calls)
            )
        )
    }
    rows = []
    for question, when, cid, status in found:
        if question.leave and question.options == SPAWN:
            child = opened.get((question.agent_id, question.tool_call_id))
            rows.append(_spawn(question, _utc(when), cid, child))
            continue
        why_not = _card_undo(
            question.leave,
            question.seen_at is not None,
            status not in AGENT_TERMINAL,
            any(one != question.answer for one in question.options or []),
        )
        rows.append(
            Decision(
                id=f"answer:{question.id}",
                at=_utc(when),
                kind="answer",
                who="orchestrator",
                what="Answered a card of KOLONİ's for you"
                if question.leave
                else "Answered a question for you",
                quote=said(question.question),
                answer=said(question.answer),
                why=said(question.lead_why),
                conversation_id=cid,
                link=DecisionLink(kind="question", id=question.id),
                undo="none" if why_not else "change",
                undo_reason=why_not,
                seen=question.seen_at is not None,
            )
        )
    return rows


def _spawn(question: Question, at: datetime, cid: str, child: str | None) -> Decision:
    yes = question.answer == SPAWN[0]
    return Decision(
        id=f"spawn:{question.id}",
        at=at,
        kind="spawn",
        who="orchestrator",
        what="Opened a sub-agent" if yes else "Did not open a sub-agent",
        quote=said(question.question),
        why=said(question.lead_why),
        conversation_id=cid,
        link=DecisionLink(kind="agent", id=child)
        if child
        else DecisionLink(kind="question", id=question.id),
        undo="none",
        undo_reason="the agent was opened" if yes else "the agent was not opened",
        seen=None,
    )


# What a command's record of the judges says, as a row: (who, what, why it cannot be undone). The
# check of the user's words is kind "words" ("" on a record from before 0.1.9); its "ask" was the
# user's card, not a decision. The judge's "fine" is counted (`of`); its "risky" and "refuse" are
# rows only where its model looked ("looked", `risk_judge_mixin._risk_asked`).
COMMANDS: dict[tuple[str, str], tuple[Literal["judge", "your_words"], str, str]] = {
    ("risk", "risky"): (
        "judge",
        "KOLONİ's judge found a command risky and asked you",
        "it was asked on its card",
    ),
    ("risk", "refuse"): (
        "judge",
        "KOLONİ's judge did not run a command; the agent went on",
        "it did not run",
    ),
    ("words", "run"): (
        "your_words",
        "Ran a command without asking, on a line of {source}",
        "it ran",
    ),
    ("words", "refuse"): (
        "your_words",
        "Did not run a command, on a line of {source}",
        "it did not run",
    ),
}


def _commands(session: Session, project_id: str, window: Window) -> tuple[list[Decision], int]:
    """The commands the judges decided - and how many the judge found fine."""
    found = session.execute(
        # (Its columns, not the record: a command's output may be long.)
        select(Command.id, Command.command, Command.judged, Command.created_at, Run.conversation_id)
        .join(Run, Run.id == Command.run_id)
        .join(Conversation, Conversation.id == Run.conversation_id)
        .where(
            Conversation.project_id == project_id,
            Command.judged.is_not(None),
            *window(Command.created_at),
        )
    ).all()
    rows, fine = [], 0
    for command_id, line, judged, at, cid in found:
        judged = judged or {}
        kind = "risk" if judged.get("kind") == "risk" else "words"
        if kind == "risk" and judged.get("verdict") == "fine":
            fine += 1
        said_of = COMMANDS.get((kind, judged.get("verdict", "")))
        # (A card of KOLONİ's the judge gave no verdict of its own for - not asked, no answer it
        # could read, the program changed while it looked - is no decision of the judge's.)
        if said_of is None or kind == "risk" and judged.get("looked") is not True:
            continue
        who, what, why_not = said_of
        rows.append(
            Decision(
                id=f"command:{command_id}",
                at=_utc(at),
                kind="command",
                who=who,
                what=what.format(source=FROM.get(judged.get("source", ""), "your words")),
                quote=said(line),
                why=said(judged.get("why") if kind == "risk" else judged.get("quote")),
                conversation_id=cid,
                link=DecisionLink(kind="command", id=command_id),
                undo="none",
                undo_reason=why_not,
                seen=None,
            )
        )
    return rows, fine


def _task_undo(task: BacklogTask, added: bool) -> str | None:
    """Why today's Change (`backlog.decide`) no longer works on the Orchestrator's word on a task;
    None: it does."""
    if (task.po or {}).get("seen"):
        return "you said OK to it"
    if added:
        return None if task.status == "todo" else "it has started"
    return None if task.status == "proposed" else "you added it since"


def _tasks(session: Session, project_id: str, window: Window) -> list[Decision]:
    """The Scout's proposals the Orchestrator took onto the To-do list, or turned down, at Full
    auto. shortcut: `po` keeps no time of the Orchestrator's word; the proposal's own (the same
    turn's end) stands for it - keep the word's time in `po` if the two are seen to differ."""
    found = session.scalars(
        select(BacklogTask).where(
            BacklogTask.project_id == project_id,
            BacklogTask.po.is_not(None),
            *window(BacklogTask.created_at),
        )
    ).all()
    rows = []
    for task in found:
        po = task.po or {}
        if po.get("lead") not in ("add", "no"):
            continue
        added = po["lead"] == "add"
        why_not = _task_undo(task, added)
        rows.append(
            Decision(
                id=f"task:{task.id}",
                at=_utc(task.created_at),
                kind="task",
                who="orchestrator",
                what="Added a task the Scout proposed to To-do"
                if added
                else "Turned down a task the Scout proposed",
                quote=said(task.title),
                why=said(po.get("lead_why")),
                conversation_id=po.get("chat"),
                link=DecisionLink(kind="task", id=task.id),
                undo="none" if why_not else "change",
                undo_reason=why_not,
                seen=None,
            )
        )
    return rows


def of(
    session: Session,
    project_id: str,
    since: datetime | None = None,
    until: datetime | None = None,
) -> DecisionLog:
    """What was decided for the user in project `project_id` at or after `since` and before
    `until` (each where given; a time with no zone is UTC's), newest first."""

    def window(at: When) -> list[ColumnElement[bool]]:
        return [
            *([at >= _utc(since)] if since else []),
            *([at < _utc(until)] if until else []),
        ]

    commands, fine = _commands(session, project_id, window)
    rows: list[Decision] = [
        *_cards(session, project_id, window),
        *commands,
        *_tasks(session, project_id, window),
    ]
    rows.sort(key=lambda row: row.at, reverse=True)
    return DecisionLog(rows=rows, judge_fine=fine)
