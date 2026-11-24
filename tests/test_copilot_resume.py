"""0.1.8: native Copilot goes on in its own session from the topic's previous turn - in a home of
its own under KOLONİ's runtime, kept between turns - where started under all the same, given all
session.create would be; else, and where it cannot go on there, anew with the whole
conversation. Its checkpoint is the session's total: a turn counts its difference. Only the
stand-in (`fake_copilot_headless.py`) runs here (measured: cli-surdurme-olcum.md)."""

import asyncio
import json
from pathlib import Path

import pytest

from app.config import load_settings
from app.db.models import Agent
from app.main import create_app
from app.model_native import (
    COPILOT_SESSIONS,
    COPILOT_TOOLS,
    RESUMED,
    SESSION_ANEW,
    CopilotNativeClient,
    forget_session,
)
from app.model_session import SessionResult, copilot_since
from tests.fakes import ScriptedModel
from tests.keyed import TestClient
from tests.test_copilot_agent import HEADLESS, PAGE, start

SID = "5f0c2a9e-7d41-4b8e-9c3a-1e2f3a4b5c6d"  # (a uuid, as Copilot names a session)
SYSTEM = {"role": "system", "content": "You are the Lead."}
FIRST = [SYSTEM, {"role": "user", "content": "fix the greeting"}]
SECOND = [*FIRST, {"role": "assistant", "content": "Done."}, {"role": "user", "content": "tests"}]
THIRD = [*SECOND, {"role": "assistant", "content": "Tested."}, {"role": "user", "content": "docs"}]
OWN = {"Origin": "http://127.0.0.1:8790"}


def checkpoint(inputs: int, outputs: int, premium: int) -> dict:
    """A session.usage_checkpoint as 1.0.114 sends it: the session's total so far."""
    return {
        "totalPremiumRequests": premium,
        "totalNanoAiu": premium * 1000,
        "accountingSnapshot": {
            "modelMetrics": {
                "gpt-6-luna": {"usage": {"inputTokens": inputs, "outputTokens": outputs}}
            }
        },
    }


def plan_of(record: Path, starts: Path, script=({"say": "Done."},), protocol=4, **more) -> str:
    return json.dumps(
        {
            "record": str(record),
            "starts": str(starts),
            "script": list(script),
            "protocol": protocol,
            "version": "1.0.114" if protocol == 4 else "1.0.105",
            "session_id": SID,
            **more,
        }
    )


@pytest.fixture
def copilot(tmp_path):
    record, plan, starts = tmp_path / "record.json", tmp_path / "plan.json", tmp_path / "starts"
    runtime = tmp_path / "runtime"
    sessions = runtime / "cli-homes" / COPILOT_SESSIONS

    def make(**more) -> CopilotNativeClient:
        plan.write_text(plan_of(record, starts, **more), encoding="utf-8")
        return CopilotNativeClient(
            None,
            "gpt-6-luna",
            timeout=30,
            launcher=HEADLESS,
            env={"FAKE_CLI_PLAN": str(plan)},
            sessions=sessions,
        )

    make.runtime, make.sessions = runtime, sessions
    make.record = lambda: json.loads(record.read_text(encoding="utf-8"))
    make.starts = lambda: (
        len(starts.read_text(encoding="utf-8").splitlines()) if starts.exists() else 0
    )
    make.homes = lambda: sorted(sessions.iterdir()) if sessions.is_dir() else []
    return make


