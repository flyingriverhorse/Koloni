"""Slice 34's acceptance set: what a step sent before is read again from the provider's cache,
and what was read is counted and priced apart. Written before the code.

An agent's step on the Anthropic API marks what the next step can read again; a question
KOLONİ asks a model itself marks nothing. Whoever says how much it read again or wrote to its
cache is believed, and nobody is guessed for. In Usage the read and the written are told apart
from what was sent, and money is shown for them only from prices the user wrote: without one
the amount is the least, and says why.
"""

import dataclasses
import json

import httpx2
import pytest

from app.model_client import StepResult

if "cache_read" not in {field.name for field in dataclasses.fields(StepResult)}:
    pytest.skip("slice 34 is not built yet", allow_module_level=True)  # written before the code

from app.model_anthropic import AnthropicClient  # noqa: E402
from app.model_client import OpenAICompatClient  # noqa: E402
from app.tools import TOOL_SCHEMAS  # noqa: E402
from tests.test_chat_flow import text  # noqa: E402
from tests.test_model_anthropic import HISTORY, events  # noqa: E402
from tests.test_spawn import begin, call, step  # noqa: E402
from tests.test_team import team  # noqa: E402, F401  (a fixture)
from tests.test_tier_scenarios import tiered  # noqa: E402
from tests.test_usage_scenarios import began, turn, usage  # noqa: E402

MARK = {"type": "ephemeral"}
PRICE = {"model_id": "fake-model", "input": 4, "output": 20, "currency": "USD"}


async def sent(messages, tools=None, told=None, **more):
    """What one step sends to the Anthropic API, and the result of what it is told back."""
    bodies = []

    def handler(request):
        if request.method == "GET":  # the Models API: the most a step may write, not said
            return httpx2.Response(404)
        bodies.append(json.loads(request.content))
        return httpx2.Response(200, content=events(
            {"type": "message_start",
             "message": {"usage": told or {"input_tokens": 5, "output_tokens": 1}}},
            {"type": "content_block_start", "index": 0, "content_block": {"type": "text"}},
            {"type": "content_block_delta", "index": 0,
             "delta": {"type": "text_delta", "text": "ok"}},
            {"type": "message_delta", "delta": {"stop_reason": "end_turn"},
             "usage": {"output_tokens": 3}},
            {"type": "message_stop"},
        ))

    async def on_delta(_text):
        pass

    client = AnthropicClient(
        "https://api.test", "sk-ant-test", "claude-haiku-5-5",
        transport=httpx2.MockTransport(handler))
    result = await client.stream_step("claude-haiku-5-5", messages, tools, on_delta, **more)
    return bodies[0], result


def blocks(content):
    return [{"type": "text", "text": content}] if isinstance(content, str) else content


def marked(body):
    """Every block of a request that carries a cache mark."""
    every = [*(body.get("tools") or []), *blocks(body.get("system") or [])]
    for message in body["messages"]:
        every += blocks(message["content"])
    return [block for block in every if "cache_control" in block]


def unmarked(body):
    """A request without its marks, a text told one way whichever way it was sent."""
    def plain(content):
        return [{k: v for k, v in block.items() if k != "cache_control"}
                for block in blocks(content)]

    return {**body, "system": plain(body.get("system") or []),
            "messages": [{**m, "content": plain(m["content"])} for m in body["messages"]]}


# --- the request -------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_an_agents_step_marks_what_the_next_step_can_read_again():
    body, _result = await sent(HISTORY, TOOL_SCHEMAS, cache=True)
    # the system text - with the tools before it, the same at every step ...
    assert blocks(body["system"])[-1] == {
        "type": "text", "text": "You are KOLONİ's agent.", "cache_control": MARK}
    # ... and the end of what is sent now, which the next step sends again
    assert blocks(body["messages"][-1]["content"])[-1] == {
        "type": "text", "text": "go on", "cache_control": MARK}
    assert len(marked(body)) == 2                      # (the API takes four at most)
    # nothing else of the request is other than it was
    as_it_was, _ = await sent(HISTORY, TOOL_SCHEMAS)
    assert unmarked(body) == unmarked(as_it_was)

    # where the last thing sent is what tools returned, the last of them carries the mark
    earlier, _ = await sent(HISTORY[:5], TOOL_SCHEMAS, cache=True)
    results = earlier["messages"][-1]["content"]
    assert results[-1] == {"type": "tool_result", "tool_use_id": "c2", "content": "a.py",
                           "cache_control": MARK}
    assert "cache_control" not in results[0] and len(marked(earlier)) == 2
    # and what was marked then is sent the very same at the step after it
    again = unmarked(body)
    assert again["messages"][:len(earlier["messages"])] == unmarked(earlier)["messages"]
    assert (again["system"], again["tools"]) == (unmarked(earlier)["system"], earlier["tools"])


