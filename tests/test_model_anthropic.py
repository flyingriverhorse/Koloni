"""The Anthropic Messages API client, against a stand-in transport."""

import json

import httpx2
import pytest

from app.model_anthropic import AnthropicClient, to_anthropic
from app.model_client import ModelUnavailable
from app.tools import TOOL_SCHEMAS

pytestmark = pytest.mark.anyio

KEY = "sk-ant-test-DO-NOT-LEAK"


def events(*items) -> bytes:
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in items).encode()


def client_for(handler, model="claude-sonnet-5-5") -> AnthropicClient:
    return AnthropicClient("https://api.test", KEY, model, transport=httpx2.MockTransport(handler))


async def collect(client, messages, tools=None):
    said, thought = [], []

    async def on_delta(text):
        said.append(text)

    async def on_thinking(text):
        thought.append(text)

    result = await client.stream_step("claude-sonnet-5-5", messages, tools, on_delta, on_thinking)
    return result, said, thought


HISTORY = [
    {"role": "system", "content": "You are KOLONİ's agent."},
    {"role": "user", "content": "fix it"},
    {"role": "assistant", "content": "Reading.", "tool_calls": [
        {"id": "c1", "type": "function",
         "function": {"name": "read_file", "arguments": '{"path": "a.py"}'}},
        {"id": "c2", "type": "function", "function": {"name": "list_dir", "arguments": "{}"}}]},
    {"role": "tool", "tool_call_id": "c1", "content": "print('hi')"},
    {"role": "tool", "tool_call_id": "c2", "content": "a.py"},
    {"role": "assistant", "content": ""},
    {"role": "user", "content": "go on"},
]


def test_history_is_rewritten_into_content_blocks():
    system, messages = to_anthropic(HISTORY)
    assert system == "You are KOLONİ's agent."
    assert [m["role"] for m in messages] == ["user", "assistant", "user", "user"]
    assert messages[1]["content"] == [
        {"type": "text", "text": "Reading."},
        {"type": "tool_use", "id": "c1", "name": "read_file", "input": {"path": "a.py"}},
        {"type": "tool_use", "id": "c2", "name": "list_dir", "input": {}},
    ]
    # both results answer in one user message; the empty assistant message is dropped
    assert messages[2]["content"] == [
        {"type": "tool_result", "tool_use_id": "c1", "content": "print('hi')"},
        {"type": "tool_result", "tool_use_id": "c2", "content": "a.py"},
    ]
    assert messages[3] == {"role": "user", "content": "go on"}


async def test_text_tools_thinking_and_usage_are_streamed():
    def handler(request):
        if request.method == "GET":  # the most it may write: not said here
            return httpx2.Response(404)
        assert request.url.path == "/v1/messages"
        assert request.headers["x-api-key"] == KEY and request.headers["anthropic-version"]
        body = json.loads(request.content)
        assert body["stream"] is True and body["model"] == "claude-sonnet-5-5"
        assert body["system"] == "You are KOLONİ's agent."
        assert body["tools"][0] == {
            "name": "list_dir", "description": TOOL_SCHEMAS[0]["function"]["description"],
            "input_schema": TOOL_SCHEMAS[0]["function"]["parameters"]}
        return httpx2.Response(200, content=events(
            {"type": "message_start", "message": {"usage": {
                "input_tokens": 20, "cache_read_input_tokens": 80, "output_tokens": 1}}},
            {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking"}},
            {"type": "content_block_delta", "index": 0,
             "delta": {"type": "thinking_delta", "thinking": "hmm"}},
            {"type": "content_block_start", "index": 1, "content_block": {"type": "text"}},
            {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "On "}},
            {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "it."}},
            {"type": "content_block_start", "index": 2,
             "content_block": {"type": "tool_use", "id": "toolu_1", "name": "read_file"}},
            {"type": "content_block_delta", "index": 2,
             "delta": {"type": "input_json_delta", "partial_json": '{"path": '}},
            {"type": "content_block_delta", "index": 2,
             "delta": {"type": "input_json_delta", "partial_json": '"a.py"}'}},
            {"type": "content_block_start", "index": 3,
             "content_block": {"type": "tool_use", "id": "toolu_2", "name": "list_dir"}},
            {"type": "message_delta", "delta": {"stop_reason": "tool_use"},
             "usage": {"output_tokens": 42}},
            {"type": "message_stop"},
        ))

    result, said, thought = await collect(client_for(handler), HISTORY, TOOL_SCHEMAS)
    assert (result.content, said, thought) == ("On it.", ["On ", "it."], ["hmm"])
    assert [(c.id, c.name, c.arguments) for c in result.tool_calls] == [
        ("toolu_1", "read_file", '{"path": "a.py"}'), ("toolu_2", "list_dir", "{}")]
    assert (result.input_tokens, result.output_tokens) == (100, 42)


