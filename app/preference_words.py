"""New preferences from the user's words (suggest_preference, the user's setting, 28 Nov): which of
their sentences a quote is of - their own prose only, as K5 reads it, never a fenced, `>`-quoted,
indented or backticked line (what they pasted: an agent's report, a file) -, how the setting
stands ("add": their sentence goes into Your preferences at once, with Undo; "ask": a card), and
Undo of a line it added."""

import re

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app import judge, masking
from app import memory as kept
from app.db.models import Memory, Message, UserPreferences, now
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


def sentence_of(messages: list[str], quote: str) -> tuple[str, str] | None:
    """The user's own sentence that holds `quote` (`messages` newest first: the newest decides),
    as they wrote it, and its message; None where none of their prose holds it."""
    wanted = plain(quote)
    for message in messages:
        for one in reversed(sentences(message)):
            if wanted in plain(one):
                return message, one
    return None


# The user's ruling (28 Nov): what is added with no click is a plain rule of theirs; anything else
# waits on the card (`adds_alone`). One-off words: a request for this work, not a rule.
QUOTE_MARKS = "\"'“”‘’«»„"
ONE_OFF = re.compile(
    r"^(?:please|pls|lütfen)\b|\b(?:now|right now|today|tonight|this time|for now|for this"
    r"|şimdi|bugün|bu sefer|bu seferlik|bu kez)\b|[\w/-]+\.[a-z]{1,6}\b"
)
STANDING = re.compile(r"\b(?:from now on|bundan sonra)\b")
NOT_PLAIN = (
    "it is no plain rule of theirs (a question, a no, a condition, words taken back or said of "
    "what they will do)"
)
NAMES_GIT = "it names a push, a pull request or a merge, which is the user's word each time"
SHOWN = "it is under a heading or in quotes: words they showed, not said"
ONE_OFF_SAID = "it reads as a request for this work, not a rule"


def adds_alone(message: str, sentence: str) -> str | None:
    """Why the user's `sentence` (of `message`) is not added with no click - None where it may be:
    a message whose prose asks plainly (`judge.plainly_asks`: K5's own look - no question, no no,
    no condition, nothing taken back nor said of what they will do), a sentence that opens with no
    quotation mark and is under no heading ("The bot said:"), names no push, pull request or merge
    (`judge.MENTIONS`: the user's word each time - their ruling, 28 Nov) and reads as no request
    for this work (`ONE_OFF`: "please …", "now", a file's name).
    shortcut: a one-off request is told by those words alone ("Fix the bug." is added); widen
    `ONE_OFF` if requests are seen added as rules."""
    lines = list(judge._headed(message))
    if not judge.plainly_asks(lines):
        return NOT_PLAIN
    said = judge._plain(sentence)
    if any(one.search(said) for one in judge.MENTIONS.values()):
        return NAMES_GIT
    if sentence.lstrip()[:1] in QUOTE_MARKS or any(
        head and sentence in line for line, _p, head in lines
    ):
        return SHOWN
    if ONE_OFF.search(STANDING.sub(" ", said)):
        return ONE_OFF_SAID
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
    row = session.get(UserPreferences, 1)
    lines = (row.text if row is not None and row.text else "").splitlines()
    key = kept.text_key(record.text)
    at = next((n for n, one in enumerate(lines) if kept.text_key(one) == key), None)
    if row is None or at is None:
        raise kept.Refused("your preferences no longer hold this line", 409)
    tidy = kept.check_rules("\n".join(lines[:at] + lines[at + 1 :]), "preferences")
    # (written only over what was read: an edit of yours meanwhile is never overwritten)
    written = session.execute(
        update(UserPreferences)
        .where(UserPreferences.id == 1, UserPreferences.text == row.text)
        .values(text=tidy, changed_at=now())
    )
    if getattr(written, "rowcount", 0) != 1:
        raise kept.Refused("your preferences changed meanwhile: look at them again", 409)
    kept._retire(record, "rejected", "user", "removed")
    message.content += UNDONE
    return record
