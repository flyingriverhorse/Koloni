"""Slice 81b's edges: what the acceptance set (tests/test_agents_teams_scenarios.py) leaves open -
what the Lead is told of the roles it may open, the record the Agents page draws, and teams."""

from tests.test_agents_teams_scenarios import WHY, patch_role, spawn
from tests.test_chat_flow import text
from tests.test_chat_teams_scenarios import no_recipe
from tests.test_spawn import begin, step
from tests.test_team import results, team  # noqa: F401  (a fixture)
from tests.test_tier_scenarios import ORIGIN, tiered

OWN = {"Origin": ORIGIN}


def spawn_tool(model, at=0):
    return next(t["function"] for t in model.tool_args[at] if t["function"]["name"] == "spawn_agent")


def test_the_lead_is_told_only_the_roles_it_may_open_and_a_range_that_is_not_the_whole(
    team, wait_run, project_dir  # noqa: F811
):
    client, default, _fast = team([text("done")])
    web = no_recipe(client, "Web app")["Web app"]
    assert patch_role(client, "Coder", tier_max="balanced").status_code == 200
    assert patch_role(client, "Tester", tier="fast").status_code == 200
    assert patch_role(client, "Reviewer", enabled=False).status_code == 200
    cid, run_id = begin(client, project_dir, teams_mode="manual", teams=[{"team_id": web["id"]}])
    wait_run(client, cid, run_id)
    listed = spawn_tool(default)["description"]
    assert "- Coder — Writes and changes code. (fast to balanced)" in listed
    assert "- Tester — Runs the tests and reports what passes and what fails. (always fast)" in listed
    assert "- Planner —" in listed and "- Debugger —" in listed       # always there; in the team
    assert "Reviewer —" not in listed and "Translator —" not in listed  # off; not in the team
    tier = spawn_tool(default)["parameters"]["properties"]["tier"]["description"]
    assert "Pick the tier for the job" in tier
    # (Live, R59: the Lead opened team leads with a tier first, was refused, and tried again.)
    assert "Never for a team's coordinator, which runs on the conversation's model" in tier


def test_the_record_the_agents_page_draws(team, wait_run, project_dir):  # noqa: F811
    client, _default, _fast = team([step(spawn("Coder", "balanced", WHY)), text("done")],
                                   [text("fixed")])
    tiered(team, client)
    assert client.get("/api/roles/activity").json() == {"last": {}, "running": {}}
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    wait_run(client, cid, run_id)
    seen = client.get("/api/roles/activity").json()
    assert seen["last"]["Coder"]["tier"] == "balanced" and seen["running"] == {}
    coder = next(r for r in client.get("/api/roles").json() if r["name"] == "Coder")
    jobs = client.get(f"/api/roles/{coder['id']}/jobs").json()
    ((job,),) = [jobs["jobs"]]
    assert (job["conversation_id"], job["tier"], job["chosen_why"], job["status"]) == (
        cid, "balanced", WHY, "completed")
    assert (jobs["days30"]["jobs"], jobs["days30"]["failed"]) == (1, 0)
    assert jobs["days30"]["tokens"] + jobs["days30"]["unreported"] > 0  # what was said, or that it was not


def test_teams_are_renamed_and_deleted_from_the_own_page_and_a_conversation_follows(
    team, project_dir  # noqa: F811
):
    client, _default, _fast = team([])
    made = client.post("/api/teams", json={"name": "  Game  "}, headers=OWN).json()
    assert (made["name"], made["roles"]) == ("Game", [])
    assert client.post("/api/teams", json={"name": "web APP"}, headers=OWN).status_code == 409
    assert client.post("/api/teams", json={"name": "‮"}, headers=OWN).status_code == 422
    assert client.patch(f"/api/teams/{made['id']}", json={"name": "Games"}).status_code == 403
    assert client.patch(f"/api/teams/{made['id']}", json={"name": "Games"},
                        headers=OWN).json()["name"] == "Games"
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    picked = {"teams_mode": "manual", "teams": [{"team_id": made["id"]}]}
    assert client.patch(f"/api/conversations/{cid}", json=picked,
                        headers=OWN).json()["teams"][0]["team_id"] == made["id"]
    assert client.delete(f"/api/teams/{made['id']}", headers=OWN).status_code == 204
    assert client.get(f"/api/conversations/{cid}").json()["conversation"]["teams"] == []


