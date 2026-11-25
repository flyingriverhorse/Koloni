"""The decision log (karar defteri, Part A): what was decided for the user in one project, by whom
and why - by the Orchestrator (the cards it answered, the sub-agents it opened or not, the Scout's
To-do proposals it took or turned down), by KOLONİ's judge (a command refused, or found risky) and
by the user's own words (Check what I said first). Read from the records that keep each of them: no
table of its own, no model asked, and nothing writes here - no row is added, changed or hidden by an
agent. The judge's "fine" is counted, not listed. Agents' and models' words are masked, cut and
marked where they read like orders (`said`); they are shown, never given to an agent as orders.
shortcut: read from the records, a row leaves the log where its record changes - the user's own
Change, and Change and redo, clear the Orchestrator's why (`api.questions.change`, `app.redo`),
and a task you turned down - one it
added, by its row's Change; one it turned down, rejected on To-do - is deleted (`backlog.decide`);
give decisions a table of their own (approach B) if the log must keep those."""

import unicodedata
from collections.abc import Callable
from datetime import UTC, datetime
from functools import partial
from typing import Literal

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import InstrumentedAttribute, Session

from app import injection
from app.agent.spawn_mixin import SPAWN_WORDS
from app.agent.words import AGENT_TERMINAL
from app.commands import OutputMask
from app.db.models import Agent, BacklogTask, Command, Conversation, Merge, Question, Run
from app.judge import whole
from app.schemas_decisions import Decision, DecisionLink, DecisionLog
from app.stories import BLANK_LOOKING

SAID_MOST = 300  # characters of an agent's or a model's words a row shows
# Rows, the newest: a night of a long To-do may have more (`DecisionLog.more`). Only those are
# built - their words masked and cut (`said`).
# shortcut: Today's "(N not seen)" counts the rows given, not the period's all; count the unseen
# here too if a period of more than MOST is seen to hide some.
MOST = 500
# (`spawn_mixin._spawn_word`'s card: the one of KOLONİ's cards with these two options)
SPAWN = list(SPAWN_WORDS)
FROM: dict[Literal["preferences", "rules", "message"], str] = {
    "preferences": "your preferences",
    "rules": "this project's rules",
    "message": "your message",
}

When = ColumnElement[datetime] | InstrumentedAttribute[datetime]
Window = Callable[[When], list[ColumnElement[bool]]]
# A row as it is found: when, whether you said OK to it (None: it has no OK), and how to build it
# - only the newest MOST are built.
Later = tuple[datetime, bool | None, Callable[[], Decision]]
# What shows as nothing, or as a blank, and is no Cf: a braille blank, a Hangul filler...
# (`stories.BLANK_LOOKING`), the combining grapheme joiner and the emoji variation selector.
UNSEEN = BLANK_LOOKING | {"\N{COMBINING GRAPHEME JOINER}", "\N{VARIATION SELECTOR-16}"}


def _masked(text: str) -> str:
    """Every secret KOLONİ knows, and those known by their shape - an API key, a Bearer token, a
    password in an address (`https://user:pass@host`), a value given to a secret's name - as a
    command's output is masked (`commands.OutputMask`)."""
    return OutputMask(()).hide(text)


def _shows(ch: str) -> bool:
    """Whether a character shows: not a format character (Cf: zero-width, bidi, a soft hyphen),
    a control character but whitespace (which `said` folds), nor one of `UNSEEN`."""
    kind = unicodedata.category(ch)
    return not (kind == "Cf" or kind == "Cc" and not ch.isspace() or ch in UNSEEN)


def said(text: str | None) -> str | None:
    """An agent's or a model's words as a row shows them: a lone surrogate the replacement
    character (`judge.whole`: else the reply fails whole), what nobody sees taken out (a secret
    split by a zero-width space or a soft hyphen is one again; no bidi control turns the row
    around), every secret masked - before the cut, which could leave half of one, and again on one
    line, where one with a space in it was written across a line break -, cut, and after
    `injection.NOTE` where the words, as written, read like orders. None for none.
    shortcut: what nobody sees goes whole - a family emoji joined by ZWJ shows as its people, a
    Persian word's ZWNJ joins its parts; keep ZWJ and ZWNJ between letters if users read those."""
    if not text:
        return None
    text = whole(text)
    seen = "".join(ch for ch in text if _shows(ch))
    shown = _masked(" ".join(_masked(seen).split()))
    cut = shown if len(shown) <= SAID_MOST else shown[: SAID_MOST - 1] + "…"
    return f"{injection.NOTE} {cut}" if injection.scan(text) else cut


def utc(at: datetime) -> datetime:
    """A time in UTC, as the records keep it; one with no zone is UTC's. OverflowError for one
    that is out of range there (year 1 at +14:00)."""
    return at.astimezone(UTC) if at.tzinfo else at.replace(tzinfo=UTC)


def offered(question: Question) -> list[str]:
    """The other answers Change - or Change and redo - can give a card, each as it is kept: only
    one shown as it is, none masked, cut or marked (`api.questions.change` takes nothing else)."""
    return [one for one in question.options or [] if one != question.answer and said(one) == one]


