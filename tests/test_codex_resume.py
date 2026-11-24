"""0.1.8: native Codex signed in for KOLONİ alone (its provider's own sign-in folder) goes on in
its own thread from the topic's previous turn - kept on disk there, never in the user's ~/.codex -
where started under all the same, its thread/resume given all thread/start would be; else, and
where it cannot go on there, a new thread sent the whole conversation. Its token usage is the
thread's total: a turn counts its difference. Only the stand-in (`fake_codex_app_server.py`)
runs here (measured: cli-surdurme-olcum.md)."""

import asyncio
import json
import sys
from pathlib import Path

import pytest

from app.config import load_settings
from app.db.models import Agent
from app.main import create_app
from app.model_native import (
    CODEX_COMPACTED,
    CODEX_ROLLOUTS,
    RESUMED,
    SESSION_ANEW,
    CodexNativeClient,
    forget_session,
    sweep_codex_threads,
)
from tests.conftest import scaled
from tests.fakes import ScriptedModel
from tests.keyed import TestClient
from tests.test_native_agent import start

FAKE = [sys.executable, str(Path(__file__).with_name("fake_codex_app_server.py"))]
TID = "01a20e24-a85d-7a31-a32d-16a0e50a9fbe"  # (a uuid v7, as Codex named a thread live)
SYSTEM = {"role": "system", "content": "You are the Lead."}
FIRST = [SYSTEM, {"role": "user", "content": "fix the greeting"}]
SECOND = [*FIRST, {"role": "assistant", "content": "Done."}, {"role": "user", "content": "tests"}]
THIRD = [*SECOND, {"role": "assistant", "content": "Tested."}, {"role": "user", "content": "docs"}]
OWN = {"Origin": "http://127.0.0.1:8790"}


def usage(inputs: int, cached: int, outputs: int) -> dict:
    """Its thread's total at a turn's end, as thread/tokenUsage/updated says it."""
    return {"input_tokens": inputs, "cached_input_tokens": cached, "output_tokens": outputs}


@pytest.fixture
def codex(tmp_path):
    record, plan, starts = tmp_path / "record.json", tmp_path / "plan.json", tmp_path / "starts"
    runtime = tmp_path / "runtime"
    own = runtime / "cli-homes" / "p1"  # (its provider's own sign-in folder: `limits.cli_home`)

    def make(script=({"say": "Done."},), home: Path | None = own, **more) -> CodexNativeClient:
        plan.write_text(
            json.dumps(
                {
                    "record": str(record),
                    "starts": str(starts),
                    "script": list(script),
                    "thread_id": TID,
                    "last_input": 9000,
                    "window": 258400,
                    **more,
                }
            ),
            encoding="utf-8",
        )
        return CodexNativeClient(
            None, None, timeout=30, launcher=FAKE, env={"FAKE_CLI_PLAN": str(plan)}, home=home
        )

    make.home, make.runtime = own, runtime
    make.record = lambda: json.loads(record.read_text(encoding="utf-8"))
    make.starts = lambda: (
        sum(1 for line in starts.read_text(encoding="utf-8").splitlines() if "app-server" in line)
        if starts.exists()
        else 0
    )
    make.rollouts = lambda: sorted(own.glob(CODEX_ROLLOUTS.format(id="*")))
    return make


def run(cli, root, messages, session=None, level="full_auto", withheld=(), tools=(), call=None):
    """One native turn of it, kept (`keep`), as `_native_work` runs it; what it put on record."""
    items: list[dict] = []

    async def call_tool(name, arguments):
        return await call(name) if call else (True, "{}")

    async def nothing(*_args):
        return None

    async def on_item(phase, item):
        items.append(item)

    result = asyncio.run(
        cli.run_native(
            "gpt-6-luna",
            messages,
            list(tools),
            str(root),
            call_tool,
            nothing,
            on_item,
            withheld=withheld,
            session=session,
            level=level,
            keep=True,
        )
    )
    return result, items


def said(items: list[dict], tool: str) -> list[str]:
    return [
        item["result"]["content"][0]["text"]
        for item in items
        if item.get("server") == "codex" and item.get("tool") == tool
    ]


