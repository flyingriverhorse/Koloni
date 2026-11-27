"""C2: a word written into a CLI's running turn - the user's Send now or Tell, another agent's
message - comes to one of three outcomes, said once: taken (its CLI showed it took it into that
turn), not sent (refused before it was written, or its CLI said no), or unknown (written, and no
sign by the turn's end that it was taken). Unknown is never sent again: it may have been read.

What each CLI shows, measured 27 Nov 2026: Claude Code 2.1.332 echoes the line it takes before
its turn's result (`--replay-user-messages`; its echo carries no id of KOLONİ's, so the words
are matched, oldest first); Codex 0.172 answers `turn/steer` with its turn's id, or -32600 "no
active turn to steer"; Copilot 1.0.114 answers `session.send` with a messageId, then says a
`user.message` with that id before its idle where it took it into its work."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any

log = logging.getLogger(__name__)

TAKEN, NOT_SENT, UNKNOWN = "taken", "not sent", "unknown"


class Delivery:
    """One word written into a running turn: its `outcome`, None while it is open."""

    def __init__(self, text: str, outcome: str | None = None) -> None:
        self.text = text
        self.outcome = outcome
        self.key: object = None  # what its CLI names it by, where it does (Copilot's messageId)
        self._waiting: list[Callable[[str], None]] = []

    def then(self, do: Callable[[str], None]) -> None:
        """`do` is told its outcome once it is known - at once, where it is."""
        if self.outcome is None:
            self._waiting.append(do)
        else:
            _tell(do, self.outcome)

    def settle(self, outcome: str) -> None:
        if self.outcome is not None:
            return  # (once)
        self.outcome = outcome
        waiting, self._waiting = self._waiting, []
        for do in waiting:
            _tell(do, outcome)


def _tell(do: Callable[[str], None], outcome: str) -> None:
    # (Told from a CLI's read loop or its end: what is done with it never ends that run.)
    try:
        do(outcome)
    except Exception:
        log.warning(
            "what came of a word sent into a turn (%s) was not taken in", outcome, exc_info=True
        )


class Deliveries:
    """A run's words written into its turn, each until it is settled; `over` once its turn is."""

    def __init__(self) -> None:
        self.open: list[Delivery] = []
        self.seen: set[object] = set()  # (ids it showed taken before KOLONİ knew them)
        # (Those sent as a request, by its number, with the field of the answer that names one.)
        self.asked: dict[object, tuple[Delivery, str | None]] = {}
        self.asking: set[asyncio.Future] = set()
        self.closed = False

    def sent(self, text: str) -> Delivery:
        """One to be written now - before it is, as its sign may be read while it is written.
        Not sent where its turn is over."""
        one = Delivery(text, NOT_SENT if self.closed else None)
        if not self.closed:
            self.open.append(one)
        return one

    def settle(self, one: Delivery, outcome: str) -> None:
        if one in self.open:
            self.open.remove(one)
        one.settle(outcome)

    def took(self, key: object = None, text: object = None) -> None:
        """A sign of its CLI's that it took one into its turn: by the `key` it was answered
        with, else by its words - the oldest open one of them."""
        one = next(
            (one for one in self.open if (one.key == key if key is not None else one.text == text)),
            None,
        )
        if one is not None:
            self.settle(one, TAKEN)
        elif key is not None:
            self.seen.add(key)

    def answered(self, number: object, message: dict) -> None:
        """Its answer to a request of `steer_asked`'s, as its read loop reads it - before a line
        after it (its turn's end) is: a no is not sent; a yes taken, or named by its `named`."""
        one, named = self.asked.pop(number, (None, None))
        if one is None:
            return
        result = message.get("result")
        if "result" not in message:
            self.settle(one, NOT_SENT)
        elif named is None:
            self.settle(one, TAKEN)
        else:
            one.key = result.get(named) if isinstance(result, dict) else None
            if one.key is not None and one.key in self.seen:
                self.settle(one, TAKEN)

    def over(self) -> bool:
        """Its turn is over: those still open are unknown - never sent again. Whether any was."""
        self.closed = True
        left, self.open = self.open, []
        for one in left:
            one.settle(UNKNOWN)
        for asking in list(self.asking):
            asking.cancel()
        return bool(left)


async def steer_asked(
    deliveries: Deliveries,
    text: str,
    asking: Coroutine[Any, Any, object],
    number: object,
    seconds: float,
    named: str | None = None,
) -> Delivery:
    """`text` sent as request `number` its CLI answers (Codex's turn/steer, Copilot's
    session.send): what came of it is its answer (`Deliveries.answered`), whenever it comes -
    or, where `named` is the field of the answer that names it, its CLI's showing that name
    (`Deliveries.took`). Returned once answered, or after `seconds`; none by the turn's end
    leaves it unknown (`over`)."""
    one = deliveries.sent(text)
    if one.outcome is not None:
        asking.close()  # (never written)
        return one
    deliveries.asked[number] = (one, named)
    task = asyncio.ensure_future(asking)
    deliveries.asking.add(task)
    task.add_done_callback(deliveries.asking.discard)

    def failed(done: asyncio.Future) -> None:
        if not done.cancelled() and done.exception() is not None:  # (not written: its pipe)
            deliveries.asked.pop(number, None)
            deliveries.settle(one, NOT_SENT)

    task.add_done_callback(failed)
    await asyncio.wait({task}, timeout=seconds)
    return one
