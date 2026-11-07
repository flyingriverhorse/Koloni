"""Regression tests for defects found in the slice 1 whole-branch review."""

import json
from pathlib import Path

import pytest

from app.agent import TRIMMED_TAIL, _trim_to_budget
from app.main import asset_path
from app.model_client import StepResult, ToolCallRequest
from app.tools import ToolError, run_read_tool
from app.workspace import Workspace
from tests.test_chat_flow import start, start_in_mode, text


def call(name, args, id="c1"):
    return ToolCallRequest(id, name, json.dumps(args))


# C1 — a message removed from the queue must never reach the model


def test_a_message_removed_from_the_queue_is_not_sent_to_the_model(
        make_client, wait_run, project_dir, gate):
    client, model = make_client([gate.step(text("first reply")), text("you are welcome")])
    cid, run_id = start(client, project_dir, "first")
    queued = client.post(f"/api/conversations/{cid}/messages", json={"content": "DELETE THE TESTS"})
    client.post(f"/api/runs/{queued.json()['run']['id']}/cancel")
    gate.release()
    wait_run(client, cid, run_id)
    later = client.post(f"/api/conversations/{cid}/messages", json={"content": "thanks"}).json()
    wait_run(client, cid, later["run"]["id"])
    assert [m["content"] for m in model.calls[1][1:]] == ["first", "first reply", "thanks"]


# C2 — the static route must not touch paths outside the build folder


@pytest.mark.parametrize("requested", [
    "\\\\host\\share\\x", "//host/share/x", "C:\\Windows\\win.ini", "C:secret.txt",
    "/etc/passwd", "..\\secret.txt", "../secret.txt", "assets/../../secret.txt", "a.txt:stream",
])
def test_asset_path_refuses_anything_but_a_plain_relative_path(tmp_path, requested):
    (tmp_path / "assets").mkdir()
    assert asset_path(tmp_path, requested) is None


def test_asset_path_returns_existing_files_inside_the_build(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("1", encoding="utf-8")
    assert asset_path(tmp_path, "assets/app.js") == tmp_path / "assets" / "app.js"
    assert asset_path(tmp_path, "assets/missing.js") is None
    assert asset_path(tmp_path, "assets") is None
    assert asset_path(tmp_path, "") is None


# I1 — a file-system error is a tool result, not a crashed run


def test_writing_under_a_file_is_refused_before_any_change_is_recorded(
        make_client, wait_run, project_dir):
    client, model = make_client([
        StepResult("", [call("write_file", {"path": "hello.py/x.txt", "content": "x"})], 1, 1),
        text("ok")])
    cid, run_id = start_in_mode(client, project_dir, "auto_edit")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed"
    assert snap["tool_calls"][0]["status"] == "failed"
    assert "is a file, not a folder" in snap["tool_calls"][0]["result"]
    assert snap["file_changes"] == []


def test_a_write_the_disk_refuses_fails_the_change_and_tells_the_model(
        make_client, wait_run, project_dir, monkeypatch):
    def refuse(self, rel, content):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(Workspace, "_write_bytes", refuse)
    client, model = make_client([
        StepResult("", [call("write_file", {"path": "locked.txt", "content": "x"})], 1, 1),
        text("I could not write it.")])
    cid, run_id = start(client, project_dir)
    change = None
    for _ in range(200):
        snap = client.get(f"/api/conversations/{cid}").json()
        if snap["file_changes"]:
            change = snap["file_changes"][0]
            break
    assert change is not None
    decided = client.post(f"/api/file-changes/{change['id']}/approve").json()
    assert decided["status"] == "failed"
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed"
    assert snap["tool_calls"][0]["status"] == "failed"
    assert model.calls[1][-1]["content"].startswith("error: could not write locked.txt")
    assert "Permission denied" in model.calls[1][-1]["content"]


def test_a_read_the_disk_refuses_is_a_tool_error(tmp_path, monkeypatch):
    (tmp_path / "a.txt").write_bytes(b"x")

    def refuse(self, *how):
        raise PermissionError(13, "Permission denied")

    # (read_file opens the file and reads it line by line since slice 36)
    monkeypatch.setattr(Path, "open", refuse)
    with pytest.raises(ToolError, match="could not read 'a.txt': Permission denied"):
        run_read_tool(Workspace(tmp_path), "read_file", {"path": "a.txt"})


# I2 — one enormous line must not blow the read cap or the context budget


def test_read_file_truncates_a_single_enormous_line(tmp_path):
    (tmp_path / "min.js").write_bytes(b"x" * 3_000_000)
    out = run_read_tool(Workspace(tmp_path), "read_file", {"path": "min.js"})
    assert len(out) < 10_000
    assert "[line truncated: 3000000 characters]" in out


def test_the_newest_tool_result_is_cut_when_it_alone_exceeds_the_budget():
    messages = [
        {"role": "system", "content": "s" * 100},
        {"role": "user", "content": "u" * 100},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "a", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "a", "content": "r" * 5000},
    ]
    _trim_to_budget(messages, 1000)
    newest = messages[-1]["content"]
    assert newest.endswith(TRIMMED_TAIL) and newest.startswith("rrr")
    assert sum(len(m["content"]) for m in messages) <= 1000


# I3 — a reconnect with an old cursor must end up with the live text


def test_live_text_is_synced_after_the_replay_not_before(make_client, project_dir, gate):
    client, _ = make_client([gate.step(text("unused"), partial="Hel")])
    cid, _run_id = start(client, project_dir)
    gate.wait_partial()
    with client.stream("GET", f"/api/conversations/{cid}/events?after=0&once=1") as r:
        types = [line[7:] for line in r.read().decode().splitlines() if line.startswith("event: ")]
    assert "message.created" in types
    assert types.index("message.sync") > max(i for i, t in enumerate(types) if t == "message.created")


# I6 — only loopback host names are served


def test_requests_for_another_host_name_are_refused(client):
    assert client.get("/api/projects", headers={"Host": "evil.example"}).status_code == 400
    assert client.get("/api/projects", headers={"Host": "localhost:8790"}).status_code == 200
    assert client.get("/api/projects").status_code == 200
