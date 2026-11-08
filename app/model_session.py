"""A CLI agent run as one session whose only tools are KOLONİ's.

The CLI keeps its own loop for the length of an agent's work, but its own tools are
switched off and the one MCP server it is given is KOLONİ's. Every tool call comes
back here, is recorded and run the usual way (approvals, commands, sub-agents,
questions) and its result is returned to the CLI.
"""

import asyncio
import contextlib
import json
import logging
import os
import re
import secrets
import shutil
import sys
import tempfile
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from functools import reduce
from pathlib import Path

from app import mcp_bridge
from app.model_cli import (
    RESULT_TEXT,
    CliStepClient,
    Exited,
    _brief,
    _cache_tokens,
    _dict,
    _events,
    _input_tokens,
    classed,
    complaints,
    conversation,
    level_in_name,
    levels_of,
    own_error,
)
from app.model_client import ModelUnavailable, OwnStop, count_of
from app.raw import feed

log = logging.getLogger(__name__)

SERVER = "koloni"
PREFIX = f"mcp__{SERVER}__"
PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")  # what this server speaks
LINE_LIMIT = 2**24  # one line can hold a whole file being written
KEY_WAIT_SECONDS = 10.0
# B-304: why a session ends when a second program presents its tool server's key.
SECOND_BRIDGE = ("a second connection with this run's key was turned away (another program "
                 "had it, or the CLI started KOLONİ's bridge again), so the run is stopped")
INIT_WAIT_SECONDS = 10.0
# K-altajan-saglayici: how long a model may stay queued (Qoder's free models, `queued`) before
# the session is given up as unavailable - its opener then moves a sub-agent to the next of
# its tier (`AgentRunner._moved_on`). An agent that could not be moved waits for as long as
# Qoder queues it (`run_session`'s `queue_wait` None, R130).
# shortcut: a guess, not measured against how long Qoder's queue usually takes (R114: 5.5 min
# ended in "Queuing failed"); set it from a measurement.
# shortcut: one constant, not a setting of the provider's (`check_options` has none for Qoder,
# nor its form a field); make it one if the user asks to tune it.
# shortcut: raised wherever the queue line comes - a session queued again mid-work (after a
# tool call) fails then too, with no move; limit it to before the first word if Qoder is seen
# queuing mid-work.
# shortcut: Qoder natively (`QoderNativeClient`) does not read its queue line at all: neither
# shown nor given up on; read it there once Qoder native is measured.
QUEUE_WAIT_SECONDS = 90
# How long a CLI is asked to wait for one tool: an approval can take a while.
TOOL_WAIT_MS = str(24 * 60 * 60 * 1000)

SESSION_RULES = """You are an agent that another program, KOLONİ, runs. The input is a JSON
document with "instructions" (who you are and how to work) and "conversation" (everything so
far, oldest first). Carry on from the end of the conversation: do what the last user message
asks.

Your only tools are the ones of the "koloni" server; their names start with mcp__koloni__.
The conversation and the instructions name tools without that prefix: read_file there is
mcp__koloni__read_file here, and so on. You have no other way to read files, run commands
or reach the network, and that is expected. A tool result that says the user declined
something is their decision, not an error to work around.

The folder you are started in is a temporary one of KOLONİ's, not the project: the project
folder is the one the instructions name.

When the work is done, say briefly what you did and what you did not verify."""
# (The temporary folder: B-77 and B-81, a Lead that took it for the project.)

SYSTEM_LINE = "You are an agent run by KOLONİ. Follow the rules at the top of the input."

# Called with a tool's short name and its arguments as JSON text; returns whether it
# succeeded and the text to give back.
CallTool = Callable[[str, str], Awaitable[tuple[bool, str]]]
# B-344: a session's tool may give pictures too, MCP image blocks after its text: a CLI that
# keeps its own loop is never sent one with a next step of KOLONİ's (`_history`).
CallShowing = Callable[[str, str], Awaitable[tuple[bool, str, list[dict]]]]


class SessionStop(Exception):
    """Raised by the tool callback to end the session; the reason is passed on."""

    # As `ModelUnavailable`'s: the model it said it ran on, and why auto picked it (B-410).
    model: str | None = None
    picked_why: str | None = None
    # B-413: how the agent's job ends - "completed" where its loop guard stopped it after the
    # turn's work was in the project (`AgentRunner._circled`).
    ended: str = "failed"


class _UnknownMethod(Exception):
    """A request this server does not answer."""


@dataclass(frozen=True)
class SessionResult:
    input_tokens: int | None
    output_tokens: int | None
    # The model the CLI said it used; None when it did not say.
    model: str | None = None
    # Of `input_tokens`: what it says it read again from the cache, and wrote to it.
    cache_read: int | None = None
    cache_write: int | None = None
    # 27: the session its run left, to be resumed ({"id", "under"}: Claude Code's native turn,
    # `run_native`); None: none.
    session: dict | None = None
    # What Copilot says it spent in its own units: AI credits in billionths (totalNanoAiu) and
    # premium requests, its older one; None where it said nothing.
    nano_aiu: int | None = None
    premium_requests: float | None = None
    # Why Copilot's auto picked `model`, as it said it (`session.auto_mode_resolved`); None: no
    # pick was said.
    picked_why: str | None = None