async def test_no_tools_means_no_tools_field():
    def handler(request):
        if request.method == "GET":
            return httpx2.Response(404)
        assert "tools" not in json.loads(request.content)
        return httpx2.Response(200, content=events(
            {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "hi"}}))

    result, _, _ = await collect(client_for(handler), HISTORY)
    assert (result.content, result.input_tokens, result.output_tokens) == ("hi", None, None)


@pytest.mark.parametrize("status, body, expected", [
    (401, {"error": {"type": "authentication_error", "message": "invalid x-api-key"}},
     "refused this key (401). It may be a Claude subscription token"),
    (429, {"error": {"message": "rate limited"}}, "429: rate limited"),
    (500, "<html>oops</html>", "500"),
])
async def test_http_errors_give_the_reason_and_never_the_key(status, body, expected):
    def handler(request):
        content = json.dumps(body) if isinstance(body, dict) else body
        return httpx2.Response(status, content=content)

    with pytest.raises(ModelUnavailable) as failure:
        await collect(client_for(handler), HISTORY)
    assert expected in str(failure.value) and KEY not in str(failure.value)


async def test_an_error_in_the_middle_of_the_stream_fails_the_step():
    def handler(request):
        return httpx2.Response(200, content=events(
            {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "par"}},
            {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}))

    with pytest.raises(ModelUnavailable, match="Overloaded"):
        await collect(client_for(handler), HISTORY)


async def test_unreachable_is_reported_without_the_key():
    def handler(request):
        raise httpx2.ConnectError("connection refused")

    with pytest.raises(ModelUnavailable) as failure:
        await collect(client_for(handler), HISTORY)
    assert "unreachable" in str(failure.value) and KEY not in str(failure.value)


async def test_info_checks_the_model_and_key_without_spending_tokens():
    asked = []

    def handler(request):
        asked.append((request.method, request.url.path))
        return httpx2.Response(200, content=json.dumps({"id": "claude-sonnet-5-5"}))

    client = client_for(handler)
    info = await client.info()
    assert (info.model_id, info.tools_supported) == ("claude-sonnet-5-5", True)
    await client.info()
    assert asked == [("GET", "/v1/models/claude-sonnet-5-5")]  # asked once, then remembered

    with pytest.raises(ModelUnavailable, match="choose a model"):
        await client_for(handler, model=None).info()
    with pytest.raises(ModelUnavailable, match="needs an API key"):
        await AnthropicClient("https://api.test", None, "m").info()

    def refused(request):
        return httpx2.Response(401, content=json.dumps({"error": {"message": "invalid x-api-key"}}))

    with pytest.raises(ModelUnavailable, match=r"refused this key \(401\)\..* It said: invalid x-api-key"):
        await client_for(refused).info()


# --- the workspace --------------------------------------------------------------------

WORKSPACE = "wrkspc_01TESTworkspace"


def answering(seen):
    def handler(request):
        seen.append((request.url.path, request.headers.get("anthropic-workspace-id"),
                     request.headers["x-api-key"], request.headers["anthropic-version"]))
        if request.url.path == "/v1/messages":
            return httpx2.Response(200, content=events(
                {"type": "content_block_delta", "index": 0,
                 "delta": {"type": "text_delta", "text": "hi"}}))
        return httpx2.Response(200, content=json.dumps({"id": "claude-sonnet-5-5"}))

    return handler


async def test_a_workspace_goes_with_every_request_when_one_is_set():
    seen = []
    client = AnthropicClient(
        "https://api.test", KEY, "claude-sonnet-5-5",
        transport=httpx2.MockTransport(answering(seen)), workspace_id=WORKSPACE)
    await client.info()
    await collect(client, HISTORY)
    assert [(path, workspace, key) for path, workspace, key, _version in seen] == [
        ("/v1/models/claude-sonnet-5-5", WORKSPACE, KEY), ("/v1/messages", WORKSPACE, KEY)]
    assert all(version for *_rest, version in seen)


