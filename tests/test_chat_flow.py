import json

from sqlalchemy import select

from app.db.models import Agent
from app.model_client import ModelUnavailable, StepResult


def text(content, i=5, o=3):
    return StepResult(content, [], i, o)


def start(client, project_dir, content="hello"):
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    posted = client.post(f"/api/conversations/{cid}/messages", json={"content": content}).json()
    return cid, posted["run"]["id"]


def start_in_mode(client, project_dir, mode, content="hello"):
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    # (a level is raised only from the app's own page: this request says it is from there)
    client.patch(f"/api/conversations/{cid}", json={"permission_mode": mode,
                 "lead_hands_code": False},  # (the Lead writes itself: slice 48's default off)
                 headers={"Origin": "http://127.0.0.1:8790"})
    posted = client.post(f"/api/conversations/{cid}/messages", json={"content": content}).json()
    return cid, posted["run"]["id"]


def test_plain_reply_is_stored_and_run_completes(make_client, wait_run, project_dir):
    client, model = make_client([text("Hi there")])
    cid, run_id = start(client, project_dir)
    snap = wait_run(client, cid, run_id)
    assert [(m["role"], m["content"], m["status"]) for m in snap["messages"]] == [
        ("user", "hello", "complete"), ("assistant", "Hi there", "complete")]
    run = snap["runs"][0]
    assert run["status"] == "completed" and run["model_id"] == "fake-model"
    assert (run["input_tokens"], run["output_tokens"]) == (5, 3)
    assert run["started_at"] and run["ended_at"]
    assert snap["conversation"]["title"] == "hello"
    assert model.calls[0][0]["role"] == "system"
    assert model.calls[0][-1] == {"role": "user", "content": "hello"}


def test_unknown_usage_stays_null(make_client, wait_run, project_dir):
    client, _ = make_client([StepResult("x", [], None, None)])
    cid, run_id = start(client, project_dir)
    run = wait_run(client, cid, run_id)["runs"][0]
    assert run["input_tokens"] is None and run["output_tokens"] is None


def test_model_failure_fails_the_run_with_its_message(make_client, wait_run, project_dir):
    client, _ = make_client([ModelUnavailable("model server unreachable: refused"), text("ok")])
    cid, run_id = start(client, project_dir)
    run = wait_run(client, cid, run_id)["runs"][0]
    assert run["status"] == "failed" and "refused" in run["error"]
    # the composer is usable again: a new message starts a fresh run
    again = client.post(f"/api/conversations/{cid}/messages", json={"content": "again"})
    assert again.status_code == 201 and again.json()["run"]["status"] == "running"
    wait_run(client, cid, again.json()["run"]["id"])


def short(why="model server returned 503: overloaded", wait=0.0):
    failed = ModelUnavailable(why)
    failed.retry_in = wait
    return failed


def test_a_short_provider_failure_is_asked_again_once_and_said_on_the_agents_record(
    make_client, wait_run, project_dir
):
    client, model = make_client([short(), text("ok")])
    cid, run_id = start(client, project_dir)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed"
    assert model.calls[0] == model.calls[1]  # the same step, with the same model
    assert snap["agents"][0]["retry_note"] == (
        "A step was asked again once, after a short failure of its provider: model server "
        "returned 503: overloaded")
    # what the failed one said it read before it failed is paid for, beside the retry's
    client, model = make_client([short(), text("ok", 5, 3)])
    plain = model.stream_step

    async def stream_step(model_id, messages, tools, on_delta, on_thinking=None, so_far=None):
        if len(model.calls) == 0:
            so_far(40, None)  # (as the Anthropic API says it when its answer begins)
        return await plain(model_id, messages, tools, on_delta, on_thinking)

    model.reports_early, model.stream_step = True, stream_step
    cid, run_id = start(client, project_dir)
    assert wait_run(client, cid, run_id)["runs"][0]["status"] == "completed"
    with client.app.state.session_factory() as session:
        lead = session.scalar(select(Agent).where(Agent.run_id == run_id))
        assert (lead.input_tokens_total, lead.cut_short) == (45, False)
    # a second failure ends the turn
    client, model = make_client([short(), short("model server returned 502: bad gateway")])
    cid, run_id = start(client, project_dir)
    assert wait_run(client, cid, run_id)["runs"][0]["status"] == "failed"

    async def wrote_first(on_delta):
        await on_delta("half an ans")
        raise short()

    # never asked again: no short failure; one after text came (it would be shown twice);
    # credits used up, though its provider says to wait a moment; one too large to be read
    for first in (ModelUnavailable("model server returned 401: invalid key"), wrote_first,
                  short("model server returned 429: You exceeded your current quota"),
                  short("model server returned 400: maximum context length is 8192")):
        client, model = make_client([first, text("never"), text("never"), text("never")])
        cid, run_id = start(client, project_dir)
        snap = wait_run(client, cid, run_id)
        assert snap["agents"][0]["retry_note"] is None, first
        assert "never" not in [m["content"] for m in snap["messages"]], first


