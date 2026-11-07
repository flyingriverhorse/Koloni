"""Slice 59b's acceptance set: how full a model's context is, and compaction for local models.
Written before the code (on top of 59a's `ModelInfo.context_window`).

The user: "local için gerekli sıkıştırma sadece". A model's window is found (llama-server's
`/props` `n_ctx`) or set in its role by the user. The last step's input tokens are how full it
is. When a model that does not compact itself (a local / OpenAI-compatible one; not Anthropic's
API nor a CLI, which do their own) passes 75% of its window, before its next step the older part
of what it is sent is summarised by the same model: the system text, every message of the user's
and the last exchange go as they are; the rest becomes one "earlier conversation, summarised"
message. The record is not changed. Unknown window: nothing is compacted.

Contract:
- `RoleOut` / `RolePatch.context_window`: a whole number > 0 or null (null: as found); own page.
- `AgentOut.context_window` (the window used, or null) and `AgentOut.summarised` (how many
  messages its history has had summarised so far; 0).
- A client with `compacts_itself = True` is never compacted by KOLONİ.
- `OpenAICompatClient.info()` reads llama-server's `/props` (beside `/v1`) for `context_window`.
"""

import json

import httpx2
import pytest

from app.schemas import RoleOut
from tests.keyed import TestClient

if "context_window" not in RoleOut.model_fields:
    pytest.skip("slice 59b is not built yet", allow_module_level=True)  # written before the code

from app.config import load_settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.model_client import ModelInfo, OpenAICompatClient  # noqa: E402
from tests.fakes import ScriptedModel  # noqa: E402
from tests.test_chat_flow import text  # noqa: E402
from tests.test_spawn import begin, call, role_id, step  # noqa: E402

ORIGIN = "http://127.0.0.1:8790"
SUMMARISED = "earlier conversation, summarised"


class Windowed(ScriptedModel):
    """A scripted local model with a window of `window` tokens."""

    def __init__(self, steps, window):
        super().__init__(steps)
        self.window = window

    async def info(self) -> ModelInfo:
        return ModelInfo(self.model_id, True, context_window=self.window)

    async def stream_step(self, model_id, messages, tools, on_delta, on_thinking=None, **_more):
        return await super().stream_step(model_id, messages, tools, on_delta, on_thinking)


@pytest.fixture
def windowed(settings_env):
    opened = []

    def make(steps, window=1000):
        model = Windowed(steps, window)
        client = TestClient(create_app(load_settings(settings_env), model=model), base_url=ORIGIN)
        client.__enter__()
        opened.append(client)
        client.headers["Origin"] = ORIGIN
        return client, model

    yield make
    for client in opened:
        client.__exit__(None, None, None)


# A read whose output is old by the third step; the second step fills 80% of a 1000 window.
WORK = [
    step(call("read_file", {"path": "hello.py"}, "r1"), i=100),
    step(call("list_dir", {}, "l1"), i=800),
]


def ran(client, wait_run, project_dir):
    cid, run_id = begin(client, project_dir, mode="full_auto", content="look at hello please")
    return cid, wait_run(client, cid, run_id)


def sent(messages):
    return "\n".join(str(m.get("content")) for m in messages)


def test_past_three_quarters_the_older_part_is_summarised_and_the_record_kept(
    windowed, wait_run, project_dir
):
    client, model = windowed([*WORK, text("SUMMARY: hello.py prints hi"), text("done")])
    cid, snap = ran(client, wait_run, project_dir)
    assert len(model.calls) == 4  # two steps, the summary, the step after it
    asked, after = model.calls[2], model.calls[3]
    assert "print('hi')" in sent(asked)  # the summary is made of the older part
    assert SUMMARISED in sent(after) and "SUMMARY: hello.py prints hi" in sent(after)
    assert "print('hi')" not in sent(after)  # the old read is gone from what is sent...
    assert "look at hello please" in sent(after)  # ...the user's words never are
    assert after[-1]["role"] == "tool"  # the last exchange goes as it was
    # The record is as it was: both tool calls, the user's message.
    assert [t["name"] for t in snap["tool_calls"]] == ["read_file", "list_dir"]
    assert any(m["content"] == "look at hello please" for m in snap["messages"])
    (lead,) = snap["agents"]
    assert lead["summarised"] >= 1 and lead["context_window"] == 1000


def test_with_no_known_window_nothing_is_summarised(windowed, wait_run, project_dir):
    client, model = windowed([*WORK, text("done")], window=None)
    _cid, snap = ran(client, wait_run, project_dir)
    assert len(model.calls) == 3 and SUMMARISED not in sent(model.calls[2])
    assert snap["agents"][0]["summarised"] == 0 and snap["agents"][0]["context_window"] is None


def test_a_window_set_in_the_role_is_used(windowed, wait_run, project_dir):
    client, model = windowed([*WORK, text("SUMMARY: x"), text("done")], window=None)
    lead = f"/api/roles/{role_id(client, 'Lead')}"
    assert client.patch(lead, json={"context_window": 1000}).json()["context_window"] == 1000
    _cid, snap = ran(client, wait_run, project_dir)
    assert len(model.calls) == 4 and SUMMARISED in sent(model.calls[3])
    assert snap["agents"][0]["context_window"] == 1000


def test_a_model_that_compacts_itself_is_left_alone(windowed, wait_run, project_dir):
    client, model = windowed([*WORK, text("done")])
    model.compacts_itself = True
    ran(client, wait_run, project_dir)
    assert len(model.calls) == 3 and SUMMARISED not in sent(model.calls[2])


def test_the_window_is_set_only_from_the_apps_own_page_and_must_make_sense(windowed):
    client, _model = windowed([])
    lead = f"/api/roles/{role_id(client, 'Lead')}"
    del client.headers["Origin"]
    assert client.patch(lead, json={"context_window": 1000}).status_code == 403
    client.headers["Origin"] = ORIGIN
    assert client.patch(lead, json={"context_window": 0}).status_code == 422
    assert client.patch(lead, json={"context_window": None}).json()["context_window"] is None


@pytest.mark.anyio
async def test_llama_server_says_its_window():
    def handler(request):
        if request.url.path == "/props":
            return httpx2.Response(200, json={"default_generation_settings": {"n_ctx": 80128}})
        if request.url.path == "/v1/models":
            return httpx2.Response(200, json={"data": [{"id": "qwen"}]})
        assert json.loads(request.content)["stream"] is False
        return httpx2.Response(200, json={"choices": [{"message": {"content": ""}}]})

    client = OpenAICompatClient("http://model/v1", transport=httpx2.MockTransport(handler))
    assert (await client.info()).context_window == 80128

    def no_props(request):
        if request.url.path == "/props":
            return httpx2.Response(404)
        return handler(request)

    bare = OpenAICompatClient("http://model/v1", transport=httpx2.MockTransport(no_props))
    assert (await bare.info()).context_window is None  # not llama-server: unknown, not guessed
