"""Codex L2 (live, 24 Nov 2026, Codex as a session): its turn completed while a call of KOLONİ's
tools was still running - its MCP item begun and never ended, then its final answer ("It is still
running") and turn/completed - and KOLONİ ended the call with the turn: the command killed, the
call interrupted, the turn Done. The turn now waits for that call, which ends by its own bound;
Stop still ends it. Only the stand-in (`fake_codex_app_server.py`) runs here, in that order."""

import asyncio
import json
import sys
import time
from pathlib import Path

import pytest

from app.config import load_settings
from app.main import create_app
from app.model_client import OwnStop
from app.model_native import CALLS_OUTLIVED, CodexNativeClient, CodexSessionClient
from tests.conftest import Gate, scaled
from tests.fakes import Script, ScriptedExecutor, ScriptedModel
from tests.keyed import TestClient
from tests.test_native_agent import start
from tests.test_parallel import until

FAKE = [sys.executable, str(Path(__file__).with_name("fake_codex_app_server.py"))]
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run a command.",
            "parameters": {"type": "object", "properties": {}},
        },
    }
]
# As the live turn's lines had it: the call sent, never answered, and the turn over after it.
SCRIPT = [
    {"koloni": "run_command", "args": {"command": "python -u wait.py"}, "pending": True},
    {"say": "Started it once. It is still running.", "phase": "final_answer"},
]
MESSAGES = [
    {"role": "system", "content": "You are the Orchestrator."},
    {"role": "user", "content": "Run python -u wait.py once."},
]


@pytest.fixture
def codex(tmp_path):
    """A Codex of either way, following SCRIPT; a home of its own (never the user's ~/.codex).
    `make.over()`: whether it has said its turn is over (its last line before turn/completed)."""
    plan, home, runs = tmp_path / "plan.json", tmp_path / "codex", tmp_path / "runs.log"
    home.mkdir()
    told = {"record": str(tmp_path / "record.json"), "script": SCRIPT, "runs": str(runs)}
    plan.write_text(json.dumps(told), encoding="utf-8")

    def make(kind):
        return kind(
            launcher=FAKE, timeout=30, env={"FAKE_CLI_PLAN": str(plan), "CODEX_HOME": str(home)}
        )

    make.over = lambda: (
        runs.exists()
        and any(line.startswith("end ") for line in runs.read_text(encoding="utf-8").splitlines())
    )
    return make


async def turn_over(codex) -> None:
    """Until the stand-in has said its turn is over."""
    deadline = time.monotonic() + scaled(30)
    while not codex.over():
        assert time.monotonic() < deadline, "its turn never ended"
        await asyncio.sleep(0.02)


class Held:
    """KOLONİ's side of the call: it runs on past Codex's answer, and ends only after it (or
    never, `forever`) - as wait.py's 120 seconds did."""

    def __init__(self, forever: bool = False) -> None:
        self.forever, self.texts, self.ended, self.cancelled = forever, [], [], []
        self.answered = asyncio.Event()

    async def on_text(self, text: str) -> None:
        self.texts.append(text)
        if "still running" in text:
            self.answered.set()

    async def call_tool(self, name: str, arguments: str) -> tuple[bool, str]:
        try:
            await self.answered.wait()
            # (On past its turn's end: before the fix it was cancelled within this.)
            await asyncio.sleep(scaled(1) if not self.forever else 3600)
        except asyncio.CancelledError:
            self.cancelled.append(name)
            raise
        self.ended.append(name)
        return True, "exit code 0"


def test_a_session_turn_waits_for_kolonis_call_its_answer_outran(codex):
    held = Held()
    result = asyncio.run(
        codex(CodexSessionClient).run_session(
            "gpt-fake", MESSAGES, TOOLS, held.call_tool, held.on_text
        )
    )
    # The call ran to its own end, never cut off by the turn's; and that is said after its answer.
    assert (held.ended, held.cancelled) == (["run_command"], [])
    assert held.texts[-1] == "\n\n" + CALLS_OUTLIVED.format(label="Codex")
    assert result.input_tokens == 4000


def test_a_native_turn_waits_too_and_stop_still_ends_it(codex, tmp_path):
    held = Held()

    async def on_item(phase, item):
        return None

    asyncio.run(
        codex(CodexNativeClient).run_native(
            "gpt-fake", MESSAGES, TOOLS, str(tmp_path), held.call_tool, held.on_text, on_item
        )
    )
    assert (held.ended, held.cancelled) == (["run_command"], [])
    assert CALLS_OUTLIVED.format(label="Codex") in held.texts[-1]

    # A call that would run on for an hour: Stop ends the wait, the call with it, and the turn.
    held, ends = Held(forever=True), []

    async def stop_once_answered() -> None:
        await held.answered.wait()
        await turn_over(codex)  # (Stop while the turn waits, past Codex's turn/completed)
        await asyncio.sleep(scaled(0.3))
        ends[0](OwnStop("Stopped by the user"))

    async def turn():
        stopper = asyncio.ensure_future(stop_once_answered())
        try:
            return await codex(CodexNativeClient).run_native(
                "gpt-fake",
                MESSAGES,
                TOOLS,
                str(tmp_path),
                held.call_tool,
                held.on_text,
                on_item,
                on_end=ends.append,
            )
        finally:
            stopper.cancel()

    with pytest.raises(OwnStop, match="Stopped by the user"):
        asyncio.run(asyncio.wait_for(turn(), scaled(60)))
    assert (held.ended, held.cancelled) == ([], ["run_command"])
    assert not any(CALLS_OUTLIVED.split("{")[0] in text for text in held.texts)


@pytest.fixture
def wait_run(wait_run):
    return lambda client, cid, run_id, timeout=30.0: wait_run(client, cid, run_id, timeout)


def test_in_the_app_its_command_ends_as_it_does_and_the_turn_after_it(
    codex, settings_env, project_dir, wait_run
):
    """L2 as it was seen: Codex as a session, KOLONİ's run_command at work past its turn."""
    command = Gate()
    executor = ScriptedExecutor([Script(chunks=["tick 0\n"], hold=command)])
    app = create_app(
        load_settings(settings_env),
        model=ScriptedModel([]),
        clients={"Codex": codex(CodexSessionClient)},
        executors=executor.factory,
    )
    with TestClient(app, base_url="http://127.0.0.1:8790") as client:
        provider = client.post(
            "/api/providers", json={"name": "Codex", "kind": "codex_cli", "mode": "session"}
        ).json()
        cid, run_id = start(client, project_dir, provider)
        snap = until(client, cid, lambda s: codex.over() and s["commands"], timeout=30)
        time.sleep(scaled(0.5))  # (past its turn/completed: before the fix, cut off here)
        snap = until(client, cid, lambda s: s["commands"], timeout=5)
        assert snap["runs"][0]["status"] == "running"
        assert [c["status"] for c in snap["commands"]] == ["running"]
        command.release()  # (its own time: wait.py's 120 seconds)
        snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    (ran,) = snap["commands"]
    assert (ran["status"], ran["exit_code"], executor.killed) == ("exited", 0, [])
    (call,) = snap["tool_calls"]
    assert (call["name"], call["status"]) == ("run_command", "succeeded")
    # Said under Codex's answer: as a session, a message of its own (the call's end starts one).
    answers = [m["content"] for m in snap["messages"] if m["role"] == "assistant"]
    assert [one.strip() for one in answers] == [
        "Started it once. It is still running.",
        CALLS_OUTLIVED.format(label="Codex"),
    ]
