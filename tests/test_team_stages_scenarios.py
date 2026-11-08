"""Slice 63a's acceptance set: a team's own stages in order, which role sits in which, and the
team's lead card - configurable, and not acting yet (84b turns it on). Written before the code.

Design: `tasarim/specs/2026-10-23-dilim-63-84-takimlar-tarifler-design.md` §1, §2 (Teams), §7.

Contract:
- `GET /api/teams` -> each team with `stages` in order ({"id", "name", "together", "roles":
  [role ids]}), its `lead` (a role of kind "lead", named "<team> lead"), `lead_on` and
  `lead_may_pick`. The ready teams come with four stages, Plan, Build, Check, Write & keep up,
  each role in the one of its kind of work; so does a new team.
- A team's lead is in no list of roles (`/api/roles`, who uses what) and no agent is opened in it.
  It is changed through `/api/roles/{id}` like a role, but keeps its name, kind and on / off (the
  team's `lead_on`), is in no team, and goes with its team.
- `POST /api/teams/{id}/stages` {"name"} adds one last; `PATCH .../stages/{sid}` {"name",
  "together"}; `PUT .../stages` {"order": [every stage id]} reorders; `DELETE .../stages/{sid}`
  moves its roles to the first stage left - the last one cannot go.
- `PUT /api/teams/{id}/roles/{role_id}` {"stage_id"} puts a role in that stage of the team (in
  the team too, if it was not): a role is in one stage of a team.
- Every one of these is the user's, from the app's own page.
"""

import pytest

from app.db.models import Team

if not hasattr(Team, "lead_on"):  # written before the code: skipped until it exists
    pytest.skip("slice 63a is not built yet", allow_module_level=True)

from tests.test_chat_flow import text  # noqa: E402
from tests.test_spawn import begin, call, role_id, step  # noqa: E402
from tests.test_team import results  # noqa: E402
from tests.test_tier_scenarios import ORIGIN  # noqa: E402

OWN = {"Origin": ORIGIN}
STAGES = ["Plan", "Build", "Check", "Write & keep up"]
# (How to split a job came later, migration 0105: K-rol-cogul; its roles do every file job,
# 0153: B-202.)
LEAD_SAYS = ("Run your team's stages in order with the recipe you were given. Your roles do the "
             "work: hand every file job and every finding to the right role - you write no file "
             "yourself; report to the Orchestrator. When a job is big and splits into "
             "independent parts (separate files or modules), you may give each part its own "
             "agent, within what your step draws, asked for in one reply, never the same file "
             "to two; a small job goes to one agent.")


def teams(client):
    return {t["name"]: t for t in client.get("/api/teams").json()}


def stage_of(team, rid):
    return next((s["name"] for s in team["stages"] if rid in s["roles"]), None)


def new_team(client, name="Game"):
    made = client.post("/api/teams", json={"name": name}, headers=OWN)
    assert made.status_code == 201, made.text
    return made.json()


def test_the_ready_teams_have_four_stages_their_roles_by_kind_and_a_lead(make_client):
    client, _ = make_client([])
    web = teams(client)["Web app"]
    assert [s["name"] for s in web["stages"]] == STAGES
    assert not any(s["together"] for s in web["stages"])
    assert stage_of(web, role_id(client, "Coder")) == "Build"
    assert stage_of(web, role_id(client, "Tester")) == "Check"
    assert sum(len(s["roles"]) for s in web["stages"]) == len(web["roles"])
    lead = web["lead"]
    assert (lead["name"], lead["kind"], lead["instructions"]) == ("Web app lead", "lead", LEAD_SAYS)
    assert (web["lead_on"], web["lead_may_pick"]) == (True, True)


def test_a_lead_is_in_no_list_of_roles_and_no_agent_is_opened_in_it(make_client, wait_run,
                                                                     project_dir):
    client, model = make_client([
        step(call("spawn_agent", {"role": "Web app lead", "task": "run the team"})), text("done")])
    names = [r["name"] for r in client.get("/api/roles").json()]
    assert "Web app lead" not in names and "Coder" in names
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    snap = wait_run(client, cid, run_id)
    ((status, _said),) = results(snap)
    assert status == "failed" and len(snap["agents"]) == 1
    offered = next(t for t in model.tool_args[0] if t["function"]["name"] == "spawn_agent")
    assert "Coder" in str(offered) and "Web app lead" not in str(offered)


