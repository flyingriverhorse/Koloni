"""Slice 81a's acceptance set: the Models page's tier slots - the order in which a tier's models
are tried is the user's. Written before the code.

Design: `tasarim/specs/2026-10-23-dilim-81-agents-models-yeniden-design.md` §1 ("Katman yuvaları").

Contract:
- `GET /api/tiers` -> {"strongest": [...], "balanced": [...], "fast": [...]}, each a list of
  {"provider_id", "provider_name", "model"} in the order they are tried. Until the user orders
  them: providers in their order, then each provider's models in its list's order (as today).
- `PUT /api/tiers` (the app's own page only) with the same shape ({"provider_id", "model"} is
  enough) saves the order and answers like GET. Each tier's list must be exactly the models that
  have that tier: one missing, one more, or one of another tier is 422 - the order is set here,
  the tier on the provider.
- The first model of a tier that may be picked (`Would.first`) follows that order.
- A model that changes tier leaves its old tier's order and comes last in its new one.
"""

import importlib
import pkgutil

import pytest

import app.api
from tests.test_chat_flow import text
from tests.test_parallel import until
from tests.test_spawn import begin, call, spawn, step
from tests.test_team import team  # noqa: F401  (a fixture)
from tests.test_tier_scenarios import ORIGIN, role_tier, tiered


def _built() -> bool:
    for found in pkgutil.iter_modules(app.api.__path__):
        router = getattr(importlib.import_module(f"app.api.{found.name}"), "router", None)
        if router and any(getattr(route, "path", "").endswith("/tiers") for route in router.routes):
            return True
    return False


if not _built():
    pytest.skip("slice 81a is not built yet", allow_module_level=True)  # written before the code


def both_strongest(team, client):  # noqa: F811
    """Local · big-model and Fast · deep both strongest; Fast · quick fast."""
    local, fast = tiered(team, client)
    assert client.patch(f"/api/providers/{fast}", json={"models": [
        {"name": "quick", "tier": "fast"}, {"name": "deep", "tier": "strongest"}]}).status_code == 200
    return local["id"], fast


def order(client, tier):
    told = client.get("/api/tiers")
    assert told.status_code == 200, told.text
    return [(one["provider_name"], one["model"]) for one in told.json()[tier]]


def picked(client, role):
    rows = {row["role"]: row for row in client.get("/api/roles/models").json()}
    return rows[role]["provider_name"], rows[role]["model_id"], rows[role]["source"]


def test_until_the_user_orders_them_a_tier_is_tried_in_the_providers_order(team):  # noqa: F811
    client, _default, _fast = team([], [])
    both_strongest(team, client)
    assert order(client, "strongest") == [("Local", "big-model"), ("Fast", "deep")]
    assert order(client, "fast") == [("Fast", "quick")]
    assert order(client, "balanced") == []
    role_tier(client, "Reviewer", "strongest")
    assert picked(client, "Reviewer") == ("Local", "big-model", "tier")


def test_the_users_order_decides_which_model_of_a_tier_runs(team):  # noqa: F811
    client, _default, _fast = team([], [])
    local, fast = both_strongest(team, client)
    role_tier(client, "Reviewer", "strongest")
    body = {"strongest": [{"provider_id": fast, "model": "deep"}, {"provider_id": local, "model": "big-model"}],
            "balanced": [], "fast": [{"provider_id": fast, "model": "quick"}]}
    del client.headers["Origin"]
    assert client.put("/api/tiers", json=body).status_code == 403  # only the app's own page
    client.headers["Origin"] = ORIGIN
    saved = client.put("/api/tiers", json=body)
    assert saved.status_code == 200, saved.text
    assert [(one["provider_name"], one["model"]) for one in saved.json()["strongest"]] == [
        ("Fast", "deep"), ("Local", "big-model")]
    assert order(client, "strongest") == [("Fast", "deep"), ("Local", "big-model")]
    assert picked(client, "Reviewer") == ("Fast", "deep", "tier")


