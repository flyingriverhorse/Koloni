"""K-dusunme-blok: Anthropic's models are asked to think as each takes it, and what they
thought goes back with their answer as it came - never edited - over a stand-in transport."""

import json

import httpx2
import pytest

from app.model_anthropic import AnthropicClient
from app.tools import TOOL_SCHEMAS
from tests.test_chat_flow import on_a_real_client, start
from tests.test_model_anthropic import HISTORY, KEY, events

pytestmark = pytest.mark.anyio

THOUGHT = {"type": "thinking", "thinking": "I should look.", "signature": "sig-AB"}
HIDDEN = {"type": "redacted_thinking", "data": "opaque=="}
CALL = {"type": "tool_use", "id": "toolu_1", "name": "list_dir", "input": {}}


def streamed(*blocks, stop="tool_use"):
    """A stream that gives these blocks the way the API does: thinking by deltas with its
    signature last, redacted thinking whole, text and a call's arguments by deltas."""
    told = [{"type": "message_start", "message": {"usage": {"input_tokens": 5}}}]
    for at, block in enumerate(blocks):
        kind = block["type"]
        if kind == "thinking":
            told += [{"type": "content_block_start", "index": at,
                      "content_block": {"type": "thinking", "thinking": "", "signature": ""}},
                     *({"type": "content_block_delta", "index": at,
                        "delta": {"type": "thinking_delta", "thinking": part}}
                       for part in (block["thinking"][:4], block["thinking"][4:])),
                     {"type": "content_block_delta", "index": at,
                      "delta": {"type": "signature_delta", "signature": block["signature"]}}]
        elif kind == "text":
            told += [{"type": "content_block_start", "index": at,
                      "content_block": {"type": "text", "text": ""}},
                     {"type": "content_block_delta", "index": at,
                      "delta": {"type": "text_delta", "text": block["text"]}}]
        elif kind == "tool_use":
            told += [{"type": "content_block_start", "index": at, "content_block": {
                         **block, "input": {}}},
                     {"type": "content_block_delta", "index": at, "delta": {
                         "type": "input_json_delta", "partial_json": json.dumps(block["input"])}}]
        else:
            told.append({"type": "content_block_start", "index": at, "content_block": block})
        told.append({"type": "content_block_stop", "index": at})
    return events(*told, {"type": "message_delta", "delta": {"stop_reason": stop},
                          "usage": {"output_tokens": 3}}, {"type": "message_stop"})


def api(*answers, bodies, most=64_000):
    """The API: the Models API says the most a step may write; each request is kept."""
    def handler(request):
        if request.method == "GET":
            return httpx2.Response(200, json={"id": "m", "max_tokens": most})
        bodies.append(json.loads(request.content))
        return httpx2.Response(200, content=answers[len(bodies) - 1])

    return handler


async def step(model, history, *answers, tools=TOOL_SCHEMAS, hears=True, most=64_000, **more):
    bodies = []
    client = AnthropicClient("https://api.test", KEY, model,
                             transport=httpx2.MockTransport(api(*answers, bodies=bodies, most=most)))
    thought = []

    async def on_delta(_text):
        pass

    async def on_thinking(text):
        thought.append(text)

    result = await client.stream_step(
        model, history, tools, on_delta, on_thinking if hears else None, **more)
    return bodies[0], result, thought


def plain(body):
    """What a request sent, without its cache marks (they move from step to step; a text
    marked is sent as its block)."""
    def unmarked(content):
        return [{"type": "text", "text": content}] if isinstance(content, str) else [
            {k: v for k, v in block.items() if k != "cache_control"} for block in content]

    return [{**m, "content": unmarked(m["content"])} for m in body["messages"]]


@pytest.mark.parametrize("model, expected", [
    ("claude-opus-5-5", {"type": "adaptive", "display": "summarized"}),
    ("claude-opus-4-8", {"type": "adaptive", "display": "summarized"}),
    ("claude-sonnet-5", {"type": "adaptive", "display": "summarized"}),
    ("claude-opus-4-6", {"type": "adaptive"}),  # (its summary is shown unasked)
    ("claude-sonnet-5-5", {"type": "adaptive", "display": "summarized"}),
    ("claude-fable-5-1", {"type": "adaptive", "display": "summarized"}),
    ("claude-haiku-4-5", {"type": "enabled", "budget_tokens": 32_000}),
    ("claude-test", None),  # (one not known: asked nothing, as before)
])
async def test_each_model_is_asked_to_think_the_way_it_takes(model, expected):
    body, _, _ = await step(model, HISTORY, streamed({"type": "text", "text": "ok"}))
    assert body.get("thinking") == expected
    if expected and expected["type"] == "enabled":
        assert 1024 <= body["thinking"]["budget_tokens"] < body["max_tokens"]
    # Sampling goes to no model: a temperature is refused by the newest.
    assert not {"temperature", "top_p", "top_k"} & set(body)