def on_a_real_client(settings_env, model):
    """An app whose model is a real client, over a stand-in transport."""
    from app.config import load_settings
    from app.main import create_app
    from tests.keyed import TestClient

    client = TestClient(create_app(load_settings(settings_env), model=model),
                        base_url="http://127.0.0.1:8790")
    client.__enter__()
    return client


def test_a_short_failure_of_a_real_client_is_asked_again_through_the_agent(
    settings_env, wait_run, project_dir
):
    import httpx2

    from app.model_anthropic import AnthropicClient
    from app.model_client import OpenAICompatClient
    from tests.test_model_anthropic import events

    answered = 'data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n'
    for status in (408, 529):
        streamed = []

        def handler(request, status=status, streamed=streamed):
            body = json.loads(request.content or b"{}")
            if request.url.path.endswith("/props"):
                return httpx2.Response(404)
            if not body.get("stream"):  # (its probe for tools)
                return httpx2.Response(200, json={"choices": [{"message": {}}]})
            streamed.append(status)
            return httpx2.Response(status, json={"error": "busy"}) if len(streamed) == 1 \
                else httpx2.Response(200, text=answered)

        client = on_a_real_client(settings_env, OpenAICompatClient(
            "https://api.acme.test/v1", model_id="m", transport=httpx2.MockTransport(handler)))
        cid, run_id = start(client, project_dir)
        snap = wait_run(client, cid, run_id)
        client.__exit__(None, None, None)
        assert snap["runs"][0]["status"] == "completed", (status, snap["runs"][0]["error"])
        assert f"returned {status}" in snap["agents"][0]["retry_note"] and len(streamed) == 2

    # Anthropic's overloaded_error, said in the stream after it began
    asked = []

    def anthropic(request):
        if request.method == "GET":
            return httpx2.Response(200, json={"id": "claude-x", "max_input_tokens": 1000})
        asked.append(1)
        began = {"type": "message_start", "message": {"usage": {"input_tokens": 3}}}
        if len(asked) == 1:
            return httpx2.Response(200, content=events(began, {"type": "error", "error": {
                "type": "overloaded_error", "message": "Overloaded"}}))
        return httpx2.Response(200, content=events(began, {
            "type": "content_block_delta", "index": 0,
            "delta": {"type": "text_delta", "text": "ok"}}))

    client = on_a_real_client(settings_env, AnthropicClient(
        "https://api.test", "sk-ant-test", "claude-x", transport=httpx2.MockTransport(anthropic)))
    cid, run_id = start(client, project_dir)
    snap = wait_run(client, cid, run_id)
    client.__exit__(None, None, None)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert "Overloaded" in snap["agents"][0]["retry_note"] and len(asked) == 2