# Why Change and redo cannot go on with the work of the turn an answer was given in (`work`).
TAKEN_IN = "its work was taken in"
DISCARDED = "its work was discarded"
WAITS_TAKE_IN = "its work waits for your Take in in its chat"


def work(session: Session, question: Question) -> tuple[Merge | None, str | None]:
    """The work of the turn a card was answered in, as it stands: the newest Merge of its chat
    from that turn on (a Take in or a Discard keeps its Merge: `parked.where`'s by-turn record) -
    and why Change and redo cannot go on with it, None where it can (a kept copy none of which was
    taken in). None, None where none is on record: the turn changed nothing, or worked in the
    project itself - a fresh turn goes on there."""
    turn = session.get_one(Run, question.run_id)
    merge = session.scalar(
        select(Merge)
        .join(Run, Run.id == Merge.run_id)
        .where(
            Run.conversation_id == turn.conversation_id,
            Run.created_at >= utc(turn.created_at).replace(tzinfo=None),
        )
        .order_by(Merge.created_at.desc())
        .limit(1)
    )
    if merge is None:
        return None, None
    if merge.status == "applied" or any(one.get("state") == "applied" for one in merge.files):
        return merge, TAKEN_IN
    if merge.status == "pending":
        return merge, WAITS_TAKE_IN
    return merge, None if merge.status == "interrupted" and merge.kept_in else DISCARDED


Undo = Literal["change", "change_and_redo", "none"]


def card_undo(
    question: Question, at_work: bool, gone: Callable[[], str | None]
) -> tuple[Undo, str | None]:
    """What still undoes the Orchestrator's answer on a card, and why nothing does where nothing
    does: today's Change while the agent that asked works (`api.questions.change`); once it has
    finished, Change and redo (`app.redo`) - not where its work was taken in or discarded (`gone`:
    why, asked only then). The row and Change and redo's own click go by this alone.
    shortcut: Change not where its agent is a CLI that hears nothing more (`steer`) - known only
    to the runner at work; the Change says so when pressed."""
    if question.leave:
        return "none", "the next step ran"
    if question.seen_at is not None:
        return "none", "you said OK to it"
    if not any(one != question.answer for one in question.options or []):
        return "none", "it has no other answer to change to"
    if not offered(question):
        return "none", "its other answers hold words masked here"
    if at_work:
        return "change", None
    why = gone()
    return ("none", why) if why else ("change_and_redo", None)


