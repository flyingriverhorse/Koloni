"""Slice 84b-1's acceptance set: the chat's teams, chosen and held to - not yet run by a recipe.
Written before the code.

Design: `tasarim/specs/2026-10-23-dilim-63-84-takimlar-tarifler-design.md` §3 and §7.

Contract:
- A conversation has `teams_mode` ("lead" / "manual" / "none"; a new chat "none") and `teams`:
  its rows in order, each {"team_id", "recipe_id" (null: the team's default), "picked_by"
  ("lead" / "user"), "why" (the Lead's reason; null for the user's)}.
- `PATCH /api/conversations/{id}` takes `teams_mode` and `teams` ([{"team_id", "recipe_id"}],
  the user's rows; only with Manual), from the app's own page alone. An unknown team or recipe,
  or a team twice, is 422. Leaving Manual for another mode takes the rows away; going to Manual
  keeps the Lead's picks, to be changed.
- With rows (Manual, or what the Lead picked), `spawn_agent` opens only the roles of those
  teams, refused with the teams named; the Lead, the Planner and a role the user names always
  may. No rows, or "No teams": any role, as before.
- Lead decides: the Lead is offered `pick_teams` ({"teams": [{"team", "recipe"?, "why"}]}),
  listing only the teams it may pick (`lead_may_pick`); its picks are the rows, "lead", with
  their reason. Elsewhere it is not offered, and refused if called.
- A project's `teams_mode` and `teams` (the same rows) are what its new chats start with.
"""

from tests.test_chat_flow import text
from tests.test_spawn import begin, call, names, step
from tests.test_tier_scenarios import ORIGIN

OWN = {"Origin": ORIGIN}


def teams_of(client):
    return {t["name"]: t for t in client.get("/api/teams").json()}


def no_recipe(client, *names):
    """These ready teams with no default recipe (migration 0093 gives three of them one), so the
    Lead runs them itself; the teams after it."""
    for name in names:
        assert client.patch(f"/api/teams/{teams_of(client)[name]['id']}",
                            json={"default_recipe_id": None}, headers=OWN).status_code == 200
    return teams_of(client)


def recipe(client, name):
    return next(r for r in client.get("/api/recipes").json()["recipes"] if r["name"] == name)


def spawned(snap):
    return [(t["status"], t["result"]) for t in snap["tool_calls"] if t["name"] == "spawn_agent"]


def pick(*teams, id="p1"):
    return step(call("pick_teams", {"teams": list(teams)}, id))


def test_a_new_chat_has_no_teams_and_the_user_picks_them_from_the_own_page(make_client, project_dir):
    client, _model = make_client([])
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    chat = client.get(f"/api/conversations/{cid}").json()["conversation"]
    assert (chat["teams_mode"], chat["teams"]) == ("none", [])
    teams, feature = teams_of(client), recipe(client, "Feature")
    rows = [{"team_id": teams["Docs"]["id"], "recipe_id": feature["id"]},
            {"team_id": teams["Web app"]["id"], "recipe_id": None}]
    body = {"teams_mode": "manual", "teams": rows}
    assert client.patch(f"/api/conversations/{cid}", json=body).status_code == 403
    saved = client.patch(f"/api/conversations/{cid}", json=body, headers=OWN)
    assert saved.status_code == 200, saved.text
    assert saved.json()["teams_mode"] == "manual"
    assert [(r["team_id"], r["recipe_id"], r["picked_by"], r["why"]) for r in saved.json()["teams"]] == [
        (teams["Docs"]["id"], feature["id"], "user", None), (teams["Web app"]["id"], None, "user", None)]
    for wrong in ([{"team_id": "nope"}], [{"team_id": teams["Docs"]["id"], "recipe_id": "nope"}],
                  [{"team_id": teams["Docs"]["id"]}, {"team_id": teams["Docs"]["id"]}]):
        answer = client.patch(f"/api/conversations/{cid}", json={"teams": wrong}, headers=OWN)
        assert answer.status_code == 422, wrong
    # Away from Manual, the rows go: "No teams" is no rows.
    gone = client.patch(f"/api/conversations/{cid}", json={"teams_mode": "none"}, headers=OWN).json()
    assert (gone["teams_mode"], gone["teams"]) == ("none", [])
    # Rows are the user's in Manual only.
    assert client.patch(f"/api/conversations/{cid}", json={"teams": rows}, headers=OWN).status_code == 422