def test_which_failures_are_short():
    import asyncio

    import httpx2

    from app.model_client import OpenAICompatClient

    def failing(response):
        async def step():
            client = OpenAICompatClient("https://api.acme.test/v1",
                                        transport=httpx2.MockTransport(response))
            try:
                await client.stream_step("m", [{"role": "user", "content": "x"}], None,
                                         lambda _text: asyncio.sleep(0))
            except ModelUnavailable as exc:
                return exc.retry_in
            raise AssertionError("it did not fail")
        return asyncio.run(step())

    def status(code, **headers):
        return lambda _request: httpx2.Response(code, json={"error": "no"}, headers=headers)

    def dropped(request):
        raise httpx2.ConnectError("connection reset", request=request)

    assert failing(status(503)) == 1.0 and failing(dropped) == 1.0
    assert failing(status(429, **{"Retry-After": "3"})) == 3.0
    for code, headers in ((429, {}), (429, {"Retry-After": "120"}), (429, {"Retry-After": "²"}),
                          (401, {}), (400, {})):
        assert failing(status(code, **headers)) is None, code
    # a quota used up is no short failure, whatever its Retry-After says
    for code in ("insufficient_quota", "token-plan quota has been exhausted"):
        assert failing(lambda _request, code=code: httpx2.Response(
            429, json={"error": {"code": code}}, headers={"Retry-After": "1"})) is None, code


def test_message_sent_while_running_is_queued_and_runs_next(make_client, wait_run, project_dir, gate):
    client, model = make_client([gate.step(text("first reply")), text("second reply")])
    cid, run_id = start(client, project_dir, "first")
    queued = client.post(f"/api/conversations/{cid}/messages", json={"content": "second"})
    assert queued.status_code == 201 and queued.json()["run"]["status"] == "queued"
    assert queued.json()["run"]["started_at"] is None
    gate.release()
    snap = wait_run(client, cid, queued.json()["run"]["id"])
    assert [r["status"] for r in snap["runs"]] == ["completed", "completed"]
    assert [m["content"] for m in snap["messages"]] == ["first", "first reply", "second", "second reply"]
    # the queued message does not leak into the running turn's model history
    assert [m["content"] for m in model.calls[0][1:]] == ["first"]
    assert [m["content"] for m in model.calls[1][1:]] == ["first", "first reply", "second"]


def test_cancelling_a_queued_run_removes_it_from_the_queue(make_client, wait_run, project_dir, gate):
    client, model = make_client([gate.step(text("only reply"))])
    cid, run_id = start(client, project_dir, "first")
    queued_id = client.post(f"/api/conversations/{cid}/messages", json={"content": "second"}).json()["run"]["id"]
    assert client.post(f"/api/runs/{queued_id}/cancel").status_code == 202
    gate.release()
    snap = wait_run(client, cid, run_id)
    assert {r["id"]: r["status"] for r in snap["runs"]} == {run_id: "completed", queued_id: "cancelled"}
    assert len(model.calls) == 1


def test_stopping_the_running_run_starts_the_next_queued_one(make_client, wait_run, project_dir, gate):
    client, _ = make_client([gate.step(text("never")), text("second reply")])
    cid, run_id = start(client, project_dir, "first")
    queued_id = client.post(f"/api/conversations/{cid}/messages", json={"content": "second"}).json()["run"]["id"]
    client.post(f"/api/runs/{run_id}/cancel")
    snap = wait_run(client, cid, queued_id)
    assert {r["id"]: r["status"] for r in snap["runs"]} == {run_id: "cancelled", queued_id: "completed"}


def test_cancel_marks_run_cancelled_and_keeps_partial_text(make_client, wait_run, project_dir, gate):
    client, _ = make_client([gate.step(text("never"), partial="Half an ans")])
    cid, run_id = start(client, project_dir)
    gate.wait_partial()
    assert client.post(f"/api/runs/{run_id}/cancel").status_code == 202
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "cancelled"
    assert (snap["messages"][-1]["content"], snap["messages"][-1]["status"]) == ("Half an ans", "complete")
    assert client.post(f"/api/runs/{run_id}/cancel").status_code == 409


