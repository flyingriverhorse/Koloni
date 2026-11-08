"""agy asked to search, after the review of slice 20b: it cannot be held to its search tool,
so a stream is judged strictly - only the steps known to be no tool pass beside the search
- and the run is stopped at the first step that is anything else. Everything here is the
stand-in's (tests/fake_agy_cli.py) or a replayed stream; the real CLI is not run.
"""

import json
import time
from pathlib import Path

import pytest

import app.web
from app import model_cli
from app.model_agy import AgySearch
from app.model_cli import SEARCH_PROMPT
from tests.test_agy_search_scenarios import STREAMS, agy, lines  # noqa: F401  (a fixture)
from tests.test_chat_flow import text
from tests.test_spawn import step
from tests.test_web_tool_scenarios import ORIGIN, Net, go, results, search, setup

CLI_SEARCH = app.web.cli_search

FOUND = '{"results": [{"title": "T", "url": "https://e.org/", "snippet": "s"}]}'
SEARCH = {"event": "step_update", "step_update": {
    "step_index": 1, "state": "DONE", "step_type": "tool", "tool_name": "search_web",
    "tool_info": {"name": "search_web", "parameters": {"query": "q"}}}}


def replayed(tmp_path, *events, status="SUCCESS", answer=FOUND):
    path = tmp_path / f"stream-{len(list(tmp_path.glob('stream-*')))}.jsonl"
    path.write_text(lines([
        {"event": "init", "init": {"model": "m", "tools": []}}, *events,
        {"event": "result", "result": {"status": status, "response": answer}}]),
        encoding="utf-8")
    return str(path)


def agy_step(**fields):
    return {"event": "step_update", "step_update": {"step_index": 2, "state": "DONE", **fields}}


@pytest.mark.anyio
@pytest.mark.parametrize("other", [
    agy_step(step_type="browser_subagent"),
    agy_step(step_type="invoke_subagent", tool_info={"name": "invoke_subagent"}),
    agy_step(step_type="planning"),                               # a step type nobody knows
    agy_step(step_type="agent_response", tool_info={"name": "view_file"}),  # told only there
    agy_step(step_type="agent_response", tool_name="read_url_content"),
    {"event": "tool_call", "tool_call": {"name": "view_file"}},   # a tool under another event
    {"event": "heartbeat", "heartbeat": {"n": 1}},                # any event nobody knows
], ids=["browser_subagent", "invoke_subagent", "unknown_step", "tool_info_only",
        "tool_name_on_an_answer", "other_event", "heartbeat"])
async def test_beside_a_search_anything_not_known_to_be_no_tool_is_no_result(
    agy, tmp_path, other  # noqa: F811
):
    make, _record = agy
    assert await make(replay=replayed(tmp_path, SEARCH)).search("q")   # alone it is one
    assert await make(replay=replayed(tmp_path, SEARCH, other)).search("q") is None


@pytest.mark.anyio
async def test_the_search_is_stopped_at_the_first_step_that_is_no_search(agy):  # noqa: F811
    """Not waited on for its answer: whatever that step does is cut short."""
    make, _record = agy
    started = time.monotonic()
    said = await make(script=[{"tool": "view_file", "never_ends": True}, {"hang": True}]
                      ).search("q")
    assert said is None and time.monotonic() - started < 10  # its limit here is 20 s


@pytest.mark.anyio
async def test_what_it_is_asked_on_stdin_is_one_json_line_in_the_measured_shape(
    agy  # noqa: F811
):
    make, record = agy
    await make(replay=str(STREAMS / "searched.jsonl")).search("python release")
    stdin = record()["stdin"]
    assert stdin.endswith("\n") and stdin.count("\n") == 1
    assert json.loads(stdin) == {"event": "user", "message": {
        "role": "user", "content": SEARCH_PROMPT + "python release"}}


@pytest.mark.anyio
async def test_an_answer_of_a_run_that_ended_in_an_error_is_no_result(
    agy, tmp_path  # noqa: F811
):
    make, _record = agy
    assert await make(replay=replayed(tmp_path, SEARCH, status="ERROR")).search("q") is None


