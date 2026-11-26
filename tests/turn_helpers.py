"""What many tests share: a project and a chat made through the API, a turn's tool calls, a
wait for another thread, the app's event loop, a clock the test holds, and an app whose provider
is a stand-in CLI."""

import asyncio
import io
import json
import struct
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.agent.limits_mixin import WATCHED_SLOW_MINUTES
from app.config import load_settings
from app.main import create_app
from app.model_agy import AgyClient
from app.model_cli import ClaudeCliClient, CodexCliClient
from app.model_native import CodexNativeClient, CopilotNativeClient
from app.model_session import ClaudeSessionClient
from tests.fakes import ScriptedModel
from tests.keyed import TestClient

ORIGIN = "http://127.0.0.1:8790"
NOBODY = "nobody is here to ask"
T0 = datetime(2026, 10, 8, 9, 0, tzinfo=UTC)
HERE = Path(__file__).parent


def setup(make_client, project_dir, scripts, executor=None, **conversation):
    client, model = make_client(scripts, executor=executor)
    client.headers["Origin"] = ORIGIN
    pid, cid = place(client, project_dir, **conversation)
    return client, model, pid, cid


def place(client, project_dir, **conversation):
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    if conversation:
        patched = client.patch(f"/api/conversations/{cid}", json=conversation)
        assert patched.status_code == 200, patched.text
    return pid, cid


def allow(client, cid, command):
    """Put a command on a conversation's allow list, as "Always run" does; returns the rule's
    id."""
    made = client.post(f"/api/conversations/{cid}/allowed-commands", json={"prefix": command})
    assert made.status_code in (200, 201), made.text
    return made.json()["id"]


def finished(client, wait_run, cid, run_id, timeout=10.0):
    return wait_run(client, cid, run_id, timeout=timeout)


def run_of(snap, run_id):
    return next(r for r in snap["runs"] if r["id"] == run_id)


def results(snap, run_id):
    return [
        (t["name"], t["status"], t["result"] or "")
        for t in snap["tool_calls"]
        if t["run_id"] == run_id
    ]


