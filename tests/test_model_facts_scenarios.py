"""Slice 59c's acceptance set: a model's facts from one place. Written before the code.

The user: "the model picking must get better, for CLIs and APIs" · "write the reasoning into the
catalogue" · "the catalogue must not grow and grow" · "tiers by family" · models.dev allowed ·
"its costs can be used too". Design: `tasarim/specs/2026-10-20-dilim-59-dusunme-ve-baglam-design.md` §3c.

Contract:
- `app/models_dev.py`: the app ships a trimmed copy of models.dev's `api.json` (same shape:
  provider id -> {"id", "name", "api", "env", "doc", "models": {model id -> {...}}}); a copy at
  `<KOLONI_RUNTIME_ROOT>/models_dev.json` (written by the update button) is read instead when it is
  there. `async def download() -> bytes` fetches `https://models.dev/api.json`; nothing else
  in the app downloads it, and only the user's button calls it.
- An OpenAI-compatible provider is in a models.dev provider's catalogue when the host of its
  address is the host of that provider's `api`; a local address is in none.
- `GET /api/providers/{id}/model-facts?model=<name>` -> {"efforts", "context_window",
  "max_output", "price", "tier", "deprecated", "sources"}: each fact null when unknown (never a
  guess); `sources` names where each known one came from ("models.dev", "catalog", "server",
  "anthropic", "you").
- Levels from `reasoning_options` `{"type": "effort", "values": [...]}` (only those KOLONİ sends);
  a model with only `budget_tokens`, or `reasoning: false`, takes none (`efforts == []`).
- Tier: the user's own row first; else `catalog.json` `tiers` by family / name; else the provider's
  models ranked by `cost.output` (dearest third strongest, middle balanced, cheapest fast); else null.
- `POST /api/catalog/update` (own page only): calls `download()`, checks it is models.dev's JSON,
  trims it and writes the runtime copy; says how many providers and models and when; a bad answer
  changes nothing.
- Model name suggestions (`GET /api/providers/{id}/models`): the user's list, then the catalogue's
  (no deprecated one), then the provider's own list.
- `POST /api/providers/suggest` {"kind", "base_url"} (a provider not added yet): the catalogue's
  model names, and the service's address and key variable where models.dev has them.
"""

import importlib.util
import json

import pytest

if importlib.util.find_spec("app.models_dev") is None:
    pytest.skip("slice 59c is not built yet", allow_module_level=True)  # written before the code

from app import models_dev  # noqa: E402

ORIGIN = {"Origin": "http://127.0.0.1:8790"}

# A small models.dev, in its own shape (field names as its README gives them, 21 Oct). A made-up
# service, so no rule of the shipped catalogue applies to it.
SNAPSHOT = {
    "acme": {
        "id": "acme", "name": "Acme", "api": "https://api.acme.test",
        "env": ["ACME_API_KEY"], "doc": "https://docs.acme.test",
        "models": {
            "acme-chat": {
                "id": "acme-chat", "name": "Acme Chat", "family": "acme",
                "reasoning": False, "tool_call": True,
                "limit": {"context": 128000, "output": 8192},
                "cost": {"input": 0.27, "output": 1.1},
            },
            "acme-reasoner": {
                "id": "acme-reasoner", "name": "Acme Reasoner", "family": "acme-thinking",
                "reasoning": True, "tool_call": True,
                "reasoning_options": [{"type": "effort", "values": ["low", "medium", "high"]}],
                "limit": {"context": 128000, "output": 65536},
                "cost": {"input": 0.55, "output": 2.19},
            },
            "acme-old": {
                "id": "acme-old", "name": "Old", "family": "acme", "status": "deprecated",
                "limit": {"context": 32000, "output": 4096}, "cost": {"input": 1, "output": 2},
            },
            "acme-budget": {
                "id": "acme-budget", "name": "Budget", "family": "acme", "reasoning": True,
                "reasoning_options": [{"type": "budget_tokens", "min": 1024}],
                "limit": {"context": 64000, "output": 8192}, "cost": {"input": 0.1, "output": 0.2},
            },
        },
    },
}


@pytest.fixture
def snapshot(settings_env):
    """models.dev as the runtime copy: read instead of the one the app ships."""
    from pathlib import Path

    root = Path(settings_env["KOLONI_RUNTIME_ROOT"])
    root.mkdir(parents=True, exist_ok=True)
    (root / "models_dev.json").write_text(json.dumps(SNAPSHOT), encoding="utf-8")
    return root / "models_dev.json"


@pytest.fixture
def quiet(monkeypatch):
    """No provider is asked for its own list: no request leaves the machine."""
    from app.api import providers as api

    async def nothing_listed(provider, providers):
        return [], None, False

    monkeypatch.setattr(api, "_own_list", nothing_listed)


