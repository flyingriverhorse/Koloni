"""89j: what an agent's CLI says of its context and plan while it works, shown on its node -
the latest of it, sent at most every LIVE_SECONDS, never on record."""

import time

import pytest

from app.model_native import ClaudeNativeClient, CodexNativeClient
from tests.test_attachment_agents import FAKE_CLAUDE, FAKE_CODEX, answered, plan, record
from tests.test_native_agent import native_app, start  # noqa: F401  (a fixture)
from tests.test_session_agent import session_app  # noqa: F401  (a fixture)

PLAN = [
    {"step": "Read <b>hello.py</b>", "status": "completed"},
    {"step": "x" * 300, "status": "inProgress"},
    {"step": "Test", "status": "somehow"},
]


async def lived(client, tmp_path) -> list[dict]:
    """What a native run of `client` said live."""
    items = []

    async def on_text(_text):
        pass

    async def on_item(phase, item):
        if phase == "live":
            items.append(item)

    await client.run_native(
        "m", [{"role": "user", "content": "go"}], [], str(tmp_path), answered, on_text, on_item
    )
    return items


@pytest.mark.anyio
async def test_codex_says_its_last_requests_fill_and_its_plan_and_not_its_own_agents(tmp_path):
    client = CodexNativeClient(
        launcher=FAKE_CODEX,
        **plan(
            tmp_path,
            [
                {"context": 34000, "window": 100000},
                {"context": 999, "window": 100000, "thread": "thr_2"},
                {"context": 5, "window": None},
                {"plan": PLAN},
                {"plan": [{"step": "no"}], "thread": "thr_2"},
                {"say": "done"},
            ],
        ),
    )
    assert await lived(client, tmp_path) == [
        # (its `total`, nine times that, is what it spent, not what it holds)
        {"type": "live", "context": {"used": 34000, "window": 100000}},
        {
            "type": "live",
            "plan": [
                {"step": "Read <b>hello.py</b>", "status": "completed"},  # (data: shown as text)
                {"step": "x" * 200, "status": "inProgress"},
                {"step": "Test", "status": "pending"},
            ],
        },
    ]


@pytest.mark.anyio
async def test_claude_code_is_asked_its_fill_once_a_step_cheaply_and_a_no_shows_nothing(tmp_path):
    told = {"totalTokens": 34000, "maxTokens": 200000, "rawMaxTokens": 200000, "percentage": 17}
    script = [{"say": "one"}, {"sleep": 0.5}, {"say": "two"}, {"sleep": 0.5}]
    client = ClaudeNativeClient(launcher=FAKE_CLAUDE, **plan(tmp_path, script, context=told))
    items = await lived(client, tmp_path)
    # (at most once a step: a step while the last ask is open is skipped)
    assert items[:1] == [{"type": "live", "context": {"used": 34000, "window": 200000}}]
    asked = record(tmp_path)["context_asked"]
    # "summary": from its last response's usage, with no token-count call of its own
    assert 1 <= len(items) <= len(asked) <= 2
    assert all(one == {"subtype": "get_context_usage", "detail": "summary"} for one in asked)
    client = ClaudeNativeClient(launcher=FAKE_CLAUDE, **plan(tmp_path, script))
    assert await lived(client, tmp_path) == []  # (it answers that it cannot)


def test_the_latest_goes_out_once_is_sent_again_to_a_page_opened_late_and_goes_at_the_end(
    native_app,
    wait_run,
    project_dir,  # noqa: F811
):
    client, provider, _ = native_app(
        [
            {"context": 20000, "window": 100000},
            {"plan": PLAN[:1]},
            {"context": 34000, "window": 100000},
            {"pause": 2.5},
            {"say": "done"},
        ]
    )
    sent, emit = [], client.app.state.bus.emit_transient

    def watch(conversation_id, kind, payload):
        if kind == "agent.live":
            sent.append(payload)
        return emit(conversation_id, kind, payload)

    client.app.state.bus.emit_transient = watch
    cid, run_id = start(client, project_dir, provider)
    for _ in range(100):
        if sent:
            break
        time.sleep(0.05)
    late = client.get(f"/api/conversations/{cid}/events", params={"once": True}).text
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    (agent,) = snap["agents"]
    shown = {
        "agent_id": agent["id"],
        "context": {"used": 34000, "window": 100000},
        "plan": [{"step": "Read <b>hello.py</b>", "status": "completed"}],
    }
    assert sent == [shown, {"agent_id": agent["id"], "context": None, "plan": None}]
    assert "event: agent.live" in late and '"used": 34000' in late
    assert (
        "agent.live"
        not in client.get(f"/api/conversations/{cid}/events", params={"once": True}).text
    )  # (on no record)
