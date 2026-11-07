"""K-model-sec: an Anthropic provider with no model, a key Anthropic refuses, and a key that
is a Claude subscription token (the only kind the API is known to refuse).

What the user hit: an Anthropic provider saved with its Default model left empty (the Models
page showed "e.g. claude-sonnet-5-5" in grey there), a conversation with no model of its own,
and every turn failed with "choose a model for this provider" - from inside the client, with
nothing said of which agent, which provider or what to do."""

import httpx2
import pytest

from app.db.models import Provider
from app.model_anthropic import AnthropicClient
from app.model_client import ModelUnavailable
from app.providers import NotListed, allowed, search_apis
from tests.test_spawn import begin
from tests.test_team import team  # noqa: F401  (a fixture)

OWN = {"Origin": "http://127.0.0.1:8790"}
# The user's own was of a prefix nobody knows; this one stands for it.
KEY = "sk-ant-usr-DO-NOT-LEAK-0123456789"
NAME = "Claude-Subscription-API"


def anthropic(client, **more):
    made = client.post("/api/providers", json={
        "name": NAME, "kind": "anthropic", "api_key": KEY, **more}, headers=OWN)
    assert made.status_code == 201, made.text
    return made.json()


def lead_row(client, cid):
    rows = client.get("/api/roles/models", params={"conversation_id": cid}).json()
    return next(row for row in rows if row["role"] == "Lead")


# --- the root cause: an Anthropic provider with no model ----------------------------------


@pytest.mark.parametrize("lead_auto", [True, False])
def test_an_anthropic_provider_with_no_model_is_refused_before_the_turn_with_why(
    team, wait_run, project_dir, lead_auto  # noqa: F811
):
    client, default, fast = team([])
    # As the Models page sends it with the Default model field left empty.
    provider = anthropic(client, default_model="")
    assert provider["default_model"] is None
    # Its own client, as the app builds it, not the stand-in every other provider has here
    # (with no model it asks nothing of the network).
    client.app.state.providers.override = None
    # No tier is given a model: the automatic Lead has nobody to ask, and changes nothing.
    cid, run_id = begin(client, project_dir, provider_id=provider["id"], model_id=None,
                        lead_auto=lead_auto)
    run = wait_run(client, cid, run_id)["runs"][0]
    assert run["status"] == "failed"
    error = run["error"]
    # which agent, which provider, and what to do - not the client's own bare words
    assert "choose a model for this provider" not in error
    assert error.startswith("Lead: ") and NAME in error and "Models page" in error
    assert KEY not in error and default.calls == [] and fast.calls == []
    # and it is said before any turn: in the table of who uses what
    row = lead_row(client, cid)
    assert (row["provider_name"], row["model_id"]) == (NAME, None)
    assert NAME in row["cannot_run"]


def test_with_a_default_model_the_lead_and_its_automatic_choice_have_a_model(
    team, project_dir  # noqa: F811
):
    # (The other places a model could come from - the automatic Lead, a tier, a sub-agent's
    # tier - give a model's name or nothing at all: it is the provider's default that was empty.)
    client, _default, _fast = team([])
    provider = anthropic(client, default_model="claude-sonnet-5-5")
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(f"/api/conversations/{cid}", json={
        "provider_id": provider["id"], "model_id": None, "lead_auto": True}, headers=OWN)
    row = lead_row(client, cid)
    assert (row["model_id"], row["cannot_run"]) == ("claude-sonnet-5-5", None)


def test_a_role_on_the_provider_with_no_model_takes_the_conversations_model_of_it(
    team, project_dir  # noqa: F811
):
    # What the user hit next: the Lead role set to the provider, with no model of its own; the
    # model picked in the conversation, of the same provider, was passed over and it refused.
    client, _default, _fast = team([])
    provider = anthropic(client, default_model="")
    lead = next(r for r in client.get("/api/roles").json() if r["name"] == "Lead")
    assert client.patch(f"/api/roles/{lead['id']}", json={
        "provider_id": provider["id"], "model_id": None}, headers=OWN).status_code == 200
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(f"/api/conversations/{cid}", json={
        "provider_id": provider["id"], "model_id": "claude-sonnet-5-5"}, headers=OWN)
    row = lead_row(client, cid)
    assert (row["model_id"], row["cannot_run"]) == ("claude-sonnet-5-5", None)


