"""Slice 21, beside its acceptance set (`test_usage_scenarios`): the tokens of a search the
API made, what a CLI that keeps its own loop reports, the prices' and the limit's own
checks, and what is not counted. No test touches the network."""

import asyncio
import json
from datetime import UTC, datetime, timedelta, timezone

import httpx2
import pytest
from sqlalchemy import select

import app.web
from app.api.usage import money
from app.db.models import Agent, Run
from tests.test_chat_flow import text
from tests.test_model_anthropic import client_for, found, hit, searched
from tests.test_native_agent import native_app  # noqa: F401  (a fixture)
from tests.test_session_agent import session_app, start  # noqa: F401  (a fixture)
from tests.test_spawn import call, role_id, spawn, step
from tests.test_usage_scenarios import began, looks, turn, usage
from tests.test_web_tool_scenarios import Net, search


def test_the_tokens_of_a_search_the_api_made_are_the_searching_agents(
    make_client, wait_run, project_dir, monkeypatch
):
    Net(monkeypatch, {"duckduckgo.com": (200, "text/html", "<html>none</html>")})
    answer = found(searched(hit("T", "https://example.org/")), usage={
        "input_tokens": 100, "cache_read_input_tokens": 20, "output_tokens": 30})
    api = client_for(lambda request: httpx2.Response(200, content=json.dumps(answer)))
    client, model, pid, cid = began(
        make_client, project_dir, [step(search(), i=5, o=2), text("done", 9, 3)])
    monkeypatch.setattr(app.web, "apis", lambda: [api])  # after the app, which sets its own
    run = turn(client, wait_run, cid)
    assert run["status"] == "completed"
    (row,) = usage(client, project_id=pid)["by_model"]
    # two steps of its own (5 and 9 sent, 2 and 3 written) and the search (120, 30) -
    # counted under the agent's own model, which is not the one that searched
    assert (row["model_id"], row["input_tokens"], row["output_tokens"]) == ("fake-model", 134, 35)
    (agent,) = client.get(f"/api/conversations/{cid}").json()["agents"]
    # the size of its conversation is its last step's, not the search's
    assert (agent["input_tokens"], agent["output_tokens"]) == (9, 35)
    assert run["output_tokens"] == 35


def test_a_search_that_found_nothing_was_paid_for_all_the_same(
    make_client, wait_run, project_dir, monkeypatch
):
    Net(monkeypatch, {"duckduckgo.com": (200, "text/html", "<html>none</html>")})
    answer = found(searched(), usage={"input_tokens": 50, "output_tokens": 4})
    api = client_for(lambda request: httpx2.Response(200, content=json.dumps(answer)))
    client, model, pid, cid = began(
        make_client, project_dir, [step(search(), i=5, o=2), text("done", 9, 3)])
    monkeypatch.setattr(app.web, "apis", lambda: [api])
    turn(client, wait_run, cid)
    (row,) = usage(client, project_id=pid)["by_model"]
    assert (row["input_tokens"], row["output_tokens"]) == (64, 9)


def test_a_cli_session_reports_once_and_is_counted_once_and_never_in_money(
    session_app, wait_run, project_dir  # noqa: F811
):
    client, provider, default = session_app([
        {"say": "Let me look."}, {"call": "read_file", "args": {"path": "hello.py"}},
        {"say": "It prints hi."}])
    client.headers["Origin"] = "http://127.0.0.1:8790"
    cid, run_id = start(client, project_dir, provider)
    assert wait_run(client, cid, run_id)["runs"][0]["status"] == "completed"
    (row,) = usage(client)["by_model"]
    # the stand-in CLI ends with 300 sent, 200 of them read from a cache, and 40 written
    assert (row["provider_name"], row["input_tokens"], row["output_tokens"]) == ("Session", 500, 40)
    assert row["unknown_agents"] == 0
    # a plan has no price for a token: a price for the model's name changes nothing here
    with client.app.state.session_factory() as session:
        named = session.scalars(select(Agent)).one().model_id
    price = {"model_id": named, "input": 3, "output": 15, "currency": "USD"}
    assert client.put("/api/prices", json=price).status_code == 200
    assert usage(client)["by_model"][0]["cost"] is None