def test_the_next_turn_goes_on_in_its_thread_given_all_a_new_one_is(codex, tmp_path):
    first, _ = run(codex(), tmp_path, FIRST)
    kept = first.session
    assert (kept["id"], kept["home"], kept["cli"]) == (TID, str(codex.home), "codex")
    seen = codex.record()
    # Kept on disk in its provider's own folder (never the user's ~/.codex), not ephemeral.
    assert seen["codex_home"] == str(codex.home) and seen["thread"]["ephemeral"] is False
    assert [one.name for one in codex.rollouts()] == [f"rollout-2026-11-24T10-00-00-{TID}.jsonl"]
    started = {k: v for k, v in seen["thread"].items() if k != "ephemeral"}

    second, _ = run(codex(), tmp_path, SECOND, session=kept)
    seen = codex.record()
    assert seen["thread_method"] == "thread/resume" and seen["thread"]["threadId"] == TID
    # Given all thread/start was - this turn's folder, leave, reviewer and sandbox - and none of
    # its earlier turns back (`excludeTurns`).
    assert {k: v for k, v in seen["thread"].items() if k not in ("threadId", "excludeTurns")} == (
        started
    )
    assert seen["thread"]["excludeTurns"] is True
    told = seen["stdin"]
    assert "tests" in told and RESUMED in told and "You are the Lead." in told
    assert "fix the greeting" not in told
    assert (second.session["id"], second.session["home"]) == (TID, kept["home"])
    assert codex.starts() == 2  # (one app-server a turn, never asked twice)


def test_its_turns_count_what_each_spent_not_the_threads_total(codex, tmp_path):
    first = run(codex(usage=usage(4000, 3000, 120)), tmp_path, FIRST)[0]
    second = run(codex(usage=usage(9000, 7000, 300)), tmp_path, SECOND, first.session)[0]
    third = run(codex(usage=usage(9500, 7400, 350)), tmp_path, THIRD, second.session)[0]
    assert codex.record()["thread_method"] == "thread/resume"
    assert [(r.input_tokens, r.cache_read, r.output_tokens) for r in (first, second, third)] == [
        (4000, 3000, 120),
        (5000, 4000, 180),
        (500, 400, 50),
    ]
    assert third.session["spent"]["input_tokens"] == 9500
    # Its size and window at its end, for KOLONİ's bound (`AgentRunner._kept_mark`).
    assert (third.context_used, third.context_window) == (9000, 258400)


@pytest.mark.parametrize("change", ["level", "folder", "withheld", "model", "home"])
def test_another_level_folder_leave_model_or_sign_in_starts_a_new_thread(codex, tmp_path, change):
    kept = run(codex(), tmp_path, FIRST)[0].session
    other = tmp_path / "other"
    other.mkdir()
    cli = codex(home=tmp_path / "runtime" / "cli-homes" / "p2" if change == "home" else codex.home)
    if change == "model":
        cli._model = "gpt-6-sol"
    result, _ = run(
        cli,
        other if change == "folder" else tmp_path,
        SECOND,
        session=kept,
        level="ask" if change == "level" else "full_auto",
        withheld=("write",) if change == "withheld" else (),
    )
    seen = codex.record()
    assert seen["thread_method"] == "thread/start"
    assert "fix the greeting" in seen["stdin"] and "tests" in seen["stdin"]
    assert result.session["under"] != kept["under"]


@pytest.mark.parametrize(
    "how, why", [("refuse", "no rollout found"), ("other", "another thread"), ("gone", "rollout")]
)
def test_a_thread_it_cannot_go_on_in_starts_anew_once_said_on_its_record(codex, tmp_path, how, why):
    kept = run(codex(), tmp_path, FIRST)[0].session
    if how == "gone":  # (removed by hand, or a backup restored without it)
        for rollout in codex.rollouts():
            rollout.unlink()
    before = codex.starts()
    result, items = run(
        codex(**({} if how == "gone" else {"resume": how})), tmp_path, SECOND, session=kept
    )
    assert codex.starts() == before + 2  # (the refused one, and the new one: never more)
    seen = codex.record()
    assert seen["thread_method"] == "thread/start" and "fix the greeting" in seen["stdin"]
    (line,) = said(items, "session")
    assert line.startswith(SESSION_ANEW.format(label="Codex", why="x").split("(")[0])
    assert why in line
    # A new thread, counted whole (none of the refused one's spent).
    assert result.session["id"] == TID and result.input_tokens == 4000