class Stand:
    """A CLI asked to search, as `app.web.searchers` lists it."""

    def __init__(self, name, held=True):
        self.name, self.held_to_search = name, held

    async def search(self, query):
        asked.append(self.name)
        return [{"title": self.name, "url": f"https://{self.name}.org/", "snippet": ""}]


asked: list[str] = []


@pytest.mark.anyio
async def test_agy_is_asked_to_search_only_where_the_project_lets_it(monkeypatch):
    asked.clear()
    monkeypatch.setattr(app.web, "searchers", lambda: [Stand("agy", held=False), Stand("codex")])
    assert (await app.web.cli_search("q"))[0]["title"] == "codex" and asked == ["codex"]
    assert (await app.web.cli_search("q", agy=True))[0]["title"] == "agy"
    # and the whole search, as an agent's tool makes it
    monkeypatch.setattr(app.web, "_duckduckgo", lambda query: _none())
    assert "agy.org" not in await app.web.search("q", None, "cli")
    assert "agy.org" in await app.web.search("q", None, "cli", agy=True)
    # it is an AgySearch that is passed over: the one `search_clients` gives
    assert AgySearch.held_to_search is False


async def _none():
    return None


def test_a_project_lets_agy_search_only_from_the_apps_own_page(client, project_dir):
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    assert client.get("/api/projects").json()[0]["search_agy"] is False
    assert client.patch(f"/api/projects/{pid}", json={"search_agy": True}).status_code == 403
    client.headers["Origin"] = ORIGIN
    assert client.patch(f"/api/projects/{pid}", json={"search_agy": True}).json()["search_agy"]
    assert client.patch(f"/api/projects/{pid}", json={"docker_network": True}).json()["search_agy"]


@pytest.mark.parametrize("allowed", [False, True])
def test_an_agents_search_hands_agy_the_query_only_where_its_project_lets_it(
    make_client, wait_run, project_dir, monkeypatch, allowed
):
    asked.clear()
    Net(monkeypatch, {"duckduckgo.com": (202, "text/html", "<html>are you a robot</html>")})
    monkeypatch.setattr(app.web, "cli_search", CLI_SEARCH)  # the real one, not the stand-in
    client, _model, _pid, cid = setup(make_client, project_dir, [step(search()), text("done")],
                                      project={"search_order": "cli", "search_agy": allowed})
    # (after the app is made: it sets its own)
    monkeypatch.setattr(app.web, "searchers", lambda: [Stand("agy", held=False)])
    snap = wait_run(client, cid, go(client, cid)["id"])
    ((status, said),) = results(snap, "web_search")
    assert asked == (["agy"] if allowed else [])
    assert (status == "succeeded" and "https://agy.org/" in said) is allowed


@pytest.mark.anyio
async def test_a_search_folder_that_cannot_be_removed_at_once_is_tried_again_and_then_left(
    agy, tmp_path, monkeypatch  # noqa: F811
):
    """A child of the CLI may hold it a moment after the CLI is gone; nothing waits long."""
    make, record = agy
    real, tries = model_cli.shutil.rmtree, []

    def rmtree(path, ignore_errors=False):
        tries.append(path)
        if len(tries) < 3:
            return None  # still held: left there, as ignore_errors does
        return real(path, ignore_errors=ignore_errors)

    monkeypatch.setattr(model_cli.shutil, "rmtree", rmtree)
    assert await make(replay=replayed(tmp_path, SEARCH)).search("q")
    folder = record()["cwd"]
    assert len(tries) == 3 and set(map(str, tries)) == {folder}
    assert not Path(folder).exists()
    tries.clear()
    monkeypatch.setattr(model_cli.shutil, "rmtree",
                        lambda path, ignore_errors=False: tries.append(path))
    started = time.monotonic()
    try:
        assert await make(replay=replayed(tmp_path, SEARCH)).search("q")  # never removed: left
        assert len(tries) == model_cli.SEARCH_REMOVE_TRIES and time.monotonic() - started < 5
    finally:
        real(record()["cwd"], ignore_errors=True)
