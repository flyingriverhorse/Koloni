"""Slice 28a's acceptance set: model tiers every role uses, and new roles. Written before
the code.

The user says of a model how strong it is (fast / balanced / strongest). A role can then
ask for a tier instead of one model; an agent that opens a sub-agent can say the job is
hard or easy, which moves it one tier, with its reason on the card; a conversation can have
its lead's model chosen by how hard the message is; and when an agent could not finish, its
opener is told which model is one tier up. Nothing is chosen from a model without a tier.

Slice 81b changed what an opener says: a `tier` for the job (with why) in place of easy / hard,
and built-in roles came without a tier. The tests below that spoke of `difficulty` say `tier`.
"""

import pytest

from app.db.models import Role

if not hasattr(Role, "tier"):  # written before the code: skipped until it exists
    pytest.skip("slice 28a is not built yet", allow_module_level=True)

from tests.test_chat_flow import text  # noqa: E402
from tests.test_spawn import begin, call, role_id, step  # noqa: E402
from tests.test_team import results, team  # noqa: E402, F401  (a fixture)

# Which model an agent ran on is read from what was ASKED of its provider (`team.asked`): the
# stand-in models here report one fixed name of their own whatever they are asked for.

ORIGIN = "http://127.0.0.1:8790"
WHY = "The failure only shows under load: it needs care."


def spawn(role, tier=None, why=None, task="do the thing", id="s1"):
    more = {key: value for key, value in (("tier", tier), ("why", why)) if value is not None}
    return call("spawn_agent", {"role": role, "task": task, **more}, id)


def tiered(team, client):  # noqa: F811
    """Local · big-model is the strongest, Fast · deep is balanced, Fast · quick is fast."""
    client.headers["Origin"] = ORIGIN
    local = client.get("/api/providers").json()[0]
    assert client.patch(f"/api/providers/{local['id']}", json={
        "models": [{"name": "big-model", "tier": "strongest"}]}).status_code == 200
    fast = team.providers["Fast"]["id"]
    assert client.patch(f"/api/providers/{fast}", json={"models": [
        {"name": "quick", "tier": "fast"}, {"name": "deep", "tier": "balanced"}]}).status_code == 200
    assert client.patch(f"/api/providers/{fast}", json={
        "models": [{"name": "quick", "tier": "fastest"}]}).status_code == 422
    return local, fast


def role_tier(client, role, tier):
    assert client.patch(f"/api/roles/{role_id(client, role)}", json={"tier": tier}).status_code == 200


# --- a role asks for a tier ----------------------------------------------------------------


@pytest.mark.no_po
def test_a_role_with_a_tier_runs_on_the_model_of_that_tier(team, wait_run, project_dir):  # noqa: F811
    client, default, fast = team([step(spawn("Reviewer")), text("done")], [text("looked")])
    tiered(team, client)
    role_tier(client, "Reviewer", "balanced")
    cid, run_id = begin(client, project_dir, spawn_approval="never")
    snap = wait_run(client, cid, run_id)
    reviewer = snap["agents"][1]
    # the user's own setting, not a pick of the agent's: nothing to ask about, no reason
    assert (reviewer["provider_name"], reviewer["chosen"]) == ("Fast", False)
    assert ("Fast", "deep") in team.asked and len(fast.calls) == 1
    rows = {row["role"]: row for row in client.get(
        "/api/roles/models", params={"conversation_id": cid}).json()}
    assert (rows["Reviewer"]["provider_name"], rows["Reviewer"]["model_id"],
            rows["Reviewer"]["source"]) == ("Fast", "deep", "tier")
    assert client.patch(f"/api/roles/{role_id(client, 'Reviewer')}",
                        json={"tier": "godlike"}).status_code == 422