def test_the_lead_the_planner_and_the_observer_are_never_off(team):  # noqa: F811
    client, _default, _fast = team([])
    for name in ("Lead", "Planner", "Observer"):
        assert patch_role(client, name, enabled=False).status_code == 422, name
    assert client.patch(f"/api/roles/{next(r['id'] for r in client.get('/api/roles').json() if r['name'] == 'Coder')}",
                        json={"enabled": False}).status_code == 403  # the user's, from the own page


def test_a_role_the_lead_makes_joins_no_team_and_is_opened_that_turn_only_without_teams(
    team, wait_run, project_dir  # noqa: F811
):
    from tests.test_spawn import new_role

    client, _default, _fast = team([new_role("Scout", ["read_file"]), step(spawn("Scout")),
                                     text("scouted"), text("done")])
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    snap = wait_run(client, cid, run_id)
    assert [a["role_name"] for a in snap["agents"]] == ["Lead", "Scout"]
    scout = next(r for r in client.get("/api/roles").json() if r["name"] == "Scout")
    assert scout["teams"] == []


def test_a_role_the_lead_makes_in_a_chat_with_teams_stays_out_of_them(
    team, wait_run, project_dir  # noqa: F811
):
    from tests.test_spawn import new_role

    # (Slice 84b: else the Lead would make itself a role with any tools inside the user's team.)
    client, _default, _fast = team([new_role("Coder 2", ["write_file", "run_command"]),
                                    step(spawn("Coder 2")), text("done")])
    web = next(t for t in client.get("/api/teams").json() if t["name"] == "Web app")
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never",
                        teams_mode="manual", teams=[{"team_id": web["id"]}])
    snap = wait_run(client, cid, run_id)
    made = next(t for t in snap["tool_calls"] if t["name"] == "create_role")
    assert "in no team" in made["result"]
    ((status, said),) = results(snap)
    assert status == "failed" and "Web app" in said
    assert next(r for r in client.get("/api/roles").json() if r["name"] == "Coder 2")["teams"] == []
    assert web["roles"] == next(t for t in client.get("/api/teams").json() if t["name"] == "Web app")["roles"]


def test_a_room_the_lead_opens_passes_the_same_door(make_client, wait_run, project_dir):
    from tests.test_room_open_scenarios import lead_calls, open_room

    client, _model = make_client({"Lead": [open_room(members=("Coder", "Translator")),
                                           text("done")]})
    client.headers["Origin"] = ORIGIN
    translator = next(r for r in client.get("/api/roles").json() if r["name"] == "Translator")
    assert client.patch(f"/api/roles/{translator['id']}", json={"enabled": False}).status_code == 200
    cid, run_id = begin(client, project_dir, mode="full_auto")
    snap = wait_run(client, cid, run_id)
    (tried,) = lead_calls(snap)
    assert tried["status"] == "failed" and "Translator role is off" in tried["result"]
    assert [a["name"] for a in snap["agents"]] == ["Lead"]


# --- the door, after review --------------------------------------------------------------------


def test_names_said_takes_the_longest_name_first():
    from app.roles import names_said

    names = ["Reviewer", "Security reviewer", "Coder"]
    assert names_said(names, "ask the security reviewer to look") == {"security reviewer"}
    assert names_said(names, "the Reviewer and the coder's fix") == {"reviewer", "coder"}
    assert names_said(names, None) == frozenset()


def test_a_message_not_sent_from_the_own_page_names_no_role(make_client, wait_run, project_dir):
    # (An agent's command posting to the app's address says nothing of where it is from.)
    client, _model = make_client([step(spawn("Translator")), text("done")])
    translator = next(r for r in client.get("/api/roles").json() if r["name"] == "Translator")
    assert client.patch(f"/api/roles/{translator['id']}", json={"enabled": False},
                        headers=OWN).status_code == 200
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    assert client.patch(f"/api/conversations/{cid}", headers=OWN, json={
        "permission_mode": "full_auto", "spawn_approval": "never"}).status_code == 200
    run_id = client.post(f"/api/conversations/{cid}/messages",
                         json={"content": "ask the translator"}).json()["run"]["id"]
    snap = wait_run(client, cid, run_id)
    ((status, said),) = results(snap)
    assert status == "failed" and "off" in said and len(snap["agents"]) == 1


