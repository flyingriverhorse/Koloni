"""Slice 81a: whether agents may use a model is said of each model, not of its provider. A
model switched off is never an agent's pick; the user can still pick it by hand."""

from app.providers import list_providers
from app.team import guide
from tests.test_chat_flow import text
from tests.test_spawn import begin
from tests.test_team import team  # noqa: F401  (a fixture)
from tests.test_tier_order_scenarios import both_strongest, order, picked
from tests.test_tier_scenarios import role_tier, tiered


def models(client, provider):
    return next(p for p in client.get("/api/providers").json() if p["id"] == provider)


def test_a_model_switched_off_is_passed_over_for_the_next_of_its_tier(team):  # noqa: F811
    client, _default, _fast = team([], [])
    local, fast = both_strongest(team, client)
    role_tier(client, "Reviewer", "strongest")
    assert picked(client, "Reviewer") == ("Local", "big-model", "tier")
    assert client.patch(f"/api/providers/{local}", json={
        "models": [{"name": "big-model", "tier": "strongest", "agents": False}]}).status_code == 200
    assert picked(client, "Reviewer") == ("Fast", "deep", "tier")
    # it keeps its place in the tier's order, said as off
    told = client.get("/api/tiers").json()["strongest"]
    assert [(one["model"], one["agents"]) for one in told] == [("big-model", False), ("deep", True)]
    assert order(client, "strongest") == [("Local", "big-model"), ("Fast", "deep")]


def test_with_every_model_off_the_provider_is_out_of_agents_picks_and_back_with_one_on(team):  # noqa: F811
    client, _default, _fast = team([], [])
    _local, fast = both_strongest(team, client)
    off = [{"name": "quick", "tier": "fast", "agents": False}, {"name": "deep", "tier": "strongest", "agents": False}]
    assert client.patch(f"/api/providers/{fast}", json={"models": off}).status_code == 200
    assert models(client, fast)["for_agents"] is False
    with client.app.state.session_factory() as session:
        assert "Fast" not in [entry.name for entry in guide(list_providers(session))]
    one = [{**off[0], "agents": True}, off[1]]
    assert client.patch(f"/api/providers/{fast}", json={"models": one}).status_code == 200
    assert models(client, fast)["for_agents"] is True
    with client.app.state.session_factory() as session:
        entry = next(e for e in guide(list_providers(session)) if e.name == "Fast")
        assert (entry.models, entry.tiers) == ((("quick", None),), (("quick", "fast"),))


def test_a_flag_said_with_the_models_is_kept_and_fill_all_keeps_its_own(team):  # noqa: F811
    client, _default, _fast = team([], [])
    _local, fast = both_strongest(team, client)
    told = client.patch(f"/api/providers/{fast}", json={
        "for_agents": False, "models": [{"name": "quick", "tier": "fast"}]})
    assert told.json()["for_agents"] is False  # said in the same request: as said
    assert told.json()["models"] == [{"name": "quick", "note": None, "tier": "fast", "agents": True, "enabled": None, "off_why": None, "inputs": None,
                                      "context": None}]
    def fill_all(*agents):
        rows = [{"name": name, "tier": "fast", "agents": on} for name, on in zip(("quick", "deep"), agents, strict=True)]
        saved = client.post("/api/providers/fill-all/save", json={"providers": [{
            "id": fast, "for_agents": True, "models": rows}]})
        assert saved.status_code == 200, saved.text
        return [m["agents"] for m in models(client, fast)["models"]]

    assert fill_all(False, True) == [False, True] and models(client, fast)["for_agents"] is True
    # ticked with every model off, the tick would do nothing: they come back on
    assert fill_all(False, False) == [True, True]
    assert client.patch(f"/api/providers/{fast}", json={
        "models": [{"name": "quick", "agents": "yes"}]}).status_code == 422


def test_the_lead_asks_how_hard_the_first_fast_model_in_the_users_order(team, wait_run, project_dir):  # noqa: F811
    client, _default, fast = team(
        [text("the lead answers")], [text("hard: it needs care"), text("unused")])
    local, fast_id = tiered(team, client)
    # Local has a fast model too, so before the user orders the tier it comes first.
    assert client.patch(f"/api/providers/{local['id']}", json={"models": [
        {"name": "big-model", "tier": "strongest"}, {"name": "little", "tier": "fast"}]}).status_code == 200
    assert order(client, "fast") == [("Local", "little"), ("Fast", "quick")]
    assert client.put("/api/tiers", json={
        "strongest": [{"provider_id": local["id"], "model": "big-model"}],
        "balanced": [{"provider_id": fast_id, "model": "deep"}],
        "fast": [{"provider_id": fast_id, "model": "quick"}, {"provider_id": local["id"], "model": "little"}],
    }).status_code == 200
    cid, run_id = begin(client, project_dir, lead_auto=True)
    rows = {row["role"]: row for row in client.get(
        "/api/roles/models", params={"conversation_id": cid}).json()}
    assert rows["Lead"]["asks_how_hard"] == {"provider_name": "Fast", "model_id": "quick"}
    lead = wait_run(client, cid, run_id)["agents"][0]
    assert (lead["asked_how_hard"], lead["chosen_why"]) == (
        {"provider_name": "Fast", "model_id": "quick"}, "hard: it needs care")
    assert len(fast.calls) == 1


def test_a_list_saved_without_saying_it_keeps_a_model_switched_off(team):  # noqa: F811
    client, _default, _fast = team([], [])
    _local, fast = both_strongest(team, client)
    assert client.patch(f"/api/providers/{fast}", json={"models": [
        {"name": "quick", "tier": "fast", "agents": False}, {"name": "deep", "tier": "strongest"}]}).status_code == 200
    # an older page, or a command, sends the list without `agents`: what was off stays off
    assert client.patch(f"/api/providers/{fast}", json={"models": [
        {"name": "quick", "tier": "fast", "note": "now noted"}, {"name": "deep", "tier": "strongest"}]}).status_code == 200
    assert [(m["name"], m["agents"]) for m in models(client, fast)["models"]] == [("quick", False), ("deep", True)]


def test_what_agents_may_pick_is_changed_only_from_the_apps_own_page(team):  # noqa: F811
    client, _default, _fast = team([], [])
    _local, fast = both_strongest(team, client)
    del client.headers["Origin"]
    for body in ({"models": [{"name": "quick", "agents": False}]}, {"for_agents": False}):
        assert client.patch(f"/api/providers/{fast}", json=body).status_code == 403
    assert client.patch(f"/api/providers/{fast}", json={"note": "Fine from anywhere."}).status_code == 200
    assert models(client, fast)["for_agents"] is True


def test_a_model_a_fill_adds_follows_the_providers_way():
    from app import catalog

    off = catalog.fill("alibaba", [{"name": "mine", "agents": False}], ["qwen3.8-max"])[0]
    assert [(row["name"], row["agents"]) for row in off] == [("mine", False), ("qwen3.8-max", False)]
    on = catalog.fill("alibaba", [{"name": "mine"}], ["qwen3.8-max"])[0]
    assert [row.get("agents", True) for row in on] == [True, True]  # (a row that never said it is on)