@pytest.mark.parametrize("strongest", [
    "missing",   # big-model left out
    "extra",     # quick is fast, not strongest
    "unknown",   # a model no provider has
], ids=str)
def test_the_order_is_set_here_and_the_tier_on_the_provider(team, strongest):  # noqa: F811
    client, _default, _fast = team([], [])
    local, fast = both_strongest(team, client)
    lists = {
        "missing": [{"provider_id": fast, "model": "deep"}],
        "extra": [{"provider_id": fast, "model": "deep"}, {"provider_id": local, "model": "big-model"},
                  {"provider_id": fast, "model": "quick"}],
        "unknown": [{"provider_id": fast, "model": "deep"}, {"provider_id": local, "model": "big-model"},
                    {"provider_id": fast, "model": "nobody-has-it"}],
    }
    refused = client.put("/api/tiers", json={
        "strongest": lists[strongest], "balanced": [], "fast": [{"provider_id": fast, "model": "quick"}]})
    assert refused.status_code == 422, refused.text
    assert order(client, "strongest") == [("Local", "big-model"), ("Fast", "deep")]  # nothing saved


def test_a_model_that_changes_tier_comes_last_in_its_new_one(team):  # noqa: F811
    client, _default, _fast = team([], [])
    local, fast = both_strongest(team, client)
    client.put("/api/tiers", json={
        "strongest": [{"provider_id": fast, "model": "deep"}, {"provider_id": local, "model": "big-model"}],
        "balanced": [], "fast": [{"provider_id": fast, "model": "quick"}]})
    # quick becomes strongest: it joins at the end, and the user's order before it stays
    assert client.patch(f"/api/providers/{fast}", json={"models": [
        {"name": "quick", "tier": "strongest"}, {"name": "deep", "tier": "strongest"}]}).status_code == 200
    assert order(client, "strongest") == [("Fast", "deep"), ("Local", "big-model"), ("Fast", "quick")]
    assert order(client, "fast") == []


def test_a_provider_that_looked_down_is_passed_over_until_it_is_seen_again(team, monkeypatch):  # noqa: F811
    from app.api import providers as api

    client, _default, _fast = team([], [])
    local, fast = both_strongest(team, client)
    role_tier(client, "Reviewer", "strongest")
    down = {local}

    async def listed(provider, providers):  # its server's list, as it answers now
        if provider.id in down:
            return [], "model server unreachable: refused", False
        return ["big-model", "deep", "quick"], None, False

    monkeypatch.setattr(api, "_own_list", listed)

    def look(provider_id):
        assert client.get(f"/api/providers/{provider_id}/availability").status_code == 200

    look(local)
    assert picked(client, "Reviewer") == ("Fast", "deep", "tier")
    # Every one of the tier down: an old reading does not leave it without one.
    down.add(fast)
    look(fast)
    assert picked(client, "Reviewer") == ("Local", "big-model", "tier")
    down.clear()
    look(local)
    assert picked(client, "Reviewer") == ("Local", "big-model", "tier")
    look(fast)
    down.add(local)
    look(local)
    assert picked(client, "Reviewer") == ("Fast", "deep", "tier")
    # A check that it answers is seeing it again.
    down.clear()
    assert client.post(f"/api/providers/{local}/test").json()["ok"] is True
    assert picked(client, "Reviewer") == ("Local", "big-model", "tier")


def test_only_a_list_nothing_answered_holds_a_tier_back_and_only_for_a_while(team, monkeypatch):  # noqa: F811
    import httpx2

    from app import providers as kinds
    from app.api import providers as api
    from app.model_client import OpenAICompatClient

    client, _default, _fast = team([], [])
    local, _fast_id = both_strongest(team, client)
    role_tier(client, "Reviewer", "strongest")
    answer = {"now": 404}

    def server(request):  # the server's /models, as it answers now
        if answer["now"] == "refused":
            raise httpx2.ConnectError("refused", request=request)
        return httpx2.Response(answer["now"], json={"error": "no such route"})

    async def served(base_url, key):
        return await OpenAICompatClient(base_url, key, transport=httpx2.MockTransport(server)).models()

    monkeypatch.setattr(api, "served_models", served)

    def look():
        assert client.get(f"/api/providers/{local}/availability").status_code == 200

    look()  # no /models here: its chat may work all the same
    assert picked(client, "Reviewer") == ("Local", "big-model", "tier")
    answer["now"] = 200  # an answer that is no list says no more
    look()
    assert picked(client, "Reviewer") == ("Local", "big-model", "tier")
    answer["now"] = "refused"
    look()
    assert picked(client, "Reviewer") == ("Fast", "deep", "tier")
    # Its time over, it is tried again: a server started after the page read it.
    with client.app.state.session_factory() as session:
        why, _until = kinds.looked_down(session)[local]
        kinds.looked_down(session)[local] = (why, 0.0)
    assert picked(client, "Reviewer") == ("Local", "big-model", "tier")