def test_a_cli_is_not_started_in_a_turn_that_is_over_its_limit(
    session_app, wait_run, project_dir  # noqa: F811
):
    client, provider, default = session_app(
        [{"say": "Looks fine."}],
        default_steps=[spawn("Reviewer", "Review hello.py"), text("never said")])
    client.headers["Origin"] = "http://127.0.0.1:8790"
    client.patch(f"/api/roles/{role_id(client, 'Reviewer')}", json={"provider_id": provider["id"]})
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    assert client.patch(f"/api/projects/{pid}", json={"turn_token_limit": 6}).status_code == 200
    cid, run_id = start(client, project_dir, None)
    run = wait_run(client, cid, run_id)["runs"][0]
    # the lead's one step sent 5 and wrote 2
    assert run["status"] == "failed"
    assert run["error"] == "this turn used 7 tokens, over the project's limit of 6"
    with pytest.raises(FileNotFoundError):
        session_app.record()                      # the CLI was never run
    assert len(default.calls) == 1


def test_a_cli_that_waited_its_turn_is_held_to_what_the_one_before_it_reported(
    native_app, wait_run, project_dir, monkeypatch  # noqa: F811
):
    from app import copies
    from tests.test_native_agent import _roles_on
    from tests.test_native_agent import start as start_native

    # No copy can be made: both work in the project, one at a time (each in a copy of its
    # own they would work at once: B-199).
    monkeypatch.setattr(copies, "MAX_FILES", 0)
    client, provider, default = native_app(
        [{"pause": 0.5}, {"say": "Done."}],
        default_steps={"Lead": [step(
            call("spawn_agent", {"role": "Coder", "task": "A"}, "s1"),
            call("spawn_agent", {"role": "Coder", "task": "B"}, "s2"),
        ), text("never said")]})
    client.headers["Origin"] = "http://127.0.0.1:8790"
    _roles_on(client, provider, "Coder")
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    assert client.patch(f"/api/projects/{pid}", json={"turn_token_limit": 100}).status_code == 200
    cid, run_id = start_native(client, project_dir, None)
    snap = wait_run(client, cid, run_id, timeout=30)
    # the lead's step is 7; the first CLI ends with 4000 sent and 120 written, and the
    # second, which waited for it, is not started
    assert snap["runs"][0]["status"] == "failed"
    assert snap["runs"][0]["error"] == "this turn used 4127 tokens, over the project's limit of 100"
    assert sorted(a["output_tokens"] or 0 for a in snap["agents"]) == [0, 2, 120]


def test_a_turn_at_its_limit_goes_on_and_one_over_it_names_both_numbers(
    make_client, wait_run, project_dir
):
    steps = [looks(1, 5, 2), looks(2, 9, 1), text("said", 1, 1)]
    client, model, pid, cid = began(make_client, project_dir, list(steps), turn_token_limit=17)
    run = turn(client, wait_run, cid)                # 17 after two steps: not over
    assert (run["status"], len(model.calls)) == ("completed", 3)
    model.steps[:] = steps
    assert client.patch(f"/api/projects/{pid}", json={"turn_token_limit": 16}).status_code == 200
    run = turn(client, wait_run, cid)
    assert run["status"] == "failed"
    assert run["error"] == "this turn used 17 tokens, over the project's limit of 16"


def test_the_limit_is_the_users_to_set_and_to_take_away(make_client, project_dir):
    client, model, pid, cid = began(make_client, project_dir, [])
    assert client.get(f"/api/projects/{pid}").json()["turn_token_limit"] is None
    patch = lambda body, **more: client.patch(f"/api/projects/{pid}", json=body, **more)  # noqa: E731
    assert patch({"turn_token_limit": 5000}).json()["turn_token_limit"] == 5000
    # a command an agent runs against the app's address says no origin: it is not the user
    assert patch({"turn_token_limit": 9_000_000}, headers={"Origin": ""}).status_code == 403
    assert patch({"turn_token_limit": None}, headers={"Origin": ""}).status_code == 403
    for wrong in (-1, 0, 1.5, "many", 2**64, True, "50", 50.0):
        assert patch({"turn_token_limit": wrong}).status_code == 422, wrong
    assert client.get(f"/api/projects/{pid}").json()["turn_token_limit"] == 5000  # none got in
    assert patch({"docker_network": True}).json()["turn_token_limit"] == 5000  # left out: kept
    assert patch({"turn_token_limit": None}).json()["turn_token_limit"] is None