@pytest.mark.anyio
async def test_a_question_asked_once_marks_nothing():
    body, _result = await sent(HISTORY)
    assert marked(body) == [] and "cache_control" not in json.dumps(body)


# --- what the provider says it read again and wrote --------------------------------------------


@pytest.mark.anyio
@pytest.mark.parametrize("told, counted", [
    ({"input_tokens": 20, "cache_read_input_tokens": 80, "cache_creation_input_tokens": 30,
      "output_tokens": 1}, (130, 80, 30)),             # sent is all three, as it was
    ({"input_tokens": 20, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
      "output_tokens": 1}, (20, 0, 0)),                # none, said: a zero
    ({"input_tokens": 20, "output_tokens": 1}, (20, None, None)),    # not said: not known
])
async def test_what_the_api_read_again_and_wrote_is_told_apart_from_what_was_sent(told, counted):
    _body, result = await sent(HISTORY, told=told, cache=True)
    assert (result.input_tokens, result.cache_read, result.cache_write) == counted


@pytest.mark.anyio
@pytest.mark.parametrize("told, read", [
    ({"prompt_tokens": 100, "completion_tokens": 2,
      "prompt_tokens_details": {"cached_tokens": 64}}, 64),
    ({"prompt_tokens": 100, "completion_tokens": 2,
      "prompt_tokens_details": {"cached_tokens": 0}}, 0),
    ({"prompt_tokens": 100, "completion_tokens": 2}, None),          # a server that says nothing
    ({"prompt_tokens": 100, "completion_tokens": 2,
      "prompt_tokens_details": {"cached_tokens": "many"}}, None),    # or nothing that counts
    ({"prompt_tokens": 100, "completion_tokens": 2, "prompt_tokens_details": None}, None),
])
async def test_an_openai_compatible_server_is_believed_for_what_it_says_it_read_again(told, read):
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        chunks = ({"choices": [{"delta": {"content": "ok"}}]}, {"choices": [], "usage": told})
        said = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"
        return httpx2.Response(200, content=said.encode())

    async def on_delta(_text):
        pass

    client = OpenAICompatClient("http://model/v1", transport=httpx2.MockTransport(handler))
    result = await client.stream_step(
        "m", [{"role": "system", "content": "s"}, {"role": "user", "content": "hi"}], None,
        on_delta)
    assert (result.input_tokens, result.cache_read, result.cache_write) == (100, read, None)
    # its server keeps a cache by itself: nothing is asked of it
    assert "cache_control" not in json.dumps(bodies[0])


# --- who is asked for the mark -----------------------------------------------------------------


def recording(model):
    """Have a scripted model say it takes `cache`, and keep what each step was called with."""
    seen, plain = [], model.stream_step

    async def stream_step(model_id, messages, tools, on_delta, on_thinking=None, **more):
        seen.append(more)
        return await plain(model_id, messages, tools, on_delta, on_thinking)

    model.stream_step, model.caches = stream_step, True
    return seen


def test_every_step_of_an_agent_asks_for_the_mark_and_a_question_of_kolonis_own_does_not(
    team, wait_run, project_dir  # noqa: F811
):
    client, default, fast = team(
        [step(call("list_dir", {}, "a")), text("the lead answers")],
        [text("hard: it needs a look around")])
    lead_steps, own = recording(default), recording(fast)
    tiered(team, client)
    cid, run_id = begin(client, project_dir, mode="full_auto", lead_auto=True)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert lead_steps == [{"cache": True}, {"cache": True}]
    assert own == [{}]         # how hard the message is: asked once, read again by nobody


def test_a_client_that_does_not_say_it_takes_the_mark_is_called_as_it_always_was(
    make_client, wait_run, project_dir
):
    client, model, pid, cid = began(make_client, project_dir, [text("a", 5, 3)])
    assert turn(client, wait_run, cid)["status"] == "completed"       # no `cache` it cannot take
    (lead,) = client.get(f"/api/conversations/{cid}").json()["agents"]
    # and what nobody said of a cache is not known - not a zero
    for row in (usage(client, project_id=pid)["by_model"][0], lead):
        assert row["cache_read_tokens"] is None and row["cache_write_tokens"] is None