def _down(client, monkeypatch, *down):
    """Those providers looked down when last looked at: a tier passes them over."""
    from app.api import providers as api

    async def listed(provider, providers):
        return ([], "model server unreachable: refused", False) if provider.id in down else (
            ["big-model", "deep", "quick", "gold"], None, False)

    monkeypatch.setattr(api, "_own_list", listed)
    for one in down:
        assert client.get(f"/api/providers/{one}/availability").status_code == 200


def test_koloni_moving_an_agent_onto_a_pay_per_token_provider_asks_at_full_auto_once(
        team, wait_run, project_dir, monkeypatch):  # noqa: F811
    # B-373 / R173 (the user's call): past Fable's full plan KOLONİ opened the Coder on a paid
    # API key, at Full auto and spawn approval "auto", with no card.
    client, _default, fast = team([spawn("Reviewer", id="s1"), spawn("Reviewer", id="s2"),
                                   text("done")], [])
    local, _fast = both_strongest(team, client)
    role_tier(client, "Reviewer", "strongest")
    _down(client, monkeypatch, local)  # (Local, on this machine, first; Fast is an API key)
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="auto")
    snap = until(client, cid, lambda s: any(a["status"] == "proposed" for a in s["agents"]))
    reviewer = next(a for a in snap["agents"] if a["status"] == "proposed")
    assert reviewer["provider_name"] == "Fast"
    assert "Fast is paid per token, Local is not: the user says whether it is used" in reviewer[
        "chosen_why"]
    assert client.post(f"/api/agents/{reviewer['id']}/reject").status_code == 200
    snap = wait_run(client, cid, run_id)
    first, again = [t for t in snap["tool_calls"] if t["name"] == "spawn_agent"]
    assert first["status"] == "denied"
    # Its word stands for the turn: not asked again, and nothing ran on the paid key.
    assert again["status"] == "failed", again
    assert "the user said no to its pay-per-token use in this turn" in again["result"]
    assert [a["status"] for a in snap["agents"][1:]] == ["rejected"] and not fast.calls


def test_no_card_where_the_roles_own_model_is_paid_per_token_already(
        team, wait_run, project_dir, monkeypatch):  # noqa: F811
    client, _default, _fast = team([spawn("Reviewer"), text("done")], [text("looked")])
    fast, paid = team.providers["Fast"]["id"], team.providers["Paid Api"]["id"]
    client.headers["Origin"] = ORIGIN
    assert client.patch(f"/api/providers/{fast}", json={"models": [
        {"name": "deep", "tier": "strongest"}]}).status_code == 200
    assert client.patch(f"/api/providers/{paid}", json={"for_agents": True, "models": [
        {"name": "gold", "tier": "strongest"}]}).status_code == 200
    role_tier(client, "Reviewer", "strongest")
    assert picked(client, "Reviewer") == ("Fast", "deep", "tier")
    _down(client, monkeypatch, fast)
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="auto")
    snap = wait_run(client, cid, run_id)
    reviewer = snap["agents"][1]
    assert reviewer["provider_name"] == "Paid Api" and reviewer["status"] != "rejected"
    assert snap["questions"] == [] and "paid per token" not in (reviewer["chosen_why"] or "")


