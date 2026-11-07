"""Slice 60d's acceptance set: every provider's tiers filled from the catalogue at once, previewed
before anything is saved. Written before the code.

The user (20 Oct): "all roles 'same as conversation' makes no sense: the Lead should know the models
we have and how strong each is". Design: `tasarim/specs/2026-10-20-dilim-60-sayfalar-ve-model-gucu-design.md`
§3 and §3b; the Agents / Models layout in `tasarim/specs/60-ornekler/agents-models.html`.

Contract:
- `POST /api/providers/fill-all` (the app's own page): a proposal for every provider, nothing saved:
  {"providers": [{"id", "name", "kind", "for_agents", "models": [{"name", "tier", "note", ...}]}]}.
  A subscription CLI (Claude Code, Codex, agy, Qoder) comes ticked for agents; a provider that is paid
  per token (an API key) comes unticked; one with no catalogue keeps its own rows and tick as they are.
- `POST /api/providers/fill-all/save` {"providers": [...]} (own page): saves what was shown, in one go.
"""

import pytest

from app.api import providers as api

if not any(getattr(route, "path", "") == "/api/providers/fill-all" for route in api.router.routes):
    pytest.skip("slice 60d is not built yet", allow_module_level=True)  # written before the code

ORIGIN = {"Origin": "http://127.0.0.1:8790"}


@pytest.fixture
def quiet(monkeypatch):
    async def nothing_listed(provider, providers):  # no request leaves the machine
        return [], None, False

    monkeypatch.setattr(api, "_own_list", nothing_listed)
    # Every CLI counts as installed: what this machine has is not the test's business.
    monkeypatch.setattr(api.catalog, "installed", lambda kind, executable: True)

    async def not_known(kind, executable, home=None):  # and no CLI is asked whether it is signed in
        return None

    monkeypatch.setattr(api.catalog, "signed_in", not_known)


def add(client, **body):
    made = client.post("/api/providers", headers=ORIGIN, json={"name": body.pop("name"), **body})
    assert made.status_code == 201, made.text
    return made.json()


def proposed(client):
    told = client.post("/api/providers/fill-all", headers=ORIGIN)
    assert told.status_code == 200, told.text
    return {p["name"]: p for p in told.json()["providers"]}


def test_the_proposal_saves_nothing_and_ticks_subscriptions_only(client, quiet):
    claude = add(client, name="Claude Code", kind="claude_cli")
    keyed = add(client, name="Anthropic API", kind="anthropic", api_key="sk-test")
    local = add(client, name="Own server", kind="openai_compat", base_url="http://127.0.0.1:8080/v1",
                models=[{"name": "qwen-local", "tier": "balanced"}])
    told = proposed(client)
    assert told["Claude Code"]["for_agents"] is True
    assert told["Anthropic API"]["for_agents"] is False
    tiers = {m["tier"] for m in told["Claude Code"]["models"]}
    assert {"strongest", "balanced", "fast"} <= tiers
    # a server of one's own keeps its rows as the user wrote them
    assert [(m["name"], m["tier"]) for m in told["Own server"]["models"]] == [("qwen-local", "balanced")]
    # nothing saved by being proposed
    now = {p["id"]: p for p in client.get("/api/providers").json()}
    for made in (claude, keyed, local):
        assert now[made["id"]]["models"] == made["models"]
        assert now[made["id"]]["for_agents"] == made["for_agents"]
    assert "sk-test" not in str(told)


def test_saving_the_proposal_gives_the_lead_a_fast_model(client, quiet):
    add(client, name="Claude Code", kind="claude_cli")
    told = proposed(client)
    assert client.post("/api/providers/fill-all/save", json={"providers": list(told.values())}).status_code == 403
    saved = client.post("/api/providers/fill-all/save", headers=ORIGIN, json={"providers": list(told.values())})
    assert saved.status_code == 200, saved.text
    (claude,) = [p for p in client.get("/api/providers").json() if p["name"] == "Claude Code"]
    assert claude["for_agents"] is True
    assert any(m["tier"] == "fast" for m in claude["models"])