def why_picked(told: dict, reported: str | None, why: str | None) -> str | None:
    """Why Copilot's auto picked the model a "model" event names: its own reason (from
    `session.auto_mode_resolved`), the one before for the same model, none for another model
    named without one - never one model's reason for another."""
    if "why" in told:
        return told["why"]
    return why if told.get("model") in (None, "", reported) else None


def _sum(one: object, other: object) -> int | None:
    """Two counts of tokens added up; None where neither is one."""
    counted = [part for part in (count_of(one), count_of(other)) if part is not None]
    return sum(counted) if counted else None


def copilot_counts(usage: dict | None) -> SessionResult:
    """What Copilot's last session.usage_checkpoint says its session spent - natively and
    with `-p` alike (measured on 1.0.103 `-p`, 5 Nov 2026: `test_copilot_agent.LUNA`). Its
    models' counts, summed (one per model it used); only the snapshot's modelMetrics: its
    agentMetrics and providerModelMetrics say the same again. inputTokens holds what it read
    from and wrote to its cache. None where it said nothing: never a made-up 0."""
    used = [_dict(_dict(one).get("usage")) for one in _dict(_dict(_dict(usage).get(
        "accountingSnapshot")).get("modelMetrics")).values()]

    def total(name: str) -> int | None:
        return reduce(_sum, (one.get(name) for one in used), None)
    premium = _dict(usage).get("totalPremiumRequests")
    return SessionResult(
        total("inputTokens"), total("outputTokens"), None, total("cacheReadTokens"),
        total("cacheWriteTokens"), nano_aiu=count_of(_dict(usage).get("totalNanoAiu")),
        premium_requests=premium if isinstance(premium, int | float)
        and not isinstance(premium, bool) else None)


# Tools whose calls do not wait for one another.
TOGETHER = frozenset({"spawn_agent"})


class ToolServer:
    """KOLONİ's tools as an MCP server for one session, on a loopback port with a key.

    One rule holds for every tool call: it ends in a reply, or it ends the session
    with a reason the session's owner gets to see.
    """

    def __init__(self, tools: list[dict], call_tool: CallTool | CallShowing,
                 alone: bool = True):
        self._tools = tools
        self._call_tool = call_tool
        self.key = secrets.token_urlsafe(24)
        # B-304: the key serves one connection, the session's one bridge: its file
        # (`bridge_file`) is removed once it is in, and another program with the key ends
        # the session, said why. Not `alone`: agy's door (`model_agy`), a connection per call.
        self._alone = alone
        self._taken = False
        self.file: Path | None = None
        self.port = 0
        self._server: asyncio.Server | None = None
        self._tasks: set[asyncio.Task] = set()
        # Why the session must end, if a tool call said so: a SessionStop from the
        # callback, a refusal to serve, or a bug inside a tool.
        self.ended: BaseException | None = None
        self.on_end: Callable[[], None] = lambda: None
        # Awaited before a call is run; may refuse it by raising.
        self.before_call: Callable[[], Awaitable[None]] | None = None
        # Calls are answered one at a time, in the order they arrive.
        self._turn = asyncio.Lock()
        self.in_flight = 0  # calls being run or waiting their turn
        self.last_reply = time.monotonic()

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._serve, "127.0.0.1", 0, limit=LINE_LIMIT
        )
        self.port = self._server.sockets[0].getsockname()[1]

    async def close(self) -> None:
        if self._server:
            self._server.close()
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        if self._server:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._server.wait_closed(), 2)

    def describe(self) -> list[dict]:
        return [
            {
                "name": tool["function"]["name"],
                "description": tool["function"]["description"],
                "inputSchema": tool["function"]["parameters"],
            }
            for tool in self._tools
        ]

    def _end(self, reason: BaseException) -> None:
        if self.ended is None:
            self.ended = reason
            self.on_end()

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:  # noqa: C901
        task = asyncio.current_task()
        if task:
            self._tasks.add(task)
        writing = asyncio.Lock()

        async def send(message: dict) -> None:
            async with writing:
                writer.write(json.dumps(message).encode("utf-8") + b"\n")
                await writer.drain()

        async def answer(request: dict) -> None:
            request_id = request.get("id")
            try:
                result = await self._handle(request.get("method"), _dict(request.get("params")))
            except _UnknownMethod as exc:
                await send({"jsonrpc": "2.0", "id": request_id,
                            "error": {"code": -32601, "message": str(exc)}})
                return
            await send({"jsonrpc": "2.0", "id": request_id, "result": result})

        try:
            presented = await asyncio.wait_for(reader.readline(), KEY_WAIT_SECONDS)
            # Whoever connects without the key is not this session's CLI.
            if not secrets.compare_digest(presented.strip(), self.key.encode("ascii")):
                return
            if self._taken:
                # shortcut: a CLI that starts its bridge again (none is measured to) ends here
                # too, said why; let one back in, by a key of its own, once one is seen to.
                log.warning("%s", SECOND_BRIDGE)
                self._end(OwnStop(SECOND_BRIDGE))
                return
            self._taken = self._alone
            if self._alone and self.file:
                self.file.unlink(missing_ok=True)  # read by its bridge, and by nobody after
            pending: set[asyncio.Task] = set()
            async for raw in reader:
                try:
                    request = json.loads(raw)
                except ValueError:
                    continue
                if not isinstance(request, dict) or request.get("id") is None:
                    continue  # a notification, or noise
                if "method" not in request:
                    continue  # a reply to something this server never asked
                job = asyncio.ensure_future(answer(request))
                pending.add(job)
                self._tasks.add(job)
                job.add_done_callback(pending.discard)
                job.add_done_callback(self._tasks.discard)
            await asyncio.gather(*pending, return_exceptions=True)
        except (ConnectionError, asyncio.IncompleteReadError, TimeoutError, ValueError):
            pass  # gone, never said who it was, or sent a line too long to be a request
        finally:
            if task:
                self._tasks.discard(task)
            writer.close()

    async def _handle(self, method: object, params: dict) -> dict:
        if method == "initialize":
            wanted = params.get("protocolVersion")
            return {
                "protocolVersion": wanted if wanted in PROTOCOLS else PROTOCOLS[0],
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER, "version": "1"},
            }
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": self.describe()}
        if method == "tools/call":
            return await self._call(params)
        raise _UnknownMethod(f"method not supported: {method}")

    async def _call(self, params: dict) -> dict:
        name = params.get("name")
        arguments = params.get("arguments")
        text = json.dumps(arguments if arguments is not None else {})
        if name not in {tool["name"] for tool in self.describe()}:
            return _tool_text(f"error: {name} is not one of the tools offered here", failed=True)
        self.in_flight += 1
        try:
            # Sub-agents asked for at once work at once; everything else takes its turn.
            together = name in TOGETHER
            if not together:
                await self._turn.acquire()
            try:
                if self.ended:
                    return _tool_text("error: the session has ended", failed=True)
                try:
                    if self.before_call:
                        await self.before_call()
                    ok, output, *images = await self._call_tool(str(name), text)
                except Exception as exc:
                    # A stop asked for by KOLONİ, a refusal, or a bug in a tool: either
                    # way the session is over and its owner hears why.
                    self._end(exc)
                    return _tool_text("error: the session has ended", failed=True)
            finally:
                if not together:
                    self._turn.release()
            said = _tool_text(output, failed=not ok)
            said["content"] += images[0] if images else []
            return said
        finally:
            self.in_flight -= 1
            self.last_reply = time.monotonic()


