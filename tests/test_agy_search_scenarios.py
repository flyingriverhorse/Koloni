"""Slice 20b's acceptance set: a web search through agy. Written before the code.

agy searched without being asked (11 Oct 2026, reads, no flag); its search tool's output is
not in the stream, so its answer is a result only when the stream shows that a search ran
and nothing else did. Two real streams are replayed (tests/agy_streams/searched*.jsonl);
the rest is the stand-in's own (tests/fake_agy_cli.py).
"""

import json
import sys
from pathlib import Path

import pytest

import app.model_agy

if not hasattr(app.model_agy, "AgySearch"):  # written before the code: skipped until it exists
    pytest.skip("slice 20b is not built yet", allow_module_level=True)

from app.model_agy import AgySearch  # noqa: E402

FAKE = [sys.executable, str(Path(__file__).with_name("fake_agy_cli.py"))]
STREAMS = Path(__file__).with_name("agy_streams")


@pytest.fixture
def agy(tmp_path):
    record, plan = tmp_path / "record.json", tmp_path / "plan.json"

    def make(model="gemini-3.8-flash-low", **plan_fields):
        plan.write_text(json.dumps({"record": str(record), **plan_fields}), encoding="utf-8")
        return AgySearch(None, model, timeout=20.0, launcher=FAKE,
                         env={"FAKE_AGY_PLAN": str(plan)})

    return make, lambda: json.loads(record.read_text(encoding="utf-8"))


def lines(answer):
    return "\n".join(json.dumps(event) for event in answer) + "\n"


def stream(tmp_path, *tools, answer='{"results": [{"title": "T", "url": "https://e.org/", '
                                    '"snippet": "s"}]}'):
    """A stream in the measured shape: each tool as (name, state), then the answer."""
    events = [{"event": "init", "init": {"model": "m", "cwd": "C:\\search", "tools": []}}]
    for at, (name, state) in enumerate(tools, 1):
        events.append({"event": "step_update", "step_update": {
            "step_index": at, "state": state, "step_type": "tool", "tool_name": name,
            "tool_info": {"name": name, "parameters": {}}}})
    events.append({"event": "result", "result": {"status": "SUCCESS", "response": answer,
                                                 "usage": {"input_tokens": 10,
                                                           "output_tokens": 2}}})
    path = tmp_path / f"stream-{len(list(tmp_path.iterdir()))}.jsonl"
    path.write_text(lines(events), encoding="utf-8")
    return str(path)


@pytest.mark.anyio
async def test_what_agy_found_with_a_search_is_the_result(agy):
    make, record = agy
    found = await make(replay=str(STREAMS / "searched.jsonl")).search("python release")
    assert found and found[0]["url"] == "https://www.python.org/downloads/source/"
    assert all(set(one) >= {"title", "url"} for one in found)
    argv = record()["argv"]
    assert "--dangerously-skip-permissions" not in argv       # reads: it can change nothing
    assert argv[-1] == "-p=" and argv[argv.index("--model") + 1] == "gemini-3.8-flash-low"
    assert argv[argv.index("--output-format") + 1] == "stream-json"
    assert "koloni-search-" in record()["cwd"]                # an empty folder of its own
    assert "python release" in record()["stdin"]


@pytest.mark.anyio
async def test_an_answer_that_is_no_list_is_no_result(agy):
    make, _record = agy
    assert await make(replay=str(STREAMS / "searched_no_json.jsonl")).search("q") is None


@pytest.mark.anyio
async def test_without_a_search_whatever_it_wrote_is_no_result(agy, tmp_path):
    make, _record = agy
    assert await make(replay=stream(tmp_path)).search("q") is None
    assert await make(replay=stream(tmp_path, ("search_web", "ERROR"))).search("q") is None
    assert await make(replay=stream(tmp_path, ("search_web", "ACTIVE"))).search("q") is None
    assert await make(replay=stream(tmp_path, ("search_web", "ACTIVE"), ("search_web", "DONE"))
                      ).search("q") == [{"title": "T", "url": "https://e.org/", "snippet": "s"}]


@pytest.mark.anyio
@pytest.mark.parametrize("other", ["view_file", "list_dir", "read_url_content",
                                   "open_browser_url", "run_command", "some_new_tool"])
async def test_a_search_beside_any_other_tool_is_no_result(agy, tmp_path, other):
    """What a file of this machine holds could come back as a "result"."""
    make, _record = agy
    replay = stream(tmp_path, ("search_web", "DONE"), (other, "DONE"))
    assert await make(replay=replay).search("q") is None


@pytest.mark.anyio
async def test_agy_is_among_the_clis_a_search_is_handed_to(settings_env):
    from app.config import load_settings
    from app.main import create_app
    from app.providers import search_clients
    from tests.keyed import TestClient

    app_ = create_app(load_settings(settings_env))
    with TestClient(app_, base_url="http://127.0.0.1:8790") as client:
        client.headers["Origin"] = "http://127.0.0.1:8790"
        made = client.post("/api/providers", json={
            "name": "agy", "kind": "agy_cli", "default_model": "gemini-3.8-flash-low"})
        assert made.status_code in (200, 201), made.text
        clients = search_clients(app_.state.session_factory)
    assert any(isinstance(one, AgySearch) for one in clients)
