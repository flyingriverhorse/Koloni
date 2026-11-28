"""explain_wait: what an agent at work waits for, as agents_at_work says it (Codex's proposal, the
user's part 1, 28 Nov) - read only from records KOLONİ keeps: its card (a command, a change, one of
KOLONİ's), its question, its command running, the agent that holds a file it wants, a place at its
provider or among the turn's agents, the agents it opened. None where they say nothing: never a
reason made up. The page reads the same records (`frontend/src/chat/atWork.ts`, `waitsFor`)."""

from datetime import UTC

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import injection
from app.commands import OutputMask
from app.db.models import Agent, Command, FileChange, Question
from app.team import quoted

SAID_MOST = 80  # characters of a command, a path or a question
AT_WORK = ("queued", "running", "waiting", "blocked")


def _data(text: str) -> str:
    """An agent's words in what is said of its wait: masked, on one line, cut, quoted - after
    KOLONİ's note where they read like orders."""
    shown = OutputMask(()).hide(" ".join(text.split()))
    shown = shown if len(shown) <= SAID_MOST else shown[: SAID_MOST - 1] + "…"
    return f"{injection.NOTE} {quoted(shown)}" if injection.scan(text, "agent") else quoted(shown)


def waits_for(session: Session, agent: Agent) -> str | None:
    """What `agent` waits for now, in words, by what its records say first: a card of its for the
    user (a command, a change, KOLONİ's own), its question, its command running, another agent
    (a file it holds; its own agents at work), a place (queued). None: the records say nothing."""
    command = session.scalar(
        select(Command)
        .where(Command.agent_id == agent.id, Command.status.in_(("proposed", "running")))
        .order_by(Command.created_at.desc())
        .limit(1)
    )
    if command is not None and command.status == "proposed":
        return f"the user's yes on its command {_data(command.command)} (a card)"
    change = session.scalar(
        select(FileChange.path)
        .where(FileChange.agent_id == agent.id, FileChange.status == "proposed")
        .limit(1)
    )
    if change is not None:
        return f"the user's yes on its change to {_data(change)} (a card)"
    question = session.scalar(
        select(Question)
        .where(Question.agent_id == agent.id, Question.status == "pending")
        .order_by(Question.created_at.desc())
        .limit(1)
    )
    if question is not None:
        if question.leave:
            return f"an answer on a card of KOLONİ's: {_data(question.question)}"
        return f"an answer to its question {_data(question.question)}"
    if command is not None:
        since = command.started_at or command.created_at
        at = since.replace(tzinfo=UTC).astimezone().strftime("%H:%M")
        return f"its command {_data(command.command)}, running since {at}"
    return _other(session, agent)


def _other(session: Session, agent: Agent) -> str | None:
    """`waits_for`'s part with no record of its own calls: another agent, or a place."""
    held = agent.waiting_for or {}
    if held.get("agent_name"):
        return f"{held['agent_name']}, which holds {_data(str(held.get('path') or ''))}"
    if agent.status == "queued":
        on = agent.queued_on or {}
        if on.get("provider"):
            return (
                f"a place at {on['provider']} ({on.get('at_work', '?')} of "
                f"{on.get('most', '?')} at work there)"
            )
        return "a place among the turn's agents at work"
    if agent.status == "proposed":
        return "the user's yes to open it (a card)"
    if agent.status == "waiting":
        names = session.scalars(
            select(Agent.name)
            .where(Agent.parent_agent_id == agent.id, Agent.status.in_(AT_WORK))
            .order_by(Agent.created_at)
        ).all()
        if names:
            return "its own agents at work: " + ", ".join(names)
    return None