def test_what_a_step_sends_is_how_the_next_step_begins(make_client, wait_run, project_dir):
    """What the cache rests on: a step's messages and tools are sent again unchanged, in a
    turn and from one turn to the next."""
    client, model, pid, cid = began(make_client, project_dir, [
        step(call("read_file", {"path": "hello.py"}, "a")),
        step(call("read_file", {"path": "hello.py"}, "b")),
        text("done"),
        step(call("read_file", {"path": "hello.py"}, "c")),
        text("done again"),
    ])
    assert turn(client, wait_run, cid)["status"] == "completed"
    assert turn(client, wait_run, cid, "and once more")["status"] == "completed"
    assert len(model.calls) == 5
    for before, after, tools_before, tools_after in zip(
        model.calls, model.calls[1:], model.tool_args, model.tool_args[1:], strict=False
    ):
        assert after[:len(before)] == before and len(after) > len(before)
        assert json.dumps(tools_after) == json.dumps(tools_before)


# --- Usage and money ---------------------------------------------------------------------------


def cached(result, read=None, write=None):
    return dataclasses.replace(result, cache_read=read, cache_write=write)


def spent(make_client, wait_run, project_dir):
    """A lead whose two steps sent 1 100 000 tokens: 400 000 of them read again from the
    cache, 500 000 written to it, 200 000 neither; and wrote 50 000."""
    client, _model, pid, cid = began(make_client, project_dir, [
        cached(step(call("list_dir", {}, "a"), i=500_000, o=0), read=0, write=400_000),
        cached(text("done", 600_000, 50_000), read=400_000, write=100_000),
    ])
    assert turn(client, wait_run, cid)["status"] == "completed"
    return client, pid, cid


def test_usage_tells_what_was_read_again_and_written_apart_from_what_was_sent(
    make_client, wait_run, project_dir
):
    client, pid, cid = spent(make_client, wait_run, project_dir)
    told = usage(client, project_id=pid)
    for row in (told["by_model"][0], told["by_conversation"][0], told["by_start"][0]):
        assert (row["input_tokens"], row["output_tokens"]) == (1_100_000, 50_000)   # as it was
        assert (row["cache_read_tokens"], row["cache_write_tokens"]) == (400_000, 500_000)
    # and the agent's own window has its sums
    (lead,) = client.get(f"/api/conversations/{cid}").json()["agents"]
    assert (lead["cache_read_tokens"], lead["cache_write_tokens"]) == (400_000, 500_000)


def test_money_for_the_cache_is_from_the_users_own_prices_and_without_them_only_the_least(
    make_client, wait_run, project_dir
):
    client, pid, _cid = spent(make_client, wait_run, project_dir)
    cost = lambda: usage(client, project_id=pid)["by_model"][0]["cost"]  # noqa: E731

    # No price for the cache: its tokens are not counted at all - not at the full price,
    # which they did not cost - and the amount says it is the least, and why.
    assert client.put("/api/prices", json=PRICE).status_code == 200
    assert cost() == {"amount": 1.8, "currency": "USD",           # 0.2 M at 4, 0.05 M at 20
                      "at_least": True, "cache_unpriced": True}

    # One of the two: what was written still has no price.
    assert client.put("/api/prices", json={**PRICE, "cache_read": 0.2}).status_code == 200
    assert cost() == {"amount": 1.88, "currency": "USD",          # and 0.4 M at 0.2
                      "at_least": True, "cache_unpriced": True}

    # Both: the amount is whole, and says nothing more.
    whole = {**PRICE, "cache_read": 0.2, "cache_write": 5}
    assert client.put("/api/prices", json=whole).status_code == 200
    assert cost() == {"amount": 4.38, "currency": "USD"}          # and 0.5 M at 5


def test_a_row_nobody_said_a_cache_of_costs_what_it_always_did(make_client, wait_run,
                                                               project_dir):
    client, _model, pid, cid = began(make_client, project_dir, [text("a", 1_000_000, 500_000)])
    turn(client, wait_run, cid)
    assert client.put("/api/prices", json=PRICE).status_code == 200
    assert usage(client, project_id=pid)["by_model"][0]["cost"] == {
        "amount": 14.0, "currency": "USD"}                        # 1 M at 4, half a million at 20


def test_a_cache_price_is_the_users_to_write_or_leave_out(make_client, project_dir):
    client, *_ = began(make_client, project_dir, [])
    price = {**PRICE, "model_id": "m"}
    assert client.put("/api/prices", json=price).json() == [price]       # nothing is added to it
    whole = {**price, "cache_read": 0.2, "cache_write": 5}
    assert client.put("/api/prices", json=whole).json() == [whole]
    for wrong in ({"cache_read": -1}, {"cache_write": True}, {"cache_read": "0.2"},
                  {"cache_write": 1e9}):
        assert client.put("/api/prices", json={**whole, **wrong}).status_code == 422, wrong
    assert client.get("/api/prices").json() == [whole]
    # a price is written whole: one written again without them has none
    assert client.put("/api/prices", json=price).json() == [price]
    assert client.get("/api/prices").json() == [price]
