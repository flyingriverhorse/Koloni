"""Codex L2 (live, 24 Nov 2026, Codex as a session): its turn completed while a call of KOLONİ's
tools was still running - its MCP item begun and never ended, then its final answer ("It is still
running") and turn/completed - and KOLONİ ended the call with the turn: the command killed, the
call interrupted, the turn Done. The turn now waits for that call, which ends by its own bound,
and says so with Codex's answer; Stop still ends it; a question is not waited for (nobody will
read its card). Only the stand-in (`fake_codex_app_server.py`) runs here, in that order: it ends
its turn only once KOLONİ has its call at work (`after`)."""

import asyncio
import json
import sys
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
OUTLIVED = CALLS_OUTLIVED.format(label="Codex")
ANSWER = "Started it once. It is still running."
ARGS = {"run_command": {"command": "python -u wait.py"}, "ask_user": {"question": "Go on?"}}
MESSAGES = [
    {"role": "system", "content": "You are the Orchestrator."},
    {"role": "user", "content": "Run python -u wait.py once."},
]


def tools(*names: str) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": name,
                "parameters": {"type": "object", "properties": {}},
            },
        }
        for name in names
    ]


@pytest.fixture
def codex(tmp_path):
    """A Codex of either way whose turn ends with its call of `tool` still at work - as the live
    turn's lines had it: the call sent, never answered, its answer and turn/completed after it -
    once `make.at_work` is there; a home of its own (never the user's ~/.codex)."""
    plan, home, at_work = tmp_path / "plan.json", tmp_path / "codex", tmp_path / "at-work"
    home.mkdir()

    def make(kind, tool="run_command"):
        script = [
            {"koloni": tool, "args": ARGS[tool], "pending": True, "after": str(at_work)},
            {"say": ANSWER, "phase": "final_answer"},
        ]
        told = {"record": str(tmp_path / "record.json"), "script": script}
        plan.write_text(json.dumps(told), encoding="utf-8")
        return kind(
            launcher=FAKE, timeout=30, env={"FAKE_CLI_PLAN": str(plan), "CODEX_HOME": str(home)}
        )

    make.at_work, make.root = at_work, tmp_path
    return make


class Held:
    """KOLONİ's side of the call: at work past Codex's turn, until the turn says it waits for it
    (or for good, `forever`) - as wait.py's 120 seconds were."""

    def __init__(self, codex, forever: bool = False) -> None:
        self.codex, self.forever = codex, forever
        self.texts, self.ended, self.cancelled = [], [], []
        self.waits = asyncio.Event()

    async def on_text(self, text: str) -> None:
        self.texts.append(text)
        if OUTLIVED in text:
            self.waits.set()

    async def call_tool(self, name: str, arguments: str) -> tuple[bool, str]:
        try:
            self.codex.at_work.touch()  # (it may end its turn now)
            await self.waits.wait()  # (before the fix: cancelled with its turn instead)
            if self.forever:
                await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled.append(name)
            raise
        self.ended.append(name)
        return True, "exit code 0"


async def nothing(*_args) -> None:
    return None


def native(codex, held, tool="run_command", on_end=None):
    return codex(CodexNativeClient, tool).run_native(
        "gpt-fake",
        MESSAGES,
        tools("run_command", "ask_user"),
        str(codex.root),
        held.call_tool,
        held.on_text,
        nothing,
        on_end=on_end,
    )


def test_a_session_turn_waits_for_kolonis_call_its_answer_outran(codex):
    held = Held(codex)
    result = asyncio.run(
        codex(CodexSessionClient).run_session(
            "gpt-fake", MESSAGES, tools("run_command"), held.call_tool, held.on_text
        )
    )
    # The call ran to its own end, never cut off by the turn's; and that is said with its answer.
    assert (held.ended, held.cancelled) == (["run_command"], [])
    assert held.texts == [ANSWER, "\n\n" + OUTLIVED]
    assert result.input_tokens == 4000


def test_a_native_turn_waits_too_and_stop_still_ends_it(codex):
    held = Held(codex)
    asyncio.run(native(codex, held))
    assert (held.ended, held.cancelled) == (["run_command"], [])
    assert held.texts == [ANSWER, "\n\n" + OUTLIVED]

    # A call that would run on for good: Stop ends the wait, the call with it, and the turn.
    held, ends = Held(codex, forever=True), []
    codex.at_work.unlink()

    async def turn():
        async def stop_while_it_waits() -> None:
            await held.waits.wait()
            ends[0](OwnStop("Stopped by the user"))

        stopper = asyncio.ensure_future(stop_while_it_waits())
        try:
            return await native(codex, held, on_end=ends.append)
        finally:
            stopper.cancel()

    with pytest.raises(OwnStop, match="Stopped by the user"):
        asyncio.run(asyncio.wait_for(turn(), scaled(60)))
    assert (held.ended, held.cancelled) == ([], ["run_command"])


def test_a_question_left_open_is_not_waited_for(codex):
    # (Nobody reads its card once the turn is over: it is closed with it, as before.)
    held = Held(codex, forever=True)
    asyncio.run(asyncio.wait_for(native(codex, held, tool="ask_user"), scaled(60)))
    assert (held.ended, held.cancelled) == ([], ["ask_user"])
    assert held.texts == [ANSWER]


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

    def answers(snap) -> list[str]:
        # (the call's own message holds no words: as live)
        return [m["content"] for m in snap["messages"] if m["role"] == "assistant" and m["content"]]

    with TestClient(app, base_url="http://127.0.0.1:8790") as client:
        provider = client.post(
            "/api/providers", json={"name": "Codex", "kind": "codex_cli", "mode": "session"}
        ).json()
        cid, run_id = start(client, project_dir, provider)
        until(client, cid, lambda s: s["commands"], timeout=30)
        codex.at_work.touch()  # (its command at work: Codex may end its turn now)
        # Its turn is over, said so, and the turn waits: its command is still at work.
        snap = until(client, cid, lambda s: any(OUTLIVED in one for one in answers(s)), timeout=30)
        assert snap["runs"][0]["status"] == "running"
        assert [c["status"] for c in snap["commands"]] == ["running"]
        command.release()  # (its own time: wait.py's 120 seconds)
        snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    (ran,) = snap["commands"]
    assert (ran["status"], ran["exit_code"], executor.killed) == ("exited", 0, [])
    (call,) = snap["tool_calls"]
    assert (call["name"], call["status"]) == ("run_command", "succeeded")
    # Said with Codex's answer, in the same message: its last answer is still Codex's words.
    assert answers(snap) == [f"{ANSWER}\n\n{OUTLIVED}"]
