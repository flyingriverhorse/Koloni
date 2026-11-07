"""K-cli-surface: a CLI updates itself, and the protocol names KOLONİ speaks to it can change
with its version (cli-denetim spec §6). A version KOLONİ's protocol use was not measured
with is asked, once, the request its protocol starts with; one that does not answer it runs
the older way (its talker: KOLONİ's own tools, its own off). Never a reason not to run.

`cli_surface.json` holds, per CLI, the versions measured and the names KOLONİ relies on
(the second for `scripts/cli-surface.ps1`)."""

import asyncio
import contextlib
import copy
import json
import logging
import re
import shutil
import tempfile
from pathlib import Path

from app.model_agy import BRIDGE_FROM
from app.model_cli import _dict
from app.model_native import HOOK, PROTOCOL, _framed

log = logging.getLogger(__name__)

SURFACE = json.loads(Path(__file__).with_name("cli_surface.json").read_text(encoding="utf-8"))
# The CLIs with a first request to ask: agy has no protocol, so none is known.
KINDS = {"codex_cli": "codex", "claude_cli": "claude", "copilot_cli": "copilot"}
SECONDS = 30.0  # from its start to its answer (Claude Code's own wait: START_SECONDS)
# What each says first in its protocol, as its run says it (`_converse`, `_control`).
FIRST = {
    "codex": {"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"clientInfo": {"name": "koloni", "version": "0"}}},
    "claude": {"type": "control_request", "request_id": "init", "request": {
        "subtype": "initialize",
        "hooks": {"PreToolUse": [{"matcher": None, "hookCallbackIds": [HOOK]}]}}},
    "copilot": {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}},
}

# shortcut: kept while KOLONİ runs, not on disk: after a restart each new version is asked
# once more (a second or two), and two runs starting together may each ask; keep it in the
# runtime folder, under a lock, if that is ever felt.
_answered: dict[tuple, bool] = {}  # (command, executable, launcher, version) -> it answered
_said: dict[tuple[str, str], str] = {}  # (command, executable) -> what the Models page says


def measured(command: str, version: str) -> bool | None:
    """Whether KOLONİ's protocol use was measured with this version; None: no version known.
    shortcut: only its numbers count (a "-beta" falls away with a fake's "-fake"); count the
    rest if a prerelease is ever seen to differ from its release."""
    found = re.match(r"\d+(?:\.\d+)+", version)
    return None if not found else found[0] in SURFACE[command]["measured"]


def note(kind: str, executable: str | None) -> str | None:
    """What the Models page says of the version a provider of this kind last ran on."""
    command = KINDS.get(kind) or ("agy" if kind == "agy_cli" else None)
    return _said.get((command, executable or "")) if command else None


async def checked(client):
    """The client to run instead of `client` (a CLI about to work with tools of its own): itself,
    or its talker where its version was not measured and its first request went unanswered."""
    command = client.command
    if command not in FIRST and command != "agy":
        return client
    whose = (command, client._executable or "")
    version = await client._version()
    if command == "agy":  # (no protocol, but KOLONİ's tools only from BRIDGE_FROM on, B-310)
        found = re.match(r"(\d+)\.(\d+)\.(\d+)", version)
        if not found or tuple(map(int, found.groups())) >= BRIDGE_FROM:
            _said.pop(whose, None)
            return client
        # (Ends as the Models card's louder words do: `cards.tsx`.)
        _said[whose] = (f"agy {version} cannot open sub-agents here (KOLONİ's tools reach agy "
                        f"from {'.'.join(map(str, BRIDGE_FROM))} on): running the old way")
        older = copy.copy(client)
        older.collaborates = False  # (offered none: `AgentRunner._native_work` says so)
        return older
    if measured(command, version) is not False:
        _said.pop(whose, None)
        return client
    key = (*whose, tuple(client._launcher or ()), version)
    answered = _answered.get(key)
    if answered is None:
        try:
            answered = await _shakes(client)
            _answered[key] = answered
        except TimeoutError:
            # shortcut: a slow start (a busy machine) is not kept as a no: asked again next run.
            answered = False
        except Exception:  # (not found, a line it cannot take: its run says so itself)
            log.warning("%s %s could not be asked its first request", command, version,
                        exc_info=True)
            return client
    label = SURFACE[command]["label"]
    if answered:
        _said[whose] = f"{label} {version} not measured with KOLONİ"
        return client
    _said[whose] = f"{label} {version} not measured; running the old way"
    return client.talker()


async def _shakes(client) -> bool:
    """Whether it answers its protocol's first request, started with its run's line in an
    empty folder (no project of anyone's, so none of a project's hooks), and ended after.
    What it answers is kept nowhere: it can say whose account it is. TimeoutError past
    SECONDS."""
    workdir = Path(tempfile.mkdtemp(prefix="koloni-cli-"))
    process = job = drained = None
    try:
        command, shim = client._command()
        # (Claude Code's line names KOLONİ's bridge with no bridge.json yet: the bridge exits
        # at once, `mcp_bridge.where`, and its server is only missing.)
        arguments = await asyncio.to_thread(
            client._native_arguments, workdir, workdir / "bridge.json")
        process, job = await client._start([*command, *arguments], shim, workdir,
                                      client._native_env(workdir))
        stdin, stdout, errors = process.stdin, process.stdout, process.stderr
        assert stdin is not None and stdout is not None and errors is not None  # all piped
        drained = asyncio.ensure_future(errors.read())  # so that it cannot fill up
        body = json.dumps(FIRST[client.command]).encode("utf-8")
        with contextlib.suppress(BrokenPipeError, ConnectionResetError):
            stdin.write(b"Content-Length: %d\r\n\r\n" % len(body) + body
                        if client.command == "copilot" else body + b"\n")
            await stdin.drain()
        return await asyncio.wait_for(_answer(client.command, stdout), SECONDS)
    finally:
        if process is not None:
            await client._end(process, job)
        if drained is not None:
            drained.cancel()
        shutil.rmtree(workdir, ignore_errors=True)


async def _answer(command: str, stdout: asyncio.StreamReader) -> bool:
    """Whether its answer to the first request is the one its run goes on from."""
    if command == "copilot":
        while (told := await _framed(stdout)) is not None:
            if told.get("id") == 1 and "method" not in told:
                return _dict(told.get("result")).get("protocolVersion") == PROTOCOL
        return False
    async for raw in stdout:
        try:
            told = _dict(json.loads(raw))
        except ValueError:
            continue
        if command == "codex" and told.get("id") == 1 and "method" not in told:
            return "result" in told
        response = _dict(told.get("response"))
        if told.get("type") == "control_response" and response.get("request_id") == "init":
            return response.get("subtype") == "success" and _dict(
                response.get("response")).get("hooks_applied") is True
    return False