def test_a_price_is_a_number_that_is_not_negative_and_only_the_users_page_writes_one(
    make_client, project_dir
):
    client, model, pid, cid = began(make_client, project_dir, [])
    price = {"model_id": "m", "input": 0, "output": 2.5, "currency": "TL"}
    assert client.put("/api/prices", json=price).json() == [price]
    assert client.put("/api/prices", json={**price, "output": 4}).json() == [{**price, "output": 4}]
    assert client.get("/api/prices").json() == [{**price, "output": 4}]
    for wrong in ({"output": -0.01}, {"input": "cheap"}, {"currency": ""}, {"currency": "  "}, {"model_id": ""},
                  {"currency": "x" * 9},
                  # a number as such, and one a sum can still be made of
                  {"input": True}, {"output": "3"}, {"input": 1e308}, {"output": 1_000_000.01},
                  # a name that can be seen, a currency of letters, digits and currency signs
                  {"model_id": "   "}, {"model_id": "a\nb"}, {"model_id": "a\x07"},
                  {"model_id": "a‮b"}, {"model_id": "x" * 201},
                  {"currency": "U S D"}, {"currency": "US\n"}, {"currency": "a\x00"},
                  {"currency": "‮USD"}, {"currency": "<b>"}):
        assert client.put("/api/prices", json={**price, **wrong}).status_code == 422, wrong
    assert client.get("/api/prices").json() == [{**price, "output": 4}]
    # a name is kept without the spaces around it; a currency may be a sign
    most = {"model_id": "  n  ", "input": 1_000_000, "output": 0, "currency": "₺"}
    assert {**most, "model_id": "n"} in client.put("/api/prices", json=most).json()
    assert client.delete("/api/prices", params={"model_id": "n"}).json() == [{**price, "output": 4}]
    for number in ("Infinity", "NaN", "1e999"):
        body = json.dumps(price).replace("2.5", number)
        sent = client.put("/api/prices", content=body, headers={"Content-Type": "application/json"})
        assert sent.status_code == 422, number
    assert client.delete("/api/prices", params={"model_id": "m"},
                         headers={"Origin": ""}).status_code == 403
    assert client.delete("/api/prices", params={"model_id": "m"}).json() == []
    assert client.delete("/api/prices", params={"model_id": "m"}).json() == []   # gone already


def test_what_is_not_on_record_is_unknown_and_an_agent_never_started_is_not_counted(
    make_client, wait_run, project_dir
):
    client, model, pid, cid = began(make_client, project_dir, [text("a", 5, 3)])
    run = turn(client, wait_run, cid)
    with client.app.state.session_factory() as session:
        lead = session.scalars(select(Agent)).one()
        # an agent from before all it sent was kept: its last step's size and what it wrote
        session.add(Agent(run_id=run["id"], role_name="Old", tools=[], provider_name=lead.provider_name,
                          model_id="fake-model", input_tokens=900, output_tokens=10,
                          started_at=lead.started_at))
        # one that was proposed and never opened
        session.add(Agent(run_id=run["id"], role_name="Never", tools=[], status="rejected",
                          provider_name=lead.provider_name, model_id="fake-model"))
        session.commit()
    (row,) = usage(client, project_id=pid)["by_model"]
    assert (row["agents"], row["unknown_agents"]) == (2, 1)
    # nothing is made up from the size of the old agent's last step
    assert (row["input_tokens"], row["output_tokens"]) == (5, 13)