def test_a_new_team_comes_with_the_stages_and_a_lead_that_go_with_it(make_client):
    client, _ = make_client([])
    assert client.post("/api/teams", json={"name": "Game"}).status_code == 403  # own page only
    game = new_team(client)
    assert [s["name"] for s in game["stages"]] == STAGES and game["lead"]["name"] == "Game lead"
    # The lead is named after its team: renamed with it.
    assert client.patch(f"/api/teams/{game['id']}", json={"name": "Games"},
                        headers=OWN).status_code == 200
    assert teams(client)["Games"]["lead"]["name"] == "Games lead"
    # A name whose lead would not fit a role's name, or whose lead's name is taken, is refused.
    assert client.post("/api/teams", json={"name": "x" * 56}, headers=OWN).status_code == 422
    assert client.post("/api/teams", json={"name": "x" * 55}, headers=OWN).status_code == 201
    mine = client.post("/api/roles", json={"name": "Art lead", "tools": ["read_file"]}, headers=OWN)
    assert mine.status_code == 201
    assert client.post("/api/teams", json={"name": "Art"}, headers=OWN).status_code == 409
    lead = teams(client)["Games"]["lead"]["id"]
    assert client.delete(f"/api/teams/{game['id']}", headers=OWN).status_code == 204
    assert client.get(f"/api/roles/{lead}/jobs").status_code == 404  # gone with its team


def test_a_teams_stages_are_added_renamed_reordered_and_removed(make_client):
    client, _ = make_client([])
    game = new_team(client)
    url = f"/api/teams/{game['id']}/stages"
    assert client.post(url, json={"name": "Playtest"}).status_code == 403
    added = client.post(url, json={"name": "Playtest"}, headers=OWN)
    assert added.status_code == 201, added.text
    play = next(s for s in added.json()["stages"] if s["name"] == "Playtest")
    assert [s["name"] for s in added.json()["stages"]] == [*STAGES, "Playtest"]
    changed = client.patch(f"{url}/{play['id']}", json={"name": "Play", "together": True},
                           headers=OWN)
    assert changed.status_code == 200, changed.text
    assert (changed.json()["stages"][-1]["name"], changed.json()["stages"][-1]["together"]) == (
        "Play", True)
    ids = [s["id"] for s in changed.json()["stages"]]
    moved = client.put(url, json={"order": [ids[-1], *ids[:-1]]}, headers=OWN)
    assert moved.status_code == 200, moved.text
    assert [s["name"] for s in moved.json()["stages"]] == ["Play", *STAGES]
    # The order names every stage of the team, once.
    assert client.put(url, json={"order": ids[:-1]}, headers=OWN).status_code == 422
    assert client.patch(f"{url}/{play['id']}", json={"name": " "}, headers=OWN).status_code == 422
    for stage in ids[:-1]:
        assert client.delete(f"{url}/{stage}", headers=OWN).status_code == 200
    assert client.delete(f"{url}/{play['id']}", headers=OWN).status_code == 409  # the last one


def test_a_role_sits_in_one_stage_of_a_team_and_a_stage_removed_gives_its_roles_to_the_first(
    make_client,
):
    client, _ = make_client([])
    web = teams(client)["Web app"]
    stages = {s["name"]: s["id"] for s in web["stages"]}
    coder, docs = role_id(client, "Coder"), role_id(client, "Docs writer")
    put = f"/api/teams/{web['id']}/roles"
    assert client.put(f"{put}/{coder}", json={"stage_id": stages["Plan"]}).status_code == 403
    assert client.put(f"{put}/{coder}", json={"stage_id": stages["Plan"]},
                      headers=OWN).status_code == 200
    web = teams(client)["Web app"]
    assert stage_of(web, coder) == "Plan" and sum(coder in s["roles"] for s in web["stages"]) == 1
    # One not in the team joins it there; its other teams are kept.
    assert client.put(f"{put}/{docs}", json={"stage_id": stages["Check"]},
                      headers=OWN).status_code == 200
    assert stage_of(teams(client)["Web app"], docs) == "Check"
    assert stage_of(teams(client)["Docs"], docs) == "Write & keep up"
    # Another team's stage, or the lead, is refused.
    other = teams(client)["Docs"]["stages"][0]["id"]
    assert client.put(f"{put}/{coder}", json={"stage_id": other}, headers=OWN).status_code == 422
    lead = web["lead"]["id"]
    assert client.put(f"{put}/{lead}", json={"stage_id": stages["Plan"]},
                      headers=OWN).status_code == 422
    # Removed: its roles go to the first stage left, none leaves the team.
    tester = role_id(client, "Tester")
    assert client.delete(f"/api/teams/{web['id']}/stages/{stages['Check']}",
                         headers=OWN).status_code == 200
    web = teams(client)["Web app"]
    assert stage_of(web, tester) == "Plan" and stage_of(web, docs) == "Plan"