def test_a_roles_own_model_comes_before_its_tier(team, wait_run, project_dir):  # noqa: F811
    client, default, fast = team([step(spawn("Reviewer")), text("done")], [text("looked")])
    _local, fast_id = tiered(team, client)
    assert client.patch(f"/api/roles/{role_id(client, 'Reviewer')}", json={
        "provider_id": fast_id, "model_id": "quick", "tier": "strongest"}).status_code == 200
    cid, run_id = begin(client, project_dir, spawn_approval="never")
    snap = wait_run(client, cid, run_id)
    assert snap["agents"][1]["provider_name"] == "Fast"
    assert ("Fast", "quick") in team.asked and ("Fast", "deep") not in team.asked


def test_a_tier_nobody_gave_a_model_changes_nothing(team, wait_run, project_dir):  # noqa: F811
    client, default, fast = team([step(spawn("Reviewer")), text("r"), text("done")])
    client.headers["Origin"] = ORIGIN                 # no model has a tier here
    role_tier(client, "Reviewer", "strongest")
    cid, run_id = begin(client, project_dir, spawn_approval="never")
    snap = wait_run(client, cid, run_id)
    assert snap["agents"][1]["provider_name"] == "Local" and fast.calls == []


# --- how hard the job is ------------------------------------------------------------------


def test_a_hard_job_goes_one_tier_up_with_its_reason(team, wait_run, project_dir):  # noqa: F811
    # (81b: the tier is said, not moved to: a hard job is given strongest, with why.)
    client, default, fast = team(
        [step(spawn("Coder", "strongest", WHY)), text("done")], [text("fixed")])
    tiered(team, client)
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    snap = wait_run(client, cid, run_id)
    coder = snap["agents"][1]
    assert coder["provider_name"] == "Local" and ("Local", "big-model") in team.asked
    # within the user's rule: the Lead's choice, not a pick of a model asked about
    assert (coder["chosen"], coder["chosen_why"], coder["tier"]) == (False, WHY, "strongest")


def test_a_hard_job_without_a_reason_is_refused(team, wait_run, project_dir):  # noqa: F811
    client, default, fast = team([step(spawn("Coder", "strongest")), text("done")])
    tiered(team, client)
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    snap = wait_run(client, cid, run_id)
    ((status, said),) = results(snap)
    assert status == "failed" and "why" in said and len(snap["agents"]) == 1


def test_an_easy_job_at_the_lowest_tier_stays_where_it_is(team, wait_run, project_dir):  # noqa: F811
    client, default, fast = team([step(spawn("Coder", "fast", WHY)), text("done")], [text("ok")])
    tiered(team, client)
    role_tier(client, "Coder", "fast")
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    snap = wait_run(client, cid, run_id)
    coder = snap["agents"][1]
    assert (coder["provider_name"], coder["chosen"]) == ("Fast", False)
    assert ("Fast", "quick") in team.asked and ("Fast", "deep") not in team.asked


# --- the lead's own model, by how hard the message is ---------------------------------------


@pytest.mark.parametrize("said, runs_on, on_default, on_fast", [
    ("hard: the failure only shows under load", ("Local", "big-model"), 1, 1),
    ("easy: a one-line answer", ("Fast", "quick"), 0, 2),
    ("banana", ("Local", None), 1, 1),                 # unreadable: the conversation's own model
])
def test_a_leads_model_can_follow_how_hard_the_message_is(team, wait_run, project_dir,  # noqa: F811
                                                          said, runs_on, on_default, on_fast):
    client, default, fast = team([text("the lead answers")],
                                 [text(said), text("the lead answers")])
    tiered(team, client)
    cid, run_id = begin(client, project_dir, lead_auto=True)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    lead = snap["agents"][0]
    assert lead["provider_name"] == runs_on[0]
    if runs_on[1]:
        assert runs_on in team.asked            # asked for by the name of its tier's model
    # the first thing the fast model was asked is how hard the message is - with no tools
    assert (len(default.calls), len(fast.calls)) == (on_default, on_fast)
    assert not fast.tool_args[0]
    if said == "banana":
        assert lead["chosen_why"] is None
    else:
        assert said.split(":")[0] in lead["chosen_why"]


