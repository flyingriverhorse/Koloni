"""K-copilot-baglam: a Copilot model's context window tier, set on its row of the Models page
and passed as `--context long_context` (CLI 1.0.103's --help) - only on the user's GitHub
account, and nothing for the default, so that a run is as it always was."""

import json

import pytest

from app import catalog
from app.config import load_settings
from app.db.models import Provider
from app.model_native import CopilotNativeClient
from app.model_session import CopilotSessionClient
from app.providers import Providers
from tests.test_copilot_agent import FAKE, HEADLESS
from tests.test_copilot_signin import plan, run_once

ORIGIN = {"Origin": "http://127.0.0.1:8790"}
LONG = {"name": "gpt-x", "tier": "strongest", "context": "long_context"}


def made(client, **more):
    answer = client.post("/api/providers", headers=ORIGIN, json={
        "name": "Copilot", "kind": "copilot_cli", "default_model": "gpt-x", **more})
    return answer


def test_a_context_tier_is_only_for_copilot_on_a_github_account(client):
    body = made(client, models=[LONG]).json()
    assert body["models"][0]["context"] == "long_context"
    own_server = made(client, name="Copilot 2", base_url="http://localhost:8080/v1",
                      models=[LONG])
    assert own_server.status_code == 422 and "GitHub account" in own_server.text
    claude = client.post("/api/providers", headers=ORIGIN, json={
        "name": "Claude", "kind": "claude_cli", "models": [LONG]})
    assert claude.status_code == 422
    odd = made(client, name="Copilot 3", models=[{**LONG, "context": "huge"}])
    assert odd.status_code == 422


def test_the_tier_survives_other_saves_and_goes_with_a_server_of_ones_own(client):
    body = made(client, models=[LONG]).json()
    url = f"/api/providers/{body['id']}"
    # A tier changed by a row that says nothing of its context keeps the context.
    changed = client.patch(url, headers=ORIGIN, json={
        "models": [{"name": "gpt-x", "tier": "balanced", "agents": True}]}).json()
    assert changed["models"][0]["context"] == "long_context"
    # The fill-all preview's rows come back with what they had.
    saved = client.post("/api/providers/fill-all/save", headers=ORIGIN, json={"providers": [{
        "id": body["id"], "for_agents": True, "models": [{**LONG, "tier": "fast"}]}]})
    assert saved.status_code == 200, saved.text
    mine = next(p for p in saved.json() if p["id"] == body["id"])
    assert mine["models"][0]["context"] == "long_context"
    # ... as the catalogue proposes them: the user's rows first, with their tier.
    assert catalog.fill("copilot_cli", [LONG], [])[0][0]["context"] == "long_context"
    # The default is passing nothing: it is not kept.
    back = client.patch(url, headers=ORIGIN, json={
        "models": [{**LONG, "context": "default"}]}).json()
    assert back["models"][0]["context"] is None
    client.patch(url, headers=ORIGIN, json={"models": [LONG]})
    # On a model server of one's own the tier means nothing; later saves still go through.
    moved = client.patch(url, headers=ORIGIN, json={"base_url": "http://localhost:8080/v1"})
    assert moved.status_code == 200 and moved.json()["models"][0]["context"] is None
    assert client.patch(url, headers=ORIGIN, json={"models": [
        {"name": "gpt-x", "tier": "fast"}]}).status_code == 200


@pytest.mark.parametrize("mode", ["session", "native"])
def test_only_the_row_that_asks_for_it_runs_with_the_long_context(settings_env, tmp_path, mode):
    providers = Providers(load_settings(settings_env))

    def arguments(model, **more):
        client = providers._build(Provider(
            id="p", name="Copilot", kind="copilot_cli", mode=mode,
            models=[LONG, {"name": "gpt-y", "tier": "fast"}], **more), model)
        if isinstance(client, CopilotNativeClient):
            return client._native_arguments(tmp_path, tmp_path / "bridge.json")
        return client._account_arguments()

    long = arguments("gpt-x")
    assert long[long.index("--context") + 1] == "long_context"
    assert "--context" not in arguments("gpt-y")
    assert "--context" not in arguments("gpt-x", base_url="http://localhost:8080/v1",
                                        default_model="gpt-x")


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize(("context", "passed"), [("long_context", True), (None, False)])
def test_copilot_is_started_with_the_long_context_only_when_it_is_set(
    settings_env, tmp_path, wait_run, project_dir, monkeypatch, native, context, passed
):
    record = plan(tmp_path, monkeypatch, script=[{"say": "hello"}])
    build, launcher = (CopilotNativeClient, HEADLESS) if native else (CopilotSessionClient, FAKE)
    cli = build(None, "gpt-x", timeout=30, launcher=launcher, options={}, context=context)
    run = run_once(settings_env, cli, project_dir, wait_run)
    assert run["status"] == "completed", run["error"]
    argv = json.loads(record.read_text(encoding="utf-8"))["argv"]
    assert (argv[argv.index("--context") + 1] == "long_context") if passed else (
        "--context" not in argv)


def test_where_copilot_sends_its_key_is_set_only_from_the_apps_page(client):
    """Copilot's key goes to its model server (COPILOT_PROVIDER_API_KEY): a command an agent
    runs against the app's address, which says no origin, may point neither elsewhere."""
    server = {"base_url": "https://models.example/v1", "api_key": "ghp_secret"}
    unsaid = client.post("/api/providers", json={
        "name": "Copilot", "kind": "copilot_cli", **server})
    assert unsaid.status_code == 403
    body = made(client).json()  # on the GitHub account, from the page
    url = f"/api/providers/{body['id']}"
    for change in ({"base_url": server["base_url"]}, {"api_key": "ghp_other"}):
        assert client.patch(url, json=change).status_code == 403
        assert client.patch(url, headers=ORIGIN, json=change).status_code == 200
    # (Remote is allowed: a Copilot model server need not be on this machine.)
    assert made(client, name="Copilot 2", **server).status_code == 201