@pytest.mark.parametrize("workspace", [None, ""])
async def test_without_a_workspace_no_such_header_is_sent(workspace):
    seen = []
    client = AnthropicClient(
        "https://api.test", KEY, "claude-sonnet-5-5",
        transport=httpx2.MockTransport(answering(seen)), workspace_id=workspace)
    await client.info()
    await collect(client, HISTORY)
    assert [(path, sent) for path, sent, _key, _version in seen] == [
        ("/v1/models/claude-sonnet-5-5", None), ("/v1/messages", None)]


# --- the models a key can use -----------------------------------------------------------


def page(*ids, more=False, last=True):
    told = {"data": [{"type": "model", "id": name, "display_name": name.title()}
                     for name in ids], "has_more": more}
    if last and ids:
        told["first_id"], told["last_id"] = ids[0], ids[-1]
    return httpx2.Response(200, content=json.dumps(told))


async def test_the_models_are_listed_page_after_page_while_there_are_more():
    asked = []
    pages = {None: page("claude-a", "claude-b", more=True),
             "claude-b": page("claude-c", more=True, last=False),   # says no last_id
             "claude-c": page("claude-d", "claude-a")}

    def handler(request):
        asked.append((request.method, request.url.path, dict(request.url.params),
                      request.headers["x-api-key"], request.headers["anthropic-version"],
                      request.headers.get("anthropic-workspace-id")))
        return pages[request.url.params.get("after_id")]

    client = AnthropicClient("https://api.test/", KEY, None,
                             transport=httpx2.MockTransport(handler), workspace_id=WORKSPACE)
    # each model once, in the order they came
    assert await client.models() == ["claude-a", "claude-b", "claude-c", "claude-d"]
    assert [(method, path, params) for method, path, params, *_ in asked] == [
        ("GET", "/v1/models", {}), ("GET", "/v1/models", {"after_id": "claude-b"}),
        ("GET", "/v1/models", {"after_id": "claude-c"})]
    assert all(sent == (KEY, "2023-06-01", WORKSPACE) for *_, sent in
               [(None, row[3:]) for row in asked])
    # without a workspace the header is not sent here either
    asked.clear()
    await client_for(handler, model=None).models()
    assert [row[5] for row in asked] == [None, None, None]


async def test_no_more_than_five_pages_are_asked_for():
    asked = []

    def handler(request):
        asked.append(request.url.params.get("after_id"))
        return page(f"claude-{len(asked)}", more=True)

    assert await client_for(handler).models() == [f"claude-{n}" for n in range(1, 6)]
    assert asked == [None, "claude-1", "claude-2", "claude-3", "claude-4"]


async def test_a_page_that_says_more_and_holds_nothing_ends_the_list():
    asked = []

    def handler(request):
        asked.append(request.url.params.get("after_id"))
        return page("claude-a", more=True) if len(asked) == 1 else page(more=True)

    assert await client_for(handler).models() == ["claude-a"]
    assert len(asked) == 2


@pytest.mark.parametrize("answer, expected", [
    (httpx2.Response(401, content=json.dumps({"error": {"message": "invalid x-api-key"}})),
     "refused this key (401). It may be a Claude subscription token"),
    (httpx2.Response(403, content=json.dumps({"error": {
        "message": "this key belongs to another workspace"}})), "another workspace"),
    (httpx2.Response(500, content="<html>oops</html>"), "500"),
    (httpx2.Response(200, content="this is not json"), "list of models"),
    (httpx2.Response(200, content=json.dumps(["claude-a"])), "list of models"),
    (httpx2.Response(200, content=json.dumps({"data": "claude-a"})), "list of models"),
])
async def test_a_list_that_cannot_be_had_says_why_and_never_the_key(answer, expected):
    with pytest.raises(ModelUnavailable) as failure:
        await client_for(lambda request: answer).models()
    assert expected in str(failure.value) and KEY not in str(failure.value)


async def test_unreachable_or_too_slow_is_said_without_the_key():
    def unreachable(request):
        raise httpx2.ConnectError("All connection attempts failed")

    def slow(request):
        raise httpx2.ReadTimeout("timed out")

    for handler in (unreachable, slow):
        with pytest.raises(ModelUnavailable) as failure:
            await client_for(handler).models()
        assert "unreachable" in str(failure.value) and KEY not in str(failure.value)
    # the list is asked for with a short limit: a page of settings is not kept waiting
    waits = []
    client = client_for(lambda request: page("claude-a"))
    real = client._client
    client._client = lambda timeout: waits.append(timeout) or real(timeout)
    await client.models()
    assert waits and all(wait is not None and wait <= 15 for wait in waits)


