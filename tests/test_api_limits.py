"""Slice 73: an API's rate limits as its answers' headers say them, and DeepSeek's balance when
the user asks - on the Plan limits view as the CLIs' plans are. Stand-ins only: a mock transport
for the API, a DeepSeek on this machine."""

import json
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx2
import pytest

import app.limits
from app.db.models import Provider
from app.limits import NO_PLAN, NOT_ANSWERED, NOT_READ, is_deepseek, of_headers
from app.model_client import ModelUnavailable
from tests.test_model_anthropic import events

ORIGIN = {"Origin": "http://127.0.0.1:8790"}
KEY = "sk-deepseek-DO-NOT-LEAK"
RESET = "2026-10-28T12:03:00Z"
ANTHROPIC = {
    "anthropic-ratelimit-requests-limit": "50", "anthropic-ratelimit-requests-remaining": "48",
    "anthropic-ratelimit-requests-reset": RESET,
    "anthropic-ratelimit-input-tokens-limit": "30000",
    "anthropic-ratelimit-input-tokens-remaining": "29000",
    "anthropic-ratelimit-input-tokens-reset": RESET,
}


def test_the_headers_say_each_window_and_nothing_is_made_up():
    now = datetime(2026, 10, 28, 12, 2, tzinfo=UTC)
    requests, tokens = of_headers(httpx2.Headers(ANTHROPIC), now)
    assert requests == {"name": "requests", "minutes": 1, "used_percent": None, "stale": False,
                        "resets_at": datetime(2026, 10, 28, 12, 3, tzinfo=UTC),
                        "limit": 50, "remaining": 48}
    assert (tokens["name"], tokens["limit"], tokens["remaining"]) == ("input tokens", 30000, 29000)
    # An OpenAI-compatible service's: its reset a duration, its window's length not said.
    (one,) = of_headers(httpx2.Headers({"x-ratelimit-limit-requests": "500",
                                        "x-ratelimit-remaining-requests": "499",
                                        "x-ratelimit-reset-requests": "6m0.5s"}), now)
    assert (one["minutes"], one["limit"], one["remaining"]) == (None, 500, 499)
    assert one["resets_at"] == now + timedelta(minutes=6, seconds=0.5)
    # Only what is said, as it is said: a remaining with no limit, no reset that reads as one.
    (half,) = of_headers(httpx2.Headers({"x-ratelimit-remaining-tokens": "7",
                                         "x-ratelimit-reset-tokens": "soon"}), now)
    assert (half["limit"], half["remaining"], half["resets_at"]) == (None, 7, None)
    assert of_headers(httpx2.Headers({"x-ratelimit-limit-requests": "lots"}), now) == []
    assert of_headers(httpx2.Headers({"content-type": "text/event-stream"}), now) == []
    # Digits of another script are no count; a reset past any date is none.
    (odd,) = of_headers(httpx2.Headers({b"x-ratelimit-limit-requests": b"\xb2",  # (latin-1 "²")
                                        b"x-ratelimit-remaining-requests": b"3",
                                        b"x-ratelimit-reset-requests": b"9" * 400 + b"h"}), now)
    assert (odd["limit"], odd["remaining"], odd["resets_at"]) == (None, 3, None)


@pytest.mark.parametrize(("kind", "base_url", "is_it"), [
    ("openai_compat", "https://api.deepseek.com", True),
    ("openai_compat", "https://api.deepseek.com/v1", True),
    ("openai_compat", "https://API.DeepSeek.com/v1", False),  # (netloc as written: shortcut)
    ("openai_compat", "http://api.deepseek.com/v1", False),  # not over https: no key sent
    ("openai_compat", "https://api.deepseek.com.evil.test/v1", False),
    ("openai_compat", "https://evil.test/api.deepseek.com/v1", False),
    ("openai_compat", "https://user@api.deepseek.com/v1", False),
    ("openai_compat", "https://api.deepseek.com:8443/v1", False),
    ("openai_compat", None, False),
    ("anthropic", "https://api.deepseek.com/anthropic", False),
    ("copilot_cli", "https://api.deepseek.com/v1", False),
])
def test_only_deepseeks_own_api_is_asked_its_balance(kind, base_url, is_it):
    assert is_deepseek(Provider(name="p", kind=kind, base_url=base_url)) is is_it


def made(client, **body):
    answer = client.post("/api/providers", json=body)
    assert answer.status_code == 201, answer.text
    return answer.json()["id"]


def built(client, provider_id, handler):
    """The client KOLONİ builds for the provider, as an agent's step gets it, on a stand-in."""
    with client.app.state.session_factory() as session:
        row = session.get_one(Provider, provider_id)
        model = client.app.state.providers._build(row, row.default_model)
    model._transport = httpx2.MockTransport(handler)
    return model


async def nothing(_text):
    return None


