"""Slice 81b's acceptance set: the Agents page's data - a role's kind of work, on / off, teams (62),
and the tier the Lead picks for each job within the role's range (79). Written before the code.

Design: `tasarim/specs/2026-10-23-dilim-81-agents-models-yeniden-design.md` §2 and §3; teams from
`tasarim/specs/2026-10-20-dilim-62-roller-takimlar-design.md`.

Contract:
- A role has `kind` (the group it is drawn in: built-ins "plan", "build", "check" or "write"; any
  1-40 printable characters the user gives), `enabled` (default true) and `teams` (team ids).
- Its tier rule: `tier` set means always that tier (the user's rule, the Lead cannot change it);
  otherwise `tier_min` / `tier_max` (null: fast / strongest) bound what the Lead may pick. A
  built-in role in a new database has no `tier` and no bounds.
- `spawn_agent` takes `tier` (fast / balanced / strongest) instead of `difficulty`, with `why`
  required when a tier is given. In range: that tier's first model (the user's order, 81a). Out of
  range, or another tier than an "always" role's: refused, saying what is allowed. No tier: balanced,
  or the range's nearest end. The sub-agent's record says the `tier` it ran at.
- A role turned off is not opened unless the user's latest message names it.
- `GET /api/teams` -> [{"id", "name", "roles": [role names]}]: KOLONİ's ready teams to begin with
  (62's table). `POST /api/teams` {"name"} (own page) 201, the same name again 409; `PATCH`
  renames; `DELETE` removes the team, never its roles.
- A conversation's teams (slice 84b's `teams_mode` and `teams`, in place of 62's `team_id`):
  with one, `spawn_agent` opens only that team's roles (the Lead is in every team).
"""

import pytest

from app.db.models import Role

if not hasattr(Role, "kind"):  # written before the code: skipped until it exists
    pytest.skip("slice 81b is not built yet", allow_module_level=True)

from tests.test_chat_flow import text  # noqa: E402
from tests.test_spawn import begin, call, role_id, step  # noqa: E402
from tests.test_team import results, team  # noqa: E402, F401  (a fixture)
from tests.test_tier_scenarios import ORIGIN, tiered  # noqa: E402

WHY = "a two-line fix, the test already exists"


def spawn(role, tier=None, why=None, id="s1"):
    more = {key: value for key, value in (("tier", tier), ("why", why)) if value is not None}
    return call("spawn_agent", {"role": role, "task": "do the thing", **more}, id)


def role(client, name):
    return next(r for r in client.get("/api/roles").json() if r["name"] == name)


def patch_role(client, name, **body):
    return client.patch(f"/api/roles/{role_id(client, name)}", json=body, headers={"Origin": ORIGIN})


# --- kind, on / off ---------------------------------------------------------------------------


def test_ready_roles_come_in_their_kind_of_work_with_no_tier(team):  # noqa: F811
    client, _default, _fast = team([], [])
    kinds = {r["name"]: r["kind"] for r in client.get("/api/roles").json()}
    assert (kinds["Planner"], kinds["Coder"], kinds["DevOps"], kinds["Tester"], kinds["Docs writer"]) == (
        "plan", "build", "ops", "check", "write")  # (DevOps in Ops since K-takim-duzen)
    coder = role(client, "Coder")
    assert (coder["tier"], coder["tier_min"], coder["tier_max"], coder["enabled"]) == (None, None, None, True)
    # A kind is a category's key (slice 63b): "Ship it" is none until the user makes it one.
    assert patch_role(client, "Coder", kind="Ship it").status_code == 422
    assert patch_role(client, "Coder", kind="check").status_code == 200
    assert role(client, "Coder")["kind"] == "check"
    assert patch_role(client, "Coder", kind="").status_code == 422
    assert patch_role(client, "Coder", kind="x" * 41).status_code == 422


def test_a_role_turned_off_is_opened_only_when_the_user_names_it(team, wait_run, project_dir):  # noqa: F811
    client, _default, _fast = team([step(spawn("Translator")), text("done")], [text("translated")])
    assert patch_role(client, "Translator", enabled=False).status_code == 200
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never",
                        content="tidy the greeting")
    snap = wait_run(client, cid, run_id)
    ((status, said),) = results(snap)
    assert status == "failed" and "off" in said.lower() and len(snap["agents"]) == 1

    client2, _d, _f = team([step(spawn("Translator")), text("done")], [text("translated")])
    assert patch_role(client2, "Translator", enabled=False).status_code == 200
    cid, run_id = begin(client2, project_dir, mode="full_auto", spawn_approval="never",
                        content="ask the translator to put the greeting in Turkish")
    snap = wait_run(client2, cid, run_id)
    assert len(snap["agents"]) == 2  # named by the user: opened though off


# --- the tier the Lead picks (79) -------------------------------------------------------------