def test_without_the_setting_nobody_is_asked_how_hard_it_is(team, wait_run, project_dir):  # noqa: F811
    client, default, fast = team([text("the lead answers")])
    tiered(team, client)
    cid, run_id = begin(client, project_dir)
    wait_run(client, cid, run_id)
    assert fast.calls == [] and len(default.calls) == 1


# --- one tier up, said to the opener --------------------------------------------------------


def test_the_opener_of_an_agent_that_could_not_finish_hears_what_is_one_tier_up(
    team, wait_run, project_dir  # noqa: F811
):
    looks = [step(call("list_dir", {}, f"c{n}"), i=5, o=2) for n in range(3)]
    # (81b: the Lead gave it the fast tier; an "Always fast" role would get no advice.)
    client, default, fast = team([step(spawn("Coder", "fast", WHY)), text("the lead goes on")], looks)
    tiered(team, client)
    assert client.patch(f"/api/roles/{role_id(client, 'Coder')}",
                        json={"max_steps": 2}).status_code == 200
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed"
    ((status, said),) = results(snap)
    assert status == "failed" and "deep" in said and "tier" in said.lower()
    assert [a["name"] for a in snap["agents"]] == ["Lead", "Coder"]    # advice, not a switch


# --- new roles -----------------------------------------------------------------------------


def test_the_new_roles_are_there_each_with_its_tools_and_its_tier(team):  # noqa: F811
    client, _default, _fast = team([text("x")])
    roles = {role["name"]: role for role in client.get("/api/roles").json()}
    for name in ("Debugger", "Architect", "Security reviewer", "Docs writer", "Refactorer"):
        assert roles[name]["builtin"] is True and roles[name]["tier"] is None, name  # 81b
        assert roles[name]["instructions"] and roles[name]["description"], name
    writes = {"write_file", "edit_file"}
    assert not writes & set(roles["Architect"]["tools"])
    assert not (writes | {"run_command"}) & set(roles["Security reviewer"]["tools"])
    assert writes <= set(roles["Debugger"]["tools"]) and "run_command" in roles["Debugger"]["tools"]
    assert writes <= set(roles["Docs writer"]["tools"])
    # slice 43 gave them a tier; slice 81b took it: the Lead picks one for each job
    assert roles["Coder"]["tier"] is None and roles["Lead"]["tier"] is None


def test_a_teams_lead_with_no_model_of_its_own_runs_on_the_chats(team, project_dir):  # noqa: F811
    # Batch-16 (REA R49): a team's lead ran on a balanced model ("balanced or stronger") beside a
    # chat on a faster one. A team's lead is its team's own Lead: on the chat's model, as the Lead.
    client, _default, _fast = team([text("hi")])
    tiered(team, client)
    assert client.post("/api/teams", json={"name": "Mine"}).status_code == 201
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    from app.db.models import Conversation
    from app.roles import find_role
    from app.team import would_run
    with client.app.state.session_factory() as session:
        chat = session.get_one(Conversation, cid)
        on = would_run(session, find_role(session, "Lead"), chat)
        for lead in ("Web app lead", "Mine lead"):
            would = would_run(session, find_role(session, lead), chat)
            assert (would.provider.id, would.model_id, would.source) == (on.provider.id, on.model_id, on.source)


def test_a_model_picked_for_a_teams_lead_is_held_to_no_tier_rule_as_the_leads(team):  # noqa: F811
    # (Review: 0083's "the conversation's model" refused every model picked for a team's lead - and
    # B-88's "run it there" found none. It is where a lead runs by default, not all it may be given.)
    client, _default, _fast = team([text("hi")])
    _local, fast_id = tiered(team, client)
    role_tier(client, "Coder", "conversation")
    from app.db.models import Provider
    from app.roles import find_role
    from app.team import outside_rule
    with client.app.state.session_factory() as session:
        fast = session.get_one(Provider, fast_id)
        assert outside_rule(find_role(session, "Web app lead"), fast, "deep") is None
        assert "conversation's model" in outside_rule(find_role(session, "Coder"), fast, "deep")