def add(client, **body):
    made = client.post("/api/providers", headers=ORIGIN, json={"name": "P", **body})
    assert made.status_code == 201, made.text
    return made.json()


def facts(client, provider, model):
    told = client.get(f"/api/providers/{provider['id']}/model-facts", params={"model": model})
    assert told.status_code == 200, told.text
    return told.json()


# --- a model's facts ---------------------------------------------------------------------------


def test_a_service_at_a_models_dev_address_has_its_models_facts(snapshot, quiet, client):
    acme = add(client, kind="openai_compat", base_url="https://api.acme.test/v1")
    said = facts(client, acme, "acme-reasoner")
    assert said["efforts"] == ["low", "medium", "high"]
    assert said["context_window"] == 128000
    assert said["max_output"] == 65536
    assert said["price"]["input"] == 0.55 and said["price"]["output"] == 2.19
    assert said["sources"]["efforts"] == "models.dev"
    assert said["deprecated"] is False


def test_a_model_that_cannot_be_given_a_level_takes_none_rather_than_a_guess(snapshot, quiet, client):
    acme = add(client, kind="openai_compat", base_url="https://api.acme.test/v1")
    assert facts(client, acme, "acme-chat")["efforts"] == []  # reasoning: false
    assert facts(client, acme, "acme-budget")["efforts"] == []  # budget tokens only


def test_a_model_no_one_knows_is_unknown_not_guessed(snapshot, quiet, client):
    acme = add(client, kind="openai_compat", base_url="https://api.acme.test/v1")
    said = facts(client, acme, "acme-next-year")
    assert said["efforts"] is None and said["context_window"] is None and said["price"] is None
    assert said["tier"] is None


def test_a_server_on_this_machine_is_in_no_services_catalogue(snapshot, quiet, client, monkeypatch):
    local = add(client, kind="openai_compat", base_url="http://127.0.0.1:8080/v1")
    # (Its own server is not asked here - a llama-server of the user's may be on 8080: what
    # llama-server says is pinned below.)
    from app.model_client import ModelInfo, OpenAICompatClient

    async def unknown(self):
        return ModelInfo("acme-chat", True)

    async def no_window(self):
        return None

    monkeypatch.setattr(OpenAICompatClient, "info", unknown)
    monkeypatch.setattr(OpenAICompatClient, "found_window", no_window)
    said = facts(client, local, "acme-chat")
    assert said["context_window"] is None and said["price"] is None
    assert "models.dev" not in said["sources"].values()


def test_a_retired_model_is_marked_and_not_offered(snapshot, quiet, client):
    acme = add(client, kind="openai_compat", base_url="https://api.acme.test/v1",
                   models=[{"name": "acme-old"}])
    assert facts(client, acme, "acme-old")["deprecated"] is True
    offered = client.get(f"/api/providers/{acme['id']}/models").json()["models"]
    assert "acme-old" in offered  # the user's own row stays offered: it still runs
    assert offered.index("acme-old") == 0
    assert "acme-reasoner" in offered and "acme-chat" in offered


def test_a_retired_model_is_not_suggested_for_a_new_provider(snapshot, client):
    said = client.post("/api/providers/suggest", headers=ORIGIN,
                       json={"kind": "openai_compat", "base_url": "https://api.acme.test"})
    assert said.status_code == 200, said.text
    told = said.json()
    assert "acme-reasoner" in told["models"] and "acme-old" not in told["models"]


# --- tiers ---------------------------------------------------------------------------------------


def test_without_a_family_rule_the_tier_follows_the_providers_prices(snapshot, quiet, client):
    acme = add(client, kind="openai_compat", base_url="https://api.acme.test/v1")
    # Not retired: chat 1.1, reasoner 2.19, budget 0.2 a million out.
    assert facts(client, acme, "acme-reasoner")["tier"] == "strongest"
    assert facts(client, acme, "acme-chat")["tier"] == "balanced"
    assert facts(client, acme, "acme-budget")["tier"] == "fast"


def test_the_users_tier_comes_first(snapshot, quiet, client):
    acme = add(client, kind="openai_compat", base_url="https://api.acme.test/v1",
                   models=[{"name": "acme-budget", "tier": "strongest"}])
    said = facts(client, acme, "acme-budget")
    assert said["tier"] == "strongest" and said["sources"]["tier"] == "you"


