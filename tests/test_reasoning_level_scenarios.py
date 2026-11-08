"""Slice 59a's acceptance set: how hard a model thinks. Written before the code.

The user: "we never choose the models' reasoning". A role keeps a level (the default for its agents)
and the most its agents may be given; the Lead asks a level for a sub-agent's task, never above the
role's most; a conversation's level is the Lead's. A level is sent only to a model that takes it;
"Default" (null) sends nothing, as today. Only from the app's own page.

Contract:
- `RoleOut` / `RolePatch`: `effort`, `max_effort` in LEVELS or null; `effort` above `max_effort` → 422.
- `ConversationOut` / `ConversationPatch`: `lead_effort` (LEVELS or null).
- `spawn_agent` takes an optional `effort`.
- `ModelInfo.efforts` (the levels the model takes, or None: unknown / none) and
  `ModelInfo.context_window` (or None); both default to None.
- A client's `stream_step(..., effort=level)` is given a level only when it is one of
  `info().efforts`.
- Anthropic: the level is `output_config.effort`; no `thinking` field; `max_tokens` above the old
  8192; `info()` reads `capabilities.effort` and `max_input_tokens` from the Models API.
"""

import json

import httpx2
import pytest

from app.schemas import RoleOut
from tests.keyed import TestClient

if "effort" not in RoleOut.model_fields:
    pytest.skip("slice 59a is not built yet", allow_module_level=True)  # written before the code

from app.config import load_settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.model_client import ModelInfo  # noqa: E402
from tests.fakes import ScriptedModel  # noqa: E402
from tests.test_chat_flow import text  # noqa: E402
from tests.test_model_anthropic import client_for, events  # noqa: E402
from tests.test_spawn import begin, call, role_id, spawn, step  # noqa: E402

ORIGIN = "http://127.0.0.1:8790"
LEVELS = ("low", "medium", "high", "xhigh", "max")


class Leveled(ScriptedModel):
    """A scripted model that takes levels and keeps, per agent, the level each step was given."""

    def __init__(self, steps, efforts=LEVELS):
        super().__init__(steps)
        self.efforts = efforts
        self.levels: dict[str, list[str | None]] = {}

    async def info(self) -> ModelInfo:
        return ModelInfo(self.model_id, True, efforts=self.efforts, context_window=100_000)

    async def stream_step(self, model_id, messages, tools, on_delta, on_thinking=None,
                          effort=None, **_more):
        named = str(messages[0]["content"]).split("Your name here is ", 1)
        name = named[1].split(".", 1)[0] if len(named) > 1 else "Lead"
        self.levels.setdefault(name, []).append(effort)
        return await super().stream_step(model_id, messages, tools, on_delta, on_thinking)


@pytest.fixture
def leveled(settings_env):
    opened = []

    def make(steps, efforts=LEVELS):
        model = Leveled(steps, efforts)
        client = TestClient(create_app(load_settings(settings_env), model=model),
                            base_url=ORIGIN)
        client.__enter__()
        opened.append(client)
        client.headers["Origin"] = ORIGIN
        return client, model

    yield make
    for client in opened:
        client.__exit__(None, None, None)


def set_role(client, name, **levels):
    answer = client.patch(f"/api/roles/{role_id(client, name)}", json=levels)
    assert answer.status_code == 200, answer.text
    return answer.json()


def ran(client, wait_run, project_dir, **conversation):
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never",
                        **conversation)
    wait_run(client, cid, run_id)
    return cid


def test_a_roles_level_goes_with_its_agents_steps_and_default_sends_none(
    leveled, wait_run, project_dir
):
    client, model = leveled({"Lead": [spawn("Coder"), text("done")], "Coder": [text("did it")]})
    assert set_role(client, "Coder", effort="high")["effort"] == "high"
    ran(client, wait_run, project_dir)
    assert model.levels["Coder"] == ["high"]
    assert set(model.levels["Lead"]) == {None}  # the Lead's role has no level: nothing is sent


@pytest.mark.parametrize(("asked", "given"), [("max", "high"), ("low", "low")])
def test_the_lead_asks_a_level_for_a_task_never_above_the_roles_most(
    leveled, wait_run, project_dir, asked, given
):
    client, model = leveled({
        "Lead": [step(call("spawn_agent", {"role": "Coder", "task": "a hard bug", "effort": asked})),
                 text("done")],
        "Coder": [text("fixed")],
    })
    set_role(client, "Coder", effort="medium", max_effort="high")
    ran(client, wait_run, project_dir)
    assert model.levels["Coder"] == [given]