async def test_without_a_key_nothing_is_asked():
    asked = []
    client = AnthropicClient("https://api.test", None, None, transport=httpx2.MockTransport(
        lambda request: asked.append(request) or page("claude-a")))
    with pytest.raises(ModelUnavailable, match="needs an API key"):
        await client.models()
    assert asked == []


# --- why the model stopped ---------------------------------------------------------------


def stopped(reason, *before, **delta):
    def handler(request):
        return httpx2.Response(200, content=events(
            *before,
            {"type": "message_delta", "delta": {"stop_reason": reason, **delta},
             "usage": {"output_tokens": 9}},
            {"type": "message_stop"}))

    return client_for(handler)


SAID = {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "I "}}


@pytest.mark.parametrize("details, expected", [
    ({"stop_details": {"type": "refusal", "category": "cyber"}},
     "the model declined to answer (cyber)"),
    ({"stop_details": None}, "the model declined to answer"), ({}, "the model declined to answer"),
    ({"stop_details": {"category": "x\ny" * 40}}, "the model declined to answer"),
])
async def test_a_refusal_fails_the_step_and_says_so(details, expected):
    with pytest.raises(ModelUnavailable) as failure:
        await collect(stopped("refusal", SAID, **details), HISTORY)
    assert str(failure.value) == expected


async def test_an_answer_cut_at_the_output_limit_is_kept_and_said_to_be_cut():
    result, said, _ = await collect(stopped("max_tokens", SAID), HISTORY)
    assert result.content == "I \n\n[cut off at the output limit]" and "".join(said) == result.content
    assert result.tool_calls == [] and result.output_tokens == 9


@pytest.mark.parametrize("partial", ['{"path": "a.py", "content": "half', "", '{"path": "a.py"'])
async def test_a_tool_call_cut_at_the_output_limit_is_marked_and_the_ones_before_are_not(partial):
    result, _, _ = await collect(stopped(
        "max_tokens", SAID,
        {"type": "content_block_start", "index": 1,
         "content_block": {"type": "tool_use", "id": "toolu_1", "name": "read_file"}},
        {"type": "content_block_delta", "index": 1,
         "delta": {"type": "input_json_delta", "partial_json": '{"path": "a.py"}'}},
        {"type": "content_block_stop", "index": 1},
        {"type": "content_block_start", "index": 2,
         "content_block": {"type": "tool_use", "id": "toolu_2", "name": "write_file"}},
        {"type": "content_block_delta", "index": 2,
         "delta": {"type": "input_json_delta", "partial_json": partial}},
        {"type": "content_block_stop", "index": 2},
    ), HISTORY, TOOL_SCHEMAS)
    assert [(c.name, c.cut) for c in result.tool_calls] == [
        ("read_file", False), ("write_file", True)]
    assert result.content == "I "             # it is the call that says it was cut


async def test_a_whole_call_before_the_limit_is_not_a_cut_one():
    result, _, _ = await collect(stopped(
        "max_tokens",
        {"type": "content_block_start", "index": 0,
         "content_block": {"type": "tool_use", "id": "toolu_1", "name": "read_file"}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "input_json_delta", "partial_json": '{"path": "a.py"}'}},
    ), HISTORY, TOOL_SCHEMAS)
    assert [(c.name, c.cut) for c in result.tool_calls] == [("read_file", False)]


def test_a_call_that_was_cut_is_not_run(make_client, wait_run, project_dir):
    from app.model_client import StepResult, ToolCallRequest
    from tests.test_chat_flow import text

    cut = [ToolCallRequest("w", "write_file", '{"path": "new.txt", "content": "ha', cut=True),
           ToolCallRequest("e", "write_file", '{"path": "whole.txt", "content": ""}', cut=True)]
    client, _model = make_client([StepResult("", cut, 5, 2), text("done")])
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(f"/api/conversations/{cid}", json={"permission_mode": "full_auto"},
                 headers={"Origin": "http://127.0.0.1:8790"})
    run = client.post(f"/api/conversations/{cid}/messages", json={"content": "go"}).json()["run"]
    snap = wait_run(client, cid, run["id"])
    assert [t["status"] for t in snap["tool_calls"]] == ["failed", "failed"]
    assert all("cut off at the output limit" in t["result"] for t in snap["tool_calls"])
    assert not (project_dir / "new.txt").exists() and not (project_dir / "whole.txt").exists()
    assert snap["file_changes"] == []


