"""Slice 49: which model writes the plan, and what never plans."""

from tests.fakes import ScriptedModel
from tests.test_auto_notes import on
from tests.test_chat_flow import text
from tests.test_claude_native import BASH, WRITE, claude_app, hello  # noqa: F401  (a fixture)
from tests.test_recall_scenarios import memory
from tests.test_spawn import begin
from tests.test_team import team  # noqa: F401  (a fixture)
from tests.test_tier_scenarios import ORIGIN
from tests.test_trigger_scenarios import run_now, trigger

PLAN = "PLAN: 1. look. 2. say done."


def lead_of(snap, run_id):
    return next(a for a in snap["agents"] if a["run_id"] == run_id and a["depth"] == 0)


def test_the_plan_is_written_by_the_teams_strongest_model_and_the_work_by_the_conversations(
    team, wait_run, project_dir  # noqa: F811
):
    client, _default, _fast = team([text("done")], [text(PLAN)])
    client.headers["Origin"] = ORIGIN
    fast = team.providers["Fast"]["id"]
    assert client.patch(f"/api/providers/{fast}", json={
        "models": [{"name": "quick"}, {"name": "deep", "tier": "strongest"}]}).status_code == 200
    cid, run_id = begin(client, project_dir, plan_first=True)
    snap = wait_run(client, cid, run_id)
    plan = next(r for r in snap["runs"] if r["id"] == run_id)["plan"]
    assert (plan["text"], plan["status"], plan["strongest"]) == (PLAN, "proposed", True)
    assert lead_of(snap, run_id)["provider_name"] == "Fast" and ("Fast", "deep") in team.asked
    work = client.post(f"/api/runs/{run_id}/plan/approve", json={}).json()["run_id"]
    snap = wait_run(client, cid, work)
    assert lead_of(snap, work)["provider_name"] == "Local"
    # approved as it was, a second answer finds nothing to decide
    assert client.post(f"/api/runs/{run_id}/plan/reject", json={}).status_code == 409


def test_with_no_strongest_model_the_conversations_own_writes_the_plan(
    team, wait_run, project_dir  # noqa: F811
):
    client, _default, _fast = team([text(PLAN)])
    cid, run_id = begin(client, project_dir, plan_first=True)
    snap = wait_run(client, cid, run_id)
    plan = next(r for r in snap["runs"] if r["id"] == run_id)["plan"]
    assert (plan["text"], plan["strongest"], plan["model_id"]) == (PLAN, False, "big-model")
    assert lead_of(snap, run_id)["provider_name"] == "Local"
    # turned off only from the app's own page; on, from anywhere
    off = {"plan_first": False}
    assert client.patch(f"/api/conversations/{cid}", json=off).status_code == 403
    assert client.patch(f"/api/conversations/{cid}", json=off, headers={"Origin": ORIGIN}).status_code == 200
    assert client.patch(f"/api/conversations/{cid}", json={"plan_first": True}).status_code == 200


def test_a_triggers_turn_never_plans(team, wait_run, project_dir):  # noqa: F811
    client, _default, _fast = team([text("first"), text("from the trigger")])
    client.headers["Origin"] = ORIGIN
    cid, first = begin(client, project_dir, plan_first=True)
    wait_run(client, cid, first)
    pid = client.get(f"/api/conversations/{cid}").json()["conversation"]["project_id"]
    run_id = run_now(client, trigger(client, pid, cid)["id"])
    snap = wait_run(client, cid, run_id)
    run = next(r for r in snap["runs"] if r["id"] == run_id)
    assert (run["status"], run["plan"], run["plan_turn"]) == ("completed", None, False)


def test_an_older_plan_is_not_approved_once_a_later_turn_has_started_but_may_be_turned_down(
    team, wait_run, project_dir  # noqa: F811
):
    client, _default, _fast = team([text(PLAN), text("PLAN B"), text("done")])
    client.headers["Origin"] = ORIGIN
    cid, first = begin(client, project_dir, plan_first=True)
    wait_run(client, cid, first)
    second = client.post(f"/api/conversations/{cid}/messages", json={"content": "b"}).json()
    wait_run(client, cid, second["run"]["id"])
    stale = client.post(f"/api/runs/{first}/plan/approve", json={})
    assert stale.status_code == 409 and "a later turn has started" in stale.json()["detail"]
    assert client.post(f"/api/runs/{first}/plan/reject", json={}).status_code == 200
    before = client.get(f"/api/conversations/{cid}").json()["conversation"]["updated_at"]
    work = client.post(f"/api/runs/{second['run']['id']}/plan/approve", json={}).json()["run_id"]
    snap = wait_run(client, cid, work)
    assert snap["conversation"]["updated_at"] > before  # its turn is activity, as a message is
    assert [r["plan"]["status"] for r in snap["runs"][:2]] == ["rejected", "approved"]


def test_a_plan_turn_notes_nothing_in_the_projects_memory(
    team, wait_run, project_dir  # noqa: F811
):
    client, _default, fast = team([text(PLAN)], [text("[]")])
    pid = on(team, client, project_dir)
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(f"/api/conversations/{cid}", json={"plan_first": True})
    run_id = client.post(f"/api/conversations/{cid}/messages", json={"content": "a"}).json()[
        "run"]["id"]
    assert wait_run(client, cid, run_id)["runs"][0]["plan"]["text"] == PLAN
    assert fast.calls == [] and memory(client, pid)["last_auto"] is None


def test_a_cli_with_tools_of_its_own_plans_with_them_off(team, wait_run, project_dir):  # noqa: F811
    client, _default, _fast = team([])
    client.headers["Origin"] = ORIGIN
    codex = team.providers["Codex"]["id"]
    # as it speaks in a discussion: one step at a time, KOLONİ's reading tools only
    talker = ScriptedModel([text(PLAN)], model_id="codex-talk")
    team.stubs["Codex"].talker = lambda: talker
    cid, run_id = begin(client, project_dir, "full_auto", plan_first=True, provider_id=codex)
    run = wait_run(client, cid, run_id)["runs"][0]
    assert (run["status"], run["plan"]["text"]) == ("completed", PLAN), run["error"]
    assert team.stubs["Codex"].started == 0 and not {"write_file", "run_command"} & {
        t["function"]["name"] for t in talker.tool_args[0]}
    # one that cannot be had so says why, and starts nothing
    team.stubs["Codex"].talker = lambda: team.stubs["Codex"]
    again = client.post(f"/api/conversations/{cid}/messages", json={"content": "b"}).json()
    run = wait_run(client, cid, again["run"]["id"])["runs"][1]
    assert run["status"] == "failed" and "cannot write a plan" in run["error"]
    assert team.stubs["Codex"].started == 0


def test_claude_code_plans_with_its_writing_and_running_tools_disallowed_and_no_mcp(
    claude_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _ = claude_app([WRITE, BASH, {"say": PLAN}])
    cid, run_id = begin(client, project_dir, "full_auto", plan_first=True,
                        provider_id=provider["id"])
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["plan"]["text"] == PLAN, snap["runs"][0]["error"]
    argv = claude_app.record()["argv"]
    assert {"Write", "Edit", "Bash"} <= set(argv[argv.index("--disallowedTools") + 1].split(","))
    assert [v["behavior"] for v in claude_app.record()["asked"]] == ["deny", "deny"]
    assert hello(project_dir) == "print('hi')\n" and snap["agents"][0]["mcp"] == []
