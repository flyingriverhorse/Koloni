"""Copilot's `auto` and `fusion` rows take a routing (1.0.114's package: Auto Efficiency /
Balance / Intelligence, Fusion Standard / High / Max): set on the model's row, only on the
user's GitHub account, sent as `--auto-tier` / `--fusion-tier` to a session and as
session.create's `capi` natively - never both."""

import json

import pytest

from app import catalog
from app.config import load_settings
from app.db.models import Provider
from app.model_native import CopilotNativeClient
from app.model_session import CopilotSessionClient
from app.providers import Providers
from tests.test_copilot_agent import HEADLESS
from tests.test_copilot_signin import plan, run_once

ORIGIN = {"Origin": "http://127.0.0.1:8790"}
AUTO = {"name": "auto", "tier": "fast", "routing": "intelligence"}
FUSION = {"name": "fusion", "routing": "high"}


def made(client, **more):
    return client.post(
        "/api/providers",
        headers=ORIGIN,
        json={"name": "Copilot", "kind": "copilot_cli", "default_model": "auto", **more},
    )


def test_a_routing_is_only_for_copilots_auto_and_fusion_on_a_github_account(client):
    body = made(client, models=[AUTO, FUSION]).json()
    assert [m["routing"] for m in body["models"]] == ["intelligence", "high"]
    for name, models in (
        ("Copilot 2", [{"name": "gpt-x", "routing": "balance"}]),  # not auto or fusion
        ("Copilot 3", [{**AUTO, "routing": "high"}]),  # fusion's, on auto
        ("Copilot 4", [{**FUSION, "routing": "balance"}]),  # auto's, on fusion
        ("Copilot 5", [{**AUTO, "routing": "fast"}]),
    ):  # (integrator-only: not offered)
        assert made(client, name=name, models=models).status_code == 422, name
    own_server = made(client, name="Copilot 6", base_url="http://localhost:8080/v1", models=[AUTO])
    assert own_server.status_code == 422 and "GitHub account" in own_server.text
    claude = client.post(
        "/api/providers",
        headers=ORIGIN,
        json={"name": "Claude", "kind": "claude_cli", "models": [AUTO]},
    )
    assert claude.status_code == 422


def test_the_routing_survives_other_saves_and_goes_with_a_server_of_ones_own(client):
    body = made(client, models=[AUTO]).json()
    url = f"/api/providers/{body['id']}"
    changed = client.patch(
        url, headers=ORIGIN, json={"models": [{"name": "auto", "tier": "balanced", "agents": True}]}
    ).json()
    assert changed["models"][0]["routing"] == "intelligence"
    saved = client.post(
        "/api/providers/fill-all/save",
        headers=ORIGIN,
        json={
            "providers": [
                {"id": body["id"], "for_agents": True, "models": [{**AUTO, "tier": "strongest"}]}
            ]
        },
    )
    assert saved.status_code == 200, saved.text
    assert next(p for p in saved.json() if p["id"] == body["id"])["models"][0]["routing"] == (
        "intelligence"
    )
    assert catalog.fill("copilot_cli", [AUTO], [])[0][0]["routing"] == "intelligence"
    back = client.patch(url, headers=ORIGIN, json={"models": [{**AUTO, "routing": None}]}).json()
    assert back["models"][0]["routing"] is None
    client.patch(url, headers=ORIGIN, json={"models": [AUTO]})
    moved = client.patch(url, headers=ORIGIN, json={"base_url": "http://localhost:8080/v1"})
    assert moved.status_code == 200 and moved.json()["models"][0]["routing"] is None
    assert (
        client.patch(
            url, headers=ORIGIN, json={"models": [{"name": "auto", "tier": "fast"}]}
        ).status_code
        == 200
    )


def test_a_routing_is_set_only_from_the_apps_page(client):
    body = made(client, models=[{"name": "auto"}]).json()
    url = f"/api/providers/{body['id']}"
    assert client.patch(url, json={"models": [AUTO]}).status_code == 403
    assert client.patch(url, headers=ORIGIN, json={"models": [AUTO]}).status_code == 200