def test_a_paid_move_in_a_turn_nobody_watches_is_refused_also_past_a_cli_it_skips(
        team, wait_run, project_dir, monkeypatch):  # noqa: F811
    # Review M3: nobody is there to say yes. Past a down Local - and past a CLI that works with
    # tools of its own, which such a turn never runs (no `moved` said then).
    from tests.test_triggers import leave, place, run_now, trigger

    for skipped in ("down", "cli"):
        client, _default, fast = team([spawn("Reviewer"), text("done")], [text("looked")])
        local, fast_id = both_strongest(team, client)
        if skipped == "down":
            _down(client, monkeypatch, local)
        else:
            codex = team.providers["Codex"]["id"]
            assert client.patch(f"/api/providers/{local}", json={"models": [
                {"name": "big-model"}]}).status_code == 200
            assert client.patch(f"/api/providers/{codex}", json={"models": [
                {"name": "gpt-x", "tier": "strongest"}]}).status_code == 200
            assert client.put("/api/tiers", json={
                "strongest": [{"provider_id": codex, "model": "gpt-x"},
                              {"provider_id": fast_id, "model": "deep"}],
                "balanced": [], "fast": [{"provider_id": fast_id, "model": "quick"}]},
            ).status_code == 200
        role_tier(client, "Reviewer", "strongest")
        pid, cid = place(client, project_dir, permission_mode="full_auto")
        run_id = run_now(client, trigger(client, pid, cid, permissions=leave(agents=2))["id"])
        snap = wait_run(client, cid, run_id)
        (opening,) = [t for t in snap["tool_calls"] if t["name"] == "spawn_agent"]
        assert opening["status"] != "succeeded", skipped
        assert "nobody is watching this turn to be asked about money" in opening["result"], opening[
        "result"]
        assert len(snap["agents"]) == 1 and not fast.calls


def test_a_paid_move_of_a_room_member_is_asked_and_a_discussion_member_is_sent_to_spawn_agent(
        team, wait_run, project_dir, monkeypatch):  # noqa: F811
    # Review M2: a room's and a discussion's members are opened on the same rule.
    room = step(call("open_room", {"goal": "agree", "with": ["Coder", "Reviewer"],
                                   "follow": False}, "o"))
    talk = step(call("discuss", {"topic": "agree", "with": ["Reviewer"], "rounds": 1}, "d"))
    client, _default, fast = team([talk, room, text("done")], [])
    local, _fast = both_strongest(team, client)
    role_tier(client, "Reviewer", "strongest")
    _down(client, monkeypatch, local)
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="auto")
    snap = until(client, cid, lambda s: any(a["status"] == "proposed" and a["role_name"] == (
        "Reviewer") for a in s["agents"]))
    reviewer = next(a for a in snap["agents"] if a["status"] == "proposed"
                    and a["role_name"] == "Reviewer")
    assert reviewer["provider_name"] == "Fast" and reviewer["chosen_why"].startswith(
        "Fast is paid per token, Local is not")
    assert client.post(f"/api/agents/{reviewer['id']}/reject").status_code == 200
    snap = wait_run(client, cid, run_id)
    said = {t["name"]: t for t in snap["tool_calls"]}
    assert said["discuss"]["status"] == "failed"
    assert "open it with spawn_agent first" in said["discuss"]["result"]
    assert "Fast is paid per token" in said["discuss"]["result"]
    assert said["open_room"]["status"] != "succeeded" and not fast.calls


def test_a_no_on_a_card_asked_for_more_than_money_does_not_bar_the_provider(
        team, wait_run, project_dir, monkeypatch):  # noqa: F811
    # Review L3: spawn approval "always" asks this card anyway - its no is about this agent.
    client, _default, _fast = team([spawn("Reviewer", id="s1"), spawn("Reviewer", id="s2"),
                                    text("done")], [])
    local, _fast = both_strongest(team, client)
    role_tier(client, "Reviewer", "strongest")
    _down(client, monkeypatch, local)
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="always")
    for _ in range(2):  # (asked twice: the first no barred nothing)
        snap = until(client, cid, lambda s: any(a["status"] == "proposed" for a in s["agents"]))
        kid = next(a for a in snap["agents"] if a["status"] == "proposed")
        assert client.post(f"/api/agents/{kid['id']}/reject").status_code == 200
    snap = wait_run(client, cid, run_id)
    assert [t["status"] for t in snap["tool_calls"] if t["name"] == "spawn_agent"] == [
        "denied", "denied"]