def test_a_role_put_in_a_team_from_its_panel_goes_to_its_kinds_stage_and_keeps_the_others(
    make_client,
):
    client, _ = make_client([])
    by_name = teams(client)
    web, quality = by_name["Web app"], by_name["Quality"]
    tester = role_id(client, "Tester")
    plan = web["stages"][0]["id"]
    assert client.put(f"/api/teams/{web['id']}/roles/{tester}", json={"stage_id": plan},
                      headers=OWN).status_code == 200
    mine = next(r for r in client.get("/api/roles").json() if r["id"] == tester)["teams"]
    game = new_team(client)["id"]
    patched = client.patch(f"/api/roles/{tester}", json={"teams": [*mine, game]}, headers=OWN)
    assert patched.status_code == 200, patched.text
    after = teams(client)
    assert stage_of(after["Game"], tester) == "Check"  # its kind of work's
    assert stage_of(after["Web app"], tester) == "Plan"  # kept where the user put it
    assert stage_of(after["Quality"], tester) == stage_of(quality, tester)


def test_the_lead_card_is_changed_like_a_role_and_keeps_what_makes_it_the_teams(make_client):
    client, _ = make_client([])
    web = teams(client)["Web app"]
    lead = web["lead"]["id"]
    url = f"/api/roles/{lead}"
    changed = client.patch(url, json={"instructions": "Keep it short.", "tier": "strongest",
                                      "tools": ["read_file", "spawn_agent"],
                                      # As its form sends them: unchanged, no refusal.
                                      "name": "Web app lead", "kind": "lead"}, headers=OWN)
    assert changed.status_code == 200, changed.text
    lead_now = teams(client)["Web app"]["lead"]
    assert (lead_now["instructions"], lead_now["tier"], lead_now["tools"]) == (
        "Keep it short.", "strongest", ["read_file", "spawn_agent"])
    for body in ({"name": "Boss"}, {"kind": "build"}, {"enabled": False},
                 {"teams": [web["id"]]}):
        assert client.patch(url, json=body, headers=OWN).status_code == 422, body
    assert client.delete(url, headers=OWN).status_code == 409
    # Its on / off and whether the Lead may pick the team are the team's.
    assert client.patch(f"/api/teams/{web['id']}", json={"lead_on": False}).status_code == 403
    off = client.patch(f"/api/teams/{web['id']}", json={"lead_on": False, "lead_may_pick": False},
                       headers=OWN)
    assert off.status_code == 200, off.text
    web = teams(client)["Web app"]
    assert (web["lead_on"], web["lead_may_pick"], web["name"]) == (False, False, "Web app")
    # A team's lead is its team's: "lead" is no category a role of the user's can be given
    # (slice 63b), and the user's own is a role as any other - listed, renamed, deleted.
    assert client.post("/api/roles", json={"name": "Boss", "tools": ["read_file"], "kind": "lead"},
                       headers=OWN).status_code == 422
    boss = client.post("/api/roles", json={"name": "Boss", "tools": ["read_file"]}, headers=OWN)
    assert boss.status_code == 201, boss.text
    assert "Boss" in [r["name"] for r in client.get("/api/roles").json()]
    url = f"/api/roles/{boss.json()['id']}"
    assert client.patch(url, json={"name": "Chief", "enabled": False}, headers=OWN).status_code == 200
    assert client.delete(url, headers=OWN).status_code == 204


