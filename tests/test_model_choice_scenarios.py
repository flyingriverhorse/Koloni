"""Slice 25c's acceptance set: which agent runs on which model, and why. Written before
the code.

An agent that picks another model for a sub-agent says why, in a sentence the user reads on
the card. A role can say which providers may be picked for it, and how far one agent of it
may go (steps, tokens). One table says, for every role, what it would run on now and where
that comes from. And a model that takes a conversation over from another is told so.
"""

import pytest

from app.db.models import Role

if not hasattr(Role, "pick_from"):  # written before the code: skipped until it exists
    pytest.skip("slice 25c is not built yet", allow_module_level=True)

from tests.test_agent_writes import wait_status  # noqa: E402
from tests.test_chat_flow import text  # noqa: E402
from tests.test_spawn import begin, call, role_id, step  # noqa: E402
from tests.test_team import results, team  # noqa: E402, F401  (a fixture)

ORIGIN = "http://127.0.0.1:8790"
WHY = "The bug is subtle: it needs the stronger model."


def pick(role, provider=None, model=None, why=None, task="do the thing", id="s1"):
    more = {key: value for key, value in (("provider", provider), ("model", model), ("why", why))
            if value is not None}
    return call("spawn_agent", {"role": role, "task": task, **more}, id)


# --- the reason for a pick -----------------------------------------------------------------


def test_a_pick_without_a_reason_is_refused_and_nothing_is_opened(team, wait_run, project_dir):  # noqa: F811
    client, default, fast = team([step(pick("Reviewer", "Fast", "deep")), text("done")])
    cid, run_id = begin(client, project_dir, spawn_approval="never")
    snap = wait_run(client, cid, run_id)
    ((status, said),) = results(snap)
    assert status == "failed" and "why" in said
    assert [a["name"] for a in snap["agents"]] == ["Lead"] and fast.calls == []


def test_the_reason_for_a_pick_is_on_the_card_and_on_the_agent(team, wait_run, project_dir):  # noqa: F811
    client, default, fast = team(
        [step(pick("Reviewer", "Fast", "deep", WHY)), text("done")], [text("looked")])
    cid, run_id = begin(client, project_dir)                 # sub-agents are asked about
    kid = wait_status(client, cid, "waiting_approval")["agents"][1]
    assert (kid["status"], kid["chosen"], kid["chosen_why"]) == ("proposed", True, WHY)
    client.post(f"/api/agents/{kid['id']}/approve")
    snap = wait_run(client, cid, run_id)
    assert snap["agents"][1]["chosen_why"] == WHY and len(fast.calls) == 1
    assert snap["agents"][0]["chosen_why"] is None


def test_what_the_role_would_get_anyway_needs_no_reason(team, wait_run, project_dir):  # noqa: F811
    client, default, fast = team([step(pick("Reviewer", "Local")), text("r"), text("done")])
    cid, run_id = begin(client, project_dir, spawn_approval="never")
    snap = wait_run(client, cid, run_id)
    assert results(snap)[0][0] == "succeeded"
    assert (snap["agents"][1]["chosen"], snap["agents"][1]["chosen_why"]) == (False, None)


# --- what may be picked for a role ----------------------------------------------------------


def test_a_role_says_which_providers_may_be_picked_for_it(team, wait_run, project_dir):  # noqa: F811
    client, default, fast = team(
        [step(pick("Reviewer", "Codex", why=WHY, id="a")),
         step(pick("Reviewer", "Fast", why=WHY, id="b")), text("done")], [text("looked")])
    client.headers["Origin"] = ORIGIN
    reviewer = role_id(client, "Reviewer")
    only_fast = [team.providers["Fast"]["id"]]
    assert client.patch(f"/api/roles/{reviewer}", json={"pick_from": only_fast}).status_code == 200
    assert client.patch(f"/api/roles/{reviewer}", json={"pick_from": ["nope"]}).status_code == 422
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    snap = wait_run(client, cid, run_id)
    (refused, said), (taken, _) = results(snap)
    assert refused == "failed" and "Fast" in said and taken == "succeeded"
    assert [(a["name"], a["provider_name"]) for a in snap["agents"][1:]] == [("Reviewer", "Fast")]


def test_a_role_nothing_may_be_picked_for_still_runs_on_its_own_model(team, wait_run,  # noqa: F811
                                                                    project_dir):
    client, default, fast = team(
        [step(pick("Reviewer", "Fast", why=WHY, id="a")),
         step(pick("Reviewer", id="b")), text("r"), text("done")])
    client.headers["Origin"] = ORIGIN
    reviewer = role_id(client, "Reviewer")
    assert client.patch(f"/api/roles/{reviewer}", json={"pick_from": []}).status_code == 200
    cid, run_id = begin(client, project_dir, spawn_approval="never")
    snap = wait_run(client, cid, run_id)
    (refused, _), (taken, _) = results(snap)
    assert (refused, taken) == ("failed", "succeeded") and fast.calls == []
    assert snap["agents"][1]["provider_name"] == "Local"