# --- a search through the API ------------------------------------------------------------


def found(*blocks, **more):
    return {"id": "msg_1", "type": "message", "role": "assistant", "stop_reason": "end_turn",
            "content": list(blocks), **more}


def hit(title, url):
    return {"type": "web_search_result", "title": title, "url": url,
            "encrypted_content": "E" * 40, "page_age": None}


def searched(*hits):
    return {"type": "web_search_tool_result", "tool_use_id": "srvtoolu_1", "content": list(hits)}


def told(*answers):
    asked, left = [], list(answers)

    def handler(request):
        asked.append(request)
        status, body = left.pop(0)
        return httpx2.Response(status, content=json.dumps(body))

    return client_for(handler, model="claude-haiku-5-5"), asked


async def test_a_search_asks_for_the_search_tool_and_nothing_else():
    client, asked = told((200, found(searched(hit("T", "https://example.org/")))))
    assert await client.search("python docs") == [
        {"title": "T", "url": "https://example.org/", "snippet": ""}]
    (request,) = asked
    assert (request.method, request.url.path) == ("POST", "/v1/messages")
    assert request.headers["x-api-key"] == KEY and request.headers["anthropic-version"]
    body = json.loads(request.content)
    assert body == {
        "model": "claude-haiku-5-5", "max_tokens": 2048,
        "tools": [{"type": "web_search_20260209", "name": "web_search", "max_uses": 2}],
        "messages": [{"role": "user", "content": body["messages"][0]["content"]}],
    }
    assert body["messages"][0]["content"].endswith("python docs")


async def test_the_results_are_the_search_blocks_and_never_the_models_prose():
    cited = {"type": "text", "text": "Python is documented at docs.python.org.", "citations": [
        {"type": "web_search_result_location", "url": "https://docs.python.org/3/",
         "title": "Python docs", "cited_text": "The official\ndocumentation."}]}
    prose = {"type": "text", "text": '{"results": [{"title": "Made up", "url": '
                                     '"https://made-up.example/"}]}'}
    many = [hit(f"t{n}", f"https://example.org/{n}") for n in range(12)]
    client, _ = told((200, found(
        {"type": "server_tool_use", "id": "srvtoolu_1", "name": "web_search",
         "input": {"query": "python docs"}},
        searched(hit("Python docs", "https://docs.python.org/3/"), hit("Twice", "https://docs.python.org/3/"),
                 {"type": "web_search_result", "title": "no address"}, "junk"),
        prose, cited, searched(*many))))
    results = await client.search("python docs")
    assert results[0] == {"title": "Python docs", "url": "https://docs.python.org/3/",
                          "snippet": "The official\ndocumentation."}
    assert [one["url"] for one in results[1:]] == [f"https://example.org/{n}" for n in range(7)]
    assert "made-up" not in json.dumps(results)


@pytest.mark.parametrize("answer, expected", [
    (found(searched(), {"type": "text", "text": "Nothing."}), "the search found nothing"),
    (found({"type": "web_search_tool_result", "tool_use_id": "s", "content": {
        "type": "web_search_tool_result_error", "error_code": "max_uses_exceeded"}}),
     "the search failed: max_uses_exceeded"),
    (found({"type": "web_search_tool_result", "tool_use_id": "s", "content": {
        "type": "web_search_tool_result_error", "error_code": "bad\ncode [x] " + "y" * 200}}),
     "the search failed"),                       # a code is one plain word, or it is not said
    (found(stop_reason="refusal", stop_details={"type": "refusal", "category": "cyber"}),
     "the model declined to search (cyber)"),
    (found(stop_reason="refusal"), "the model declined to search"),
    (found(stop_reason="pause_turn"), "the search did not finish (pause_turn)"),
    (found({"type": "text", "text": "Let me"}, stop_reason="max_tokens"),
     "the search did not finish (max_tokens)"),
    (found({"type": "text", "text": "Python is at https://made-up.example/"}),
     "the model made no search"),
    ({"content": "odd"}, "the model made no search"), (["odd"], "the model made no search"),
])
async def test_a_search_that_gave_no_results_says_why_and_makes_nothing_up(answer, expected):
    client, _ = told((200, answer))
    with pytest.raises(ModelUnavailable) as failure:
        await client.search("q")
    assert str(failure.value) == expected