def test_history_is_sent_on_the_next_turn(make_client, wait_run, project_dir):
    client, model = make_client([text("one"), text("two")])
    cid, run_id = start(client, project_dir, "first")
    wait_run(client, cid, run_id)
    second = client.post(f"/api/conversations/{cid}/messages", json={"content": "next"}).json()
    wait_run(client, cid, second["run"]["id"])
    assert [m["content"] for m in model.calls[1][1:]] == ["first", "one", "next"]


def test_empty_message_is_rejected(make_client, project_dir):
    client, _ = make_client([])
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    r = client.post(f"/api/conversations/{cid}/messages", json={"content": "   "})
    assert r.status_code == 422 and r.json()["detail"] == "message is empty"


def test_unknown_conversation_is_404(make_client):
    client, _ = make_client([])
    assert client.get("/api/conversations/nope").status_code == 404
    assert client.post("/api/conversations/nope/messages", json={"content": "x"}).status_code == 404
    assert client.post("/api/runs/nope/cancel").status_code == 404


def test_conversations_are_listed_newest_first_and_can_be_renamed(make_client, project_dir):
    client, _ = make_client([])
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    a = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    b = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    renamed = client.patch(f"/api/conversations/{a}", json={"title": "  Renamed  ", "permission_mode": "auto_edit"},
                           headers={"Origin": "http://127.0.0.1:8790"})
    assert (renamed.json()["title"], renamed.json()["permission_mode"]) == ("Renamed", "auto_edit")
    assert [c["id"] for c in client.get(f"/api/projects/{pid}/conversations").json()] == [a, b]
    assert client.patch(f"/api/conversations/{a}", json={"permission_mode": "yolo"}).status_code == 422


def test_sse_replays_only_events_after_the_cursor(make_client, wait_run, project_dir):
    client, _ = make_client([text("Hi")])
    cid, run_id = start(client, project_dir)
    snap = wait_run(client, cid, run_id)
    cursor = snap["last_event_id"]
    client.patch(f"/api/conversations/{cid}", json={"title": "Renamed"})
    with client.stream("GET", f"/api/conversations/{cid}/events?after={cursor}&once=1") as r:
        frames = [f for f in r.read().decode().split("\n\n") if f.strip() and not f.startswith(":")]
    assert len(frames) == 1
    assert "event: conversation.updated" in frames[0] and f"id: {cursor + 1}" in frames[0]
    assert json.loads(frames[0].split("data: ", 1)[1])["title"] == "Renamed"


def test_full_replay_tells_the_whole_story_in_order(make_client, wait_run, project_dir):
    client, _ = make_client([text("Hi")])
    cid, run_id = start(client, project_dir)
    wait_run(client, cid, run_id)
    with client.stream("GET", f"/api/conversations/{cid}/events?after=0&once=1") as r:
        types = [line[7:] for line in r.read().decode().splitlines() if line.startswith("event: ")]
    assert types[0] == "run.started" and types[-1] == "run.finished"
    assert types.index("message.created") < types.index("message.completed")
    assert "message.delta" not in types


def test_snapshot_includes_partial_streaming_message(make_client, project_dir, gate):
    client, _ = make_client([gate.step(text("unused"), partial="Hel")])
    cid, _run_id = start(client, project_dir)
    gate.wait_partial()
    snap = client.get(f"/api/conversations/{cid}").json()
    assert snap["messages"][-1]["status"] == "streaming"
    assert snap["messages"][-1]["content"] == "Hel"


def test_reconnecting_stream_starts_with_the_live_text_of_a_streaming_message(make_client, project_dir, gate):
    client, _ = make_client([gate.step(text("unused"), partial="Hel")])
    cid, _run_id = start(client, project_dir)
    gate.wait_partial()
    snap = client.get(f"/api/conversations/{cid}").json()
    with client.stream("GET", f"/api/conversations/{cid}/events?after={snap['last_event_id']}&once=1") as r:
        frames = [f for f in r.read().decode().split("\n\n") if f.startswith("event: message.sync")]
    assert len(frames) == 1 and "id:" not in frames[0]
    assert json.loads(frames[0].split("data: ", 1)[1]) == {
        "message_id": snap["messages"][-1]["id"], "content": "Hel"}