@pytest.mark.anyio
async def test_each_anthropic_answer_says_its_limits_a_429_too(client):
    pid = made(client, name="Claude API", kind="anthropic", api_key="sk-ant-test",
               default_model="claude-sonnet-5-5")
    assert client.get(f"/api/providers/{pid}/limits").json()["unknown"] == NOT_ANSWERED
    said = events({"type": "message_start", "message": {"usage": {"input_tokens": 5}}},
                  {"type": "content_block_start", "index": 0,
                   "content_block": {"type": "text", "text": ""}},
                  {"type": "content_block_delta", "index": 0,
                   "delta": {"type": "text_delta", "text": "hi"}},
                  {"type": "message_stop"})
    answers = iter([
        httpx2.Response(200, headers=ANTHROPIC, content=said),
        httpx2.Response(429, headers={**ANTHROPIC, "anthropic-ratelimit-requests-remaining": "0"},
                        json={"error": {"message": "rate limited"}}),
    ])

    def handler(request):
        if request.url.path.startswith("/v1/models"):
            return httpx2.Response(404)
        return next(answers)

    model = built(client, pid, handler)
    messages = [{"role": "user", "content": "hello"}]
    await model.stream_step("claude-sonnet-5-5", messages, None, nothing)
    shown = client.get(f"/api/providers/{pid}/limits").json()
    assert shown["source"] == "its last answer" and shown["unknown"] is None
    assert [(w["name"], w["remaining"], w["limit"], w["minutes"]) for w in shown["windows"]] == [
        ("requests", 48, 50, 1), ("input tokens", 29000, 30000, 1)]
    with pytest.raises(ModelUnavailable):
        await model.stream_step("claude-sonnet-5-5", messages, None, nothing)
    assert client.get(f"/api/providers/{pid}/limits").json()["windows"][0]["remaining"] == 0
    # "Check now" asks the API nothing: what its last answer said stands.
    assert client.post(f"/api/providers/{pid}/limits/check", headers=ORIGIN).json() == (
        client.get(f"/api/providers/{pid}/limits").json())


@pytest.mark.anyio
async def test_an_openai_compatible_answer_says_its_limits_and_a_window_past_its_reset_is_stale(
        client):
    pid = made(client, name="Hosted", kind="openai_compat", base_url="http://127.0.0.1:9/v1",
               default_model="m")
    assert client.get(f"/api/providers/{pid}/limits").json()["unknown"] == NO_PLAN
    body = b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\ndata: [DONE]\n\n'
    model = built(client, pid, lambda request: httpx2.Response(200, content=body, headers={
        "x-ratelimit-limit-requests": "60", "x-ratelimit-remaining-requests": "59",
        "x-ratelimit-reset-requests": "0ms"}))
    await model.stream_step("m", [{"role": "user", "content": "hello"}], None, nothing)
    (window,) = client.get(f"/api/providers/{pid}/limits").json()["windows"]
    # Reset already: what was left then is not what is left now - stale, its limit still said.
    assert (window["stale"], window["limit"], window["remaining"]) == (True, 60, 59)


class DeepSeek(BaseHTTPRequestHandler):
    """DeepSeek's balance on this machine: what it was asked is kept on the server."""

    def do_GET(self):  # noqa: N802
        self.server.asked.append((self.path, self.headers.get("Authorization")))
        status, told = self.server.answer
        data = json.dumps(told).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_args):
        pass


@pytest.fixture
def deepseek(monkeypatch):
    server = ThreadingHTTPServer(("127.0.0.1", 0), DeepSeek)
    server.asked, server.answer = [], (200, {})
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    monkeypatch.setattr(app.limits, "DEEPSEEK", url)
    server.url = url
    yield server
    server.shutdown()
    server.server_close()


def test_deepseeks_balance_is_read_on_check_now_only_and_beside_its_windows(client, deepseek):
    pid = made(client, name="DeepSeek", kind="openai_compat", base_url=f"{deepseek.url}/v1",
               api_key=KEY, default_model="deepseek-chat")
    other = made(client, name="Other", kind="openai_compat", base_url="http://127.0.0.1:9/v1",
                 api_key=KEY, default_model="m")
    assert client.get(f"/api/providers/{pid}/limits").json()["unknown"] == NOT_READ
    assert deepseek.asked == []  # opening the page asks nothing
    # what an answer of its said before
    client.app.state.providers.limits.api_said((pid,), httpx2.Headers(
        {"x-ratelimit-limit-requests": "60", "x-ratelimit-remaining-requests": "59"}))
    deepseek.answer = (200, {"is_available": True, "balance_infos": [
        {"currency": "CNY", "total_balance": "110.00", "granted_balance": "10.00",
         "topped_up_balance": "100.00"}]})
    before = datetime.now(UTC)
    shown = client.post(f"/api/providers/{pid}/limits/check", headers=ORIGIN).json()
    assert shown["credits"] == {"balance": "110.00 CNY", "has_credits": True, "unlimited": None}
    # The balance as read now, with its own time; the answer's windows were not read now.
    assert shown["windows"] == [] and shown["source"] is None
    assert datetime.fromisoformat(shown["read_at"]).replace(tzinfo=UTC) >= before
    # the key as its Bearer header, never in the address
    assert deepseek.asked == [("/user/balance", f"Bearer {KEY}")]
    # Another service is never asked, nor sent the key.
    assert client.post(f"/api/providers/{other}/limits/check", headers=ORIGIN).json()[
        "unknown"] == NO_PLAN
    assert len(deepseek.asked) == 1
    # A refusal that echoes the key: said by its status only, the last balance kept beside it.
    deepseek.answer = (401, {"error": {"message": f"bad key {KEY}"}})
    failed = client.post(f"/api/providers/{pid}/limits/check", headers=ORIGIN)
    assert KEY not in failed.text
    assert failed.json()["failed"] == "DeepSeek's balance answered 401"
    assert failed.json()["credits"]["balance"] == "110.00 CNY"
    # its balance out: no room for it (`has_room`)
    deepseek.answer = (200, {"is_available": False, "balance_infos": []})
    assert client.post(f"/api/providers/{pid}/limits/check", headers=ORIGIN).json()[
        "credits"] == {"balance": None, "has_credits": False, "unlimited": None}
    with client.app.state.session_factory() as session:
        row = session.get_one(Provider, pid)
        reading = client.app.state.providers.limits.last(row)
        assert app.limits.has_room(session, row, reading) is None