def test_its_own_compaction_is_said_on_its_record(codex, tmp_path):
    _, items = run(codex([{"compaction": True}, {"say": "Done."}]), tmp_path, FIRST)
    assert said(items, "compaction") == [CODEX_COMPACTED]


def test_on_the_users_own_sign_in_no_thread_is_kept_nor_written(codex, tmp_path):
    cli = codex(home=None)
    assert not cli.resumes
    result, _ = run(cli, tmp_path, FIRST)
    seen = codex.record()
    assert result.session is None and seen["thread"]["ephemeral"] is True
    assert seen["thread_method"] == "thread/start" and not codex.runtime.exists()


def test_a_turn_that_outran_kolonis_call_keeps_no_thread(codex, tmp_path):
    tools = [
        {
            "type": "function",
            "function": {"name": "run_command", "description": "Run.", "parameters": {}},
        }
    ]
    runs = tmp_path / "runs.log"

    async def call(name):
        # On past its turn's end (Codex L2): until it said its turn is over, and a while after.
        for _ in range(int(scaled(30) / 0.02)):
            if runs.exists() and "end" in runs.read_text(encoding="utf-8"):
                break
            await asyncio.sleep(0.02)
        await asyncio.sleep(scaled(0.5))
        return True, "exit code 0"

    script = [
        {"koloni": "run_command", "args": {"command": "python -u wait.py"}, "pending": True},
        {"say": "It is still running."},
    ]
    result, _ = run(codex(script, runs=str(runs)), tmp_path, FIRST, tools=tools, call=call)
    # Its thread never saw that call's end: not gone on in, and not left on disk.
    assert result.session is None and codex.rollouts() == []


def test_a_codex_thread_forgotten_is_its_rollout_in_a_koloni_folder_alone(tmp_path):
    runtime = tmp_path / "runtime"
    home = runtime / "cli-homes" / "p1"
    rollout = home / "sessions" / "2026" / "11" / "24" / f"rollout-x-{TID}.jsonl"
    other = rollout.with_name("rollout-x-01a20e24-0000-7000-8000-000000000001.jsonl")
    rollout.parent.mkdir(parents=True)
    for one in (rollout, other):
        one.write_text("{}\n", encoding="utf-8")
    elsewhere = tmp_path / "elsewhere" / "cli-homes" / "p1"
    outside = elsewhere / rollout.relative_to(home)
    outside.parent.mkdir(parents=True)
    outside.write_text("{}\n", encoding="utf-8")
    forget_session({"id": TID, "home": str(elsewhere), "cli": "codex"}, runtime)
    forget_session({"id": "../*", "home": str(home), "cli": "codex"}, runtime)
    assert rollout.exists() and outside.exists()
    forget_session({"id": TID, "home": str(home), "cli": "codex"}, runtime)
    assert not rollout.exists() and other.exists() and outside.exists()


def test_threads_no_agent_names_are_swept_in_codex_providers_folders_alone(tmp_path):
    runtime = tmp_path / "runtime"
    homes = runtime / "cli-homes"
    day = Path("sessions") / "2026" / "11" / "24"
    named = homes / "p1" / day / f"rollout-x-{TID}.jsonl"
    stray = homes / "p1" / day / "rollout-x-01a20e24-0000-7000-8000-000000000002.jsonl"
    claude = homes / "p9" / day / "rollout-x-01a20e24-0000-7000-8000-000000000003.jsonl"
    for one in (named, stray, claude):
        one.parent.mkdir(parents=True, exist_ok=True)
        one.write_text("{}\n", encoding="utf-8")
    kept = [{"id": TID, "home": str(homes / "p1"), "cli": "codex"}, None, {"id": "x"}]
    sweep_codex_threads(runtime, kept, ["p1", "..", "none"])
    assert named.exists() and not stray.exists() and claude.exists()


# --- in the app: the topic's later turns -----------------------------------------------------


