"""A provider, or a model of it, switched off on the Models page: nobody uses it - no chat, no
sub-agent, no Observer - and it keeps its key and settings until it is switched on again."""

import sqlite3

from alembic import command

from tests.test_chat_flow import text
from tests.test_migration_0002 import _config
from tests.test_observer_model_scenarios import REPORT, TASK, child_of, project, turn
from tests.test_spawn import begin, role_id, spawn
from tests.test_team import results, team  # noqa: F401  (a fixture)

OWN = {"Origin": "http://127.0.0.1:8790"}
OFF = "Fast is switched off. Turn it on on the Models page, or pick another model."


def switch(client, provider_id, **body):
    changed = client.patch(f"/api/providers/{provider_id}", headers=OWN, json=body)
    assert changed.status_code == 200, changed.text
    return changed.json()


def chat_on(client, project_dir, provider_id, model_id):
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(f"/api/conversations/{cid}", json={"provider_id": provider_id,
                                                    "model_id": model_id})
    return cid


def say(client, wait_run, cid):
    run = client.post(f"/api/conversations/{cid}/messages", json={"content": "hi"}).json()["run"]
    return wait_run(client, cid, run["id"])["runs"][-1]


def test_a_provider_switched_off_runs_no_chat_keeps_its_key_and_runs_again_when_on(
    team, wait_run, project_dir  # noqa: F811
):
    client, _default, fast = team([], [text("back on")])
    fast_id = team.providers["Fast"]["id"]
    cid = chat_on(client, project_dir, fast_id, "quick")
    told = switch(client, fast_id, enabled=False)
    assert told["enabled"] is False and told["has_key"] is True  # (its key stays)
    ended = say(client, wait_run, cid)
    assert (ended["status"], ended["error"]) == ("failed", f"Lead: {OFF}")
    assert fast.calls == []  # no model call
    # R186: said in the chat too, once, as a line of KOLONİ's own.
    lines = [m["content"] for m in client.get(f"/api/conversations/{cid}").json()["messages"]
             if m["role"] == "koloni"]
    assert lines == [f"Lead: {OFF}"]
    # Not in the team guide either: no agent picks it.
    rows = {r["role"]: r for r in client.get("/api/roles/models").json()}
    assert "Fast" not in rows["Coder"]["pick_from"]
    # An agent's request against the app's address does not switch it back on.
    assert client.patch(f"/api/providers/{fast_id}", json={"enabled": True}).status_code == 403
    switch(client, fast_id, enabled=True)
    assert say(client, wait_run, cid)["status"] == "completed" and len(fast.calls) == 1


def test_a_model_switched_off_is_refused_and_its_providers_others_still_run(
    team, wait_run, project_dir  # noqa: F811
):
    client, _default, fast = team([], [text("quick ran")])
    fast_id = team.providers["Fast"]["id"]
    told = switch(client, fast_id, models=[{"name": "quick"}, {"name": "deep", "enabled": False}])
    assert [m["enabled"] for m in told["models"]] == [None, False]
    cid = chat_on(client, project_dir, fast_id, "deep")
    ended = say(client, wait_run, cid)
    assert ended["error"] == "Lead: " + (
        "Fast's deep is switched off. Turn it on on the Models page, or pick another model.")
    assert fast.calls == []
    # A list saved again without saying it keeps it off (a fill, a page from before).
    told = switch(client, fast_id, models=[{"name": "quick"}, {"name": "deep"}])
    assert [m["enabled"] for m in told["models"]] == [None, False]
    filled = client.post("/api/providers/fill-all/save", headers=OWN, json={"providers": [{
        "id": fast_id, "for_agents": True,
        "models": [{"name": "quick", "tier": "fast"}, {"name": "deep", "tier": "strongest"}]}]})
    assert filled.status_code == 200, filled.text
    fast_row = next(p for p in filled.json() if p["id"] == fast_id)
    assert [(m["tier"], m["enabled"]) for m in fast_row["models"]] == [
        ("fast", None), ("strongest", False)]
    client.patch(f"/api/conversations/{cid}", json={"provider_id": fast_id, "model_id": "quick"})
    assert say(client, wait_run, cid)["status"] == "completed" and len(fast.calls) == 1


def test_the_providers_default_model_switched_off_refuses_a_chat_on_the_default(
    team, wait_run, project_dir  # noqa: F811
):
    client, _default, fast = team([])
    fast_id = team.providers["Fast"]["id"]
    switch(client, fast_id, models=[{"name": "quick", "enabled": False}, {"name": "deep"}])
    cid = chat_on(client, project_dir, fast_id, None)
    assert say(client, wait_run, cid)["error"].startswith("Lead: Fast's quick is switched off.")
    assert fast.calls == []