@pytest.mark.parametrize("mode", ["session", "native"])
def test_only_the_row_that_asks_for_it_runs_with_its_routing(settings_env, tmp_path, mode):
    providers = Providers(load_settings(settings_env))

    def built(model, **more):
        return providers._build(
            Provider(
                id="p",
                name="Copilot",
                kind="copilot_cli",
                mode=mode,
                models=[AUTO, FUSION, {"name": "gpt-y", "routing": None}],
                **more,
            ),
            model,
        )

    def argv(client):
        if isinstance(client, CopilotNativeClient):
            return client._native_arguments(tmp_path, tmp_path / "bridge.json")
        return client._account_arguments()

    if mode == "session":
        auto, fusion = argv(built("auto")), argv(built("fusion"))
        assert auto[auto.index("--auto-tier") + 1] == "intelligence"
        assert "--fusion-tier" not in auto
        assert fusion[fusion.index("--fusion-tier") + 1] == "high"
        assert "--auto-tier" not in fusion
    else:  # (natively it goes in session.create, not its argv)
        assert not {"--auto-tier", "--fusion-tier"} & set(argv(built("auto")))
    for client in (
        built("gpt-y"),
        built("auto", base_url="http://localhost:8080/v1", default_model="auto"),
    ):
        assert not {"--auto-tier", "--fusion-tier"} & set(argv(client))


def test_fusion_takes_no_thinking_level_as_auto_does():
    for client in (CopilotSessionClient(None, "fusion"), CopilotNativeClient(None, "fusion")):
        assert client.efforts == () and client.level_named
    told, said = catalog.facts("copilot_cli", None, "fusion")
    assert told["efforts"] == [] and said["efforts"] == "Copilot picks it (auto)"


def test_the_catalogue_offers_fusion_with_no_tier():
    rows = {row["name"]: row for row in catalog.models_for("copilot_cli")}
    assert rows["fusion"]["tier"] is None and "costs more than auto" in rows["fusion"]["note"]
    assert rows["auto"]["tier"] == "fast"


@pytest.mark.parametrize(
    ("model", "routing", "protocol", "sent"),
    [
        ("auto", "intelligence", 3, {"capi": {"autoTier": "intelligence"}}),
        ("fusion", "high", 4, {"github": {"capi": {"fusionTier": "high"}}}),
        ("gpt-x", "high", 4, {}),
    ],
)
def test_natively_its_routing_goes_in_its_session(
    settings_env, tmp_path, wait_run, project_dir, monkeypatch, model, routing, protocol, sent
):
    record = plan(
        tmp_path,
        monkeypatch,
        script=[{"say": "hello"}],
        protocol=protocol,
        version="1.0.105" if protocol == 3 else "1.0.114",
    )
    cli = CopilotNativeClient(
        None, model, timeout=30, launcher=HEADLESS, options={}, routing=routing
    )
    run = run_once(settings_env, cli, project_dir, wait_run)
    assert run["status"] == "completed", run["error"]
    seen = json.loads(record.read_text(encoding="utf-8"))
    made = seen["create"]
    assert {key: made[key] for key in ("capi", "github") if key in made} == sent
    capi = made.get("capi") or made.get("github", {}).get("capi") or {}
    assert not {"autoTier", "fusionTier"} <= set(capi)  # never both
    assert "autoTier" not in made  # (not a session.create field of its own)
    assert not {"--auto-tier", "--fusion-tier"} & set(seen["argv"])


def test_a_routing_the_plan_lacks_is_named_as_the_cause(
    settings_env, tmp_path, wait_run, project_dir, monkeypatch
):
    """Live (1.0.114, 21 Nov 2026): Fusion High on a plan without it is refused at session.create.
    The turn says the routing is the cause - not "run it as a session", which would be refused
    too - and not in the words that switch a model's row off (`_refused`)."""
    plan(tmp_path, monkeypatch, script=[], protocol=4, version="1.0.114", handshake="tier")
    cli = CopilotNativeClient(
        None, "fusion", timeout=30, launcher=HEADLESS, options={}, routing="high"
    )
    run = run_once(settings_env, cli, project_dir, wait_run)
    assert run["status"] == "failed"
    assert run["error"] == (
        "Copilot refused fusion at High (This tier is not available for the user's Copilot "
        "plan): pick another routing for it on the Models page or in the chat's model panel"
    )
    assert "on your account" not in run["error"]