def test_the_lead_picks_a_tier_in_range_and_says_why(team, wait_run, project_dir):  # noqa: F811
    client, _default, _fast = team([step(spawn("Coder", "balanced", WHY)), text("done")], [text("fixed")])
    tiered(team, client)  # strongest: Local big-model; balanced: Fast deep; fast: Fast quick
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    coder = wait_run(client, cid, run_id)["agents"][1]
    assert ("Fast", "deep") in team.asked
    assert (coder["tier"], coder["chosen_why"]) == ("balanced", WHY)


def test_a_tier_out_of_the_roles_range_is_refused(team, wait_run, project_dir):  # noqa: F811
    client, _default, _fast = team([step(spawn("Coder", "strongest", WHY)), text("done")])
    tiered(team, client)
    assert patch_role(client, "Coder", tier_min="fast", tier_max="balanced").status_code == 200
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    snap = wait_run(client, cid, run_id)
    ((status, said),) = results(snap)
    assert status == "failed" and "balanced" in said and len(snap["agents"]) == 1
    assert patch_role(client, "Coder", tier_min="strongest", tier_max="fast").status_code == 422


def test_a_tier_without_a_reason_is_refused(team, wait_run, project_dir):  # noqa: F811
    client, _default, _fast = team([step(spawn("Coder", "fast")), text("done")])
    tiered(team, client)
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    ((status, said),) = results(wait_run(client, cid, run_id))
    assert status == "failed" and "why" in said


def test_no_tier_said_is_balanced_or_the_nearest_end_of_the_range(team, wait_run, project_dir):  # noqa: F811
    client, _default, _fast = team([step(spawn("Coder")), text("done")], [text("fixed")])
    tiered(team, client)
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    assert wait_run(client, cid, run_id)["agents"][1]["tier"] == "balanced"

    client2, _d, _f = team([step(spawn("Coder")), text("done")], [text("fixed")])
    tiered(team, client2)
    assert patch_role(client2, "Coder", tier_min="strongest").status_code == 200
    cid, run_id = begin(client2, project_dir, mode="full_auto", spawn_approval="never")
    assert wait_run(client2, cid, run_id)["agents"][1]["tier"] == "strongest"


def test_an_always_role_runs_on_its_tier_and_the_lead_cannot_change_it(team, wait_run, project_dir):  # noqa: F811
    client, _default, _fast = team([step(spawn("Security reviewer", "fast", WHY)), text("done")])
    tiered(team, client)
    assert patch_role(client, "Security reviewer", tier="strongest").status_code == 200
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    snap = wait_run(client, cid, run_id)
    ((status, said),) = results(snap)
    assert status == "failed" and "strongest" in said and len(snap["agents"]) == 1

    client2, _d, _f = team([step(spawn("Security reviewer")), text("done")], [text("looked")])
    tiered(team, client2)
    assert patch_role(client2, "Security reviewer", tier="strongest").status_code == 200
    cid, run_id = begin(client2, project_dir, mode="full_auto", spawn_approval="never")
    reviewer = wait_run(client2, cid, run_id)["agents"][1]
    assert reviewer["tier"] == "strongest" and ("Local", "big-model") in team.asked


# --- teams (62) -------------------------------------------------------------------------------


def test_ready_teams_and_the_users_own(team):  # noqa: F811
    client, _default, _fast = team([], [])
    teams = {t["name"]: t for t in client.get("/api/teams").json()}
    assert {"Web app", "Backend / API", "Docs", "Quality"} <= set(teams)
    assert "Coder" in teams["Web app"]["roles"] and "Translator" in teams["Docs"]["roles"]
    assert client.post("/api/teams", json={"name": "Game"}).status_code == 403  # own page only
    made = client.post("/api/teams", json={"name": "Game"}, headers={"Origin": ORIGIN})
    assert made.status_code == 201, made.text
    assert client.post("/api/teams", json={"name": "Game"}, headers={"Origin": ORIGIN}).status_code == 409
    game = made.json()["id"]
    assert patch_role(client, "Tester", teams=[game, teams["Quality"]["id"]]).status_code == 200
    assert set(role(client, "Tester")["teams"]) == {game, teams["Quality"]["id"]}
    assert client.delete(f"/api/teams/{game}", headers={"Origin": ORIGIN}).status_code in (200, 204)
    assert role(client, "Tester")["teams"] == [teams["Quality"]["id"]]  # the role stays


def test_a_conversations_team_opens_only_its_roles(team, wait_run, project_dir):  # noqa: F811
    client, _default, _fast = team([step(spawn("Translator")), text("done")])
    docs = next(t for t in client.get("/api/teams").json() if t["name"] == "Web app")
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never",
                        teams_mode="manual", teams=[{"team_id": docs["id"]}])
    snap = wait_run(client, cid, run_id)
    ((status, said),) = results(snap)
    assert status == "failed" and "Web app" in said and len(snap["agents"]) == 1