# --- one table: who uses what ---------------------------------------------------------------


def test_one_table_says_what_each_role_would_run_on_and_where_that_comes_from(team, project_dir):  # noqa: F811
    client, default, fast = team([text("x")])
    client.headers["Origin"] = ORIGIN
    fast_id = team.providers["Fast"]["id"]
    assert client.patch(f"/api/roles/{role_id(client, 'Reviewer')}", json={
        "provider_id": fast_id, "model_id": "deep", "pick_from": [fast_id]}).status_code == 200
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]

    def table():
        told = client.get("/api/roles/models", params={"conversation_id": cid})
        assert told.status_code == 200, told.text
        return {row["role"]: row for row in told.json()}

    rows = table()
    assert (rows["Reviewer"]["provider_name"], rows["Reviewer"]["model_id"],
            rows["Reviewer"]["source"]) == ("Fast", "deep", "role")
    assert rows["Reviewer"]["pick_from"] == ["Fast"]
    assert (rows["Coder"]["provider_name"], rows["Coder"]["source"]) == ("Local", "default")
    assert sorted(rows["Coder"]["pick_from"]) == ["Codex", "Fast", "Local"]   # all in the guide
    assert client.patch(f"/api/conversations/{cid}", json={"provider_id": fast_id}).status_code == 200
    rows = table()
    assert (rows["Coder"]["provider_name"], rows["Coder"]["model_id"],
            rows["Coder"]["source"]) == ("Fast", "quick", "conversation")
    assert rows["Reviewer"]["source"] == "role"


# --- how far one agent of a role may go -----------------------------------------------------


def looks(n):
    return step(call("list_dir", {}, f"c{n}"), i=5, o=2)


@pytest.mark.parametrize("limit, why", [({"max_steps": 2}, "step"), ({"max_tokens": 10}, "token")])
def test_an_agent_over_its_roles_limit_stops_and_its_opener_goes_on(make_client, wait_run,
                                                                   project_dir, limit, why):
    client, model = make_client({
        "Lead": [step(call("spawn_agent", {"role": "Coder", "task": "look around"}, "s")),
                 text("the lead goes on")],
        "Coder": [looks(1), looks(2), looks(3), text("never said")],
    })
    client.headers["Origin"] = ORIGIN
    coder = role_id(client, "Coder")
    assert client.patch(f"/api/roles/{coder}", json=limit).status_code == 200
    assert client.patch(f"/api/roles/{coder}", json={next(iter(limit)): 0}).status_code == 422
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed"                # the turn goes on
    kid = snap["agents"][1]
    assert kid["status"] == "failed" and why in (kid["error"] or "").lower()
    assert len(model.calls_of["Coder"]) == 2                       # no third step was asked for
    ((status, said),) = results(snap)
    assert status == "failed" and "limit" in said.lower()


# --- a model that takes a conversation over -------------------------------------------------


def test_a_model_that_takes_a_conversation_over_is_told_whose_it_was(team, wait_run, project_dir):  # noqa: F811
    client, default, fast = team([text("first answer"), text("third answer")],
                                 [text("second answer")])
    cid, run_id = begin(client, project_dir, spawn_approval="never")
    wait_run(client, cid, run_id)
    fast_id = team.providers["Fast"]["id"]
    assert client.patch(f"/api/conversations/{cid}", json={"provider_id": fast_id}).status_code == 200
    second = client.post(f"/api/conversations/{cid}/messages", json={"content": "and now?"}).json()
    wait_run(client, cid, second["run"]["id"])
    # one sentence of it names the model the earlier turns were with
    assert any(
        "earlier turns" in line.lower() and "Local" in line
        for m in fast.calls[0] if isinstance(m["content"], str)
        for line in m["content"].splitlines()
    )
    # the same model going on with its own conversation is told nothing of the kind
    assert "earlier turns" not in "\n".join(
        m["content"] for m in default.calls[0] if isinstance(m["content"], str)).lower()


# --- a model closed to agents (B-385) -------------------------------------------------------


def _close_to_agents(client):
    """The Lead's provider with every model of it closed to agents, as Copilot's 12 were live."""
    from app.db.models import Provider

    with client.app.state.session_factory() as session:
        local = session.query(Provider).filter_by(name="Local").one()
        local.models, local.for_agents = [{"name": "fake-model", "agents": False}], False
        session.commit()


def test_a_sub_agent_is_never_opened_on_a_model_closed_to_agents(make_client, wait_run,
                                                                 project_dir):
    # B-385 (live): under a Copilot Lead with every Copilot model closed to agents, sub-agents
    # fell back to the Lead's model. Nothing else open: it is not opened, and its opener is told.
    client, model = make_client([step(pick("Coder")), text("done")])
    _close_to_agents(client)
    cid, run_id = begin(client, project_dir, spawn_approval="never")
    snap = wait_run(client, cid, run_id)
    ((status, said),) = results(snap)
    told = ("Coder can't open: no model of Local is open to agents. Tick \"Agents may use\" on the "
            "Models page.")
    assert (status, said) == ("failed", f"error: {told}")  # (nothing else open: no pick offered)
    assert [a["name"] for a in snap["agents"]] == ["Lead"]  # (the Lead runs on it: its own)
    # The user is told too, whatever the Lead says (a fresh install's CLIs start closed).
    assert [m["content"] for m in snap["messages"] if m["role"] == "koloni"] == [told]


