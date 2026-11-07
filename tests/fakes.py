import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path

from app.executors.base import StartError
from app.model_client import ModelInfo, StepResult


def sse_body(*chunks: dict) -> bytes:
    lines = [f"data: {json.dumps(c)}\n\n" for c in chunks] + ["data: [DONE]\n\n"]
    return "".join(lines).encode()


class ScriptedModel:
    """A ModelClient that replays scripted steps.

    A step is a StepResult, an exception to raise, or an async callable taking
    on_delta and returning a StepResult (used to hold a step open in tests).

    Given a dict, each agent has steps of its own, by its name ("Lead", "Coder",
    "Reviewer 2"): agents working at the same time do not take steps in a fixed order.
    """

    def __init__(self, steps, tools_supported: bool = True, model_id: str = "fake-model"):
        self.by_agent = {name: list(own) for name, own in steps.items()} if isinstance(
            steps, dict) else None
        self.steps = [] if self.by_agent is not None else list(steps)
        self.calls_of: dict[str, list[list[dict]]] = {}
        self.tools_supported = tools_supported
        self.model_id = model_id
        self.calls: list[list[dict]] = []
        self.tool_args: list[list[dict] | None] = []

    async def info(self) -> ModelInfo:
        return ModelInfo(self.model_id, self.tools_supported)

    async def stream_step(self, model_id, messages, tools, on_delta, on_thinking=None) -> StepResult:
        self.calls.append([dict(m) for m in messages])
        self.tool_args.append(tools)
        steps = self.steps
        if self.by_agent is not None:
            system = str(messages[0]["content"])
            named = system.split("Your name here is ", 1)
            name = named[1].split(".", 1)[0] if len(named) > 1 else "Lead"
            self.calls_of.setdefault(name, []).append([dict(m) for m in messages])
            steps = self.by_agent[name]
        step = steps.pop(0)
        if isinstance(step, Exception):
            raise step
        if callable(step):
            return await step(on_delta)
        for i in range(0, len(step.content), 2):
            await on_delta(step.content[i : i + 2])
        return step


@dataclass
class Script:
    """What a scripted command does: print chunks, optionally hang, then exit."""

    chunks: list[str] = field(default_factory=list)
    exit_code: int = 0
    hold: object | None = None  # a tests.conftest.Gate: stay running until released
    start_error: str | None = None
    kill_seconds: float = 0.0  # how long kill() takes
    start_failure: str | None = None  # reported after exit, like docker run exiting 125
    linger: bool = False  # the process exits but its output stream never ends
    writes: dict[str, str] = field(default_factory=dict)  # files it writes as it starts, by cwd


class ScriptedCommand:
    def __init__(self, script: Script, executor: "ScriptedExecutor", command_id: str):
        self._script, self._executor, self._id = script, executor, command_id
        self._killed = False
        self._finished = False
        self._closed = False

    async def __aiter__(self):
        for chunk in self._script.chunks:
            yield chunk
        hold = self._script.hold
        while hold is not None and not hold.released and not self._killed:
            await asyncio.sleep(0.005)
        self._finished = True
        while self._script.linger and not self._closed:
            await asyncio.sleep(0.005)

    async def wait(self) -> int:
        while not self._finished and not self._killed:
            await asyncio.sleep(0.005)
        return -9 if self._killed else self._script.exit_code

    async def kill(self) -> None:
        if not self._killed:
            self._executor.killed.append(self._id)
        await asyncio.sleep(self._script.kill_seconds)
        self._killed = True

    async def close(self) -> None:
        self._closed = True
        self._executor.closed.append(self._id)

    def start_failure(self, code: int, output: str) -> str | None:
        return self._script.start_failure


class ScriptedExecutor:
    """An Executor that plays scripts instead of starting processes."""

    location = "host"

    def __init__(self, scripts):
        self.scripts = list(scripts)
        self.started: list[tuple[str, str]] = []  # (command, cwd)
        self.copies: list[tuple] = []  # (the working copy it ran in, that copy's links)
        self.killed: list[str] = []
        self.closed: list[str] = []
        self.locations: list[str] = []
        self.envs: list[dict] = []  # the secrets given for each started command (slice 91)

    def factory(self, location: str, project) -> "ScriptedExecutor":
        self.locations.append(location)
        return self

    async def start(
        self, command_id: str, command: str, cwd, copy=None, links=None, secrets=None
    ) -> ScriptedCommand:
        script = self.scripts.pop(0)
        if script.start_error:
            raise StartError(script.start_error)
        self.started.append((command, str(cwd)))
        for rel, content in script.writes.items():
            (Path(cwd) / rel).parent.mkdir(parents=True, exist_ok=True)
            (Path(cwd) / rel).write_bytes(content.encode("utf-8"))
        self.copies.append((copy, links))
        self.envs.append(dict(secrets or {}))
        return ScriptedCommand(script, self, command_id)
