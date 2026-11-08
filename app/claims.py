"""Who holds which file: two agents do not change one file at a time.

An agent that is about to change a file takes it and holds it until its own work is done.
Another agent that wants the same file waits for it, in the order it came. The table is the
project's - a project's conversations share it - and it is kept in memory only: it is for
the turns now running, and a turn does not outlive the process either.

Nothing here touches the database or waits (no await): `AgentRunner` owns one table, asks
it, and is told through `Wait.changed` when something a waiter was waiting for has moved.

A file has a line of holders, not one. An agent takes without waiting a file held by an
agent above it in its own chain - that one is waiting for it anyway - and stands over it;
when it ends, the file is the upper agent's again. Only the last in that line counts for
everyone else: a sibling does not get its sibling's file through the agent both work for.
"""

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.workspace import Workspace, WorkspaceError

# A project's folder and a path inside it, as they are compared: any case.
Key = tuple[str, str]


def place(root: str | Path, path: object) -> tuple[Key, str] | None:
    """Where a path of a project leads, as the table knows it, and how it is shown: the
    path inside the project folder, however it was written (`./a.txt`, `A.TXT`, with
    backslashes where those part folders, with a dot at its end where that is dropped).
    Not seen as one: two names of one file by a hard link, and a file of a project whose
    folder lies inside another project's. None for what is not a file inside the
    project: that is nobody's to hold, and whoever writes it is refused as before."""
    if not isinstance(path, str):
        return None
    try:
        ws = Workspace(root)
        shown = ws.rel(ws.resolve(path))
    except (WorkspaceError, ValueError, OSError):
        return None
    if shown in ("", "."):
        return None
    name = shown.casefold()
    if os.name == "nt":
        # Windows drops dots and spaces from the end of a name: "new.txt." is "new.txt",
        # which the resolved path only shows once the file is there.
        name = "/".join(part.rstrip(". ") or part for part in name.split("/"))
    return (str(ws.root).casefold(), name), shown


@dataclass
class Wait:
    """One agent waiting for one file. `holder` is the agent it waits for now; `state`
    is "waiting", then "held" (the file is its own) or "refused" (waiting on would never
    end: `through` is the chain from the holder back to it)."""

    agent: str
    line: tuple[str, ...]
    key: Key
    path: str
    holder: str
    state: str = "waiting"
    through: tuple[str, ...] = ()
    # Called, with nothing, whenever `holder` or `state` has changed.
    changed: Callable[[], None] | None = None

    def _tell(self) -> None:
        if self.changed is not None:
            self.changed()