def _tool_text(text: str, failed: bool) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": failed}


def queued(event: dict) -> dict | None:
    """Qoder's `model_queue_status` line as what is shown live of its queue (K-qoder-kuyruk).
    Measured 29 Oct 2026 (qodercli 1.1.51, `tests/qoder_streams/queue-status.jsonl`): while a
    free model is queued, one every ~30 s with `status` "queued", how long it has waited and
    how long it would at most. None with any other status: it is queued no longer.
    shortcut: how the queue ends ("Queuing failed", REA R114) was not measured - it goes as
    any CLI error does; read its line once seen."""
    if event.get("status") != "queued":
        return None
    elapsed, most = event.get("queue_wait_elapsed_ms"), event.get("queue_max_wait_ms")
    available = event.get("service_available")
    return {
        "elapsed_s": round(elapsed / 1000) if isinstance(elapsed, (int, float)) else None,
        "max_s": round(most / 1000) if isinstance(most, (int, float)) else None,
        "available": available if isinstance(available, bool) else None,
    }


def bridge_file(server: ToolServer, workdir: Path) -> Path:
    """The session's port and key in its folder's bridge.json, which only its bridge
    (`mcp_bridge`) is pointed at: never on a command line, nor in a CLI's own config."""
    server.file = workdir / "bridge.json"
    server.file.write_text(json.dumps({"port": server.port, "key": server.key}),
                           encoding="utf-8")
    return server.file


def build_session_prompt(messages: list[dict], rules: str = SESSION_RULES) -> str:
    """What the CLI reads on stdin: the rules, then instructions and conversation as JSON."""
    instructions = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    document = {"instructions": instructions, "conversation": conversation(messages)}
    return f"{rules}\n\n{json.dumps(document, ensure_ascii=False)}"


