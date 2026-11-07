"""Slice 81c, after review: a provider's limit holds wherever its provider would spend - a
sub-agent and a room's member, each side of a comparison, the model asked for the day's
words, a trigger's turn - and is read once a request; a limit in dollars is not kept against
prices in another currency; a Lead moved by a limit says why from the start."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.api import usage
from app.db.models import Agent, Conversation
from app.room import member_model
from tests.test_agents_teams_scenarios import patch_role, spawn
from tests.test_budget_scenarios import PRICE
from tests.test_chat_flow import text
from tests.test_day_note import MIDNIGHT, words
from tests.test_spawn import step
from tests.test_team import results, team  # noqa: F401  (a fixture)
from tests.test_tier_order_scenarios import both_strongest
from tests.test_tier_scenarios import ORIGIN, role_tier, tiered
from tests.test_trigger_scenarios import one, tick, trigger
from tests.test_usage_scenarios import began, turn


def local(client):
    return client.get("/api/providers").json()[0]


def past(make_client, wait_run, project_dir, steps=()):
    """Local, the Lead's provider, past its day's limit: 10.50 USD spent of 5."""
    client, model, pid, cid = began(make_client, project_dir, [text("a", 1_000_000, 500_000), *steps])
    run = turn(client, wait_run, cid)
    client.put("/api/prices", json=PRICE)
    assert client.patch(f"/api/providers/{local(client)['id']}", json={"day_limit": 5}).status_code == 200
    return client, model, pid, cid, run


def other(client, run, name="Other", model="other-model", **more):
    """Another provider, on which 10.50 USD was spent today in `run`, with a limit of 5."""
    made = client.post("/api/providers", json={
        "name": name, "kind": "openai_compat", "base_url": "http://127.0.0.1:9/v1",
        "default_model": model, **more}).json()
    with client.app.state.session_factory() as session:
        lead = session.scalars(select(Agent)).first()
        session.add(Agent(run_id=run["id"], role_name="Other", tools=[], provider_name=name,
                          model_id=model, input_tokens_total=1_000_000, output_tokens=500_000,
                          started_at=lead.started_at))
        session.commit()
    client.put("/api/prices", json={**PRICE, "model_id": model})
    assert client.patch(f"/api/providers/{made['id']}", json={"day_limit": 5}).status_code == 200
    return made


def test_no_sub_agent_opens_past_its_providers_limit(team, wait_run, project_dir):  # noqa: F811
    client, _default, _fast = team([
        text("a", 1_000_000, 500_000), step(spawn("Reviewer")), step(spawn("Tester", id="s2")),
        text("done")])
    local_id = tiered(team, client)[0]["id"]  # strongest: Local big-model alone
    role_tier(client, "Reviewer", "strongest")
    assert patch_role(client, "Tester", provider_id=local_id, model_id="big-model").status_code == 200
    cid = client.post(f"/api/projects/{client.post('/api/projects', json={'root_path': str(project_dir)}).json()['id']}/conversations").json()["id"]
    first = client.post(f"/api/conversations/{cid}/messages", json={"content": "go"}).json()
    wait_run(client, cid, first["run"]["id"])
    client.put("/api/prices", json={**PRICE, "model_id": "big-model"})
    assert client.patch(f"/api/providers/{local_id}", json={"day_limit": 5}).status_code == 200
    went = client.post(f"/api/conversations/{cid}/messages",
                       json={"content": "check it", "over_budget": True}).json()
    snap = wait_run(client, cid, went["run"]["id"])
    # Every strongest model past its limit, so the conversation's (Local); the role's own (Local).
    assert [status for status, _said in results(snap)] == ["failed", "failed"]
    assert all("over Local's limit of 5.00 USD a day" in said for _status, said in results(snap))
    assert {agent["role_name"] for agent in snap["agents"]} == {"Lead"}


def test_a_comparison_holds_each_side_to_its_providers_limit(make_client, wait_run, project_dir):
    client, _model, _pid, cid = began(make_client, project_dir, [text("a", 10, 10), text("b")])
    run = turn(client, wait_run, cid)
    beside = other(client, run)
    body = {"content": "x", "sides": [{"provider_id": local(client)["id"]}, {"provider_id": beside["id"]}]}
    refused = client.post(f"/api/conversations/{cid}/compare", json=body)
    assert refused.status_code == 409 and "over Other's limit" in refused.json()["detail"]
    # The Lead's own provider is under its limit: a message goes on.
    assert client.post(f"/api/conversations/{cid}/messages", json={"content": "more"}).status_code == 201


def test_the_days_words_hold_the_model_asked_to_its_limit(make_client, wait_run, project_dir):
    client, _model, pid, cid = began(make_client, project_dir, [text("a", 10, 10), text("A day.")])
    run = turn(client, wait_run, cid)
    # The first fast model the Lead may pick is asked for the words, not the Lead's.
    other(client, run, "Quick", "quick-model", for_agents=True,
          models=[{"name": "quick-model", "tier": "fast"}])
    refused = words(client, pid, cid)
    assert refused.status_code == 409 and "over Quick's limit" in refused.json()["detail"]
    going = client.post(f"/api/projects/{pid}/day/words", json={
        "since": MIDNIGHT.isoformat(), "conversation_id": cid, "over_budget": True})
    assert going.status_code == 200, going.text


def test_a_trigger_past_its_leads_limit_starts_nothing_and_says_so(make_client, wait_run, project_dir):
    client, _model, pid, cid, _run = past(make_client, wait_run, project_dir, [text("b", 1, 1)])
    made = trigger(client, pid, cid)
    assert tick(client, datetime.now(UTC) + timedelta(hours=2)) == []
    seen = one(client, made["id"])["runs"][0]
    assert seen["outcome"] == "skipped_limit" and "over Local's limit" in seen["note"]
    refused = client.post(f"/api/triggers/{made['id']}/run")
    assert refused.status_code == 409 and "over its limit" in refused.text


def test_going_on_past_a_providers_limit_is_the_users_word(make_client, wait_run, project_dir):
    client, _model, _pid, cid, _run = past(make_client, wait_run, project_dir, [text("b", 1, 1)])
    del client.headers["Origin"]
    going = client.post(f"/api/conversations/{cid}/messages", json={"content": "more", "over_budget": True})
    assert going.status_code == 403


def test_a_requests_limits_read_the_record_once(team, monkeypatch):  # noqa: F811
    client, _default, _fast = team([], [])
    local_id, fast = both_strongest(team, client)
    for provider in (local_id, fast):
        assert client.patch(f"/api/providers/{provider}", json={"day_limit": 5}).status_code == 200
    read = []
    sums = usage._sums
    monkeypatch.setattr(usage, "_sums", lambda *args: read.append(1) or sums(*args))
    assert client.get("/api/roles/models").status_code == 200  # where each of 20-odd roles runs
    assert len(read) == 1


def test_a_limit_in_dollars_is_not_kept_against_prices_in_another_currency(
    make_client, wait_run, project_dir,
):
    client, _model, _pid, cid, _run = past(make_client, wait_run, project_dir, [text("b", 1, 1)])
    assert client.post(f"/api/conversations/{cid}/messages", json={"content": "x"}).status_code == 409
    client.put("/api/prices", json={**PRICE, "model_id": "elsewhere", "currency": "EUR"})
    with client.app.state.session_factory() as session:
        assert usage.unkept(session) == "This limit can't be kept: your prices are in EUR and USD"
    assert client.post(f"/api/conversations/{cid}/messages", json={"content": "x"}).status_code == 201


def test_a_lead_moved_by_a_limit_says_why_from_the_start(team, wait_run, project_dir):  # noqa: F811
    client, _default, _fast = team([text("a", 1_000_000, 500_000)], [text("on fast")])
    local_id, _fast_id = both_strongest(team, client)  # strongest: Local big-model, then Fast deep
    assert patch_role(client, "Lead", tier="strongest").status_code == 200
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    first = client.post(f"/api/conversations/{cid}/messages", json={"content": "go"}).json()
    wait_run(client, cid, first["run"]["id"])
    client.put("/api/prices", json={**PRICE, "model_id": "big-model"})
    assert client.patch(f"/api/providers/{local_id}", json={"day_limit": 5}).status_code == 200
    went = client.post(f"/api/conversations/{cid}/messages", json={"content": "more"},
                       headers={"Origin": ORIGIN})
    assert went.status_code == 201, went.text  # its Lead opens on Fast, under its limit
    run_id = went.json()["run"]["id"]
    lead = next(a for a in wait_run(client, cid, run_id)["agents"] if a["run_id"] == run_id)
    assert lead["provider_name"] == "Fast"
    assert lead["chosen_why"] == (
        "over Local's limit of 5.00 USD a day (10.50 spent today): the next strongest model")


def test_a_rooms_members_are_held_to_their_providers_limits(make_client, wait_run, project_dir):
    client, _model, _pid, cid = began(make_client, project_dir, [text("a", 10, 10), text("b")])
    run = turn(client, wait_run, cid)
    other(client, run, for_agents=True)  # open to agents: this test is about the limit (B-385)
    # The user's room: asked first, as a message is, of a member's provider too.
    room = {"goal": "together", "with": [{"role": "Coder", "provider": "Other"}, {"role": "Reviewer"}]}
    refused = client.post(f"/api/conversations/{cid}/rooms", json=room)
    assert refused.status_code == 409 and "over Other's limit" in refused.text
    # An agent's room: a member past its provider's limit is not opened, as a sub-agent is not.
    with client.app.state.session_factory() as session:
        conversation = session.get_one(Conversation, cid)
        conversation.provider_id = next(p["id"] for p in client.get("/api/providers").json()
                                        if p["name"] == "Other")
        with pytest.raises(ValueError, match="Other is over Other's limit"):
            member_model(session, conversation, "Coder", None, None)