def test_a_cost_is_a_models_own_and_rows_come_most_spent_first(make_client, wait_run,
                                                                 project_dir):
    client, model, pid, cid = began(make_client, project_dir, [text("a", 2_000_000, 0)])
    run = turn(client, wait_run, cid)
    with client.app.state.session_factory() as session:
        lead = session.scalars(select(Agent)).one()
        session.add(Agent(run_id=run["id"], role_name="Other", tools=[], provider_name="Elsewhere",
                          model_id="big", input_tokens_total=3_000_000, output_tokens=1_000_000,
                          started_at=lead.started_at))
        session.add(Agent(run_id=run["id"], role_name="Silent", tools=[], provider_name="Quiet",
                          model_id="mute", started_at=lead.started_at))
        session.commit()
    for name, costs, currency in (("fake-model", 1.5, "USD"), ("big", 10, "TL"), ("mute", 1, "USD")):
        assert client.put("/api/prices", json={
            "model_id": name, "input": costs, "output": costs, "currency": currency}).status_code == 200
    told = usage(client, project_id=pid)
    assert [(row["model_id"], row["cost"]) for row in told["by_model"]] == [
        ("big", {"amount": 40.0, "currency": "TL"}),
        ("fake-model", {"amount": 3.0, "currency": "USD"}),
        ("mute", None),                              # a price, and nothing known to price
    ]
    # money is a model's row's, and a starter's its models' added up: never two currencies
    assert all("cost" not in row for row in told["by_conversation"])
    assert [row["cost"] for row in told["by_start"]] == [None]
    (talk,) = told["by_conversation"]
    assert (talk["runs"], talk["agents"], talk["input_tokens"], talk["unknown_agents"]) == (
        1, 3, 5_000_000, 1)


# --- the fixes after the review (design §10) ----------------------------------


def test_a_cost_is_rounded_and_over_an_unknown_agent_it_is_only_the_least(
    make_client, wait_run, project_dir
):
    client, model, pid, cid = began(make_client, project_dir, [text("a", 7, 3)])
    run = turn(client, wait_run, cid)
    assert client.put("/api/prices", json={
        "model_id": "fake-model", "input": 0.1, "output": 0.2, "currency": "USD"}).status_code == 200
    cost = lambda: usage(client, project_id=pid)["by_model"][0]["cost"]  # noqa: E731
    # 0.0000013 as it adds up: six places are kept, and a whole row says nothing more
    assert cost() == {"amount": 0.000001, "currency": "USD"}
    with client.app.state.session_factory() as session:
        lead = session.scalars(select(Agent)).one()
        session.add(Agent(run_id=run["id"], role_name="Old", tools=[], provider_name=lead.provider_name,
                          model_id="fake-model", output_tokens=10, started_at=lead.started_at))
        session.commit()
    # what the other sent is not known: the amount is what is known, and says it is the least
    assert cost() == {"amount": 0.000003, "currency": "USD", "at_least": True}


def test_a_period_that_no_calendar_holds_is_refused(make_client, project_dir):
    client, model, pid, cid = began(make_client, project_dir, [])
    for since in ("0001-01-01T00:00:00+05:00", "9999-12-31T23:59:59-05:00"):
        assert client.get("/api/usage", params={"since": since}).status_code == 422, since
    assert client.get("/api/usage", params={"since": "0001-01-01T00:00:00"}).status_code == 200


def test_a_period_goes_by_when_the_turn_began_whatever_zone_it_is_asked_in(
    make_client, wait_run, project_dir
):
    client, model, pid, cid = began(make_client, project_dir, [text("a", 5, 3)])
    run = turn(client, wait_run, cid)
    began_at = datetime.now(UTC) - timedelta(days=10)
    with client.app.state.session_factory() as session:
        # the turn, not its agent: the agent's own times stay today's
        session.get_one(Run, run["id"]).created_at = began_at
        session.commit()
    rows = lambda since: usage(client, project_id=pid, since=since.isoformat())["by_model"]  # noqa: E731
    assert rows(datetime.now(UTC) - timedelta(days=7)) == []
    assert len(rows(datetime.now(UTC) - timedelta(days=30))) == 1
    # one moment, said with no zone (it is UTC), in UTC, and east and west of it
    for zone in (None, UTC, timezone(timedelta(hours=5, minutes=30)), timezone(timedelta(hours=-8))):
        for hours, found_it in ((-1, 1), (1, 0)):
            at = began_at + timedelta(hours=hours)
            assert len(rows(at.astimezone(zone) if zone else at.replace(tzinfo=None))) == found_it, zone