class CliSessionClient(CliStepClient):
    """Runs a CLI for a whole agent session with KOLONİ's tools as its only tools."""

    session = True
    # Whether what a failed `result` holds is the CLI's own error line (Copilot: its
    # `session.error`) and not the text of its answer, which can be the model's words.
    result_is_its_error = False

    async def stream_step(self, model_id, messages, tools, on_delta, on_thinking=None,
                          effort=None):
        raise OwnStop(f"{self.label} runs as a session, not step by step")

    def _session_arguments(self, config: Path, allowed: list[str]) -> list[str]:
        raise NotImplementedError

    def _session_env(self, workdir: Path) -> dict[str, str]:
        return {}

    def _mcp_config(self, server: "ToolServer", workdir: Path) -> dict:
        """What the CLI is told about its one MCP server, KOLONİ's."""
        return {"mcpServers": {SERVER: {
            "command": sys.executable,
            "args": [str(Path(mcp_bridge.__file__)), str(bridge_file(server, workdir))],
        }}}

    def _translate(self, event: dict) -> list[dict]:
        """One line of the CLI's stream, as the events this client reads (those of
        Claude Code's stream-json). A CLI with a stream of its own puts it into them."""
        return [event]

    def _hide(self, text: str) -> str:
        """What the CLI said, without anything that must not be repeated (a key).
        Applied to the whole text, before it is cut short for an error message."""
        return text

    async def run_session(
        self,
        model_id: str,
        messages: list[dict],
        tools: list[dict] | None,
        call_tool: CallTool | CallShowing,
        on_text: Callable[[str], Awaitable[None]],
        on_message: Callable[[object], None] | None = None,
        effort: str | None = None,
        on_live: Callable[[dict], None] | None = None,
        queue_wait: float | None = QUEUE_WAIT_SECONDS,
    ) -> SessionResult:
        """`on_message`: told, before anything of it is passed on, which message of
        the model a piece of the stream belongs to - a message with several tool calls
        comes in several pieces, and is one step. `on_live`: what the CLI says of its
        queue while it waits for its model (`queued`), shown and never on record.
        `queue_wait`: the seconds after which a model still queued is given up as
        unavailable; None: never by KOLONİ (an agent that could not be moved on)."""
        server = ToolServer(tools or [], call_tool)
        allowed = [PREFIX + tool["name"] for tool in server.describe()]
        workdir: Path | None = None
        try:
            workdir = Path(tempfile.mkdtemp(prefix="koloni-cli-"))
            await server.start()
            config = workdir / "mcp.json"
            config.write_text(json.dumps(self._mcp_config(server, workdir)), encoding="utf-8")
            command, shim = self._command()
            arguments, prompt = await asyncio.to_thread(  # (its pictures are read)
                self._given, self._leveled(self._session_arguments(config, allowed), effort),
                build_session_prompt(messages), messages, workdir)
            return await self._converse(
                [*command, *arguments], shim, prompt, workdir, server, allowed, on_text,
                on_message, on_live, queue_wait,
            )
        finally:
            await server.close()
            if workdir:
                shutil.rmtree(workdir, ignore_errors=True)

    async def _converse(  # noqa: C901
        self, argv, shim, prompt, workdir, server: ToolServer, allowed: list[str], on_text,
        on_message=None, on_live=None, queue_wait: float | None = QUEUE_WAIT_SECONDS,
    ) -> SessionResult:
        try:
            process, job = await self._start(argv, shim, workdir, self._session_env(workdir))
        except OSError as exc:
            reason = exc.strerror or exc
            raise OwnStop(f"{self.label} could not be started: {reason}") from None
        stdin, stdout, errors = process.stdin, process.stdout, process.stderr
        assert stdin is not None and stdout is not None and errors is not None  # all piped
        stderr = asyncio.ensure_future(complaints(errors, (server.key,)))
        result: dict | None = None
        counted: SessionResult | None = None  # what it last said it spent, where not in `result`
        reported: str | None = None  # the model it says it is using
        picked_why: str | None = None  # why Copilot's auto picked it, where it said so
        limited = None  # what it said of its plan's limit, if it turned this run away
        own_word: tuple | None = None  # what its own word says a failure is (`own_error`)
        in_queue: dict | None = None  # what it last said of its model's queue (`queued`)
        heard = time.monotonic()  # when the CLI last said anything
        # The CLI says which tools it starts with before anything else. Until it has,
        # and they are all KOLONİ's, nothing it writes is taken and no tool is run.
        vetted = asyncio.Event()
        # The stream says "the model calls tool X" before the call itself arrives here.
        # A call waits (briefly) until the stream has got that far, so the text the
        # model wrote before the call is already recorded when the call is.
        announced = 0
        answered = 0
        caught_up = asyncio.Condition()
        text_open = False  # whether the model message being written already has text

        async def before_call() -> None:
            nonlocal answered
            try:
                await asyncio.wait_for(vetted.wait(), INIT_WAIT_SECONDS)
            except TimeoutError:
                raise OwnStop(
                    f"{self.label} did not say which tools it started with, so its tool "
                    "calls are not served"
                ) from None
            async with caught_up:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(caught_up.wait_for(lambda: announced > answered), 3)
                answered += 1

        def end_now() -> None:
            # The session is over as far as KOLONİ is concerned: end the CLI at once.
            if job:
                job.terminate()
            with contextlib.suppress(ProcessLookupError):
                process.kill()

        server.before_call = before_call
        server.on_end = end_now

        async def talk() -> None:  # noqa: C901
            nonlocal result, counted, announced, heard, text_open, reported, limited, own_word
            nonlocal in_queue, picked_why
            with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                stdin.write(prompt.encode("utf-8"))
                await stdin.drain()
            stdin.close()
            async for raw in stdout:
                heard = time.monotonic()
                written = raw.decode("utf-8", errors="replace")
                feed("stdout", written, (server.key,))
                for event in (
                    told
                    for line in _events(written)
                    for told in self._translate(line)
                ):
                    kind = event.get("type")
                    if in_queue and kind != "system" and on_live:
                        # Its model is at work (words, a tool call, its result): queued no more.
                        in_queue = None
                        on_live({"queue": None})
                    if isinstance(event.get("model"), str) and kind in ("system", "model"):
                        picked_why = why_picked(event, reported, picked_why)
                        reported = event["model"] or reported
                    if kind == "model":
                        continue
                    if kind == "koloni.usage":  # (Copilot's checkpoint: its session's total so far)
                        counted = event["counted"]
                        continue
                    if kind == "rate_limit_event":
                        limited = self._limit_event(event)
                        continue
                    if kind == "system" and event.get("subtype") == "init":
                        started_with = event.get("tools")
                        if not isinstance(started_with, list):
                            continue
                        own = [t for t in started_with if t not in allowed]
                        if own:
                            # Tools KOLONİ would neither approve nor record.
                            raise OwnStop(
                                f"{self.label} started with tools of its own "
                                f"({', '.join(map(str, own[:5]))}); the session was stopped"
                            )
                        vetted.set()
                    elif kind == "system" and event.get("subtype") == "model_queue_status":
                        in_queue = queued(event)
                        if on_live:
                            on_live({"queue": in_queue})
                        if in_queue and queue_wait is not None and (
                                in_queue["elapsed_s"] or 0) >= queue_wait:
                            raise ModelUnavailable(
                                f"{self.label} kept its model queued for "
                                f"{round(in_queue['elapsed_s'] / 60)} min")
                    elif kind in ("assistant", "result") and not vetted.is_set():
                        raise OwnStop(
                            f"{self.label} did not say which tools it started with; "
                            "the session was stopped"
                        )
                    elif kind == "assistant":
                        own_word = own_error(event) or own_word
                        message = _dict(event.get("message"))
                        if on_message:
                            # Claude Code writes one event for each piece of a message,
                            # all under the message's id. An event that names none is a
                            # whole message (Copilot's, as `_translate` hands it on).
                            on_message(message.get("id") or object())
                        for block in message.get("content") or []:
                            if not isinstance(block, dict):
                                continue
                            if block.get("type") == "text" and block.get("text"):
                                # Two pieces of text in one message are two paragraphs.
                                await on_text(("\n\n" if text_open else "") + block["text"])
                                text_open = True
                            elif (block.get("type") == "tool_use"
                                  and str(block.get("name", "")).startswith(PREFIX)):
                                text_open = False
                                async with caught_up:
                                    announced += 1
                                    caught_up.notify_all()
                    elif kind == "result":
                        result = event
                        return  # it has finished; whatever lingers is ended below
                if server.ended:
                    return
            await process.wait()

        talking = asyncio.ensure_future(talk())
        try:
            # The limit is on silence. Time spent on a tool - an approval, a long
            # command, a whole sub-agent - is KOLONİ's time, not the CLI's silence. A CLI
            # that is gone (`Exited`) is said below as it ended.
            gone = Exited(process, job)
            while not talking.done():
                await asyncio.wait({talking}, timeout=min(1.0, self._timeout / 4))
                quiet = time.monotonic() - max(heard, server.last_reply)
                if not talking.done() and await gone():
                    break
                if not talking.done() and server.in_flight == 0 and quiet > self._timeout:
                    raise ModelUnavailable(
                        f"{self.label} sent nothing for {self._timeout:g} seconds"
                    )
            if talking.done():
                try:
                    talking.result()
                except ValueError:
                    raise ModelUnavailable(
                        f"{self.label} sent a line too long to read") from None
        except ModelUnavailable as exc:
            exc.model, exc.picked_why = reported, picked_why  # (B-410: its pick, on record)
            raise
        finally:
            talking.cancel()
            with contextlib.suppress(BaseException):
                await asyncio.shield(asyncio.wait({talking}, timeout=2))
            await self._end(process, job)
            complaint = b""
            with contextlib.suppress(Exception):
                complaint = await asyncio.wait_for(asyncio.shield(stderr), 2)
            stderr.cancel()
        if server.ended:
            if isinstance(server.ended, SessionStop | ModelUnavailable):
                server.ended.model, server.ended.picked_why = reported, picked_why
            raise server.ended
        if result is None:
            reason = _brief(self._hide(complaint.decode("utf-8", errors="replace")))
            code = process.returncode or 0
            failed = ModelUnavailable(
                f"{self.label} exited with code {code}: {reason}"
                if reason
                else f"{self.label} ended without finishing (exit code {code})"
            )
            failed.failure = classed(limited, own_word)
            failed.model, failed.picked_why = reported, picked_why
            raise failed
        if result.get("is_error"):
            reason = _brief(self._hide(str(result.get("result") or result.get("errors"))))
            failed = ModelUnavailable(f"{self.label} reported an error: {reason}")
            failed.failure = classed(limited, own_word) or (
                None if self.result_is_its_error else RESULT_TEXT)
            failed.model, failed.picked_why = reported, picked_why
            raise failed
        if counted is not None:
            return replace(counted, model=reported, picked_why=picked_why)
        usage = _dict(result.get("usage"))
        sent, made = _input_tokens(usage), usage.get("output_tokens")
        made = made if isinstance(made, int) else None
        cache = _cache_tokens(usage)
        if not sent and not made:
            # zeros from a CLI that does not count are not a count
            sent, made, cache = None, None, (None, None)
        return SessionResult(sent, made, reported, *cache, picked_why=picked_why)