def _cards(session: Session, project_id: str, window: Window) -> list[Later]:
    """The cards the Orchestrator answered for the user - a sub-agent to open among them."""
    at = func.coalesce(Question.answered_at, Question.created_at)
    found = session.execute(
        select(Question, at, Run.conversation_id, Conversation.title, Agent.status)
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
    rows: list[Later] = []
    for question, when, cid, title, status in found:
        if question.leave and question.options == SPAWN:
            child = opened.get((question.agent_id, question.tool_call_id))
            build = partial(_spawn, question, utc(when), cid, title, child)
        else:
            build = partial(_answer, session, question, utc(when), cid, title, status)
        rows.append((utc(when), question.seen_at is not None, build))
    return rows


def _answer(
    session: Session, question: Question, at: datetime, cid: str, title: str, status: str
) -> Decision:
    undo, why_not = card_undo(
        question, status not in AGENT_TERMINAL, lambda: work(session, question)[1]
    )
    return Decision(
        id=f"answer:{question.id}",
        at=at,
        kind="answer",
        who="orchestrator",
        what="Answered a card of KOLONİ's for you"
        if question.leave
        else "Answered a question for you",
        quote=said(question.question),
        answer=said(question.answer),
        options=offered(question),
        why=said(question.lead_why),
        conversation_id=cid,
        chat=said(title),
        link=DecisionLink(kind="question", id=question.id),
        undo=undo,
        undo_reason=why_not,
        seen=question.seen_at is not None,
    )


def _spawn(question: Question, at: datetime, cid: str, title: str, child: str | None) -> Decision:
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
        chat=said(title),
        link=DecisionLink(kind="agent", id=child)
        if child
        else DecisionLink(kind="question", id=question.id),
        undo="none",
        undo_reason="the agent was opened" if yes else "the agent was not opened",
        seen=question.seen_at is not None,  # (its card is under Decided for you, as an answer's)
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


def _commands(session: Session, project_id: str, window: Window) -> tuple[list[Later], int]:
    """The commands the judges decided - and how many the judge found fine."""
    found = session.execute(
        # (Its columns, not the record: a command's output may be long.)
        select(
            Command.id,
            Command.command,
            Command.judged,
            Command.created_at,
            Run.conversation_id,
            Conversation.title,
        )
        .join(Run, Run.id == Command.run_id)
        .join(Conversation, Conversation.id == Run.conversation_id)
        .where(
            Conversation.project_id == project_id,
            # (A JSON column keeps None as the text "null": not SQL's NULL.)
            func.json_type(Command.judged) == "object",
            *window(Command.created_at),
        )
    ).all()
    rows: list[Later] = []
    fine = 0
    for command_id, line, judged, at, cid, title in found:
        judged = judged or {}
        kind = "risk" if judged.get("kind") == "risk" else "words"
        if kind == "risk" and judged.get("verdict") == "fine":
            fine += 1
        said_of = COMMANDS.get((kind, judged.get("verdict", "")))
        # (A card of KOLONİ's the judge gave no verdict of its own for - not asked, no answer it
        # could read, the program changed while it looked - is no decision of the judge's.)
        if said_of is None or kind == "risk" and judged.get("looked") is not True:
            continue
        build = partial(_command, command_id, line, judged, utc(at), (cid, title), said_of)
        rows.append((utc(at), _command_seen(judged), build))
    return rows, fine


def _command(
    command_id: str,
    line: str,
    judged: dict,
    at: datetime,
    chat: tuple[str, str],
    said_of: tuple[Literal["judge", "your_words"], str, str],
) -> Decision:
    who, what, why_not = said_of
    cid, title = chat
    return Decision(
        id=f"command:{command_id}",
        at=at,
        kind="command",
        who=who,
        what=what.format(source=FROM.get(judged.get("source", ""), "your words")),
        quote=said(line),
        why=said(judged.get("why") if who == "judge" else judged.get("quote")),
        conversation_id=cid,
        chat=said(title),
        link=DecisionLink(kind="command", id=command_id),
        undo="none",
        undo_reason=why_not,
        seen=_command_seen(judged),
        # (one of `FROM`'s, or none: the record's word is not taken as it is)
        source=next((one for one in FROM if one == judged.get("source")), None)
        if who == "your_words"
        else None,
    )


def _command_seen(judged: dict) -> bool | None:
    """One it ran or did not run waits for your OK, as a card's answer; one it asked you about on
    its card ("risky") has none."""
    return None if judged.get("verdict") == "risky" else bool(judged.get("seen"))


def _task_undo(task: BacklogTask, added: bool) -> str | None:
    """Why today's Change (`backlog.decide`) no longer works on the Orchestrator's word on a task;
    None: it does."""
    if (task.po or {}).get("seen"):
        return "you said OK to it"
    if added:
        return None if task.status == "todo" else "it has started"
    return None if task.status == "proposed" else "you added it since"


def _tasks(session: Session, project_id: str, window: Window) -> list[Later]:
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
    return [
        (utc(task.created_at), _task_seen(task), partial(_task, task))
        for task in found
        if (task.po or {}).get("lead") in ("add", "no")
    ]


def _task_seen(task: BacklogTask) -> bool:
    """Your OK on the Orchestrator's word on a task - or one it turned down that you added since:
    your own word on it, nothing left to OK."""
    po = task.po or {}
    return bool(po.get("seen")) or (po.get("lead") == "no" and task.status != "proposed")


def _task(task: BacklogTask) -> Decision:
    po = task.po or {}
    added = po["lead"] == "add"
    why_not = _task_undo(task, added)
    return Decision(
        id=f"task:{task.id}",
        at=utc(task.created_at),
        kind="task",
        who="orchestrator",
        what="Decided on a task the Scout proposed",
        quote=said(task.title),
        answer="Add" if added else "Reject",
        why=said(po.get("lead_why")),
        conversation_id=po.get("chat"),
        link=DecisionLink(kind="task", id=task.id),
        undo="none" if why_not else "change",
        undo_reason=why_not,
        seen=_task_seen(task),
    )


def as_shown(task: BacklogTask, expect: str) -> bool:
    """Whether the Orchestrator's word on a task stands as a row of the log showed it - the
    state its Change acts on (`api.backlog.decide`'s `expect`): "proposed", one it turned down
    and still proposed; "added", one it added, still todo and not OK'd (`backlog.unseen`)."""
    po = task.po or {}
    if expect == "proposed":
        return po.get("lead") == "no" and task.status == "proposed"
    unseen = po.get("lead") == "add" and not po.get("seen")
    return expect == "added" and unseen and task.status == "todo"


def of(
    session: Session,
    project_id: str,
    since: datetime | None = None,
    until: datetime | None = None,
    unseen: bool = False,
) -> DecisionLog:
    """What was decided for the user in project `project_id` at or after `since` and before
    `until` (each where given; a time with no zone is UTC's), newest first - the newest `MOST`,
    `more` where there were more. `unseen`: only those that wait for your OK."""

    def window(at: When) -> list[ColumnElement[bool]]:
        return [
            *([at >= utc(since)] if since else []),
            *([at < utc(until)] if until else []),
        ]

    commands, fine = _commands(session, project_id, window)
    rows = [*_cards(session, project_id, window), *commands, *_tasks(session, project_id, window)]
    if unseen:  # (only what waits for your OK - before the cut: one of any age is found)
        rows = [row for row in rows if row[1] is False]
    rows.sort(key=lambda row: row[0], reverse=True)
    return DecisionLog(
        rows=[build() for _at, _seen, build in rows[:MOST]],
        # (Not seen has no period: the judge's "fine" of all time is no count of it - nor waits.)
        judge_fine=0 if unseen else fine,
        more=len(rows) > MOST,
    )