def test_a_teams_coordinator_and_a_room_member_are_held_to_it_too(make_client, project_dir):
    # B-385: a team's coordinator runs on the conversation's model (0083) - not one closed to them.
    from app import room as rooms
    from app.db.models import Conversation, Role, Team
    from app.team import would_run

    client, _model = make_client([text("hi")])
    _close_to_agents(client)
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    with client.app.state.session_factory() as session:
        team = session.query(Team).filter(Team.lead_role_id.is_not(None)).first()
        lead = session.get_one(Role, team.lead_role_id)
        conversation = session.get_one(Conversation, cid)
        would = would_run(session, lead, conversation)
        assert would.refused is not None and str(would.refused).startswith(
            f"{lead.name} can't open: no model of Local is open to agents")
        with pytest.raises(ValueError, match="Tick \"Agents may use\" on the Models page"):
            rooms.member_model(session, conversation, lead.name, None, None, lead=lead)
        lead_role = session.query(Role).filter_by(name="Lead").one()
        assert would_run(session, lead_role, conversation).refused is None  # (the Lead's own)


def test_a_room_the_user_opens_on_a_model_closed_to_agents_says_what_to_do(make_client,
                                                                            project_dir):
    # B-385: the user who opens the room reads why it does not open, and what to tick.
    client, _model = make_client([text("hi")])
    _close_to_agents(client)
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    opened = client.post(f"/api/conversations/{cid}/rooms", headers={"Origin": ORIGIN}, json={
        "goal": "x", "with": [{"role": "Coder"}, {"role": "Reviewer"}]})
    assert opened.status_code == 422 and "Tick \"Agents may use\" on the Models page" in (
        opened.json()["detail"]), opened.text


def test_a_lead_that_may_pick_an_open_provider_is_told_so(team, wait_run, project_dir):  # noqa: F811
    # B-385 (review): with a provider open to agents in the guide, the Lead may still pick it.
    from app.team import PICK_AN_OPEN_ONE

    client, default, fast = team([step(pick("Coder")), text("done")])
    _close_to_agents(client)
    with client.app.state.session_factory() as session:
        from app.db.models import Role

        session.query(Role).filter_by(name="Coder").one().tier = "conversation"
        session.commit()
    cid, run_id = begin(client, project_dir, spawn_approval="never")
    ((status, said),) = results(wait_run(client, cid, run_id))
    assert status == "failed" and said.endswith(PICK_AN_OPEN_ONE), said


def test_a_cli_whose_model_is_closed_to_agents_runs_none_of_its_own(make_client):
    # B-385 (review): Claude Code's own Agent would run a role on its Lead's closed model.
    from types import SimpleNamespace

    from app.db.models import Provider
    from app.model_native import claude_without

    assert {"Agent", "Task"} <= set(claude_without(("agents",)))
    assert "Agent" not in claude_without(())
    client, _model = make_client([text("hi")])
    runner = client.app.state.runner
    with client.app.state.session_factory() as session:
        local = session.query(Provider).filter_by(name="Local").one().id
    ctx = SimpleNamespace(provider_id=local, model_name="fake-model")
    assert not runner._closed_here(ctx)
    _close_to_agents(client)
    assert runner._closed_here(ctx)


def test_a_model_of_the_roles_list_closed_to_agents_is_passed_over(team, project_dir):  # noqa: F811
    # B-385 (review): the role's own list was not held to a model's "agents: false".
    from app.db.models import Provider, Role
    from app.team import would_run

    client, _default, _fast = team([text("hi")])
    with client.app.state.session_factory() as session:
        fast = session.query(Provider).filter_by(name="Fast").one()
        fast.models = [{"name": "quick"}, {"name": "deep", "agents": False}]
        coder = session.query(Role).filter_by(name="Coder").one()
        coder.models = [{"provider_id": fast.id, "model_id": "deep"},
                        {"provider_id": fast.id, "model_id": "quick"}]
        session.commit()
        would = would_run(session, coder, None)
        assert (would.provider.name, would.model_id) == ("Fast", "quick")
        assert "Fast's deep is closed to agents" in (would.moved or "")


def test_a_turn_that_fails_still_tells_the_user_what_to_tick(make_client, wait_run, project_dir):
    # B-385 (re-review): the line came only at a completed turn's end.
    from app.model_client import ModelUnavailable

    client, _model = make_client([step(pick("Coder")), ModelUnavailable("gone")])
    _close_to_agents(client)
    cid, run_id = begin(client, project_dir, spawn_approval="never")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "failed"
    (said,) = [m["content"] for m in snap["messages"] if m["role"] == "koloni"]
    assert said.startswith("Coder can't open: no model of Local is open to agents.")