def test_only_an_anthropic_provider_needs_a_model_named():
    def row(kind, **more):
        return Provider(id="p", name=NAME, kind=kind, **more)

    with pytest.raises(NotListed) as refused:
        allowed(row("anthropic"), None)
    assert NAME in str(refused.value) and "Models page" in str(refused.value)
    assert "model" in refused.value.to_agent
    allowed(row("anthropic"), "claude-sonnet-5-5")
    # A server of one's own runs the first model it lists; a CLI, its own default.
    allowed(row("openai_compat"), None)
    allowed(row("claude_cli"), None)


def test_a_web_search_does_not_go_through_an_anthropic_provider_with_no_model(team):  # noqa: F811
    client, _default, _fast = team([])
    anthropic(client)
    assert search_apis(client.app.state.session_factory) == []


# --- a key Anthropic refuses --------------------------------------------------------------

REFUSED = ("Anthropic refused this key ({status}). It may be a Claude subscription token, "
           "which the API does not take; use the Claude Code provider for a subscription.")


@pytest.mark.anyio
@pytest.mark.parametrize("status", [401, 403])
async def test_a_refused_key_is_said_so_and_nothing_of_the_key_is_shown(status):
    def handler(request):
        # A server that echoes what it was sent: none of it may reach the user.
        return httpx2.Response(status, json={"type": "error", "error": {
            "type": "authentication_error", "message": f"invalid x-api-key {KEY}"}})

    client = AnthropicClient("https://api.test", KEY, "claude-sonnet-5-5",
                             transport=httpx2.MockTransport(handler))

    async def nothing(_text):
        return None

    for call in (client.models, client.info, lambda: client.search("q"),
                 lambda: client.stream_step("claude-sonnet-5-5", [
                     {"role": "user", "content": "hi"}], None, nothing)):
        with pytest.raises(ModelUnavailable) as failed:
            await call()
        said = str(failed.value)
        # what the server said of it is kept (a key of another workspace, ...), less the key
        assert said == REFUSED.format(status=status) + " It said: invalid x-api-key [key]"
        assert "sk-ant" not in said and KEY[10:20] not in said


# --- a subscription token given as an API key ----------------------------------------------

SUBSCRIPTION = ("this looks like a Claude subscription token - the API does not accept it; "
                "add Claude Code instead")
def test_only_a_subscription_token_is_warned_of(team):  # noqa: F811
    client, _default, _fast = team([])
    # The user's own key, of a prefix nobody knows, works: it is not warned of.
    made = anthropic(client, default_model="claude-sonnet-5-5")
    assert made["has_key"] and made["key_warning"] is None
    pid = made["id"]
    for key, warning in (("sk-ant-oat01-abc", SUBSCRIPTION), ("sk-ant-api03-abc", None),
                         ("sk-ant-admin01-abc", None)):
        changed = client.patch(f"/api/providers/{pid}", json={"api_key": key}, headers=OWN)
        assert changed.status_code == 200, changed.text
        assert changed.json()["key_warning"] == warning
        listed = next(p for p in client.get("/api/providers").json() if p["id"] == pid)
        assert listed["key_warning"] == warning and key not in changed.text
    # No key, or a key of another kind of provider: nothing to say.
    assert client.patch(f"/api/providers/{pid}", json={"api_key": ""},
                        headers=OWN).json()["key_warning"] is None
    other = next(p for p in client.get("/api/providers").json() if p["name"] == "Fast")
    assert other["key_warning"] is None


def test_the_team_guide_does_not_offer_a_default_an_anthropic_provider_does_not_have():
    from app.team import describe, guide

    (entry,) = guide([Provider(id="p", name=NAME, kind="anthropic", for_agents=True,
                               models=[{"name": "claude-sonnet-5-5", "note": None}])])
    assert (entry.default, entry.must_name) == (None, True)
    assert "It has no default: name one of its models." in describe([entry])
