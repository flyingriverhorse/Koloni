"""The decision log (`app.decisions`) as the API gives it - beside `app.schemas`, which is at its
size limit, and imports nothing of it: a night's job carries its rows (`AwayJobOut.decisions`).
Read only: nothing adds, changes or deletes a row of it."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class DecisionLink(BaseModel):
    """What a row is of: the card, the command, the To-do task or the agent opened."""

    kind: Literal["question", "command", "task", "agent"]
    id: str


class Decision(BaseModel):
    """One thing decided for the user. `what` is KOLONİ's own sentence; `quote`, `answer` and `why`
    are agents' and models' words (and, of Check what I said first, the user's own line): every
    secret KOLONİ knows masked, on one line, cut, and after `injection.NOTE` where they read like
    orders."""

    id: str  # "<kind>:<record id>"
    at: datetime
    kind: Literal["answer", "command", "task", "spawn"]
    who: Literal["orchestrator", "judge", "your_words"]
    what: str
    # The question, the command or the task's title.
    quote: str | None
    # The answer the Orchestrator gave, on an answer's row ("Add" or "Reject" on a task's); None on
    # the others.
    answer: str | None = None
    # An answer's row: the other answers Change can give, each as it is kept; None on the others.
    options: list[str] | None = None
    # The model's reason - of Check what I said first, the line of yours it rested on; None: none.
    why: str | None
    conversation_id: str | None
    chat: str | None = None  # (its chat's title, as `quote` is shown; None for a To-do task's)
    # A rule of yours (`who` "your_words"): where its line is - your preferences, the project's
    # rules or your message; None on the others, and on a record from before 0.1.9 that says not.
    source: Literal["preferences", "rules", "message"] | None = None
    link: DecisionLink
    # "change": today's Change still works (an answer while its agent works; a To-do choice).
    # "change_and_redo": an answer whose agent has finished, its work still there to go on with -
    # the user's answer in its place and a new turn of its chat (`app.redo`).
    undo: Literal["change", "change_and_redo", "none"]
    undo_reason: str | None  # (where it is "none": why, in plain words)
    # Whether the user said OK to it: a card's answer, a sub-agent opened or not, a command run or
    # not run on their words or refused by the judge, a To-do choice; None for one with no OK (a
    # command the judge asked about on its card).
    seen: bool | None


class DecisionLog(BaseModel):
    rows: list[Decision]  # newest first: the newest `decisions.MOST`
    # The judge's "fine" in the period: a count, not rows (a night can have hundreds).
    judge_fine: int
    more: bool = False  # there were more rows than `rows` holds