class ClaudeSessionClient(CliSessionClient):
    command = "claude"
    label = "Claude Code"
    efforts = levels_of("claude_cli")

    def _session_env(self, workdir: Path) -> dict[str, str]:
        return {"MCP_TOOL_TIMEOUT": TOOL_WAIT_MS}

    def _session_arguments(self, config: Path, allowed: list[str]) -> list[str]:
        arguments = [
            "-p",
            "--tools", "",  # none of its own tools
            "--strict-mcp-config",  # no MCP server but KOLONİ's
            "--mcp-config", str(config),
            "--no-session-persistence",
            "--setting-sources", "",
            "--output-format", "stream-json",
            "--verbose",
            "--system-prompt", SYSTEM_LINE,
        ]
        if allowed:
            arguments += ["--allowedTools", ",".join(allowed)]
        if self._model:
            arguments += ["--model", self._model]
        return arguments


QODER_MODELS_SECONDS = 10.0
# A model's name first on its line, of letters, digits and `._:/-`, then nothing, or a column
# (two spaces, a tab, a box's bar) or a remark ("(default)", "- fast"): not a sentence.
_MODEL_LINE = re.compile(r"([A-Za-z0-9][A-Za-z0-9._:/-]*)(?:$|\s{2}|\t|\s*[│|]|\s+[(\[—*✓-])")
_HEADINGS = {"name", "model", "models", "id"}  # a table's first column, named
_COLOURS = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def qoder_models(printed: str) -> list[str]:
    """The model names in what `qodercli --list-models` prints: of each line, its colours
    and marks (`*`, `-`, `>`, a box's `│`) taken off, the name it begins with (`_MODEL_LINE`,
    with a letter in it); a line that ends in ":" (a heading) is passed over.
    Measured on 29 Oct 2026 (qodercli 1.1.51): a "MODEL" heading, then one model a line, a
    paid one as `Name (where it is served) (its/id)`; the name is kept.
    shortcut: whether --model takes a paid model's name or the id in its last parentheses
    is not measured (the free ones ran by name); keep the id instead if the name is refused.
    shortcut: an image model is passed over by "image" in its line; use catalog.json's
    not_chat if another kind of model turns up there."""
    names: list[str] = []
    for line in _COLOURS.sub("", printed).splitlines():
        line = line.strip().lstrip("*->•│|✓→ \t")
        skip = line.endswith(":") or "image" in line.lower()
        found = None if skip else _MODEL_LINE.match(line)
        name = found.group(1) if found else ""
        if re.search("[A-Za-z]", name) and name.lower() not in _HEADINGS and name not in names:
            names.append(name)
    return names


