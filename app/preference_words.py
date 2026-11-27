"""New preferences from the user's words (suggest_preference, the user's setting, 28 Nov): which of
their sentences a quote is of - their own prose only, as K5 reads it, never a fenced, `>`-quoted,
indented or backticked line (what they pasted: an agent's report, a file) -, how the setting
stands ("add": their sentence goes into Your preferences at once, with Undo; "ask": a card), and
Undo of a line it added."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import judge, masking
from app import memory as kept
from app.db.models import Memory, Message
from app.db.turn_models import Flag

FLAG = "preferences_from_words"
MODES = ("add", "ask")  # Add them, tell me (the default, the user's) · Ask me first
LINE_MOST = 300  # characters of what is kept
ADDED = "Added to your preferences: {line}"  # KOLONİ's line in the chat, with Undo on the page
UNDONE = " · undone"


def mode(session: Session) -> str:
    """The user's setting: "add" unless they chose "ask"."""
    row = session.get(Flag, FLAG)
    return row.value if row is not None and row.value in MODES else "add"


def choose(session: Session, value: str) -> None:
    """Keep the user's setting (not committed)."""
    row = session.get(Flag, FLAG)
    if row is None:
        session.add(Flag(name=FLAG, value=value))
    else:
        row.value = value


def plain(text: str) -> str:
    """Words as a quote is compared: case, spacing and quotation marks do not count."""
    return " ".join(text.casefold().replace("“", '"').replace("”", '"').split()).strip(" \"'")


def sentences(text: str) -> list[str]:
    """A message's sentences of the user's own prose, as written: its lines that are no code,
    quote or indented block (`judge._prose`), split as K5 splits them, none with a backtick."""
    found = []
    for line in judge._prose(text):
        if line is None or not line.strip():
            continue
        for one in judge.SENTENCE.split(judge.LIST_MARK.sub("", line.strip())):
            if one.strip() and "`" not in one:
                found.append(judge._BIDI.sub("", one.strip()))
    return found


def sentence_of(messages: list[str], quote: str) -> str | None:
    """The user's own sentence that holds `quote` (`messages` newest first: the newest decides),
    as they wrote it; None where none of their prose holds it."""
    wanted = plain(quote)
    for message in messages:
        for one in reversed(sentences(message)):
            if wanted in plain(one):
                return one
    return None


def kept_line(text: str) -> str:
    """What is kept of a line or a quote: masked, on one line, cut."""
    shown = masking.masked(text)
    return shown if len(shown) <= LINE_MOST else shown[: LINE_MOST - 1] + "…"


def undo(session: Session, message: Message) -> Memory:
    """Undo of a line `suggest_preference` added (its KOLONİ line, `message`): exactly that line
    taken out of Your preferences, the record set aside, the chat's line marked undone. Refused
    (`kept.Refused`) where it is no such line, was undone already, or the preferences no longer
    hold it. Not committed."""
    record = session.scalar(
        select(Memory).where(func.json_extract(Memory.noted_by, "$.line_id") == message.id)
    )
    if message.role != "koloni" or record is None:
        raise kept.Refused("no line of your preferences was added by that", 404)
    if message.content.endswith(UNDONE):
        raise kept.Refused("it was undone already", 409)
    lines = (kept.preferences(session) or "").splitlines()
    key = kept.text_key(record.text)
    at = next((n for n, one in enumerate(lines) if kept.text_key(one) == key), None)
    if at is None:
        raise kept.Refused("your preferences no longer hold this line", 409)
    kept.change_preferences(session, "\n".join(lines[:at] + lines[at + 1 :]))
    kept._retire(record, "rejected", "user", "removed")
    message.content += UNDONE
    return record
