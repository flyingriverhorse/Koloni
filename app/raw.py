"""The raw stream of an agent's CLI: what the CLI itself wrote, line by line, as it came.

Beside the tidy record. Kept in memory only, for as long as KOLONİ runs: up to MAX_BYTES
for an agent and never more than MAX_LINES lines, the oldest dropped (and counted) when
there is more. Nothing here reaches the database or the event stream. A secret KOLONİ
knows is `***` before a line is kept, and again when it is read; one it does not know is
kept as the CLI wrote it.
"""

import contextlib
import contextvars
import itertools
import json
import re
import threading
import time
from collections import Counter, OrderedDict, deque
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field

# What is kept for one agent: the bytes of its lines' text and, for each line, LINE_COST -
# what Python spends on a kept line beside its text (measured: about 130 bytes), so that
# short lines, and empty ones, are not kept for nothing. MAX_LINES bounds it once more.
MAX_BYTES = 1024 * 1024
LINE_COST = 128
MAX_LINES = 8000
ANSWER_LINES = 2000  # how many lines one reading carries; the rest is asked for again
LINE_CHARS = 16 * 1024  # what is kept of one line; the rest of it is cut
CUT = "… (cut)"
# How many agents have a raw stream at once. With more, that of the agent whose CLI has
# been silent longest is forgotten - never one whose agent is at work.
MAX_AGENTS = 64
HIDDEN = "***"
# A shorter secret is not looked for: it would blank ordinary text.
MIN_SECRET = 8
# How old the secrets a line is kept without may be; when it is read they are read anew.
FRESH_SECONDS = 1.0
# A webhook's key is kept nowhere (only its hash), so it is known by where it stands: in
# the hook's address, as in the server's own log (`app.main.NoWebhookKeys`) - also as a
# JSON writer that escapes the slashes puts it (`\/api\/hooks\/`).
HOOK = re.compile(r"(\\?/api\\?/hooks\\?/)[^/?#\s\"'\\]+", re.IGNORECASE)


@dataclass
class _Kept:
    # (n, stream, text in UTF-8: what it is charged for is what it takes)
    lines: deque[tuple[int, str, bytes]] = field(default_factory=deque)
    size: int = 0  # the bytes of the lines' text, and LINE_COST for each
    written: int = 0  # every line that came, kept or not: the number of the last


_lock = threading.Lock()  # a reader on the loop and a request in a thread may meet here
_agents: OrderedDict[str, _Kept] = OrderedDict()  # the one written to last is last
_at_work: Counter[str] = Counter()
_feeding: contextvars.ContextVar[str | None] = contextvars.ContextVar("raw_agent", default=None)
_source: Callable[[], Iterable[str | None]] = tuple  # none, until `use` says where from
_secrets: list[str] = []
_read_at = 0.0


def use(source: Callable[[], Iterable[str | None]]) -> None:
    """Where the secrets KOLONİ knows are read from (`app.main`)."""
    global _source, _secrets, _read_at
    _source, _secrets, _read_at = source, [], 0.0


def read_again() -> None:
    """A secret was just given (slice 91): the next look reads them anew, not a second on."""
    global _read_at
    _read_at = 0.0


def spellings(secrets: Iterable[object]) -> list[str]:
    """Secrets as they are looked for (`hide`): each as it is and as a JSON writer puts it
    (most lines are JSON; `&`, `<`, `>` and `/` as some writers escape them), the longest
    first. One shorter than MIN_SECRET is left out."""
    found: set[str] = set()
    for secret in secrets:
        if not isinstance(secret, str) or len(secret) < MIN_SECRET:
            continue
        for written in (json.dumps(secret)[1:-1], json.dumps(secret, ensure_ascii=False)[1:-1]):
            safe = written.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
            found |= {secret, written, safe, written.replace("/", "\\/")}
    return sorted(found, key=len, reverse=True)


def _known(fresh: bool = False) -> list[str]:
    """The secrets KOLONİ knows, as they are looked for; read anew when they are old."""
    global _secrets, _read_at
    if not fresh and time.monotonic() - _read_at < FRESH_SECONDS:
        return _secrets
    _read_at = time.monotonic()  # also when the read fails: not tried again at every line
    _secrets = spellings(_source())
    return _secrets


