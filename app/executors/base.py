"""What the agent needs from a place that runs commands."""

from collections.abc import AsyncIterator, Mapping
from pathlib import Path
from typing import Protocol


class StartError(Exception):
    """The command could not be started; the message is shown to the user and the model."""


class RunningCommand(Protocol):
    def __aiter__(self) -> AsyncIterator[str]:
        """Output as it arrives (stdout and stderr merged); ends when the process does."""
        ...

    async def wait(self) -> int:
        """The exit code, once the process has ended."""
        ...

    async def kill(self) -> None:
        """Stop the process and everything it started. Safe to call more than once."""
        ...

    async def close(self) -> None:
        """The command is over: release it and leave nothing it started running."""
        ...

    def start_failure(self, code: int, output: str) -> str | None:
        """If this exit means the command never really started, say why; else None."""
        ...


class Executor(Protocol):
    location: str  # "host" | "docker"

    async def start(
        self, command_id: str, command: str, cwd: Path, copy: Path | None = None,
        links: dict[str, Path] | None = None, secrets: Mapping[str, str] | None = None,
    ) -> RunningCommand:
        """`copy`: the working copy the command runs in (`cwd` is inside it), when it
        runs for an agent that works in one and not in the project folder. `links`:
        the folders in that copy that are links to the project's own, with where each
        leads - for a place the links themselves do not reach. `secrets`: the variables
        the user gave this turn on a card (slice 91), by name, for its environment."""
        ...