def test_a_sub_agent_on_a_provider_switched_off_is_not_opened_and_the_user_is_told(
    team, wait_run, project_dir  # noqa: F811
):
    client, _default, fast = team([spawn("Reviewer"), text("done")])
    fast_id = team.providers["Fast"]["id"]
    client.patch(f"/api/roles/{role_id(client, 'Reviewer')}",
                 json={"provider_id": fast_id, "model_id": "deep"})
    switch(client, fast_id, enabled=False)
    cid, run_id = begin(client, project_dir, spawn_approval="never")
    snap = wait_run(client, cid, run_id)
    ((status, said),) = results(snap)
    assert status == "failed" and "Fast is switched off by the user" in said
    assert [a["name"] for a in snap["agents"]] == ["Lead"] and fast.calls == []
    assert [m["content"] for m in snap["messages"] if m["role"] == "koloni"] == [OFF]


def test_the_observer_on_a_provider_switched_off_is_not_asked(team, wait_run, project_dir):  # noqa: F811
    client, default, fast = team([spawn("Reviewer", TASK), text(REPORT), text("Good.")])
    fast_id = team.providers["Fast"]["id"]
    observer = role_id(client, "Observer")
    assert client.patch(f"/api/roles/{observer}", headers=OWN, json={
        "provider_id": fast_id, "model_id": "quick"}).status_code == 200
    switch(client, fast_id, enabled=False)
    cid, run_id = turn(client, project(client, project_dir, observe_reports=True))
    snap = wait_run(client, cid, run_id)
    kid = child_of(snap)
    assert kid["observation"] is None and "Fast is switched off by the user" in (
        kid["observation_note"] or "")
    assert fast.calls == [] and snap["runs"][0]["status"] == "completed"


def test_migration_0144_switches_every_provider_from_before_on_and_back(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0143")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO providers (id, name, kind, position, created_at, updated_at) "
                     "VALUES ('p', 'Local', 'openai_compat', 0, '2026-11-04', '2026-11-04')")
    command.upgrade(cfg, "0144")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT enabled FROM providers").fetchall() == [(1,)]
    command.downgrade(cfg, "0143")
    with sqlite3.connect(db) as conn:
        assert "enabled" not in {row[1] for row in conn.execute("PRAGMA table_info(providers)")}


def test_a_cli_with_no_default_and_every_model_off_does_not_run_its_own():
    # (Its own default, which KOLONİ does not know, may be the very model switched off.)
    import pytest

    from app.db.models import Provider
    from app.providers import SwitchedOff, allowed, stand_in

    cli = Provider(name="Copilot", kind="copilot_cli",
                   models=[{"name": "opus", "agents": True, "enabled": False}])
    assert stand_in(cli) is None
    with pytest.raises(SwitchedOff, match="^Every model of Copilot is switched off"):
        allowed(cli, None)
    cli.models = [*cli.models, {"name": "mini", "agents": True}]
    assert stand_in(cli) == "mini"
    allowed(cli, "mini")


def test_a_plan_is_not_read_for_a_provider_switched_off(team):  # noqa: F811
    client, _default, _fast = team([])
    made = client.post("/api/providers", json={"name": "agy", "kind": "agy_cli"})
    assert made.status_code == 201, made.text
    agy = made.json()["id"]
    limits = client.app.state.providers.limits
    asked = []
    limits._asking = asked.append  # (no CLI is run: who would be asked is recorded)
    switch(client, agy, enabled=False)
    assert client.get(f"/api/providers/{agy}/limits").status_code == 200 and asked == []
    # "Read now" - for Claude Code a model turn - is refused, and nothing is asked.
    checked = client.post(f"/api/providers/{agy}/limits/check", headers=OWN)
    assert (checked.status_code, checked.json()["detail"]) == (409, "agy is switched off")
    assert asked == []
    switch(client, agy, enabled=True)
    client.get(f"/api/providers/{agy}/limits")
    assert [p.name for p in asked] == ["agy"]


def test_a_roles_list_keeps_a_provider_switched_off(team):  # noqa: F811
    client, _default, _fast = team([])
    fast_id = team.providers["Fast"]["id"]
    switch(client, fast_id, enabled=False)
    url = f"/api/roles/{role_id(client, 'Coder')}"
    saved = client.patch(url, headers=OWN, json={"models": [{"provider_id": fast_id,
                                                             "model_id": "deep"}]})
    assert saved.status_code == 200, saved.text
    assert saved.json()["models"] == [{"provider_id": fast_id, "model_id": "deep"}]
    # (Still refused for one not used for sub-agents at all: B-330.)
    paid = team.providers["Paid Api"]["id"]
    refused = client.patch(url, headers=OWN, json={"models": [{"provider_id": paid,
                                                               "model_id": "gold"}]})
    assert refused.status_code == 422
