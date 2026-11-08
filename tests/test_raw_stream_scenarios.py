"""Slice 25b's acceptance set: the raw stream of an agent's CLI. Written before the code.

Beside the tidy record there is what the CLI itself wrote, line by line, as it came: its
standard output and its error output, the events KOLONİ does not know among them. It is
kept in memory for as long as KOLONİ runs, up to a size; a secret KOLONİ knows is not in it;
and an agent whose model is not a CLI has none.
"""

import importlib.util
import json

import pytest

if importlib.util.find_spec("app.raw") is None:  # skipped until the code exists
    pytest.skip("slice 25b is not built yet", allow_module_level=True)

import app.raw  # noqa: E402, I001
from tests.test_agy_agent import agy_app, start  # noqa: E402, F401  (a fixture)
from tests.test_chat_flow import text  # noqa: E402

ORIGIN = "http://127.0.0.1:8790"
KEY = "sk-ant-SECRET-0123456789abcdef"
READS = {"tool": "view_file", "parameters": {"AbsolutePath": "hello.py"}, "output": "print('hi')"}


def raw_of(client, snap, **asked):
    lead = snap["agents"][0]
    answer = client.get(f"/api/agents/{lead['id']}/raw", params=asked)
    assert answer.status_code == 200, answer.text
    return answer.json()


def test_what_the_cli_wrote_is_there_line_by_line_with_what_koloni_does_not_know(
    agy_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _default = agy_app([
        {"say": "Let me look."}, READS, {"other": True}, {"say": "It prints hi."}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    told = raw_of(client, snap)
    assert told["available"] is True and told["dropped"] == 0
    lines = told["lines"]
    assert [line["n"] for line in lines] == list(range(1, len(lines) + 1))
    assert {line["stream"] for line in lines} <= {"stdout", "stderr"}
    events = [json.loads(line["text"]).get("event") for line in lines if line["stream"] == "stdout"]
    assert events[0] == "init" and events[-1] == "result" and "step_update" in events
    # what the tidy record passes over is here as it came
    assert "heartbeat" in events
    assert any('"planning"' in line["text"] for line in lines)
    # only what came after a line the page already has
    later = raw_of(client, snap, after=lines[2]["n"])["lines"]
    assert [line["n"] for line in later] == [line["n"] for line in lines[3:]]


def test_what_the_cli_wrote_to_its_error_output_is_there_too(agy_app, wait_run, project_dir):  # noqa: F811
    client, provider, _default = agy_app([{"exit": 3, "stderr": "boom: the disk is full"}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "failed"
    errors = [line["text"] for line in raw_of(client, snap)["lines"] if line["stream"] == "stderr"]
    assert any("boom: the disk is full" in line for line in errors)


def test_only_so_much_is_kept_and_the_newest_stays(agy_app, wait_run, project_dir,  # noqa: F811
                                                   monkeypatch):
    monkeypatch.setattr(app.raw, "MAX_BYTES", 3000)
    client, provider, _default = agy_app([READS] * 12 + [{"say": "done"}])
    cid, run_id = start(client, project_dir, provider)
    told = raw_of(client, wait_run(client, cid, run_id))
    assert told["dropped"] > 0
    assert sum(len(line["text"].encode()) for line in told["lines"]) <= 3000
    assert told["lines"][0]["n"] == told["dropped"] + 1      # the numbers go on, with a gap
    assert json.loads(told["lines"][-1]["text"])["event"] == "result"


def test_a_secret_koloni_knows_is_not_in_it(agy_app, wait_run, project_dir):  # noqa: F811
    client, provider, _default = agy_app([
        {"tool": "view_file", "parameters": {"AbsolutePath": ".env"},
         "output": f"ANTHROPIC_API_KEY={KEY}"},
        {"say": "read"}])
    client.headers["Origin"] = ORIGIN
    made = client.post("/api/providers", json={
        "name": "Paid", "kind": "anthropic", "api_key": KEY, "default_model": "claude-haiku-5-5"})
    assert made.status_code == 201, made.text
    cid, run_id = start(client, project_dir, provider)
    told = raw_of(client, wait_run(client, cid, run_id))
    written = json.dumps(told)
    assert KEY not in written and "***" in written
    assert any("ANTHROPIC_API_KEY=" in line["text"] for line in told["lines"])  # the rest stays


def test_an_agent_whose_model_is_no_cli_has_no_raw_stream(make_client, wait_run, project_dir):
    client, _model = make_client([text("hello")])
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    run_id = client.post(f"/api/conversations/{cid}/messages", json={"content": "hi"}).json()[
        "run"]["id"]
    told = raw_of(client, wait_run(client, cid, run_id))
    assert told["available"] is False and told["lines"] == []
    assert client.get("/api/agents/00000000000000000000000000000000/raw").status_code == 404