def hide(text: str, secrets: Iterable[str]) -> str:
    for secret in secrets:
        text = text.replace(secret, HIDDEN)
    return HOOK.sub(rf"\1{HIDDEN}", text)


def hidden(text: str) -> str:
    """Text with every secret KOLONİ knows now masked - for what is sent out of the raw
    stream too (the Observer's request: `app.observer`)."""
    return hide(text, _known())


@contextlib.contextmanager
def of(agent_id: str | None) -> Iterator[None]:
    """While this lasts, what a CLI writes in this task - and in the tasks started from it
    - is that agent's raw stream. None: nobody's (a CLI asked to search the web)."""
    token = _feeding.set(agent_id)
    if agent_id:
        with _lock:
            _at_work[agent_id] += 1
    try:
        yield
    finally:
        _feeding.reset(token)
        if agent_id:
            with _lock:
                _at_work[agent_id] -= 1
                if not _at_work[agent_id]:
                    del _at_work[agent_id]


def feed(stream: str, text: str, also: tuple[str, ...] = ()) -> None:
    """One line a CLI wrote ("stdout" or "stderr") - or KOLONİ sent it ("stdin") - kept for
    the agent it works for; for nobody's work, not kept. `also`: secrets of this run alone,
    hidden like the others. Never raises: keeping a line does not break the run it came in."""
    _keep(stream, text.rstrip("\r\n"), 0, also)


def feed_lines(stream: str, lines: list[bytes], also: tuple[str, ...] = ()) -> None:
    """Lines a CLI wrote one after another, without their ends, as one reading brought
    them: taken in one go, however many they are - and of more than are kept of an
    agent at all, only the last are looked at; the others are counted."""
    if lines and _feeding.get() is not None:
        passed = max(0, len(lines) - MAX_LINES)
        _keep(stream, b"\n".join(lines[passed:]).decode("utf-8", errors="replace"), passed, also)


def _keep(stream: str, text: str, passed: int, also: tuple[str, ...]) -> None:
    """The lines of `text` are the agent's newest, after `passed` more that only count."""
    agent_id = _feeding.get()
    if agent_id is None:
        return
    with contextlib.suppress(Exception):
        try:
            secrets = _known()
        except Exception:
            secrets = _secrets  # the last that were read
        # Hidden first, cut after: a secret across the cut would be left half in sight.
        # (All the lines at once: no secret and no hook's key has a line end in it.)
        new = [
            (line if len(line) <= LINE_CHARS else line[:LINE_CHARS] + CUT)
            .encode("utf-8", errors="replace")
            for line in hide(text, [*also, *secrets]).split("\n")
        ]
        with _lock:
            kept = _agents.get(agent_id)
            if kept is None:
                kept = _agents[agent_id] = _Kept()
                for old in list(_agents):
                    if len(_agents) <= MAX_AGENTS:
                        break
                    if old != agent_id and old not in _at_work:
                        del _agents[old]
            _agents.move_to_end(agent_id)
            kept.written += passed
            for data in new:
                kept.written += 1
                kept.lines.append((kept.written, stream, data))
                kept.size += len(data) + LINE_COST
            while kept.lines and (kept.size > MAX_BYTES or len(kept.lines) > MAX_LINES):
                kept.size -= len(kept.lines.popleft()[2]) + LINE_COST


def read(agent_id: str, after: int = 0) -> dict | None:
    """What is kept for an agent: its lines numbered above `after`, the oldest first and
    at most ANSWER_LINES of them (`more`: there are later ones, to be asked for with the
    number of the last), and how many of its earlier lines are no longer kept. None:
    nothing of it is kept. A secret that became known after a line was kept is hidden
    here."""
    with _lock:
        kept = _agents.get(agent_id)
        if kept is None:
            return None
        dropped = kept.written - len(kept.lines)
        # A number no line of it has: of what was kept before it was forgotten and began
        # again at 1. Everything there is now is new to who asks.
        first = max(0, after - dropped) if after <= kept.written else 0
        lines = list(itertools.islice(kept.lines, first, first + ANSWER_LINES))
        more = first + len(lines) < len(kept.lines)
    secrets = _known(fresh=True)
    return {
        "lines": [{"n": n, "stream": stream, "text": hide(text.decode("utf-8"), secrets)}
                  for n, stream, text in lines],
        "dropped": dropped,
        "more": more,
    }