async def test_no_thinking_where_nobody_hears_it_or_a_budget_would_not_fit():
    # KOLONİ's own one-off asking (a summary, a guess) has no `on_thinking`: asked nothing.
    body, _, _ = await step("claude-opus-4-8", HISTORY, streamed({"type": "text", "text": "ok"}),
                            hears=False)
    assert "thinking" not in body
    body, _, _ = await step("claude-haiku-4-5", HISTORY, streamed({"type": "text", "text": "o"}),
                            most=2000)
    assert "thinking" not in body  # (half of 2000 is under the least budget)


@pytest.mark.parametrize("model, expected", [
    ("claude-opus-5-5", {"type": "adaptive", "display": "summarized"}),  # (it thinks anyway)
    ("claude-fable-5", {"type": "adaptive", "display": "summarized"}),
    ("claude-opus-4-8", None), ("claude-sonnet-4-6", None), ("claude-haiku-4-5", None),
])
async def test_a_room_members_step_asks_for_thinking_only_of_a_model_that_thinks_anyway(
        model, expected):
    body, _, _ = await step(model, HISTORY, streamed({"type": "text", "text": "ok"}), think=False)
    assert body.get("thinking") == expected


async def test_thinking_and_its_signature_are_put_together_from_the_stream():
    _, result, thought = await step(
        "claude-opus-5-5", HISTORY, streamed(THOUGHT, {"type": "text", "text": "Look."}, CALL))
    assert thought == ["I sh", "ould look."]
    assert result.blocks["content"] == [THOUGHT, {"type": "text", "text": "Look."}, CALL]
    assert [c.id for c in result.tool_calls] == ["toolu_1"]


async def test_an_answer_with_no_thinking_keeps_nothing_and_unsigned_thinking_is_never_kept():
    _, result, _ = await step("claude-opus-5-5", HISTORY, streamed({"type": "text", "text": "ok"}))
    assert result.blocks is None
    # Cut before its signature, a thinking block cannot be sent back.
    # (Nor a text block that began and said nothing: no empty text is sent.)
    _, result, _ = await step("claude-opus-5-5", HISTORY, streamed(
        HIDDEN, {"type": "text", "text": ""}, {**THOUGHT, "signature": ""}, stop="max_tokens"))
    assert result.blocks["content"] == [HIDDEN]