def test_an_earlier_agent_in_a_role_now_off_is_not_gone_on_with(make_client, wait_run, project_dir):
    from tests.test_topic_scenarios import (
        FIRST,
        GO_ON,
        OLD_WORDS,
        SECOND,
        SPAWN_CODER,
        agents_of,
        calls_of,
        setup,
        turn,
    )

    scripts = {"Lead": [SPAWN_CODER, text("made"), GO_ON, text("done")],
               "Coder": [text(OLD_WORDS), text("must not be asked")]}
    client, _model, _pid, cid = setup(make_client, project_dir, scripts)
    turn(client, wait_run, cid, FIRST)
    coder = next(r for r in client.get("/api/roles").json() if r["name"] == "Coder")
    assert client.patch(f"/api/roles/{coder['id']}", json={"enabled": False}).status_code == 200
    snap, second = turn(client, wait_run, cid, SECOND)
    ((status, said),) = calls_of(snap, second["id"], "message_agent")
    assert status == "failed" and "Coder role is off" in said
    assert [a["name"] for a in agents_of(snap, second["id"])] == ["Lead"]


def test_a_discussion_invites_no_role_that_is_off_nor_lists_one(make_client, wait_run, project_dir):
    from tests.test_spawn import call

    client, _model = make_client([
        step(call("discuss", {"topic": "Tabs?", "with": ["Translator"], "rounds": 1}, "d")),
        text("done")])
    translator = next(r for r in client.get("/api/roles").json() if r["name"] == "Translator")
    assert client.patch(f"/api/roles/{translator['id']}", json={"enabled": False},
                        headers=OWN).status_code == 200
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    snap = wait_run(client, cid, run_id)
    (said,) = [t["result"] for t in snap["tool_calls"] if t["name"] == "discuss"]
    assert "Translator role is off" in said and "Translator," not in said.split("Roles:")[1]


def test_a_model_named_is_held_to_the_roles_tier_rule(team, wait_run, project_dir):  # noqa: F811
    from tests.test_spawn import call

    client, _default, _fast = team([
        step(call("spawn_agent", {"role": "Coder", "task": "t", "provider": "Local",
                                  "model": "big-model", "why": WHY}, "p")), text("done")])
    tiered(team, client)
    assert patch_role(client, "Coder", tier="fast").status_code == 200
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    snap = wait_run(client, cid, run_id)
    ((status, said),) = results(snap)
    assert status == "failed" and "always runs on the fast tier" in said and len(snap["agents"]) == 1


def test_the_tier_rule_is_changed_only_from_the_own_page_and_its_ends_stay_in_order(team):  # noqa: F811
    client, _default, _fast = team([])
    coder = next(r for r in client.get("/api/roles").json() if r["name"] == "Coder")
    for body in ({"tier": "fast"}, {"tier_min": "balanced"}, {"kind": "mine"}):
        assert client.patch(f"/api/roles/{coder['id']}", json=body).status_code == 403, body
    assert patch_role(client, "Coder", tier_max="fast").status_code == 200
    assert patch_role(client, "Coder", tier_min="balanced").status_code == 422  # above the stored end
    # a new role is on: saying so is no leave to ask for
    made = client.post("/api/roles", json={"name": "Helper", "tools": ["read_file"], "enabled": True})
    assert made.status_code == 201, made.text


def test_a_role_can_run_on_the_conversations_model_as_before(team, wait_run, project_dir):  # noqa: F811
    client, _default, _fast = team([step(spawn("Coder")), step(spawn("Coder", "fast", WHY, "s2")),
                                    text("coded"), text("done")])
    tiered(team, client)
    assert patch_role(client, "Coder", tier="conversation").status_code == 200
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    snap = wait_run(client, cid, run_id)
    (first, _), (second, said) = results(snap)
    assert first == "succeeded" and snap["agents"][1]["provider_name"] == "Local"
    assert ("Fast", "deep") not in team.asked
    assert second == "failed" and "conversation's model" in said
    rows = {row["role"]: row for row in client.get("/api/roles/models").json()}
    assert (rows["Coder"]["source"], rows["Coder"]["tier"]) == ("default", None)