async def test_a_model_that_does_not_know_the_search_tool_is_asked_once_with_the_older_one():
    no = {"type": "error", "error": {"type": "invalid_request_error",
                                     "message": "'claude-haiku-4-5' does not support programmatic tool "
                                     "calling. The following tools have `allowed_callers` "
                                     "that require it: web_search."}}
    client, asked = told((400, no), (200, found(searched(hit("T", "https://example.org/")))))
    assert [one["title"] for one in await client.search("q")] == ["T"]
    assert [json.loads(request.content)["tools"][0]["type"] for request in asked] == [
        "web_search_20260209", "web_search_20250305"]
    client, asked = told((400, no), (400, no), (200, found()))
    with pytest.raises(ModelUnavailable, match="400") as failure:
        await client.search("q")
    assert len(asked) == 2 and KEY not in str(failure.value)
    # a refusal that is about anything else, or cannot be read, is not paid for twice
    other = {"type": "error", "error": {"type": "invalid_request_error",
                                        "message": "max_tokens: too large"}}
    for refusal in (other, "not json", {"error": "odd"}):
        client, asked = told((400, refusal), (200, found(searched(hit("T", "https://e.org/")))))
        with pytest.raises(ModelUnavailable, match="400"):
            await client.search("q")
        assert len(asked) == 1


@pytest.mark.parametrize("status, body, expected", [
    (401, {"error": {"type": "authentication_error", "message": "invalid x-api-key"}}, "401"),
    (529, {"error": {"message": "Overloaded"}}, "Overloaded"), (200, "not json", "unreadable"),
])
async def test_a_search_that_fails_says_why_and_never_the_key(status, body, expected):
    def handler(request):
        return httpx2.Response(status, content=body if isinstance(body, str) else json.dumps(body))

    with pytest.raises(ModelUnavailable) as failure:
        await client_for(handler).search("q")
    assert expected in str(failure.value) and KEY not in str(failure.value)


async def test_without_a_key_or_a_model_no_search_is_asked_for():
    asked = []
    transport = httpx2.MockTransport(lambda request: asked.append(request) or page("x"))
    for key, model in ((None, "claude-haiku-5-5"), (KEY, None)):
        with pytest.raises(ModelUnavailable):
            await AnthropicClient("https://api.test", key, model, transport=transport).search("q")
    assert asked == []


async def test_a_step_cut_before_its_end_has_said_what_it_sent_by_then():
    import asyncio

    async def answer():
        yield events({"type": "message_start", "message": {"usage": {
            "input_tokens": 20, "cache_read_input_tokens": 80, "output_tokens": 1}}})
        yield events({"type": "content_block_delta", "index": 0,
                      "delta": {"type": "text_delta", "text": "On "}})
        await asyncio.Event().wait()                 # and nothing more comes

    told, said = [], asyncio.Event()

    async def on_delta(text):
        said.set()

    step = asyncio.ensure_future(client_for(
        lambda request: httpx2.Response(404) if request.method == "GET"
        else httpx2.Response(200, content=answer())
    ).stream_step("claude-sonnet-5-5", HISTORY, None, on_delta,
                  so_far=lambda *counts: told.append(counts)))
    await asyncio.wait_for(said.wait(), 5)
    step.cancel()
    with pytest.raises(asyncio.CancelledError):
        await step
    # what it sent is known from the start of the answer - and what of that was read again
    # from the cache (of what was written there it said nothing); what it wrote comes at its end
    assert told == [(100, None, 80, None)]


def test_the_anthropic_providers_with_a_key_are_the_ones_a_search_can_go_through(client):
    from app.providers import search_apis

    client.headers["Origin"] = "http://127.0.0.1:8790"
    for name, key, more in (("No key", None, {}), ("Mine", KEY, {"options": {"workspace_id": "w1"}}),
                            ("Listed", KEY, {"only_listed": True,
                                             "models": [{"name": "claude-opus-5-5"}]})):
        body = {"name": name, "kind": "anthropic", "default_model": "claude-haiku-5-5", **more}
        if key:
            body["api_key"] = key
        assert client.post("/api/providers", json=body).status_code == 201, name
    (one,) = search_apis(client.app.state.session_factory)
    # ("Listed" runs only with a model on its list, and its own default is not on it.)
    assert (one._key, one._model_id, one._workspace) == (KEY, "claude-haiku-5-5", "w1")
