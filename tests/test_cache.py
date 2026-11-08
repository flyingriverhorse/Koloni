"""Slice 34, beside its acceptance set (`test_cache_scenarios`): what each CLI says of its
cache, a step that was cut short, a question KOLONİ asked itself, a count that cannot be, and
the migration.

The CLIs are the stand-ins the other tests use; what they report of a cache is what the real
ones were measured to (Claude Code, agy) or what their stand-ins already carried (Codex).
"""

import asyncio
import dataclasses
import sqlite3
import threading

import pytest
from alembic import command

from app.api.usage import _cost, _Sum
from app.db.models import Price
from app.model_cli import ClaudeCliClient, CodexCliClient
from tests.test_agy_agent import STREAMS, agy_app, translator  # noqa: F401  (a fixture)
from tests.test_agy_agent import result as agy_result
from tests.test_agy_agent import start as start_agy
from tests.test_chat_flow import text
from tests.test_claude_native import claude_app  # noqa: F401  (a fixture)
from tests.test_claude_native import start as start_claude
from tests.test_migration_0002 import _config
from tests.test_model_cli import cli, step  # noqa: F401  (a fixture)
from tests.test_native_agent import native_app  # noqa: F401  (a fixture)
from tests.test_native_agent import start as start_codex
from tests.test_session_agent import session_app  # noqa: F401  (a fixture)
from tests.test_session_agent import start as start_session
from tests.test_spawn import begin
from tests.test_team import team  # noqa: F401  (a fixture)
from tests.test_tier_scenarios import tiered
from tests.test_usage_scenarios import began, usage


def cache_of(snap):
    lead = snap["agents"][0]
    return lead["input_tokens"], lead["cache_read_tokens"], lead["cache_write_tokens"]


# --- the CLIs ----------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_a_cli_run_step_by_step_says_what_it_read_again(cli):  # noqa: F811
    make, _record = cli

    async def told(kind, **plan):
        result, _said = await step(make(kind, **plan))
        return result.input_tokens, result.cache_read, result.cache_write

    # Claude Code: both, from the usage block its tokens are counted from
    assert await told(ClaudeCliClient) == (100, 60, 0)
    # ... also where its message was cut at a tool it called as its own
    assert await told(ClaudeCliClient, mode="native") == (55, 5, None)
    # Codex: what of its input was cached; of what it wrote there it says nothing
    assert await told(CodexCliClient) == (900, 100, None)
    for kind in (ClaudeCliClient, CodexCliClient):
        assert await told(kind, usage=False) == (None, None, None)       # not said: not known


