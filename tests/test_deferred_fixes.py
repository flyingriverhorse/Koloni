"""Slice 1 review findings that were deferred and settled at the start of slice 2."""

import asyncio
import time

import httpx2
import pytest

from app import agent
from app.agent import AgentRunner, recover_interrupted
from app.config import load_settings
from app.db.models import Agent, Conversation, FileChange, Message, Project, Run, ToolCall
from app.db.session import make_engine, make_session_factory, upgrade_db
from app.main import create_app
from app.model_client import ModelUnavailable, OpenAICompatClient, StepResult, ToolCallRequest
from app.workspace import sha256_text
from tests.fakes import ScriptedModel, sse_body
from tests.keyed import TestClient
from tests.test_chat_flow import start, text


async def _collect(client):
    async def on_delta(_):
        pass

    return await client.stream_step("m", [{"role": "user", "content": "hi"}], None, on_delta)


@pytest.mark.anyio
async def test_a_stalled_stream_fails_with_a_reason():
    class Stalling(httpx2.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"choices": [{"delta": {"content": "Hel"}}]}\n\n'
            await asyncio.sleep(30)

    def handler(request):
        return httpx2.Response(200, stream=Stalling())

    client = OpenAICompatClient(
        "http://model/v1", transport=httpx2.MockTransport(handler), stall_seconds=0.2
    )
    started = time.monotonic()
    with pytest.raises(ModelUnavailable, match="sent nothing for 0.2 seconds"):
        await _collect(client)
    assert time.monotonic() - started < 5


@pytest.mark.anyio
async def test_an_error_chunk_inside_the_stream_fails_the_step():
    def handler(request):
        return httpx2.Response(200, content=sse_body(
            {"choices": [{"delta": {"content": "par"}}]},
            {"error": {"message": "context size exceeded"}},
        ))

    client = OpenAICompatClient("http://model/v1", transport=httpx2.MockTransport(handler))
    with pytest.raises(ModelUnavailable, match="context size exceeded"):
        await _collect(client)


def test_shutdown_does_not_start_queued_runs(settings_env, project_dir, gate):
    model = ScriptedModel([gate.step(text("never")), text("must not run")])
    settings = load_settings(settings_env)
    client = TestClient(create_app(settings, model=model), base_url="http://127.0.0.1:8790")
    client.__enter__()
    cid, _run_id = start(client, project_dir, "first")
    client.post(f"/api/conversations/{cid}/messages", json={"content": "second"})
    client.__exit__(None, None, None)  # server shutdown with one run active and one queued

    assert len(model.calls) == 1
    with TestClient(
        create_app(settings, model=ScriptedModel([])), base_url="http://127.0.0.1:8790"
    ) as again:
        runs = again.get(f"/api/conversations/{cid}").json()["runs"]
    assert [r["status"] for r in runs] == ["interrupted", "interrupted"]


def _seed_proposed_change(tmp_path, written: bool):
    db = tmp_path / "r.db"
    upgrade_db(db)
    factory = make_session_factory(make_engine(db))
    root = tmp_path / "proj"
    root.mkdir()
    if written:
        (root / "f.txt").write_bytes(b"new\n")
    with factory() as s:
        s.add(Project(id="p", name="p", root_path=str(root)))
        s.flush()
        s.add(Conversation(id="c", project_id="p"))
        s.flush()
        s.add(Run(id="r", conversation_id="c", status="running"))
        s.flush()
        s.add(Agent(id="a", run_id="r", role_name="Lead", tools=[]))
        s.flush()
        s.add(Message(id="m", conversation_id="c", run_id="r", role="assistant"))
        s.flush()
        s.add(ToolCall(id="t", run_id="r", agent_id="a", message_id="m", seq=1, provider_call_id="t",
                       name="write_file", arguments="{}", status="running"))
        s.flush()
        s.add(FileChange(id="f", run_id="r", agent_id="a", tool_call_id="t", path="f.txt", kind="create",
                         after_content="new\n", after_sha=sha256_text("new\n"), status="proposed"))
        s.commit()
    return factory


def test_recovery_marks_a_change_applied_when_the_file_already_has_it(tmp_path):
    factory = _seed_proposed_change(tmp_path, written=True)
    recover_interrupted(factory)
    with factory() as s:
        change = s.get(FileChange, "f")
        assert change.status == "applied" and change.decided_at is not None


def test_recovery_rejects_a_change_whose_file_was_not_written(tmp_path):
    factory = _seed_proposed_change(tmp_path, written=False)
    recover_interrupted(factory)
    with factory() as s:
        assert s.get(FileChange, "f").status == "rejected"


def test_stop_lets_the_running_read_finish_and_records_its_result(
        make_client, wait_run, project_dir, monkeypatch):
    def slow_read(ws, name, args, *search):  # (a search's time limit and its stop: slice 36)
        time.sleep(0.3)
        return "slow result"

    monkeypatch.setattr(agent, "run_read_tool", slow_read)
    client, _ = make_client([StepResult("", [
        ToolCallRequest("a", "list_dir", "{}"), ToolCallRequest("b", "list_dir", "{}")], 1, 1)])
    cid, run_id = start(client, project_dir)
    time.sleep(0.1)
    client.post(f"/api/runs/{run_id}/cancel")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "cancelled"
    first, second = snap["tool_calls"]
    assert (first["status"], first["result"]) == ("succeeded", "slow result")
    assert second["status"] == "interrupted"


def test_a_failing_finish_does_not_strand_the_queue(
        make_client, wait_run, project_dir, gate, monkeypatch):
    real_finish = AgentRunner._finish
    calls = {"n": 0}

    def flaky_finish(self, run_id, cid, status, error):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("disk full")
        return real_finish(self, run_id, cid, status, error)

    monkeypatch.setattr(AgentRunner, "_finish", flaky_finish)
    client, _ = make_client([gate.step(text("first reply")), text("second reply")])
    cid, run_id = start(client, project_dir, "first")
    queued = client.post(f"/api/conversations/{cid}/messages", json={"content": "second"}).json()
    gate.release()
    snap = wait_run(client, cid, queued["run"]["id"])
    statuses = {r["id"]: r["status"] for r in snap["runs"]}
    assert statuses[run_id] == "failed" and statuses[queued["run"]["id"]] == "completed"