def test_in_manual_the_lead_opens_only_the_chosen_teams_roles(make_client, wait_run, project_dir):
    client, _model = make_client([
        step(call("spawn_agent", {"role": "Coder", "task": "write it"}, "s1"),
             call("spawn_agent", {"role": "Translator", "task": "translate it"}, "s2")),
        text("translated"), text("done")])
    docs = no_recipe(client, "Docs")["Docs"]  # (0103 gives Docs its own: none here)
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never",
                        teams_mode="manual", teams=[{"team_id": docs["id"]}])
    snap = wait_run(client, cid, run_id)
    (coder, translator) = spawned(snap)
    assert coder[0] == "failed" and "Coder" in coder[1] and "Docs" in coder[1]
    assert translator[0] == "succeeded"
    assert [a["role_name"] for a in snap["agents"]] == ["Lead", "Translator"]


def test_with_no_teams_the_lead_opens_any_role(make_client, wait_run, project_dir):
    client, _model = make_client([
        step(call("spawn_agent", {"role": "Coder", "task": "write it"})), text("written"), text("done")])
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    snap = wait_run(client, cid, run_id)
    assert [status for status, _ in spawned(snap)] == ["succeeded"]


def test_the_lead_picks_teams_it_may_pick_with_a_reason_and_is_held_to_them(
    make_client, wait_run, project_dir
):
    client, model = make_client([
        pick({"team": "DevOps", "why": "it ships"}, id="p0"),
        pick({"team": "docs", "recipe": "Review only", "why": "it is a text to check"}),
        step(call("spawn_agent", {"role": "Coder", "task": "write it"})),
        text("done")])
    teams = teams_of(client)
    assert client.patch(f"/api/teams/{teams['DevOps']['id']}", json={"lead_may_pick": False},
                        headers=OWN).status_code == 200
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never",
                        teams_mode="lead")
    snap = wait_run(client, cid, run_id)
    offered = next(t["function"] for t in model.tool_args[0] if t["function"]["name"] == "pick_teams")
    assert "Docs" in offered["description"] and "DevOps" not in offered["description"]
    picks = [(t["status"], t["result"]) for t in snap["tool_calls"] if t["name"] == "pick_teams"]
    assert picks[0][0] == "failed" and "DevOps" in picks[0][1]
    assert picks[1][0] == "succeeded"
    chat = snap["conversation"]
    assert chat["teams_mode"] == "lead"
    assert [(r["team_id"], r["recipe_id"], r["picked_by"], r["why"]) for r in chat["teams"]] == [
        (teams["Docs"]["id"], recipe(client, "Review only")["id"], "lead", "it is a text to check")]
    ((status, said),) = spawned(snap)
    assert status == "failed" and "Docs" in said
    # To Manual, the Lead's picks stay, the user's now to change.
    moved = client.patch(f"/api/conversations/{cid}", json={"teams_mode": "manual"}, headers=OWN).json()
    assert [r["picked_by"] for r in moved["teams"]] == ["lead"]


def test_pick_teams_is_the_leads_in_lead_decides_only(make_client, wait_run, project_dir):
    client, model = make_client([pick({"team": "Docs", "why": "words"}), text("done")])
    docs = teams_of(client)["Docs"]
    cid, run_id = begin(client, project_dir, teams_mode="manual", teams=[{"team_id": docs["id"]}])
    snap = wait_run(client, cid, run_id)
    assert "pick_teams" not in names(model.tool_args[0])
    ((status, said),) = [(t["status"], t["result"]) for t in snap["tool_calls"] if t["name"] == "pick_teams"]
    assert status == "failed" and "Manual" in said
    assert [r["picked_by"] for r in snap["conversation"]["teams"]] == ["user"]


def test_a_projects_default_teams_are_a_new_chats(make_client, project_dir):
    client, _model = make_client([])
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    docs, feature = teams_of(client)["Docs"], recipe(client, "Feature")
    body = {"teams_mode": "manual", "teams": [{"team_id": docs["id"], "recipe_id": feature["id"]}]}
    assert client.patch(f"/api/projects/{pid}", json=body).status_code == 403
    saved = client.patch(f"/api/projects/{pid}", json=body, headers=OWN)
    assert saved.status_code == 200, saved.text
    assert saved.json()["teams_mode"] == "manual"
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    chat = client.get(f"/api/conversations/{cid}").json()["conversation"]
    assert chat["teams_mode"] == "manual"
    assert [(r["team_id"], r["recipe_id"], r["picked_by"]) for r in chat["teams"]] == [
        (docs["id"], feature["id"], "user")]
    # A team deleted since is not a new chat's.
    assert client.delete(f"/api/teams/{docs['id']}", headers=OWN).status_code == 204
    assert client.get(f"/api/conversations/{cid}").json()["conversation"]["teams"] == []
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    assert client.get(f"/api/conversations/{cid}").json()["conversation"]["teams"] == []
    # (Nor is it kept in the project's default.)
    assert next(p for p in client.get("/api/projects").json() if p["id"] == pid)["teams"] == []
    # Lead decides and No teams are saved as a default too, with no rows - as the window sends them.
    for mode in ("lead", "none"):
        saved = client.patch(f"/api/projects/{pid}", json={"teams_mode": mode, "teams": []}, headers=OWN)
        assert saved.status_code == 200, saved.text
        assert (saved.json()["teams_mode"], saved.json()["teams"]) == (mode, [])