def test_claude_code_as_a_session_says_what_it_read_again(
    session_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _default = session_app([{"say": "It prints hi."}])
    snap = wait_run(client, *start_session(client, project_dir, provider))
    assert cache_of(snap) == (500, 200, None)


def test_zeros_from_a_cli_that_does_not_count_are_no_count_of_its_cache_either(
    session_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _default = session_app([{"say": "It prints hi."}], usage={
        "input_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
        "output_tokens": 0})
    snap = wait_run(client, *start_session(client, project_dir, provider))
    assert cache_of(snap) == (None, None, None)


def test_claude_code_with_its_own_tools_says_what_it_read_again(
    claude_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _default = claude_app([{"say": "It prints hi."}])
    snap = wait_run(client, *start_claude(client, project_dir, provider, "full_auto"))
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert cache_of(snap) == (500, 100, None)


def test_codex_with_its_own_tools_says_what_of_its_input_was_cached(
    native_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _default = native_app([{"say": "It prints hi."}])
    snap = wait_run(client, *start_codex(client, project_dir, provider))
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert cache_of(snap) == (4000, 3000, None)


def test_agy_is_believed_for_what_it_says_it_read_from_its_cache(
    agy_app, wait_run, project_dir  # noqa: F811
):
    done = translator()(agy_result(response="hi", usage={
        "input_tokens": 2100, "output_tokens": 45, "cache_read_tokens": 700}))[-1]
    assert done["usage"]["cached_input_tokens"] == 700
    # the stream kept from the real CLI says none: a zero it said, not one made up
    client, provider, _default = agy_app([], replay=str(STREAMS / "reads_a_file.jsonl"))
    snap = wait_run(client, *start_agy(client, project_dir, provider))
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert cache_of(snap) == (25911, 0, None)


# --- the record --------------------------------------------------------------------------------


def test_a_step_cut_short_keeps_what_the_api_had_said_of_its_cache(
    make_client, wait_run, project_dir
):
    async def never_ends(on_delta):
        await asyncio.Event().wait()

    client, model, _pid, cid = began(make_client, project_dir, [never_ends])
    plain, flying = model.stream_step, threading.Event()

    async def stream_step(model_id, messages, tools, on_delta, on_thinking=None, so_far=None):
        # As the Anthropic API does: said when its answer begins.
        so_far(40, None, 30, 5)
        flying.set()
        return await plain(model_id, messages, tools, on_delta, on_thinking)

    model.reports_early, model.stream_step = True, stream_step
    run_id = client.post(f"/api/conversations/{cid}/messages", json={"content": "go"}).json()[
        "run"]["id"]
    assert flying.wait(5)
    client.post(f"/api/runs/{run_id}/cancel")
    assert cache_of(wait_run(client, cid, run_id)) == (40, 30, 5)


def test_what_a_question_of_kolonis_own_read_again_is_counted_where_it_was_asked(
    team, wait_run, project_dir  # noqa: F811
):
    asked = dataclasses.replace(text("hard: it needs a look", 9, 2), cache_read=7, cache_write=3)
    client, _default, _fast = team([text("the lead answers", 5, 1)], [asked])
    tiered(team, client)
    cid, run_id = begin(client, project_dir, mode="full_auto", lead_auto=True)
    assert wait_run(client, cid, run_id)["runs"][0]["status"] == "completed"
    rows = {row["provider_name"]: row for row in usage(client)["by_model"]}
    assert (rows["Fast"]["cache_read_tokens"], rows["Fast"]["cache_write_tokens"]) == (7, 3)
    lead = next(row for name, row in rows.items() if name != "Fast")
    assert lead["cache_read_tokens"] is None and lead["cache_write_tokens"] is None


# --- money -------------------------------------------------------------------------------------


def test_a_cache_count_larger_than_what_was_sent_never_makes_an_amount_smaller():
    one = _Sum()
    one.add("r", 100, 0, False, False, 500, None)      # a provider that says what cannot be
    price = Price(model_id="m", input=4, output=20, currency="USD", cache_read=2)
    assert _cost(one, price) == {"amount": 0.001, "currency": "USD"}      # 500 at 2, and no less


# --- the migration -----------------------------------------------------------------------------


def columns(conn, table):
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def test_the_cache_columns_are_added_and_taken_away_again(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0040")
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO prices (model_id, input, output, currency) VALUES ('m', 3, 15, 'USD')")
    command.upgrade(cfg, "head")
    with sqlite3.connect(db) as conn:
        # a price from before has none for the cache: not known, not a zero
        assert conn.execute("SELECT input, cache_read, cache_write FROM prices").fetchall() == [
            (3.0, None, None)]
        for table in ("agents", "own_requests"):
            assert {"cache_read_tokens", "cache_write_tokens"} <= columns(conn, table)
    command.downgrade(cfg, "0040")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT model_id, input, output FROM prices").fetchall() == [
            ("m", 3.0, 15.0)]
        for table in ("agents", "own_requests", "prices"):
            assert not {name for name in columns(conn, table) if name.startswith("cache_")}


# --- what is sent with one step only --------------------------------------------------------


@pytest.mark.anyio
async def test_what_is_sent_with_one_step_only_is_never_marked_but_what_is_before_it():
    from app.model_client import Transient
    from tests.test_cache_scenarios import MARK, marked, sent
    from tests.test_model_anthropic import HISTORY

    told = [*HISTORY, Transient(role="user", content="How the room stands now: ...")]
    body, _result = await sent(told, cache=True)
    assert body["messages"][-1] == {"role": "user", "content": "How the room stands now: ..."}
    assert body["messages"][-2]["content"] == [{"type": "text", "text": "go on", "cache_control": MARK}]
    assert len(marked(body)) == 2
    # two of them, after results of tools: the last result carries the mark
    told = [*HISTORY[:5], Transient(role="user", content="a"), Transient(role="user", content="b")]
    body, _result = await sent(told, cache=True)
    assert body["messages"][-3]["content"][-1]["cache_control"] == MARK
    assert len(marked(body)) == 2
    # without the cache it is sent as any message is
    plain, _result = await sent(told)
    assert plain["messages"][-2:] == [{"role": "user", "content": "a"}, {"role": "user", "content": "b"}]


def test_a_room_members_mark_is_on_what_its_next_step_sends_again(
    make_client, wait_run, project_dir, monkeypatch
):
    from app.model_client import Transient
    from tests.fakes import ScriptedModel
    from tests.test_cache_scenarios import marked, sent, unmarked
    from tests.test_room_scenarios import LONG, add, finish, start, take
    from tests.test_spawn import call, step

    plain, coder = ScriptedModel.stream_step, []

    async def stream_step(self, model_id, messages, tools, on_delta, on_thinking=None, **more):
        if "Your name here is Coder" in str(messages[0]["content"]):
            coder.append((list(messages), tools))      # the messages themselves, as sent
        return await plain(self, model_id, messages, tools, on_delta, on_thinking)

    # (before the room opens: its first steps are taken while `start` returns)
    monkeypatch.setattr(ScriptedModel, "stream_step", stream_step)
    client, _model, cid, run_id, _room = start(make_client, project_dir, {
        "Coder": [step(add("Change the greeting", ["hello.py"], "a1"), take(1, "t1")),
                  step(call("read_file", {"path": "hello.py"}, "r1")),
                  step(finish(1, "read it", "f1")),
                  text("My part is done.")],
        "Reviewer": [step(add("Review", id="a2"), take(2, "t2")),
                     step(finish(2, "fine", "f2")),
                     text("Looked at it.")],
    })
    assert wait_run(client, cid, run_id, timeout=LONG)["runs"][0]["status"] == "completed"
    assert len(coder) >= 3
    bodies = [asyncio.run(sent(messages, tools, cache=True))[0] for messages, tools in coder]
    for (messages, _tools), body in zip(coder, bodies, strict=True):
        # how the room stands is told at the end of every step, and with that step only
        assert isinstance(messages[-1], Transient) and "cache_control" not in str(
            body["messages"][-1])
        assert len(marked(body)) == 2
    # what was marked is what the next step begins with (the first two steps: what the room
    # says to a member later is placed again at each step, which this does not pin)
    first, after = bodies[0], bodies[1]
    upto = next(at for at, m in enumerate(first["messages"]) if "cache_control" in str(m))
    assert upto == len(first["messages"]) - 2
    assert unmarked(after)["messages"][:upto + 1] == unmarked(first)["messages"][:upto + 1]


def test_a_bool_is_never_counted_as_a_token():
    from app.model_cli import _input_tokens
    from app.model_native import ClaudeNativeClient

    assert _input_tokens({"input_tokens": 5, "cache_read_input_tokens": True}) == 5
    assert _input_tokens({"input_tokens": True}) is None
    (done,) = ClaudeNativeClient()._translator()({"type": "result", "usage": {
        "input_tokens": 5, "cache_creation_input_tokens": True, "output_tokens": 2}})
    assert done["usage"]["input_tokens"] == 5 and done["usage"]["cache_creation_input_tokens"] is None
