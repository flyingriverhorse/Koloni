"""herdr's `pane.wait_for_output`, for command_output (28 Nov 2026): wait for a piece of text in a
command's output - "listening on", "passed" - instead of a step spent on each look. A piece of
text, never a pattern: Python's `re` can backtrack without end on a pattern an agent writes, and a
piece of text is found in time linear in the output. Looked for only in what command_output itself
would hand the agent (its output as it was kept, secrets hidden), after the agent's `since`.
"""

import asyncio
from collections.abc import Callable

from app.db.models import Command
from app.tools import ToolError, _fn

UNTIL_MOST = 200  # characters of the text waited for
WAIT_MOST = 120  # seconds a call waits at most
WAIT_SET = 30  # seconds where none are given
LOOK = 0.5  # seconds between looks at the output
LINE_MOST = 500  # characters of the line it was seen in, said back

_COMMAND_ID = {"type": "string", "description": "The command's id, as run_command gave it."}
COMMAND_OUTPUT_SCHEMA = _fn(
    "command_output",
    "Read what a command that keeps running in this conversation (a server started with "
    "keep_running) printed, by its id: its newest output, or from since on - the number the "
    "last answer gave. Of one that has ended, its last output and how it ended. With until, it "
    "first waits until that text is in its output (after since), the command ends, or "
    "timeout_seconds pass - and says the line it was seen in.",
    {
        "id": _COMMAND_ID,
        "since": {
            "type": "integer",
            "description": "Optional: the character to read from, as the last answer said.",
        },
        "until": {
            "type": "string",
            "description": (
                f"Optional: a piece of text to wait for, as it is printed (not a pattern), at "
                f'most {UNTIL_MOST} characters - "listening on", "passed".'
            ),
        },
        "timeout_seconds": {
            "type": "integer",
            "description": f"Optional, with until: how long to wait, 1 to {WAIT_MOST} "
            f"(default {WAIT_SET}).",
        },
    },
    ["id"],
)


def until_of(args: dict) -> tuple[str, float] | None:
    """The text a call waits for and how long it waits - None where it waits for nothing."""
    until, seconds = args.get("until"), args.get("timeout_seconds")
    if until is None:
        if seconds is not None:
            raise ToolError("timeout_seconds is for until: say the text to wait for")
        return None
    if not isinstance(until, str) or not until or len(until) > UNTIL_MOST:
        raise ToolError(f"until is a piece of text, 1 to {UNTIL_MOST} characters")
    if seconds is None:
        return until, float(WAIT_SET)
    if isinstance(seconds, bool) or not isinstance(seconds, int | float):
        raise ToolError(f"timeout_seconds is a number of seconds, 1 to {WAIT_MOST}")
    if not 1 <= seconds <= WAIT_MOST:
        raise ToolError(f"timeout_seconds is a number of seconds, 1 to {WAIT_MOST}")
    return until, float(seconds)


async def waited(
    read: Callable[[], str | None],
    until: str,
    seconds: float,
    since: object,
    kept: Callable[[], str] | None = None,
) -> str:
    """Looks at `read()` - its output so far, None once it is no longer running - every LOOK
    seconds until `until` is in it after `since`, it ends, or `seconds` pass: what is said first -
    never `until` itself (a secret the agent wrote is not said back, unhidden). Ended, what it
    printed is looked at once more as it was `kept` (on record): "passed", then its end, between
    two looks - or before the first.
    shortcut: looked at, not woken by its output; wake on its next piece if a wait is felt."""
    start = since if isinstance(since, int) and not isinstance(since, bool) and since > 0 else 0
    loop = asyncio.get_running_loop()
    ends = loop.time() + seconds
    while True:
        text = read()
        over = text is None
        if over and kept is not None:
            text = kept()
        at = -1 if text is None else text.find(until, min(start, len(text)))
        if at >= 0 and text is not None:
            first = text.rfind("\n", 0, at) + 1
            last = text.find("\n", at)
            line = text[first : last if last >= 0 else len(text)][:LINE_MOST]
            return f"Seen at character {at}, in the line: {line}\n"
        if over:
            return "Not seen: it is no longer running.\n"
        if loop.time() >= ends:
            return f"Not seen in {seconds:g} s.\n"
        await asyncio.sleep(min(LOOK, max(0.0, ends - loop.time())))


def kept_output(factory, command_id: str) -> str:
    """A command's output on record - kept, its secrets hidden - once it no longer runs."""
    with factory() as session:
        command = session.get(Command, command_id)
        return (command.output or "") if command is not None else ""