def run(cli, root, messages, session=None, level="full_auto", withheld=(), also=()):
    """One native turn of it, kept (`keep`), as `_native_work` runs it; what it put on record."""
    items: list[dict] = []

    async def call_tool(name, arguments):
        return True, "{}"

    async def nothing(*_args):
        return None

    async def on_item(phase, item):
        items.append(item)

    result = asyncio.run(
        cli.run_native(
            "gpt-6-luna",
            messages,
            [],
            str(root),
            call_tool,
            nothing,
            on_item,
            withheld=withheld,
            also=also,
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
        if item.get("server") == "copilot" and item.get("tool") == tool
    ]


def test_the_next_turn_goes_on_in_its_session_given_all_a_new_one_is(copilot, tmp_path):
    first, _ = run(copilot(), tmp_path, FIRST)
    kept = first.session
    home = Path(kept["home"])
    assert kept["id"] == SID and kept["under"]
    # In a home of its own in KOLONİ's runtime, kept after the turn - never the user's ~/.copilot.
    assert home.parent.resolve() == copilot.sessions.resolve() and home.is_dir()
    assert (home / "session-state" / SID / "events.jsonl").is_file()
    seen = copilot.record()
    assert seen["env"]["COPILOT_HOME"] == str(home) and seen["home_was_empty"]
    created = seen["create"]

    second, _ = run(copilot(), tmp_path, SECOND, session=kept)
    seen = copilot.record()
    assert "create" not in seen and seen["resume"]["sessionId"] == SID
    assert seen["env"]["COPILOT_HOME"] == str(home)
    # Given all session.create was: this turn's tools, leave, hook, folder, model and bridge.
    assert {k: v for k, v in seen["resume"].items() if k != "sessionId"}.keys() == created.keys()
    assert seen["resume"]["permissions"]["request"] is True
    assert seen["resume"]["hooks"]["hasHandlers"] is True
    assert seen["resume"]["tools"]["availableTools"][: len(COPILOT_TOOLS)] == COPILOT_TOOLS
    assert seen["resume"]["workingDirectory"] == str(tmp_path)
    assert seen["resume"]["model"] == "gpt-6-luna" and "koloni" in seen["resume"]["mcp"]["servers"]
    assert seen["tools"] is not None  # (its bridge reached KOLONİ's tool server)
    # Sent only what is new since its last answer.
    told = seen["prompt"]
    assert "tests" in told and RESUMED in told and "You are the Lead." in told
    assert "fix the greeting" not in told
    assert second.session["id"] == SID and second.session["home"] == kept["home"]
    assert copilot.homes() == [home]


@pytest.mark.parametrize("change", ["level", "folder", "withheld", "also", "model"])
def test_another_level_folder_leave_or_model_starts_a_new_session_in_a_new_home(
    copilot, tmp_path, change
):
    kept = run(copilot(), tmp_path, FIRST)[0].session
    other = tmp_path / "other"
    other.mkdir()
    cli = copilot()
    if change == "model":
        cli._model = "claude-haiku-5.5"
    result, _ = run(
        cli,
        other if change == "folder" else tmp_path,
        SECOND,
        session=kept,
        level="ask" if change == "level" else "full_auto",
        withheld=("write",) if change == "withheld" else (),
        also=(str(other),) if change == "also" else (),
    )
    seen = copilot.record()
    assert "resume" not in seen and "create" in seen
    assert "fix the greeting" in seen["prompt"] and "tests" in seen["prompt"]
    assert result.session["home"] != kept["home"] and result.session["under"] != kept["under"]
    assert seen["home_was_empty"]


def test_a_session_it_does_not_have_starts_anew_once_said_on_its_record(copilot, tmp_path):
    kept = run(copilot(usage=[checkpoint(100, 10, 1)]), tmp_path, FIRST)[0].session
    (Path(kept["home"]) / "session-state" / SID / "events.jsonl").unlink()  # (gone)
    before = copilot.starts()
    result, items = run(copilot(usage=[checkpoint(80, 8, 1)]), tmp_path, SECOND, session=kept)
    assert copilot.starts() == before + 2  # (the refused one, and the new one: never more)
    seen = copilot.record()
    assert "create" in seen and "fix the greeting" in seen["prompt"] and "tests" in seen["prompt"]
    (line,) = said(items, "session")
    assert line.startswith(SESSION_ANEW.split("(")[0]) and "Session not found" in line
    # A new session in a new home, counted whole (none of the refused one's spent).
    assert result.session["home"] != kept["home"] and result.input_tokens == 80
    assert result.session["spent"]["input_tokens"] == 80


def test_at_protocol_3_no_session_is_kept_nor_gone_on_in(copilot, tmp_path):
    result, _ = run(copilot(protocol=3), tmp_path, FIRST)
    assert result.session is None and copilot.homes() == []  # (its home went with it)
    # A session kept by a Copilot of protocol 4 is not gone on in by one of 3: anew, once.
    kept = run(copilot(), tmp_path, FIRST)[0].session
    before = copilot.starts()
    result, items = run(copilot(protocol=3), tmp_path, SECOND, session=kept)
    assert copilot.starts() == before + 2 and "fix the greeting" in copilot.record()["prompt"]
    assert "protocol 3" in said(items, "session")[0] and result.session is None
    assert copilot.homes() == [Path(kept["home"])]  # (the kept one is its agent's to forget)


def test_its_turns_count_what_each_spent_not_the_sessions_total(copilot, tmp_path):
    first = run(copilot(usage=[checkpoint(100, 10, 1)]), tmp_path, FIRST)[0]
    second = run(copilot(usage=[checkpoint(250, 25, 2)]), tmp_path, SECOND, first.session)[0]
    third = run(copilot(usage=[checkpoint(450, 45, 3)]), tmp_path, THIRD, second.session)[0]
    assert "resume" in copilot.record()
    assert [(r.input_tokens, r.output_tokens) for r in (first, second, third)] == [
        (100, 10),
        (150, 15),
        (200, 20),
    ]
    assert [(r.premium_requests, r.nano_aiu) for r in (first, second, third)] == [(1, 1000)] * 3
    assert third.session["spent"]["input_tokens"] == 450


def test_what_a_checkpoint_does_not_say_is_never_made_up():
    total = SessionResult(250, None, cache_read=5)
    # A new session: all of it this turn's.
    assert copilot_since(total, None)[0] == total
    counted, spent = copilot_since(total, {"input_tokens": 100, "cache_read": 9})
    # Known before and now: the difference; not known before, or gone down: not known.
    assert (counted.input_tokens, counted.output_tokens, counted.cache_read) == (150, None, None)
    assert spent["input_tokens"] == 250
    # A turn that said nothing keeps the total before it for the next.
    nothing, spent = copilot_since(SessionResult(None, None), {"input_tokens": 100})
    assert nothing.input_tokens is None and spent["input_tokens"] == 100


def test_its_window_and_its_compaction_are_what_its_session_says(copilot, tmp_path):
    result, items = run(
        copilot(
            usage_info=[{"tokenLimit": 128000}, {"tokenLimit": 272000, "currentTokens": 9}],
            compaction={
                "success": True,
                "preCompactionTokens": 569494,
                "postCompactionTokens": 9298,
            },
        ),
        tmp_path,
        FIRST,
    )
    assert result.context_window == 272000  # (its last word)
    (line,) = said(items, "compaction")
    assert "569,494 -> 9,298 tokens" in line and "its own summary" in line
    _, items = run(
        copilot(compaction={"success": False, "error": "model refused"}), tmp_path, FIRST
    )
    (failed,) = [item for item in items if item.get("tool") == "compaction"]
    assert failed["status"] == "failed" and "model refused" in failed["error"]["message"]


def test_without_a_folder_for_its_sessions_nothing_is_kept(tmp_path, copilot):
    copilot()  # (its plan)
    bare = CopilotNativeClient(
        None, "gpt-6-luna", timeout=30, launcher=HEADLESS, env=copilot()._env
    )
    assert not bare.resumes
    result, _ = run(bare, tmp_path, FIRST)
    assert result.session is None and "COPILOT_HOME" in copilot.record()["env"]
    assert not copilot.runtime.exists()


def test_a_copilot_home_forgotten_is_only_one_koloni_made(tmp_path):
    runtime = tmp_path / "runtime"
    homes = runtime / "cli-homes" / COPILOT_SESSIONS
    home = homes / ("a" * 32)
    (home / "session-state").mkdir(parents=True)
    # A provider's sign-in folder, one by another name, and one outside the runtime stay.
    kept = [
        runtime / "cli-homes" / ("b" * 32),
        homes / "not-ours",
        tmp_path / "elsewhere" / "cli-homes" / COPILOT_SESSIONS / ("c" * 32),
    ]
    for one in kept:
        one.mkdir(parents=True)
        forget_session({"id": SID, "home": str(one)}, runtime)
    forget_session({"id": SID, "home": str(homes / ".." / COPILOT_SESSIONS / ("a" * 32))}, runtime)
    assert not home.exists() and all(one.is_dir() for one in kept)


# --- in the app: the topic's later turns -----------------------------------------------------


@pytest.fixture
def chat(settings_env, tmp_path, project_dir, wait_run):
    settings = load_settings(settings_env)
    record, plan, starts = tmp_path / "record.json", tmp_path / "plan.json", tmp_path / "starts"

    def rescript(**more):
        plan.write_text(plan_of(record, starts, **more), encoding="utf-8")

    rescript(usage=[checkpoint(100, 10, 1)], usage_info=[{"tokenLimit": 272000}])
    cli = CopilotNativeClient(
        None,
        "gpt-6-luna",
        timeout=30,
        launcher=HEADLESS,
        env={"FAKE_CLI_PLAN": str(plan)},
        sessions=settings.runtime_root / "cli-homes" / COPILOT_SESSIONS,
    )
    app = create_app(settings, model=ScriptedModel([]), clients={"Copilot": cli})
    with TestClient(app, base_url="http://127.0.0.1:8790", headers=PAGE) as client:
        provider = client.post(
            "/api/providers", json={"name": "Copilot", "kind": "copilot_cli", "mode": "native"}
        ).json()
        cid, run_id = start(client, project_dir, provider)
        snap = wait_run(client, cid, run_id)
        assert snap["runs"][-1]["status"] == "completed", snap["runs"][-1]["error"]

        def turn(words, new_topic=False, **more):
            rescript(**more)
            run_id = client.post(
                f"/api/conversations/{cid}/messages",
                json={"content": words, **({"new_topic": True} if new_topic else {})},
            ).json()["run"]["id"]
            snap = wait_run(client, cid, run_id)
            assert snap["runs"][-1]["status"] == "completed", snap["runs"][-1]["error"]
            return snap

        turn.client, turn.cid, turn.db = client, cid, app.state.session_factory
        turn.record = lambda: json.loads(record.read_text(encoding="utf-8"))
        turn.runtime = settings.runtime_root
        turn.sessions = settings.runtime_root / "cli-homes" / COPILOT_SESSIONS
        yield turn


def leads(chat) -> list[Agent]:
    with chat.db() as session:
        return (
            session.query(Agent)
            .filter(Agent.parent_agent_id.is_(None))
            .order_by(Agent.created_at)
            .all()
        )


def homes_of(chat) -> list[Path]:
    return sorted(chat.sessions.iterdir()) if chat.sessions.is_dir() else []


def test_it_goes_on_within_its_topic_counts_each_turn_and_its_home_goes_with_a_new_topic(chat):
    (lead,) = leads(chat)
    home = Path(lead.cli_session["home"])
    assert home.is_dir() and homes_of(chat) == [home]  # (it survived its turn, in the runtime)
    assert str(home.resolve()).startswith(str(chat.runtime.resolve()))
    assert (lead.input_tokens, lead.context_window) == (100, 272000)
    snap = chat(
        "now the tests",
        usage=[checkpoint(250, 25, 2)],
        compaction={"success": True, "preCompactionTokens": 900, "postCompactionTokens": 90},
    )
    assert chat.record()["resume"]["sessionId"] == SID
    assert "now the tests" in chat.record()["prompt"]
    assert "what does it print?" not in chat.record()["prompt"]
    assert any(
        call["name"] == "copilot__compaction" and "900 -> 90 tokens" in call["result"]
        for call in snap["tool_calls"]
    )
    chat("and the docs", usage=[checkpoint(450, 45, 3)])
    assert [one.input_tokens for one in leads(chat)] == [100, 150, 200]
    assert [one.premium_requests for one in leads(chat)] == [1, 1, 1]
    # Taken over by each later lead: one session goes on in one run at a time.
    assert [one.cli_session is not None for one in leads(chat)] == [False, False, True]
    assert homes_of(chat) == [home]

    chat("something else", new_topic=True, usage=[checkpoint(30, 3, 1)])
    assert "resume" not in chat.record() and "something else" in chat.record()["prompt"]
    assert not home.exists()  # (the other topic's session is gone with it)
    newer = Path(leads(chat)[-1].cli_session["home"])
    assert homes_of(chat) == [newer] and leads(chat)[-1].input_tokens == 30
    assert all(one.cli_session is None for one in leads(chat)[:-1])

    client = chat.client
    assert (
        client.patch(f"/api/conversations/{chat.cid}", json={"archived": True}, headers=OWN)
    ).status_code == 200
    deleted = client.post("/api/conversations/delete", json={"ids": [chat.cid]}, headers=OWN)
    assert deleted.json()["deleted"] == [chat.cid]
    assert homes_of(chat) == []  # (gone with its conversation)


def test_a_turn_at_another_permission_level_starts_anew_and_its_old_home_goes(chat):
    (lead,) = leads(chat)
    home = Path(lead.cli_session["home"])
    chat.client.patch(
        f"/api/conversations/{chat.cid}", json={"permission_mode": "ask"}, headers=OWN
    )
    chat("now the tests", usage=[checkpoint(40, 4, 1)])
    assert "resume" not in chat.record() and "what does it print?" in chat.record()["prompt"]
    assert not home.exists()
    newer = Path(leads(chat)[-1].cli_session["home"])
    assert homes_of(chat) == [newer] and leads(chat)[-1].input_tokens == 40