@pytest.fixture
def chat(settings_env, tmp_path, project_dir, wait_run):
    settings = load_settings(settings_env)
    record, plan = tmp_path / "record.json", tmp_path / "plan.json"
    home = settings.runtime_root / "cli-homes" / "codex-own"

    def rescript(**more):
        told = {"record": str(record), "script": [{"say": "Done."}], "thread_id": TID}
        plan.write_text(
            json.dumps({**told, "last_input": 9000, "window": 258400, **more}), encoding="utf-8"
        )

    rescript()
    cli = CodexNativeClient(
        None, None, timeout=30, launcher=FAKE, env={"FAKE_CLI_PLAN": str(plan)}, home=home
    )
    app = create_app(settings, model=ScriptedModel([]), clients={"Codex": cli})
    with TestClient(app, base_url="http://127.0.0.1:8790") as client:
        provider = client.post(
            "/api/providers", json={"name": "Codex", "kind": "codex_cli", "mode": "native"}
        ).json()
        cid, run_id = start(client, project_dir, provider)
        snap = wait_run(client, cid, run_id, 30.0)
        assert snap["runs"][-1]["status"] == "completed", snap["runs"][-1]["error"]

        def turn(words, new_topic=False, **more):
            rescript(**more)
            run_id = client.post(
                f"/api/conversations/{cid}/messages",
                json={"content": words, **({"new_topic": True} if new_topic else {})},
            ).json()["run"]["id"]
            snap = wait_run(client, cid, run_id, 30.0)
            assert snap["runs"][-1]["status"] == "completed", snap["runs"][-1]["error"]
            return snap

        turn.client, turn.cid, turn.db = client, cid, app.state.session_factory
        turn.record = lambda: json.loads(record.read_text(encoding="utf-8"))
        turn.rollouts = lambda: sorted(home.glob(CODEX_ROLLOUTS.format(id="*")))
        yield turn


def leads(chat) -> list[Agent]:
    with chat.db() as session:
        return (
            session.query(Agent)
            .filter(Agent.parent_agent_id.is_(None))
            .order_by(Agent.created_at)
            .all()
        )


def test_it_goes_on_within_its_topic_and_its_thread_goes_with_a_new_topic_and_the_chat(chat):
    (lead,) = leads(chat)
    assert lead.cli_session["id"] == TID and len(chat.rollouts()) == 1
    # (KOLONİ holds it below where Codex was measured not to compact itself)
    assert lead.context_window == 166_000
    chat("now the tests", usage=usage(9000, 7000, 300))
    assert chat.record()["thread_method"] == "thread/resume"
    assert "now the tests" in chat.record()["stdin"]
    assert [one.input_tokens for one in leads(chat)] == [4000, 5000]
    assert [one.cli_session is not None for one in leads(chat)] == [False, True]

    other = "01a20e24-0000-7000-8000-00000000000b"
    chat("something else", new_topic=True, thread_id=other)
    assert chat.record()["thread_method"] == "thread/start"
    # (the other topic's thread is gone with it)
    assert [one.name.endswith(f"{other}.jsonl") for one in chat.rollouts()] == [True]

    client = chat.client
    assert (
        client.patch(f"/api/conversations/{chat.cid}", json={"archived": True}, headers=OWN)
    ).status_code == 200
    deleted = client.post("/api/conversations/delete", json={"ids": [chat.cid]}, headers=OWN)
    assert deleted.json()["deleted"] == [chat.cid]
    assert chat.rollouts() == []  # (gone with its conversation)


def test_a_thread_past_its_bound_is_not_gone_on_in_and_its_record_says_why(chat):
    # 75 % (Summarise a long context at) of 166,000 (its bound, under its 258,400).
    snap = chat("now the tests", last_input=130_000)
    assert chat.record()["thread_method"] == "thread/resume"
    assert leads(chat)[-1].cli_session is None and chat.rollouts() == []
    (line,) = [c["result"] for c in snap["tool_calls"] if c["name"] == "codex__session"]
    assert "130,000 tokens, 75% or more of 166,000" in line and line.startswith("Codex's")
    chat("and the docs")
    assert chat.record()["thread_method"] == "thread/start"
    assert "fix the greeting" in chat.record()["stdin"]