def until(check, what, seconds=10.0):
    """Look again and again until `check()` is true: for what another thread is doing."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        found = check()
        if found:
            return found
        time.sleep(0.02)
    raise AssertionError(f"never happened: {what}")


def on_loop(client, work):
    """Do something on the app's event loop, from the test's thread."""
    return client.app.state.triggers._on_loop(work)


def everything_kept(client) -> bytes:
    """The database as it is on disk, with what has not been folded into it yet."""
    database = client.app.state.settings.db_path
    return b"".join(
        path.read_bytes() for path in (database, Path(f"{database}-wal")) if path.exists()
    )


def zone_with_summer_time() -> ZoneInfo:
    """Central European time as zoneinfo reads it from a file: no table of past changes,
    only the rule (last Sunday of March 02:00 -> 03:00, last Sunday of October 03:00 ->
    02:00). Built here because this machine has no zone files and none may be installed."""

    def block() -> bytes:
        header = b"TZif2" + bytes(15) + struct.pack(">6l", 0, 0, 0, 0, 1, 4)
        return header + struct.pack(">lBB", 3600, 0, 0) + b"CET\0"

    data = block() + block() + b"\nCET-1CEST,M3.5.0,M10.5.0/3\n"
    return ZoneInfo.from_file(io.BytesIO(data), key="Test/Central_Europe")


class HeldClock:
    """Stands where the event loop's `call_later` is: what was set is kept, and happens
    when the test says so - no minute is ever waited for. `but`: clocks the test is not about
    (K-yavas: a watched Orchestrator's, `NOT_SLOW`), left to the event loop."""

    def __init__(self, but: tuple[float, ...] = ()):
        self.set: list[SimpleNamespace] = []
        self.but = but

    def __call__(self, delay, callback, *args):
        if delay in self.but:
            return asyncio.get_running_loop().call_later(delay, callback, *args)
        timer = SimpleNamespace(delay=delay, cancelled=False)
        timer.fire = lambda: callback(*args)
        timer.cancel = lambda: setattr(timer, "cancelled", True)
        self.set.append(timer)
        return timer


NOT_SLOW = (WATCHED_SLOW_MINUTES * 60.0,)  # (`HeldClock`'s `but`)


FAKES = {
    "session": HERE / "fake_session_cli.py",
    "step": HERE / "fake_cli.py",
    "native": HERE / "fake_codex_app_server.py",
    "copilot": HERE / "fake_copilot_cli.py",
    "agy": HERE / "fake_agy_cli.py",
}


def _fake(name):
    return [sys.executable, str(FAKES[name])]


# name -> (the provider as the user makes it, how its stand-in is built around a plan)
CLIS = {
    "claude session": (
        {"kind": "claude_cli", "mode": "session"},
        lambda plan: ClaudeSessionClient(
            launcher=_fake("session"), timeout=30, env={"FAKE_CLI_PLAN": plan}
        ),
    ),
    "claude step": (
        {"kind": "claude_cli", "mode": "step"},
        lambda plan: ClaudeCliClient(
            model=None, timeout=20, launcher=_fake("step"), env={"FAKE_CLI_PLAN": plan}
        ),
    ),
    "codex step": (
        {"kind": "codex_cli", "mode": "step"},
        lambda plan: CodexCliClient(
            model=None, timeout=20, launcher=_fake("step"), env={"FAKE_CLI_PLAN": plan}
        ),
    ),
    "codex native": (
        {"kind": "codex_cli", "mode": "native"},
        lambda plan: CodexNativeClient(
            launcher=_fake("native"), timeout=30, env={"FAKE_CLI_PLAN": plan}
        ),
    ),
    "copilot native": (
        {
            "kind": "copilot_cli",
            "mode": "native",
            "base_url": "http://127.0.0.1:9/v1",
            "api_key": "sk-secret-123",
            "default_model": "qwen-local",
        },
        lambda plan: CopilotNativeClient(
            None,
            "qwen-local",
            timeout=30,
            launcher=_fake("copilot"),
            env={"FAKE_CLI_PLAN": plan},
            base_url="http://127.0.0.1:9/v1",
            api_key="sk-secret-123",
            options={},
        ),
    ),
    "agy native": (
        {"kind": "agy_cli", "mode": "native"},
        lambda plan: AgyClient(
            None, None, timeout=30, reads=False, launcher=_fake("agy"), env={"FAKE_AGY_PLAN": plan}
        ),
    ),
    "agy reads": (
        {"kind": "agy_cli", "mode": "reads"},
        lambda plan: AgyClient(
            None, None, timeout=30, reads=True, launcher=_fake("agy"), env={"FAKE_AGY_PLAN": plan}
        ),
    ),
}


@pytest.fixture
def cli_app(settings_env, tmp_path):
    """An app with one provider, "Cli", that is a stand-in CLI following a plan; every
    other provider is a scripted model."""
    opened = []
    record, plan = tmp_path / "record.json", tmp_path / "plan.json"

    def make(which, default_steps=(), executor=None, provider=None, **plan_fields):
        told, build = CLIS[which]
        plan.write_text(json.dumps({"record": str(record), **plan_fields}), encoding="utf-8")
        default = ScriptedModel(
            default_steps if isinstance(default_steps, dict) else list(default_steps)
        )
        app = create_app(
            load_settings(settings_env),
            model=default,
            clients={"Cli": build(str(plan))},
            executors=executor.factory if executor else None,
        )
        client = TestClient(app, base_url=ORIGIN)
        client.__enter__()
        opened.append(client)
        client.headers["Origin"] = ORIGIN
        made = client.post("/api/providers", json={"name": "Cli", **told, **(provider or {})})
        assert made.status_code == 201, made.text
        return client, made.json(), default

    make.ran = record.exists
    make.record = lambda: json.loads(record.read_text(encoding="utf-8"))
    yield make
    for client in opened:
        client.__exit__(None, None, None)


@pytest.fixture
def started(settings_env):
    """The app, started again and again on the same data, one at a time."""
    opened = []

    def stop():
        for client in opened:
            client.__exit__(None, None, None)
        opened.clear()

    def start(steps):
        stop()
        model = ScriptedModel(steps)
        client = TestClient(create_app(load_settings(settings_env), model=model), base_url=ORIGIN)
        client.__enter__()
        client.headers["Origin"] = ORIGIN
        opened.append(client)
        return client

    start.stop = stop
    yield start
    stop()