class QoderSessionClient(CliSessionClient):
    command = "qodercli"
    label = "Qoder"
    # shortcut: the same levels for every model; xhigh measured on the two free ones only
    # (29 Oct), max not offered. Upgrade once each model's are known.
    efforts = levels_of("qoder_cli")
    effort_flag = "--reasoning-effort"
    effort_words = {"off": "none"}  # its own word for no thinking

    async def models(self) -> list[str]:
        """The names `qodercli --list-models` prints; none where it fails. No model is used.
        What it says on stderr (it could name the account) is never kept."""
        code, printed, _ = await self.run_status(["--list-models"], QODER_MODELS_SECONDS)
        return qoder_models(printed) if code == 0 else []

    def _session_env(self, workdir: Path) -> dict[str, str]:
        return {"MCP_TOOL_TIMEOUT": TOOL_WAIT_MS}

    def _session_arguments(self, config: Path, allowed: list[str]) -> list[str]:
        # Measured 4 Nov 2026 (R185, Qwen3.8-Flash): `--tools ""` starts it with `"tools":[]` and
        # no tool_use. Its init still lists plugin `agents` and `skills`, but with no tool of its
        # own (no Task, no Skill) nothing can start them.
        arguments = [
            "-p",
            "--tools", "",
            "--strict-mcp-config",
            "--mcp-config", str(config),
            "--no-session-persistence",
            "--setting-sources", "",
            "-o", "stream-json",
            "--system-prompt", SYSTEM_LINE,
        ]
        for name in allowed:
            arguments += ["--allowed-tools", name]
        if self._model:
            arguments += ["-m", self._model]
        return arguments


COPILOT_PREFIX = f"{SERVER}-"  # how the Copilot CLI names an MCP server's tools
# B-410 (live, R206): on a Claude model (its auto picked one) it first asks for its own
# `tool_search_tool`, which finds the tools it may call - here only KOLONİ's
# (`--available-tools`); each one it then calls comes over KOLONİ's server, asked and recorded
# as any. Let through by its name: a search acts on nothing.
# shortcut: that it only lists tools is read off its name and Claude Code's ToolSearch (measured
# on 2.1.311), not measured for Copilot, and no flag that turns it off is known; check its
# arguments and result live, and stop it again if it reads a file or reaches anything else.
COPILOT_FINDS = ("tool_search_tool",)


def _finds(said: dict, key: str) -> bool:
    """Copilot's own tool search (`COPILOT_FINDS`): by its name, and of no MCP server's."""
    return said.get(key) in COPILOT_FINDS and said.get("mcpServerName") is None