def test_a_saved_tier_that_is_the_catalogues_is_said_to_be_the_catalogues(snapshot, quiet, client):
    # As a fill saved it: the user changed nothing, so it is not "set by you".
    acme = add(client, kind="openai_compat", base_url="https://api.acme.test/v1",
               models=[{"name": "acme-budget", "tier": "fast"}])
    said = facts(client, acme, "acme-budget")
    assert said["tier"] == "fast" and said["sources"]["tier"] == "models.dev"


def test_the_shipped_catalogue_has_family_rules_not_a_row_per_model():
    from pathlib import Path

    shipped = json.loads((Path(models_dev.__file__).with_name("catalog.json")).read_text("utf-8"))
    assert "anthropic" in shipped["tiers"]
    rules = shipped["tiers"]["anthropic"]
    assert {"opus", "sonnet", "haiku"} <= set(rules)


# --- suggestions ---------------------------------------------------------------------------------


def test_a_new_provider_gets_the_services_models_address_and_key_name(snapshot, client):
    said = client.post("/api/providers/suggest", headers=ORIGIN,
                       json={"kind": "openai_compat", "base_url": "https://api.acme.test"}).json()
    assert said["api"] == "https://api.acme.test"
    assert said["env"] == ["ACME_API_KEY"]
    assert all("acme" not in (p["base_url"] or "") for p in client.get("/api/providers").json())  # nothing saved


def test_an_openai_compatible_provider_is_offered_the_known_addresses(snapshot, client):
    def addresses(kind):
        return client.post("/api/providers/suggest", headers=ORIGIN,
                           json={"kind": kind}).json()["addresses"]

    known = {one["api"]: one["name"] for one in addresses("openai_compat")}
    # The catalogue's services by their own address, and the plans models.dev has none for.
    assert known["https://api.acme.test"] == "Acme"
    assert "Token Plan" in known[
        "https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1"]
    assert addresses("anthropic") == []


def test_suggestions_are_the_users_then_the_catalogues_then_the_providers(snapshot, client, monkeypatch):
    from app.api import providers as api

    async def listed(provider, providers):
        return ["acme-chat", "its-own-new-model"], None, False

    monkeypatch.setattr(api, "_own_list", listed)
    acme = add(client, kind="openai_compat", base_url="https://api.acme.test/v1",
                   models=[{"name": "my-pick"}])
    offered = client.get(f"/api/providers/{acme['id']}/models").json()["models"]
    assert offered[0] == "my-pick"
    assert offered.index("acme-reasoner") < offered.index("its-own-new-model")
    assert offered.count("acme-chat") == 1


# --- the update button ---------------------------------------------------------------------------


def test_the_catalogue_is_updated_only_by_the_users_button(client, settings_env, monkeypatch):
    from pathlib import Path

    asked = []

    async def download():
        asked.append(1)
        return json.dumps(SNAPSHOT).encode()

    monkeypatch.setattr(models_dev, "download", download)
    assert client.post("/api/catalog/update").status_code == 403  # not the app's own page
    assert asked == []
    done = client.post("/api/catalog/update", headers=ORIGIN)
    assert done.status_code == 200, done.text
    told = done.json()
    assert told["providers"] >= 1 and told["models"] >= 1 and told["updated_at"]
    copy = Path(settings_env["KOLONI_RUNTIME_ROOT"]) / "models_dev.json"
    assert "acme" in json.loads(copy.read_text("utf-8"))


def test_a_bad_answer_changes_nothing(snapshot, client, monkeypatch):
    before = snapshot.read_bytes()

    async def broken():
        return b"<html>not models.dev</html>"

    monkeypatch.setattr(models_dev, "download", broken)
    failed = client.post("/api/catalog/update", headers=ORIGIN)
    assert failed.status_code >= 400
    assert snapshot.read_bytes() == before


# --- the local llama-server ------------------------------------------------------------------


@pytest.mark.anyio
async def test_llama_server_that_takes_levels_offers_them_and_off():
    import httpx2

    from app.model_client import OpenAICompatClient

    sent = []

    def handler(request):
        if request.url.path == "/props":
            return httpx2.Response(200, json={
                "default_generation_settings": {"n_ctx": 80128},
                "chat_template_caps": {"supports_reasoning_effort": True},
                "chat_template": "{% if enable_thinking %}…{% endif %}",
            })
        if request.url.path == "/v1/models":
            return httpx2.Response(200, json={"data": [{"id": "qwen"}]})
        sent.append(json.loads(request.content))
        return httpx2.Response(200, json={"choices": [{"message": {"content": ""}}]})

    client = OpenAICompatClient("http://model/v1", transport=httpx2.MockTransport(handler))
    info = await client.info()
    assert info.efforts is not None
    assert {"low", "medium", "high"} <= set(info.efforts) and "off" in info.efforts
