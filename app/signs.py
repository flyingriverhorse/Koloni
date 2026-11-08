"""Signs of being stuck, counted from an agent's own tool calls in its turn - no model.

Two things are counted, each for one call (the tool and its arguments, in a fixed order):
the call failing the same way (a failed call, or a command that exited other than 0), and
a reading call returning the same. What differs every time in an error does not tell two
failures apart: a clock time, a duration, a process number (`_NOISE`); every other digit
does - another test, another count, another exit code is another failure. A change of the
turn that went on record, a command of the agent's that succeeded, a sub-agent opened or a
message sent starts every count again: something moved, and trying again is a new try.
What is counted is a fact, said as one; nothing here judges, and only in a turn nobody
watches does a count end anybody's work (`STOP_AT`) - or (B-413) stop the Orchestrator, which
counts no steps: the same failure STOP_AT times, or IDLE_STOP calls in a row that each repeat a
call with the result it had since something last moved.
"""

import json
import os
import re

SIGN_AT = 3  # the agent, the one who opened it and the user are told from here on
STOP_AT = 5  # in a turn nobody watches, the same failure this often ends the agent's work
# B-413: the Orchestrator's calls in a row that brought nothing new, which stop it -
# twice STOP_AT: it is told of a repeat from SIGN_AT on, and has calls left to change course.
IDLE_STOP = 10
IDLE = ("its last {count} calls each repeated one it had made, with the same result, with no "
        "change of this turn on record and no command of its own succeeding in between.")
FAILED = "failed {count} times with the same arguments and the same error"
SAME = "returned the same result {count} times with the same arguments"
# What a sign that stood before something moved is said with, from then on.
EARLIER = "Earlier in its work: "
# G4.2: edit_file failed this often on one file in the turn, whatever it was given.
EDIT_MISSES = ("\n\n[KOLONİ: edit_file failed {count} times on {path} in this turn. Read the "
               "file again with read_file and copy its lines exactly, or write it whole with "
               "write_file.]")
# A clock time, a duration (KOLONİ's own "exit code 1 (0.3s)" too) and a process number.
_NOISE = re.compile(r"\d+:\d+(?::\d+)?(?:\.\d+)?|\d+(?:\.\d+)?\s*m?s\b|\bpid \d+")


def _canonical(arguments: str) -> str:
    try:
        return json.dumps(json.loads(arguments), sort_keys=True, ensure_ascii=False)
    except ValueError:
        return arguments


def same_error(error: str) -> str:
    """An error as it is compared with the one before it."""
    return _NOISE.sub("#", error)


def sign(kind: str, tool: str, count: int) -> dict:
    said = (FAILED if kind == "same_failure" else SAME).format(count=count)
    return {
        "kind": kind, "count": count,
        # Only what the records show: a change made outside KOLONİ is not seen.
        "text": f"{tool} {said}, with no change of this turn on record and no command of "
        "its own succeeding in between.",
    }


def stopped(text: str) -> str:
    """Why the work of an agent in a turn nobody watches ended."""
    return f"stopped: {text} Nobody watches this turn, so this agent's work ends here."


CIRCLING = "stopped going round in circles: "


def circling(text: str) -> str:
    """B-413: why the work of the Orchestrator, which counts no steps, ended."""
    return f"{CIRCLING}{text}"


class Counts:
    """One agent's counts in its turn."""

    def __init__(self) -> None:
        # (kind, tool, arguments) -> (what it said last, how often in a row)
        self._seen: dict[tuple[str, str, str], tuple[str, int]] = {}
        # The sign that stands now: reached, and nothing has moved since.
        self._standing: dict | None = None
        # How the turn's changes stood on record at the last count (the caller's to set).
        self.stamp: tuple | None = None
        # path -> how often edit_file failed on it in the turn
        self._misses: dict[str, int] = {}
        # B-413: (tool, arguments, what it said) of its calls since something last moved, and
        # how many of its calls in a row were one of them.
        self._heard: set[tuple[str, str, str]] = set()
        self.idle = 0

    def heard(self, tool: str, arguments: str, said: str) -> None:
        """A call's result: one that repeats a call and its result since something moved adds
        to `idle`; any other sets it back to 0."""
        key = (tool, _canonical(arguments), same_error(said))
        self.idle = self.idle + 1 if key in self._heard else 0
        self._heard.add(key)

    def missed_edit(self, arguments: str) -> str:
        """An edit_file that failed, counted by its file: from the third, what to do
        instead (EDIT_MISSES); else ""."""
        try:
            path = json.loads(arguments).get("path")
        except (ValueError, AttributeError):
            return ""
        if not isinstance(path, str):
            return ""
        # (one file by any spelling: sub/../a.py, A.PY on Windows)
        key = os.path.normcase(os.path.normpath(path))
        count = self._misses[key] = self._misses.get(key, 0) + 1
        return EDIT_MISSES.format(count=count, path=path) if count >= SIGN_AT else ""

    def changed(self) -> dict | None:
        """Every count starts again. The sign that stood, said as an earlier one; or None."""
        self._seen.clear()
        self._heard.clear()
        self.idle = 0
        stood, self._standing = self._standing, None
        return {**stood, "text": EARLIER + stood["text"]} if stood else None

    def failed(self, tool: str, arguments: str, error: str) -> dict | None:
        return self._count("same_failure", tool, arguments, same_error(error))

    def read(self, tool: str, arguments: str, result: str) -> dict | None:
        return self._count("same_result", tool, arguments, result)

    def _count(self, kind: str, tool: str, arguments: str, said: str) -> dict | None:
        key = (kind, tool, _canonical(arguments))
        last, count = self._seen.get(key, (None, 0))
        count = count + 1 if last == said else 1
        self._seen[key] = (said, count)
        if count < SIGN_AT:
            return None
        self._standing = sign(kind, tool, count)
        return self._standing