class Claims:
    def __init__(self) -> None:
        # file -> its holders, the one that counts last; and how its path is shown
        self._held: dict[Key, list[str]] = {}
        self._shown: dict[Key, str] = {}
        # file -> the agents waiting for it, in the order they came
        self._queue: dict[Key, list[Wait]] = {}
        # agent -> the agents it is waiting to hear back from (its sub-agents at work,
        # one it sent a message to), each with how many times
        self._out: dict[str, dict[str, int]] = {}

    # --- asking ------------------------------------------------------------------

    def holder(self, root: str | Path, path: object) -> str | None:
        """The agent that holds this file now, if any does."""
        found = place(root, path)
        stack = self._held.get(found[0]) if found else None
        return stack[-1] if stack else None

    def of(self, root: str | Path) -> list[tuple[str, str]]:
        """Every file of a project that is held, with its holder: (path, agent)."""
        folder = str(Workspace(root).root).casefold()
        return sorted(
            (self._shown[key], stack[-1])
            for key, stack in self._held.items() if key[0] == folder and stack
        )

    def held_by(self, agent: str) -> list[str]:
        """The files this agent holds now (not the ones a sub-agent stands over)."""
        return sorted(
            self._shown[key] for key, stack in self._held.items() if stack and stack[-1] == agent
        )

    def waited(self, root: str | Path) -> list[tuple[str, str]]:
        """Who waits for which file of a project now: (path, agent)."""
        folder = str(Workspace(root).root).casefold()
        return sorted(
            (wait.path, wait.agent)
            for key, queue in self._queue.items() if key[0] == folder for wait in queue
        )

    def waiting(self, agent: str) -> list[Wait]:
        return [wait for queue in self._queue.values() for wait in queue if wait.agent == agent]

    def cycle(self, agent: str, holder: str) -> tuple[str, ...] | None:
        """Whether `agent` waiting for `holder` would never end: the chain of agents
        from `holder` to `agent`, each waiting for the next - for a file it holds, or to
        hear back from it. None when the wait can end."""
        seen: set[str] = set()

        def walk(at: str) -> tuple[str, ...] | None:
            if at == agent:
                return (at,)
            if at in seen:
                return None
            seen.add(at)
            for nxt in self._waits_for(at):
                rest = walk(nxt)
                if rest is not None:
                    return (at, *rest)
            return None

        return walk(holder)

    def _waits_for(self, agent: str) -> list[str]:
        files = [wait.holder for wait in self.waiting(agent)]
        return [*files, *self._out.get(agent, {})]

    # --- taking, waiting, releasing ---------------------------------------------------

    def take(
        self, root: str | Path, path: object, agent: str, line: tuple[str, ...] = ()
    ) -> str | None:
        """Take a file for an agent. `line`: the agents above it in its own chain.
        None when it holds the file now (also for a path that is nobody's to hold);
        otherwise the agent that holds it, which is not of its line: nothing is taken."""
        found = place(root, path)
        if found is None:
            return None
        key, shown = found
        stack = self._held.setdefault(key, [])
        if not stack:
            self._shown[key] = shown
        if stack and stack[-1] != agent and stack[-1] not in line:
            return stack[-1]
        if not stack:
            stack.append(agent)
        elif stack[-1] != agent:
            stack.append(agent)
            # Whoever waited for the agent it took the file from waits for this one now.
            self._settle(key)
        return None

    def wait(
        self, root: str | Path, path: object, agent: str, line: tuple[str, ...] = (),
        changed: Callable[[], None] | None = None,
    ) -> Wait:
        """Stand in line for a file `take` did not give. The caller has asked `cycle`."""
        found = place(root, path)
        if found is None or not self._held.get(found[0]):
            raise ValueError("nothing to wait for: the file is not held")
        key, _shown = found
        wait = Wait(agent, tuple(line), key, self._shown[key], self._held[key][-1],
                    changed=changed)
        self._queue.setdefault(key, []).append(wait)
        return wait

    def leave(self, wait: Wait) -> None:
        """Stop waiting (the turn was stopped). One that holds the file by now keeps it."""
        queue = self._queue.get(wait.key, [])
        if wait in queue:
            queue.remove(wait)
            if not queue:
                del self._queue[wait.key]

    def release(self, agent: str, to: str | None = None) -> list[Wait]:
        """An agent's work is over, however it ended: everything it holds is let go, and
        it waits for nothing. A file it stood over for an agent above it is that agent's
        again. Returns the waits this moved - each has been told (`changed`).

        `to`: the agent its files go on to instead - the one in whose working copy it
        changed them, which holds them until that copy is taken into the project."""
        for queue in list(self._queue.values()):
            for wait in [w for w in queue if w.agent == agent]:
                self.leave(wait)
        self._out.pop(agent, None)
        return self.hand_on(agent, to)

    def hand_on(
        self, agent: str, to: str | None = None, which: Callable[[Key], bool] | None = None
    ) -> list[Wait]:
        """Let go of the files an agent holds - of those `which` picks, or all - going on
        to `to` where one is given (as `release` says), while the agent itself works on.
        Returns the waits this moved."""
        moved: list[Wait] = []
        for key in [
            key for key, stack in self._held.items()
            if agent in stack and (which is None or which(key))
        ]:
            stack = self._held[key]
            if to is not None and to not in stack:
                self._held[key] = [to if holder == agent else holder for holder in stack]
            else:
                self._held[key] = [holder for holder in stack if holder != agent]
            moved += self._settle(key)
        return moved

    def _settle(self, key: Key) -> list[Wait]:
        """A file's holders changed: give it to the first in line that may have it - the
        first of all when nobody holds it, else the first that works below its holder -
        and tell the others whom they wait for now. Not strictly the head of the line:
        an agent's own sub-agent must not be kept behind someone waiting for that agent."""
        stack = self._held[key]
        queue = self._queue.get(key, [])
        moved: list[Wait] = []
        while True:
            given = next(
                (w for w in queue if not stack or stack[-1] in w.line or stack[-1] == w.agent),
                None,
            )
            if given is None:
                break
            queue.remove(given)
            if not stack or stack[-1] != given.agent:
                stack.append(given.agent)
            given.state = "held"
            moved.append(given)
        for wait in list(queue):
            if wait.holder == stack[-1]:
                continue
            wait.holder = stack[-1]
            chain = self.cycle(wait.agent, wait.holder)
            if chain is not None:
                # Waiting for the new holder would never end: it is told so instead.
                queue.remove(wait)
                wait.state, wait.through = "refused", chain
            moved.append(wait)
        if not queue:
            self._queue.pop(key, None)
        if not stack:
            del self._held[key]
            self._shown.pop(key, None)
        for wait in moved:
            wait._tell()
        return moved

    # --- waiting to hear back from another agent ------------------------------------------

    def awaiting(self, agent: str, other: str) -> None:
        """`agent` does nothing until `other` is back: its sub-agent at work, or an agent
        taking a turn on its message."""
        out = self._out.setdefault(agent, {})
        out[other] = out.get(other, 0) + 1

    def returned(self, agent: str, other: str) -> None:
        out = self._out.get(agent, {})
        if other in out:
            out[other] -= 1
            if out[other] <= 0:
                del out[other]
        if not out:
            self._out.pop(agent, None)