def test_before_the_lead_picks_a_team_it_may_not_pick_stays_shut(make_client, wait_run, project_dir):
    client, _model = make_client([
        step(call("spawn_agent", {"role": "Translator", "task": "translate it"}, "s1"),
             call("spawn_agent", {"role": "Coder", "task": "write it"}, "s2")),
        text("written"), text("done")])
    # Translator is in Docs alone, which the Lead may not pick; Coder is in teams it may.
    docs = teams_of(client)["Docs"]
    assert client.patch(f"/api/teams/{docs['id']}", json={"lead_may_pick": False},
                        headers=OWN).status_code == 200
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never",
                        teams_mode="lead")
    snap = wait_run(client, cid, run_id)
    (translator, coder) = spawned(snap)
    assert translator[0] == "failed" and "Docs" in translator[1], translator
    assert coder[0] == "succeeded"


def test_plan_first_still_plans_and_the_lead_may_pick_while_planning(make_client, wait_run, project_dir):
    client, model = make_client([pick({"team": "Docs", "why": "words"}), text("1. Translate it.")])
    cid, run_id = begin(client, project_dir, teams_mode="lead", plan_first=True)
    snap = wait_run(client, cid, run_id)
    run = next(r for r in snap["runs"] if r["id"] == run_id)
    assert run["plan"]["status"] == "proposed"
    assert "spawn_agent" not in names(model.tool_args[0])
    assert [r["why"] for r in snap["conversation"]["teams"]] == ["words"]


def test_no_recipe_in_one_chat_leaves_the_teams_default_to_the_others(
    make_client, wait_run, project_dir
):
    """K-tarifsiz: a chat's "No recipe" runs its team with none - not its default, which 0103
    gives Docs - while another chat with the team still runs by that default."""
    client, _model = make_client([
        step(call("spawn_agent", {"role": "Translator", "task": "translate it"}, "s1")),
        text("translated"), text("done"),
        step(call("spawn_agent", {"role": "Translator", "task": "translate it"}, "s2")),
        text("done")])
    docs = teams_of(client)["Docs"]
    assert docs["default_recipe_id"]
    bare = {"team_id": docs["id"], "no_recipe": True}
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never",
                        teams_mode="manual", teams=[bare])
    snap = wait_run(client, cid, run_id)
    assert [status for status, _ in spawned(snap)] == ["succeeded"]
    (row,) = snap["conversation"]["teams"]
    assert (row["recipe_id"], row["no_recipe"], row["state"]) == (None, True, None)
    both = [{**bare, "recipe_id": docs["default_recipe_id"]}]
    assert client.patch(f"/api/conversations/{cid}", json={"teams": both},
                        headers=OWN).status_code == 422
    # Another chat with the same team: its default, its first step's role only.
    other = client.post(f"/api/projects/{snap['conversation']['project_id']}/conversations").json()["id"]
    assert client.patch(f"/api/conversations/{other}", json={
        "permission_mode": "full_auto", "spawn_approval": "never", "teams_mode": "manual",
        "teams": [{"team_id": docs["id"]}]}, headers=OWN).status_code == 200
    run_id = client.post(f"/api/conversations/{other}/messages", json={"content": "translate it"},
                         headers=OWN).json()["run"]["id"]
    snap = wait_run(client, other, run_id)
    ((status, said),) = spawned(snap)
    assert status == "failed" and "Docs writer" in said, said
    assert snap["conversation"]["teams"][0]["no_recipe"] is False
    # As a folder's default, a new chat there starts with it.
    pid = snap["conversation"]["project_id"]
    assert client.patch(f"/api/projects/{pid}", json={"teams_mode": "manual", "teams": [bare]},
                        headers=OWN).status_code == 200
    new = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    assert client.get(f"/api/conversations/{new}").json()["conversation"]["teams"][0]["no_recipe"]