def after_a_call(blocks, *more):
    """The history of the next step: the answer as the agent's history carries it, its
    call's result, and what else is sent with it."""
    return [*HISTORY, {"role": "assistant", "content": "", "blocks": blocks, "tool_calls": [
        {"id": "toolu_1", "type": "function", "function": {"name": "list_dir", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "toolu_1", "content": "a.py"}, *more]


@pytest.mark.parametrize("model", ["claude-opus-5-5", "claude-haiku-4-5"])
async def test_the_next_step_sends_the_answer_back_as_it_came(model):
    body, result, _ = await step(model, HISTORY, streamed(THOUGHT, HIDDEN, CALL))
    body2, _, _ = await step(model, after_a_call(result.blocks),
                             streamed({"type": "text", "text": "done"}, stop="end_turn"))
    # What was sent before is sent again as it was, then the answer whole, thinking first.
    assert plain(body2)[:len(body["messages"])] == plain(body)
    assert plain(body2)[len(body["messages"])] == {
        "role": "assistant", "content": [THOUGHT, HIDDEN, CALL]}
    assert body2["messages"][-1]["content"][0]["type"] == "tool_result"


async def test_thinking_written_after_what_is_no_longer_sent_is_left_out_never_edited():
    # Sent with that step only (a note of how things stand): the next does not send it.
    note = {"role": "user", "content": "(how the room stands now)"}
    _, result, _ = await step("claude-opus-5-5", [*HISTORY, note], streamed(THOUGHT, CALL))
    body2, _, _ = await step("claude-opus-5-5", after_a_call(result.blocks),
                             streamed({"type": "text", "text": "done"}, stop="end_turn"))
    assert [m["content"] for m in body2["messages"] if m["role"] == "assistant"][-1] == [CALL]
    assert result.blocks["content"] == [THOUGHT, CALL]  # (what is kept is never touched)
    # A model that checks nothing, and wants it in its tool loop, is sent it all the same.
    _, result, _ = await step("claude-haiku-4-5", [*HISTORY, note], streamed(THOUGHT, CALL))
    body2, _, _ = await step("claude-haiku-4-5", after_a_call(result.blocks),
                             streamed({"type": "text", "text": "done"}, stop="end_turn"))
    assert [m["content"] for m in body2["messages"] if m["role"] == "assistant"][-1] == [
        THOUGHT, CALL]


def test_summaries_and_trimming_count_the_thinking_and_never_edit_inside_an_answer():
    import copy

    from app.agent import _size, _summarised, _Summary, _trim_to_budget

    def answer(n):
        return {"role": "assistant", "content": f"step {n}", "tool_calls": [
            {"id": f"c{n}", "type": "function",
             "function": {"name": "list_dir", "arguments": "{}"}}],
                "blocks": {"after": f"d{n}", "content": [
                    {**THOUGHT, "thinking": "t" * 2000}, CALL]}}

    history = [{"role": "system", "content": "s"}, {"role": "user", "content": "go"}]
    for n in range(3):
        history += [answer(n), {"role": "tool", "tool_call_id": f"c{n}", "content": "x" * 500}]
    answers = copy.deepcopy([m for m in history if m["role"] == "assistant"])
    # What is sent back is counted: its words and calls alone would fit this budget.
    assert _size(answers[0]) > 2000
    budget = sum(map(_size, history)) - 1000
    trimmed = copy.deepcopy(history)
    assert _trim_to_budget(trimmed, budget) == 2
    # Summarised up to the second answer, or (none made) its older outputs left out, then
    # trimmed: an answer is there whole, or not at all.
    for summary in (_Summary(1, "so far"), _Summary(failed=True)):
        sent = _summarised(copy.deepcopy(history), summary)
        _trim_to_budget(sent, 100)
        kept = [m for m in sent if m["role"] == "assistant"]
        assert kept and kept == answers[-len(kept):], summary


@pytest.mark.parametrize("filed", [
    # A lead opened beside the model's own call, under its answer (`_leads_beside`)...
    {"id": "koloni_beside", "type": "function",
     "function": {"name": "spawn_agent", "arguments": '{"role": "Tester"}'}},
    # ...and a team's lead asked for by another team, under the Lead's last answer.
    {"id": "koloni_team", "type": "function",
     "function": {"name": "spawn_agent", "arguments": '{"role": "Lead", "asked_by": "x"}'}},
])
async def test_an_answer_koloni_filed_a_call_of_its_own_under_is_rebuilt_whole(filed):
    _, result, _ = await step("claude-opus-5-5", HISTORY, streamed(THOUGHT, CALL))
    history = after_a_call(result.blocks)
    history[-2]["tool_calls"].append(filed)
    history.append({"role": "tool", "tool_call_id": filed["id"], "content": "opened"})
    body, _, _ = await step("claude-opus-5-5", history,
                            streamed({"type": "text", "text": "done"}, stop="end_turn"))
    answered = body["messages"][-1]["content"]
    asked = [b["id"] for b in body["messages"][-2]["content"] if b["type"] == "tool_use"]
    # Every result answers a call sent with it; its thinking is not sent with a changed answer.
    assert [b["tool_use_id"] for b in answered] == asked == ["toolu_1", filed["id"]]
    assert all(b["type"] not in ("thinking", "redacted_thinking")
               for b in body["messages"][-2]["content"])


def test_an_agents_tool_loop_sends_its_thinking_back_and_keeps_it_on_record(
    settings_env, wait_run, project_dir
):
    bodies = []
    client = on_a_real_client(settings_env, AnthropicClient(
        "https://api.test", "sk-ant-test", "claude-opus-5-5", transport=httpx2.MockTransport(api(
            streamed(THOUGHT, {"type": "text", "text": "Looking."}, CALL),
            streamed({"type": "text", "text": "Done."}, stop="end_turn"), bodies=bodies))))
    cid, run_id = start(client, project_dir)
    snap = wait_run(client, cid, run_id)
    client.__exit__(None, None, None)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert bodies[0]["thinking"] == {"type": "adaptive", "display": "summarized"}
    first, second = plain(bodies[0]), plain(bodies[1])
    # Its first request again, then its answer as it came - its thinking first, signed.
    assert second[:len(first)] == first
    assert second[len(first)] == {"role": "assistant", "content": [
        THOUGHT, {"type": "text", "text": "Looking."}, CALL]}
    assert second[len(first) + 1]["content"][0]["tool_use_id"] == "toolu_1"
    # Never shown: the page is given the words only.
    assert "blocks" not in snap["messages"][-1] and "sig-AB" not in json.dumps(snap)


def test_an_answer_whose_call_carries_a_secret_is_never_kept_with_it(
    settings_env, wait_run, project_dir
):
    from app.db.models import Message, ToolCall
    from tests.test_chat_flow import start_in_mode

    asked = {"type": "tool_use", "id": "toolu_h", "name": "http_request", "input": {
        "method": "GET", "url": "http://127.0.0.1:9/x",
        "headers": {"Authorization": "Bearer SECRET-123"}}}
    client = on_a_real_client(settings_env, AnthropicClient(
        "https://api.test", "sk-ant-test", "claude-opus-5-5", transport=httpx2.MockTransport(api(
            streamed(THOUGHT, asked), streamed({"type": "text", "text": "Done."}, stop="end_turn"),
            bodies=[]))))
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    wait_run(client, cid, run_id)
    with client.app.state.session_factory() as session:
        kept = [m.blocks for m in session.query(Message).filter_by(conversation_id=cid)]
        (arguments,) = [c.arguments for c in session.query(ToolCall).filter_by(run_id=run_id)]
    client.__exit__(None, None, None)
    assert "SECRET-123" not in arguments  # (KOLONİ keeps it masked...)
    assert kept and all(blocks is None for blocks in kept)  # (...and so nothing keeps it)