def test_renaming_a_team_is_a_change_to_its_lead(make_client):
    client, _ = make_client([])
    web = teams(client)["Web app"]
    assert client.patch(f"/api/teams/{web['id']}", json={"name": "Site"}, headers=OWN).status_code == 200
    assert teams(client)["Site"]["lead"]["updated_at"] > web["lead"]["updated_at"]


def test_the_lead_and_the_observer_sit_in_no_stage(make_client):
    client, _ = make_client([])
    web = teams(client)["Web app"]
    for name in ("Lead", "Observer"):
        placed = client.put(f"/api/teams/{web['id']}/roles/{role_id(client, name)}",
                            json={"stage_id": web["stages"][0]["id"]}, headers=OWN)
        assert placed.status_code == 422, name


def test_a_command_is_for_no_teams_lead(make_client):
    client, _ = make_client([])
    made = client.post("/api/own-commands", json={"name": "ship", "template": "ship it",
                                              "role": "Web app lead"}, headers=OWN)
    assert made.status_code == 422, made.text


def test_an_agent_is_told_a_name_is_a_teams_lead_and_gives_it_no_skill(make_client, wait_run,
                                                                       project_dir):
    client, _model = make_client([
        step(call("create_role", {"name": "Web app lead", "tools": ["read_file"]}, "r1"),
             call("add_skill", {"folder": str(project_dir), "roles": ["Web app lead"]}, "k1")),
        text("done")])
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    snap = wait_run(client, cid, run_id)
    said = {t["name"]: t["result"] for t in snap["tool_calls"]}
    assert "team's coordinator" in said["create_role"] and "spawn_agent" not in said["create_role"]
    assert "team's coordinator" in said["add_skill"]


def test_a_no_recipe_teams_lead_is_told_its_stages_in_order_and_opens_them_so(make_client, wait_run,
                                                                              project_dir):
    # B-171 (live): the user's game studio, Plan (Spec writer) → Build (Coder) → Check (Reviewer) with no
    # recipe, beside Docs: its lead never opened the Spec writer though the user asked for a short plan first.
    from tests.test_recipe_ends_scenarios import SCRIPTS
    from tests.test_recipe_run_scenarios import READY, answer, asked
    from tests.test_spawn import spawn
    client, model = make_client({
        **SCRIPTS, "Lead": [spawn("Game lead", "the game", "l1"), text("done")],
        "Game lead": [spawn("Spec writer", "a short plan", "p"), spawn("Coder", "build it", "b"),
                      spawn("Reviewer", "check it", "c"), text("game done")],
        "Spec writer": [text("the plan")], "Coder": [text("built")],
        "Reviewer": [text("Fine.\n\nFindings: none")]})
    game = new_team(client)
    stages = {s["name"]: s["id"] for s in game["stages"]}
    for name, stage in (("Spec writer", "Plan"), ("Coder", "Build"), ("Reviewer", "Check")):
        put = client.put(f"/api/teams/{game['id']}/roles/{role_id(client, name)}",
                         json={"stage_id": stages[stage]}, headers=OWN)
        assert put.status_code == 200, put.text
    cid, run_id = begin(client, project_dir, mode="full_auto", teams_mode="manual",
                        content="Game: first a short plan, then build it, then check it; Docs: its README",
                        teams=[{"team_id": game["id"], "recipe_id": None},
                               {"team_id": teams(client)["Docs"]["id"], "recipe_id": None}],
                        spawn_approval="never")
    from tests.test_parallel import until
    snap = until(client, cid, lambda s: s["runs"][-1]["status"] != "running" or (
        asked(s) and READY in asked(s)["question"]))
    if asked(snap):
        answer(client, asked(snap), "Take in")
    snap = wait_run(client, cid, run_id)
    told = model.calls_of["Game lead"][0][1]["content"]
    # (The stage left empty, Write & keep up, is not named.)
    assert ("Work in your team's stages, in order: Plan (Spec writer) → Build (Coder) → Check "
            "(Reviewer).") in told
    lead = next(a["id"] for a in snap["agents"] if a["role_name"] == "Game lead")
    assert [a["role_name"] for a in snap["agents"] if a["parent_agent_id"] == lead] == [
        "Spec writer", "Coder", "Reviewer"]