def test_a_step_that_was_stopped_leaves_its_agent_unknown_whatever_it_reported_before(
    make_client, wait_run, project_dir, gate
):
    client, model, pid, cid = began(
        make_client, project_dir, [looks(1, 5, 2), gate.step(text("never"), partial="Half")])
    run_id = client.post(f"/api/conversations/{cid}/messages", json={"content": "go"}).json()[
        "run"]["id"]
    gate.wait_partial()
    assert client.post(f"/api/runs/{run_id}/cancel").status_code == 202
    assert wait_run(client, cid, run_id)["runs"][0]["status"] == "cancelled"
    (row,) = usage(client, project_id=pid)["by_model"]
    # its first step is counted; what the second had spent when Stop came, nobody said
    assert (row["input_tokens"], row["output_tokens"], row["unknown_agents"]) == (5, 2, 1)


def test_a_limit_that_cuts_work_in_flight_counts_what_it_had_said_and_says_at_least(
    make_client, wait_run, project_dir
):
    flying = []

    async def after_the_other_began(on_delta):
        while not flying:
            await asyncio.sleep(0.01)
        return looks(1, 50, 2)

    async def never_ends(on_delta):
        await asyncio.Event().wait()

    client, model, pid, cid = began(make_client, project_dir, {
        "Lead": [step(call("spawn_agent", {"role": "Reviewer", "task": "A"}, "s1"),
                      call("spawn_agent", {"role": "Coder", "task": "B"}, "s2"))],
        "Reviewer": [after_the_other_began, text("never said")],
        "Coder": [never_ends],
    }, turn_token_limit=20)
    plain = model.stream_step

    async def stream_step(model_id, messages, tools, on_delta, on_thinking=None, so_far=None):
        # As the Anthropic API does: what the step sent is said when its answer begins.
        if "Your name here is Coder" in str(messages[0]["content"]):
            so_far(40, None)
            flying.append(True)
        return await plain(model_id, messages, tools, on_delta, on_thinking)

    model.reports_early, model.stream_step = True, stream_step
    run = turn(client, wait_run, cid)
    # the lead's step is 7 and the reviewer's 52: over 20 before the reviewer's second. The
    # coder's step was cut by the stop; the 40 it had sent by then are in the sum
    assert run["status"] == "failed"
    assert run["error"] == "this turn used at least 99 tokens, over the project's limit of 20"
    (row,) = usage(client, project_id=pid)["by_model"]
    assert (row["agents"], row["input_tokens"], row["output_tokens"], row["unknown_agents"]) == (
        3, 95, 4, 1)


def test_a_cli_that_was_stopped_before_its_end_is_on_record_as_cut(
    session_app, wait_run, project_dir  # noqa: F811
):
    from tests.test_agent_writes import wait_status

    client, provider, default = session_app([
        {"say": "Working."}, {"call": "write_file", "args": {"path": "n.txt", "content": "x"}},
        {"hang": True}])
    cid, run_id = start(client, project_dir, provider, mode="ask")
    wait_status(client, cid, "waiting_approval")
    client.post(f"/api/runs/{run_id}/cancel")
    assert wait_run(client, cid, run_id)["runs"][0]["status"] == "cancelled"
    with client.app.state.session_factory() as session:
        assert session.scalars(select(Agent)).one().cut_short is True
    assert usage(client)["by_model"][0]["unknown_agents"] == 1


def test_a_tiny_amount_is_not_said_to_be_nothing():
    # (R116: a cost under half a cent read "0.00 USD")
    assert [money(x) for x in (0, 0.0031, 0.004999, 0.01, 10.5)] == ["0", "0.0031", "0.0050", "0.01", "10.50"]
