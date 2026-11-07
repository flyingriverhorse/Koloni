import json

import httpx2
import pytest

from app.model_client import ModelUnavailable, OpenAICompatClient, redact_urls, safe_url
from tests.fakes import sse_body

pytestmark = pytest.mark.anyio


def client_for(handler) -> OpenAICompatClient:
    # Not llama-server: its `/props` (slice 59b) is not there.
    def served(request):
        return httpx2.Response(404) if request.url.path == "/props" else handler(request)

    return OpenAICompatClient("http://model/v1", transport=httpx2.MockTransport(served))


def reply(*chunks):
    return lambda request: httpx2.Response(200, content=sse_body(*chunks))


async def collect(client, tools=None):
    seen: list[str] = []

    async def on_delta(t: str) -> None:
        seen.append(t)

    result = await client.stream_step("m", [{"role": "user", "content": "hi"}], tools, on_delta)
    return result, seen


async def test_streams_text_and_usage():
    def handler(request):
        body = json.loads(request.content)
        assert body["stream"] is True and body["stream_options"] == {"include_usage": True}
        assert "tools" not in body
        return httpx2.Response(200, content=sse_body(
            {"choices": [{"delta": {"content": "Hel"}}]},
            {"choices": [{"delta": {"content": "lo"}}]},
            {"choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 2}},
        ))

    result, seen = await collect(client_for(handler))
    assert seen == ["Hel", "lo"] and result.content == "Hello"
    assert (result.input_tokens, result.output_tokens) == (7, 2)


async def test_missing_usage_is_none():
    result, _ = await collect(client_for(reply({"choices": [{"delta": {"content": "x"}}]})))
    assert result.input_tokens is None and result.output_tokens is None


async def test_assembles_fragmented_tool_calls():
    def call(index, **fields):
        return {"choices": [{"delta": {"tool_calls": [{"index": index, **fields}]}}]}

    handler = reply(
        call(0, id="c1", function={"name": "read_file", "arguments": '{"pa'}),
        call(0, function={"arguments": 'th": "a.py"}'}),
        call(1, id="c2", function={"name": "list_dir", "arguments": "{}"}),
    )
    result, _ = await collect(client_for(handler), tools=[{"type": "function"}])
    assert [(c.id, c.name, c.arguments) for c in result.tool_calls] == [
        ("c1", "read_file", '{"path": "a.py"}'), ("c2", "list_dir", "{}")]


async def test_reasoning_goes_to_thinking_not_content():
    handler = reply(
        {"choices": [{"delta": {"reasoning_content": "hmm"}}]},
        {"choices": [{"delta": {"content": "ok"}}]},
    )
    thinking: list[str] = []

    async def on_thinking(t):
        thinking.append(t)

    async def on_delta(_):
        pass

    result = await client_for(handler).stream_step("m", [], None, on_delta, on_thinking)
    assert result.content == "ok" and thinking == ["hmm"]


async def test_connection_error_is_model_unavailable():
    def handler(request):
        raise httpx2.ConnectError("refused")

    with pytest.raises(ModelUnavailable, match="refused"):
        await collect(client_for(handler))


async def test_http_error_carries_server_message():
    def handler(request):
        return httpx2.Response(500, json={"error": {"message": "context too long"}})

    with pytest.raises(ModelUnavailable, match="context too long"):
        await collect(client_for(handler))


async def test_stream_cut_mid_chunk_is_model_unavailable():
    def handler(request):
        return httpx2.Response(200, content=b'data: {"choices": [{"delta": {"content": "Hel')

    with pytest.raises(ModelUnavailable, match="unreadable"):
        await collect(client_for(handler))


async def test_info_discovers_model_and_probes_tools():
    def handler(request):
        if request.url.path == "/v1/models":
            return httpx2.Response(200, json={"data": [{"id": "qwen"}]})
        body = json.loads(request.content)
        assert body["tools"][0]["function"]["name"] == "ping" and body["stream"] is False
        return httpx2.Response(200, json={"choices": [{"message": {"tool_calls": [
            {"id": "x", "function": {"name": "ping", "arguments": "{}"}}]}}]})

    info = await client_for(handler).info()
    assert info.model_id == "qwen" and info.tools_supported is True


async def test_info_reports_no_tool_support_when_probe_answers_in_text():
    def handler(request):
        if request.url.path == "/v1/models":
            return httpx2.Response(200, json={"data": [{"id": "plain"}]})
        return httpx2.Response(200, json={"choices": [{"message": {"content": "I would call ping"}}]})

    assert (await client_for(handler).info()).tools_supported is False


async def test_tool_probe_runs_once_per_model():
    probes = 0

    def handler(request):
        nonlocal probes
        if request.url.path == "/v1/models":
            return httpx2.Response(200, json={"data": [{"id": "qwen"}]})
        probes += 1
        return httpx2.Response(200, json={"choices": [{"message": {"content": ""}}]})

    client = client_for(handler)
    await client.info()
    await client.info()
    assert probes == 1

async def test_an_error_names_no_password_or_key_of_the_address():
    # httpx names the URL it asked in its error, user name and password and all.
    def handler(request):
        if request.url.path.endswith("/models"):
            return httpx2.Response(401, request=request)
        raise httpx2.ConnectError(f"refused for {request.url}?key=k2")

    client = OpenAICompatClient("http://user:s3cret@model/v1", transport=httpx2.MockTransport(handler))
    with pytest.raises(ModelUnavailable) as listed:
        await client.models()
    with pytest.raises(ModelUnavailable) as streamed:
        await collect(client)
    # (The list's answer was a status: said as one, which names no address at all.)
    assert str(listed.value).startswith("model server returned 401")
    assert "http://model/v1/" in str(streamed.value)
    for told in (str(listed.value), str(streamed.value)):
        assert "s3cret" not in told and "user" not in told and "k2" not in told


def test_safe_url_keeps_the_place_and_drops_what_can_be_a_secret():
    assert safe_url("http://user:pass@127.0.0.1:8080/v1") == "http://127.0.0.1:8080/v1"
    assert safe_url("https://token@api.example.com/v1") == "https://api.example.com/v1"
    assert safe_url("https://api.example.com/v1?key=abc#frag") == "https://api.example.com/v1"
    assert safe_url("http://[::1]:8080/v1") == "http://[::1]:8080/v1"
    assert safe_url("") == ""
    assert safe_url("tok@not a url?key=1") == "not a url"
    assert redact_urls("for url 'http://a:b@h/v1?key=c' and http://h2/x#y here") == "for url 'http://h/v1' and http://h2/x here"