class CopilotSessionClient(CliSessionClient):
    """GitHub Copilot CLI as a session: KOLONİ's tools over MCP, none of its own.

    Measured on 2026-10-06 (CLI 1.0.91): `--available-tools` with only KOLONİ's names
    turns every tool of its own off; `--allow-tool koloni` instead of `--allow-all-tools`
    leaves it no permission for anything else; a `COPILOT_HOME` of its own keeps the
    user's MCP servers, plugins and settings out. With COPILOT_PROVIDER_BASE_URL it
    runs on a model server of the user's own and needs no GitHub sign-in. It reported
    no token counts then; its session.usage_checkpoint has them (`copilot_counts`).

    On a GitHub account it signs in by the provider's token, or without one by the user's
    own GitHub CLI login (measured on 1.0.103, 24 Oct 2026: `authType: "gh-cli"` in that
    empty home) - never with the user's own Copilot home, its plugins, skills and hooks.
    """

    command = "copilot"
    label = "GitHub Copilot CLI"
    result_is_its_error = True
    # Its levels as its --help names them (CLI 1.0.105, 6 Nov 2026), the same for every model.
    # Measured 6 Nov 2026 (`-p`, CLI 1.0.105): a level its model does not take is no error -
    # gpt-6-luna ran at max and at none, claude-haiku-4.5 at none (still with reasoning
    # tokens: taken, apparently not applied). So no refused-level fallback (`refused_effort`).
    # shortcut: a level on a model server of the user's own is not measured; measure it with
    # one cheap call if one errors there.
    efforts = levels_of("copilot_cli")
    effort_flag = "--reasoning-effort"
    effort_words = {"off": "none"}  # its own word for no thinking
    # Its sign-in's variables (COPILOT_GITHUB_TOKEN, GH_TOKEN, GITHUB_TOKEN: the MIT SDK's
    # docs/auth/authenticate.md) are the user's own set-up, never given (`_inherited`):
    # it is given KOLONİ's token, or finds gh's login. No other secret variable either.
    logins = frozenset()

    def __init__(
        self,
        executable: str | None = None,
        model: str | None = None,
        timeout: float = 900.0,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        options: dict | None = None,
        context: str | None = None,
        **more,
    ):
        super().__init__(executable, model, timeout, **more)
        self._base_url, self._api_key, self._options = base_url, api_key, dict(options or {})
        self._context = context  # the model row's tier (K-copilot-baglam)
        # Its `auto` on GitHub takes no level (`level_in_name`): none is sent.
        self.level_named = not base_url and level_in_name("copilot_cli", model)
        if self.level_named:
            self.efforts = ()

    def _leveled(self, arguments: list[str], effort: str | None) -> list[str]:
        return super()._leveled(arguments, None if self.level_named else effort)

    def _command(self) -> tuple[list[str], bool]:
        # On Windows `copilot` is usually a .bat or .cmd wrapper, and what follows it
        # would be read by the command interpreter. The app alias is the program itself.
        if not self._launcher and not self._executable and sys.platform == "win32":
            alias = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/WindowsApps/copilot.exe"
            if alias.is_file():
                return [str(alias)], False
        return super()._command()

    def _inherited(self, pass_env: str | None = None) -> dict[str, str]:
        # Nothing of the user's own Copilot or GitHub set-up reaches the run: such a
        # variable can grant every tool, send another credential, or name another model -
        # nor does one the user passes (`pass_env`) for its commands.
        # shortcut: without a token it signs in by gh's stored login (measured); a gh login
        # held only in GH_TOKEN is stripped here - pass it on if a user signs in that way.
        return {
            name: value for name, value in super()._inherited(pass_env).items()
            if not name.upper().startswith("COPILOT_")
            and name.upper() not in ("GH_TOKEN", "GITHUB_TOKEN")
        }

    def _hide(self, text: str) -> str:
        return text.replace(self._api_key, "[key]") if self._api_key else text

    def _mcp_config(self, server: ToolServer, workdir: Path) -> dict:
        return {"mcpServers": {SERVER: {
            "type": "local", "command": sys.executable,
            "args": [str(Path(mcp_bridge.__file__)), str(bridge_file(server, workdir))],
            "tools": ["*"],
        }}}

    def _session_env(self, workdir: Path) -> dict[str, str]:
        # A home of its own, empty, either way: none of the user's Copilot plugins,
        # skills, hooks, MCP servers or settings, and none of its stored sign-in.
        home = workdir / "home"
        home.mkdir(exist_ok=True)
        if not self._base_url:
            # On the user's GitHub account: by the token they gave this provider, or else
            # by their own gh login, which Copilot finds itself.
            # shortcut: measured with gh's login; Copilot's own device login without gh is
            # not measured - it may not be found from this empty home; measure it if used.
            token = {"COPILOT_GITHUB_TOKEN": self._api_key} if self._api_key else {}
            return {"COPILOT_HOME": str(home), **token}
        if not self._model:
            raise OwnStop(
                "choose a model for this provider: a model server of your own has no "
                "default that Copilot knows"
            )
        env = {
            "COPILOT_HOME": str(home),
            "COPILOT_PROVIDER_BASE_URL": self._base_url,
            "COPILOT_PROVIDER_TYPE": str(self._options.get("provider_type") or "openai"),
            "COPILOT_MODEL": self._model,
        }
        if self._api_key:
            env["COPILOT_PROVIDER_API_KEY"] = self._api_key
        for name, variable in (("max_prompt_tokens", "COPILOT_PROVIDER_MAX_PROMPT_TOKENS"),
                               ("max_output_tokens", "COPILOT_PROVIDER_MAX_OUTPUT_TOKENS")):
            if self._options.get(name):
                env[variable] = str(self._options[name])
        if self._options.get("offline", True):
            env["COPILOT_OFFLINE"] = "true"
        return env

    def _session_arguments(self, config: Path, allowed: list[str]) -> list[str]:
        names = [COPILOT_PREFIX + name.removeprefix(PREFIX) for name in allowed]
        arguments = [
            "--output-format", "json",
            "--allow-tool", SERVER,  # permission for KOLONİ's server and nothing else
            "--additional-mcp-config", f"@{config}",
            "--disable-builtin-mcps",
            "--no-custom-instructions",
            "--no-auto-update",
            "--no-color",
            "--no-ask-user",
        ]
        arguments += self._account_arguments()
        # Only these exist for the model. With no tool at all, a name nothing has.
        return [*arguments, "--available-tools", *(names or [COPILOT_PREFIX + "none"])]

    def _account_arguments(self) -> list[str]:
        """What depends on where the model comes from: the secret to keep out of the
        CLI's own output, and - on a GitHub account - which of GitHub's models."""
        if self._base_url:
            return ["--secret-env-vars=COPILOT_PROVIDER_API_KEY"] if self._api_key else []
        arguments = ["--secret-env-vars=COPILOT_GITHUB_TOKEN"] if self._api_key else []
        if self._model:
            arguments += ["--model", self._model]
        return [*arguments, *self.context_arguments()]

    def context_arguments(self) -> list[str]:
        """Copilot's long context window, where the model's row asks for it; nothing for the
        default, so that it runs as it always has. Never on a model server of the user's own.
        shortcut: which models offer the long tier, and what Copilot does with it on one that
        does not (an error, or ignored), is not measured; its own error is what the user sees
        then - say "choose Default" for it once that error has been seen.
        shortcut: `--model auto` with the long tier is not measured (whether auto then picks
        only models that offer it); measure with one cheap call before trusting it."""
        return (["--context", "long_context"]
                if self._context == "long_context" and not self._base_url else [])

    def _translate(self, event: dict) -> list[dict]:
        kind, data = event.get("type"), _dict(event.get("data"))
        if kind == "session.tools_updated":
            # It has settled what it starts with; its own tools are off by the flags
            # above, and any use of one is caught below.
            return [{"type": "system", "subtype": "init", "tools": [],
                     "model": data.get("model")}]
        if kind == "model.call_start":  # (under auto: the model it picked - 1.0.105, 7 Nov 2026)
            return [{"type": "model", "model": data.get("model")}]
        if kind == "session.auto_mode_resolved":  # its auto has picked a model, and says why
            return [{"type": "model", "model": data.get("chosenModel"),
                     "why": data.get("selectionReason")}]
        if kind == "session.usage_checkpoint":  # (its tokens and AI credits, as natively)
            return [{"type": "koloni.usage", "counted": copilot_counts(data)}]
        if kind == "tool.execution_start" and data.get("mcpServerName") != SERVER and not (
                _finds(data, "toolName")):
            raise OwnStop(
                f"{self.label} used a tool of its own ({data.get('toolName')}); "
                "the session was stopped"
            )
        if kind == "assistant.message":
            blocks: list[dict] = []
            if data.get("content"):
                blocks.append({"type": "text", "text": str(data["content"])})
            # (Its tool search is no tool of KOLONİ's: nothing comes to its server for it.)
            asked = [_dict(one) for one in data.get("toolRequests") or []]
            for request in [one for one in asked if not _finds(one, "name")]:
                if request.get("mcpServerName") != SERVER:
                    raise OwnStop(
                        f"{self.label} asked for a tool of its own ({request.get('name')}); "
                        "the session was stopped"
                    )
                name = PREFIX + str(request.get("mcpToolName"))
                blocks.append({"type": "tool_use", "name": name})
            return [{"type": "assistant", "message": {"content": blocks}}] if blocks else []
        if kind == "session.error":
            return [{"type": "result", "is_error": True, "result": data.get("message")}]
        if kind == "result":
            code = event.get("exitCode")
            return [{"type": "result", "is_error": bool(code), "result": f"exit code {code}"}]
        return []

    async def run_session(
        self, model_id, messages, tools, call_tool, on_text, on_message=None, effort=None,
        on_live=None, queue_wait=QUEUE_WAIT_SECONDS,
    ) -> SessionResult:
        try:
            return await super().run_session(
                model_id, messages, tools, call_tool, on_text, on_message, effort, on_live,
                queue_wait)
        except ModelUnavailable as exc:
            # Whatever the CLI or the server said, the key is not repeated.
            if self._api_key and self._api_key in str(exc):
                # (Still what it was: KOLONİ's own stop or the provider's, with its class.)
                hidden = type(exc)(str(exc).replace(self._api_key, "[key]"))
                hidden.failure, hidden.model, hidden.picked_why = (
                    exc.failure, exc.model, exc.picked_why)
                raise hidden from None
            raise