def test_a_conversations_level_is_the_leads_alone(leveled, wait_run, project_dir):
    client, model = leveled({"Lead": [spawn("Coder"), text("done")], "Coder": [text("ok")]})
    set_role(client, "Coder", effort="low")
    cid = ran(client, wait_run, project_dir, lead_effort="xhigh")
    assert client.get(f"/api/conversations/{cid}").json()["conversation"]["lead_effort"] == "xhigh"
    assert set(model.levels["Lead"]) == {"xhigh"}
    assert model.levels["Coder"] == ["low"]


# K-rol-model: where it does not take it, the nearest lower one it takes goes instead.
@pytest.mark.parametrize(("efforts", "sent"), [(None, None), (("low", "medium", "high"), "high")])
def test_a_level_the_model_does_not_take_is_never_sent(
    leveled, wait_run, project_dir, efforts, sent
):
    client, model = leveled({"Lead": [text("hi")]}, efforts=efforts)
    set_role(client, "Lead", effort="max")
    ran(client, wait_run, project_dir)
    assert model.levels["Lead"] == [sent]


def test_levels_are_set_only_from_the_apps_own_page_and_must_make_sense(leveled, project_dir):
    client, _model = leveled({"Lead": []})
    coder = f"/api/roles/{role_id(client, 'Coder')}"
    del client.headers["Origin"]
    assert client.patch(coder, json={"effort": "high"}).status_code == 403
    client.headers["Origin"] = ORIGIN
    assert client.patch(coder, json={"effort": "turbo"}).status_code == 422
    assert client.patch(coder, json={"effort": "max", "max_effort": "medium"}).status_code == 422
    kept = client.patch(coder, json={"effort": "medium", "max_effort": "xhigh"}).json()
    assert (kept["effort"], kept["max_effort"]) == ("medium", "xhigh")
    assert client.patch(coder, json={"effort": None}).json()["effort"] is None
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    assert client.patch(f"/api/conversations/{cid}", json={"lead_effort": "turbo"}).status_code == 422


# --- Anthropic ------------------------------------------------------------------------

ENDED = events(
    {"type": "message_start", "message": {"usage": {"input_tokens": 3, "output_tokens": 1}}},
    {"type": "content_block_start", "index": 0, "content_block": {"type": "text"}},
    {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "ok"}},
    {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 2}},
    {"type": "message_stop"},
)
MODEL = {
    "id": "claude-sonnet-5-5", "max_input_tokens": 1_000_000, "max_tokens": 128_000,
    "capabilities": {"effort": {"supported": True, **{
        level: {"supported": level != "xhigh"} for level in LEVELS}}},
}


@pytest.mark.anyio
async def test_anthropic_is_sent_the_level_and_room_to_think():
    sent = []

    def handler(request):
        if request.method == "GET":
            return httpx2.Response(200, content=json.dumps(MODEL))
        sent.append(json.loads(request.content))
        return httpx2.Response(200, content=ENDED)

    async def on_delta(_text):
        pass

    client = client_for(handler)
    said = [{"role": "user", "content": "fix it"}]
    await client.stream_step("claude-sonnet-5-5", said, None, on_delta, effort="high")
    await client.stream_step("claude-sonnet-5-5", said, None, on_delta)
    assert sent[0]["output_config"] == {"effort": "high"} and "thinking" not in sent[0]
    assert "output_config" not in sent[1]  # Default: the model's own
    assert sent[0]["max_tokens"] > 8192  # thinking takes from the same limit


@pytest.mark.anyio
async def test_anthropic_says_which_levels_a_model_takes_and_its_window():
    info = await client_for(lambda _r: httpx2.Response(200, content=json.dumps(MODEL))).info()
    assert tuple(info.efforts) == ("low", "medium", "high", "max")
    assert info.context_window == 1_000_000
    bare = await client_for(
        lambda _r: httpx2.Response(200, content=json.dumps({"id": "claude-sonnet-5-5"}))).info()
    assert (bare.efforts, bare.context_window) == (None, None)  # not said: unknown, never guessed
