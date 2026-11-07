"""Model providers: who an agent's model steps go to, and the settings behind it."""

import json
import sqlite3

import pytest
from alembic import command

from app.catalog import models_for
from app.config import load_settings
from app.main import create_app
from app.model_client import ModelUnavailable
from app.providers import NOT_WATCHED, ON_HOST
from tests.fakes import ScriptedModel
from tests.keyed import TestClient
from tests.test_chat_flow import text
from tests.test_migration_0002 import _config
from tests.test_spawn import reported, role_id, spawn

# (What agents may pick is the user's to change, from the app's own page: slice 81a.)
OWN = {"Origin": "http://127.0.0.1:8790"}

SECRET = "sk-test-DO-NOT-LEAK-12345"


@pytest.fixture
def two_models(settings_env):
    """An app with a default model and a second provider called Fast."""
    opened = []

    def make(default_steps, fast_steps):
        default = ScriptedModel(default_steps, model_id="big-model")
        fast = ScriptedModel(fast_steps, model_id="fast-model")
        app = create_app(load_settings(settings_env), model=default, clients={"Fast": fast})
        client = TestClient(app, base_url="http://127.0.0.1:8790")
        client.__enter__()
        opened.append(client)
        created = client.post("/api/providers", json={
            "name": "Fast", "kind": "openai_compat", "base_url": "http://127.0.0.1:9/v1"})
        assert created.status_code == 201, created.text
        return client, default, fast, created.json()

    yield make
    for client in opened:
        client.__exit__(None, None, None)


def start(client, project_dir, **conversation):
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    if conversation:
        patched = client.patch(f"/api/conversations/{cid}", json=conversation)
        assert patched.status_code == 200, patched.text
    run = client.post(f"/api/conversations/{cid}/messages", json={"content": "hi"}).json()["run"]
    return cid, run["id"]


# --- first start and the API ---------------------------------------------------


def test_the_first_start_adds_the_local_provider_from_the_environment(client):
    (local,) = client.get("/api/providers").json()
    assert (local["name"], local["kind"], local["base_url"]) == (
        "Local", "openai_compat", "http://127.0.0.1:9/v1")
    assert local["has_key"] is False and "api_key" not in local


def test_installed_clis_are_offered_on_the_first_start_only(settings_env, tmp_path):
    settings_env["KOLONI_DETECT_CLI"] = "1"
    found = {"claude": str(tmp_path / "claude.cmd"), "codex": None}
    app = create_app(load_settings(settings_env), model=ScriptedModel([]), which=found.get)
    with TestClient(app, base_url="http://127.0.0.1:8790") as client:
        providers = client.get("/api/providers").json()
        assert [(p["name"], p["kind"]) for p in providers] == [
            ("Local", "openai_compat"), ("Claude Code", "claude_cli")]
        client.delete(f"/api/providers/{providers[1]['id']}")
    # The user removed it: a later start does not bring it back.
    app = create_app(load_settings(settings_env), model=ScriptedModel([]), which=found.get)
    with TestClient(app, base_url="http://127.0.0.1:8790") as client:
        assert [p["name"] for p in client.get("/api/providers").json()] == ["Local"]


def test_a_key_is_stored_but_never_shown(client):
    created = client.post("/api/providers", json={
        "name": " Claude  API ", "kind": "anthropic", "api_key": SECRET,
        "default_model": "claude-sonnet-5-5"})
    assert created.status_code == 201, created.text
    provider = created.json()
    assert (provider["name"], provider["has_key"]) == ("Claude API", True)
    assert provider["base_url"] == "https://api.anthropic.com"
    everything = [
        created.text,
        client.get("/api/providers").text,
        client.patch(f"/api/providers/{provider['id']}", headers=OWN, json={"default_model": "x"}).text,
        client.post(f"/api/providers/{provider['id']}/test").text,
        json.dumps(client.app.openapi()),  # (not served: slice 94)
    ]
    assert all(SECRET not in body for body in everything)
    # an empty key clears it; leaving the key out keeps it
    assert client.patch(f"/api/providers/{provider['id']}", headers=OWN, json={"name": "Renamed"}).json()[
        "has_key"] is True
    assert client.patch(f"/api/providers/{provider['id']}", headers=OWN, json={"api_key": ""}).json()[
        "has_key"] is False


def test_provider_rules(client):
    def post(**body):
        return client.post("/api/providers", json=body)

    assert post(name="local", kind="openai_compat", base_url="http://x/v1").status_code == 409
    assert post(name="X", kind="telepathy").status_code == 422
    assert post(name="X", kind="openai_compat").status_code == 422  # needs an address
    assert post(name="X", kind="openai_compat", base_url="ftp://x").status_code == 422
    assert post(name=" ", kind="claude_cli").status_code == 422
    cli = post(name="Codex", kind="codex_cli")
    assert cli.status_code == 201 and cli.json()["base_url"] is None

    (local, codex) = client.get("/api/providers").json()
    assert client.delete(f"/api/providers/{codex['id']}").status_code == 204
    assert client.delete(f"/api/providers/{local['id']}").status_code == 409  # the last one stays
    assert client.delete("/api/providers/nope").status_code == 404


def test_a_cli_says_which_rules_nobody_watches_in_each_way_it_runs_with_its_own_tools(client):
    """K-native-not: per way of running (`providers.NOT_WATCHED`), for the agent's window and
    node; empty where every tool of its own is asked about, none for a model server. In a
    project whose commands run in Docker, each way that runs commands says they run here."""
    for kind in ("codex_cli", "agy_cli", "claude_cli", "qoder_cli"):
        assert client.post("/api/providers", json={"name": kind, "kind": kind}).status_code == 201
    shown = client.get("/api/providers").json()
    said = {one["kind"]: one["not_watched"] for one in shown}
    assert said["openai_compat"] is None and said["claude_cli"] == {"native": []}
    assert said["agy_cli"]["native"] == [] and len(said["agy_cli"]["reads"]) == 3
    assert any("web" in rule for rule in said["agy_cli"]["reads"])
    assert said["codex_cli"].keys() == {"native"}
    assert any("secret files" in rule for rule in said["codex_cli"]["native"])
    assert said["qoder_cli"] == {"native": [NOT_WATCHED[("qoder_cli", "native")][0]]}
    docker = {one["kind"]: one["not_watched_in_docker"] for one in shown}
    assert docker["openai_compat"] is None and docker["claude_cli"] == {"native": [ON_HOST]}
    assert docker["agy_cli"] == {"native": [ON_HOST], "reads": said["agy_cli"]["reads"]}
    assert docker["codex_cli"]["native"] == [*said["codex_cli"]["native"], ON_HOST]


def test_test_reports_what_the_provider_answers(make_client):
    client, _ = make_client([])
    local = client.get("/api/providers").json()[0]
    tested = client.post(f"/api/providers/{local['id']}/test").json()
    assert tested == {"ok": True, "model_id": "fake-model", "tools_supported": True, "error": None,
                               "reply": None, "model_from": None}

    class Down(ScriptedModel):
        async def info(self):
            raise ModelUnavailable("model server unreachable: refused")

    client.app.state.providers.override = Down([])
    tested = client.post(f"/api/providers/{local['id']}/test").json()
    assert tested["ok"] is False and "refused" in tested["error"]


def test_health_reports_the_default_provider(make_client):
    client, _ = make_client([])
    health = client.get("/api/health").json()
    assert (health["provider_name"], health["model_reachable"], health["model_id"]) == (
        "Local", True, "fake-model")
    assert health["provider_id"] == client.get("/api/providers").json()[0]["id"]


def test_health_asks_the_provider_it_is_given_or_else_the_default(two_models):
    """K-model-seridi: the model strip is of the open conversation's provider."""
    client, _default, _fast, provider = two_models([], [])
    fast = client.get("/api/health", params={"provider_id": provider["id"]}).json()
    assert (fast["provider_id"], fast["provider_name"], fast["model_id"]) == (
        provider["id"], "Fast", "fast-model")
    gone = client.get("/api/health", params={"provider_id": "nope"}).json()
    assert (gone["provider_name"], gone["model_id"]) == ("Local", "big-model")


# --- which model an agent gets ---------------------------------------------------


def test_the_conversation_picks_the_model_and_the_agent_records_it(
    two_models, wait_run, project_dir
):
    client, default, fast, provider = two_models([], [text("fast reply")])
    cid, run_id = start(client, project_dir, provider_id=provider["id"])
    snap = wait_run(client, cid, run_id)
    assert (len(default.calls), len(fast.calls)) == (0, 1)
    agent = snap["agents"][0]
    assert (agent["provider_name"], agent["model_id"]) == ("Fast", "fast-model")
    assert snap["runs"][0]["model_id"] == "fast-model"
    assert snap["conversation"]["provider_id"] == provider["id"]


def test_without_a_choice_the_first_provider_is_used(two_models, wait_run, project_dir):
    client, default, fast, _ = two_models([text("default reply")], [])
    cid, run_id = start(client, project_dir)
    agent = wait_run(client, cid, run_id)["agents"][0]
    assert (agent["provider_name"], agent["model_id"]) == ("Local", "big-model")
    assert len(fast.calls) == 0


def test_a_role_overrides_the_conversation_for_its_own_agents(two_models, wait_run, project_dir):
    client, default, fast, provider = two_models(
        [spawn("Reviewer"), text("lead done")], [text("reviewed quickly")])
    patched = client.patch(f"/api/roles/{role_id(client, 'Reviewer')}",
                           json={"provider_id": provider["id"], "model_id": "tiny"})
    assert (patched.json()["provider_id"], patched.json()["model_id"]) == (provider["id"], "tiny")
    cid, run_id = start(client, project_dir)
    snap = wait_run(client, cid, run_id)
    lead, reviewer = snap["agents"]
    assert (lead["provider_name"], reviewer["provider_name"]) == ("Local", "Fast")
    # the Reviewer's step went to the other model, and only that step
    assert (len(default.calls), len(fast.calls)) == (2, 1)
    assert "Reviewer sub-agent" in fast.calls[0][0]["content"]
    assert reported(default.calls[1][-1]["content"]) == "Reviewer finished.\n\nreviewed quickly"
    assert snap["runs"][0]["model_id"] == "big-model"  # the turn carries its lead's model


def test_a_sub_agent_whose_provider_is_down_fails_alone(two_models, wait_run, project_dir):
    client, default, fast, provider = two_models([spawn("Reviewer"), text("carrying on")], [])

    async def down():
        raise ModelUnavailable("model server unreachable: refused")

    fast.info = down
    client.patch(f"/api/roles/{role_id(client, 'Reviewer')}", json={"provider_id": provider["id"]})
    cid, run_id = start(client, project_dir)
    snap = wait_run(client, cid, run_id)
    assert snap["agents"][1]["status"] == "failed" and "refused" in snap["agents"][1]["error"]
    assert snap["agents"][1]["provider_name"] == "Fast"
    assert snap["runs"][0]["status"] == "completed"


def test_changing_the_choice_mid_turn_does_not_move_a_running_agent(
    two_models, wait_run, project_dir, gate
):
    client, default, fast, provider = two_models([gate.step(text("one")), ], [text("two")])
    cid, run_id = start(client, project_dir)
    gate.wait_partial()
    client.patch(f"/api/conversations/{cid}", json={"provider_id": provider["id"]})
    gate.release()
    assert wait_run(client, cid, run_id)["agents"][0]["provider_name"] == "Local"
    second = client.post(f"/api/conversations/{cid}/messages", json={"content": "again"}).json()
    snap = wait_run(client, cid, second["run"]["id"])
    assert [a["provider_name"] for a in snap["agents"]] == ["Local", "Fast"]


def test_a_deleted_provider_falls_back_to_the_next_level(two_models, wait_run, project_dir):
    client, default, fast, provider = two_models([text("default reply")], [])
    client.patch(f"/api/roles/{role_id(client, 'Lead')}", json={"provider_id": provider["id"]})
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(f"/api/conversations/{cid}", json={"provider_id": provider["id"]})
    assert client.put(
        f"/api/projects/{pid}/backlog/choice", headers={"Origin": "http://127.0.0.1:8790"},
        json={"permission_mode": "ask", "provider_id": provider["id"], "model_id": "m"},
    ).json()["model_id"] == "m"
    assert client.delete(f"/api/providers/{provider['id']}").status_code == 204
    assert client.get(f"/api/conversations/{cid}").json()["conversation"]["provider_id"] is None
    choice = client.get(f"/api/projects/{pid}/backlog/auto").json()  # (the backlog's too)
    assert (choice["provider_id"], choice["model_id"]) == (None, None)
    lead = next(r for r in client.get("/api/roles").json() if r["name"] == "Lead")
    assert lead["provider_id"] is None
    run = client.post(f"/api/conversations/{cid}/messages", json={"content": "hi"}).json()["run"]
    assert wait_run(client, cid, run["id"])["agents"][0]["provider_name"] == "Local"


def test_choices_are_validated(two_models, project_dir):
    client, _, _, provider = two_models([], [])
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    assert client.patch(f"/api/conversations/{cid}", json={"provider_id": "nope"}).status_code == 422
    chosen = client.patch(f"/api/conversations/{cid}",
                          json={"provider_id": provider["id"], "model_id": " m1 "}).json()
    assert (chosen["provider_id"], chosen["model_id"]) == (provider["id"], "m1")
    # a title change leaves the choice alone; null clears it
    kept = client.patch(f"/api/conversations/{cid}", json={"title": "t"}).json()
    assert kept["provider_id"] == provider["id"]
    cleared = client.patch(f"/api/conversations/{cid}", json={"provider_id": None}).json()
    assert (cleared["provider_id"], cleared["model_id"]) == (None, None)
    reviewer = role_id(client, "Reviewer")
    assert client.patch(f"/api/roles/{reviewer}", json={"provider_id": "nope"}).status_code == 422
    client.patch(f"/api/roles/{reviewer}", json={"provider_id": provider["id"]})
    assert client.post(f"/api/roles/{reviewer}/reset").json()["provider_id"] is None


# --- migration -------------------------------------------------------------------


def test_migration_0005_and_back(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0004")
    at = "2026-10-05 10:00:00"
    with sqlite3.connect(db) as conn:
        conn.execute(f"INSERT INTO projects (id, name, root_path, created_at, exec_location, "
                     f"docker_network) VALUES ('p', 'p', 'C:/p', '{at}', 'host', 0)")
        conn.execute(f"INSERT INTO conversations (id, project_id, title, permission_mode, "
                     f"spawn_approval, spawn_max_depth, spawn_max_agents, created_at, updated_at) "
                     f"VALUES ('c', 'p', 't', 'ask', 'auto', 2, 6, '{at}', '{at}')")
        conn.execute(f"INSERT INTO runs (id, conversation_id, status, model_id, created_at, "
                     f"started_at) VALUES ('r', 'c', 'completed', 'qwen', '{at}', '{at}')")
        conn.execute(f"INSERT INTO agents (id, run_id, role_name, tools, depth, status, created_at) "
                     f"VALUES ('a', 'r', 'Lead', '{json.dumps(['read_file'])}', 0, 'completed', '{at}')")
    command.upgrade(cfg, "head")
    with sqlite3.connect(db) as conn:
        agent = conn.execute("SELECT provider_name, model_id FROM agents").fetchone()
        conversation = conn.execute("SELECT provider_id, model_id FROM conversations").fetchone()
        providers = conn.execute("SELECT count(*) FROM providers").fetchone()[0]
    # the model an old agent ran on is known from its turn; which provider is not recorded
    assert agent == (None, "qwen")
    assert conversation == (None, None) and providers == 0
    command.downgrade(cfg, "0004")
    with sqlite3.connect(db) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
        columns = [row[1] for row in conn.execute("PRAGMA table_info(agents)")]
        assert conn.execute("SELECT count(*) FROM agents").fetchone()[0] == 1
    assert "providers" not in tables and "provider_name" not in columns


def test_each_kind_of_provider_gets_its_own_client(settings):
    from app.db.models import Provider
    from app.model_anthropic import AnthropicClient
    from app.model_client import OpenAICompatClient
    from app.model_native import CodexSessionClient
    from app.model_session import ClaudeSessionClient
    from app.providers import Providers

    providers = Providers(settings)
    # a CLI row that names no mode runs in its kind's default one
    kinds = {"openai_compat": OpenAICompatClient, "anthropic": AnthropicClient,
             "claude_cli": ClaudeSessionClient, "codex_cli": CodexSessionClient}
    for kind, expected in kinds.items():
        row = Provider(id=kind, name=kind, kind=kind, base_url="http://x/v1", api_key=SECRET)
        client = providers.client(row, "m")
        assert type(client) is expected
        assert providers.client(row, "m") is client  # kept while the settings stay the same
        assert providers.client(row, "other") is not client


# --- review fixes -----------------------------------------------------------------


def test_a_refused_request_never_repeats_the_key_back(client):
    refused = [
        client.post("/api/providers", json={"kind": "anthropic", "api_key": SECRET}),  # no name
        client.post("/api/providers", json={"name": "X", "kind": "anthropic",
                                            "api_key": SECRET + "x" * 600}),
        client.post("/api/providers", json={"name": "X", "kind": "anthropic",
                                            "api_key": SECRET + "\u200b"}),
        client.post("/api/providers", json={"name": "X", "kind": "anthropic",
                                            "api_key": "sk-test\n-DO-NOT-LEAK"}),
        client.post("/api/providers", json={"name": "X", "kind": "anthropic",
                                            "api_key": "has space"}),
    ]
    assert [r.status_code for r in refused] == [422] * 5
    assert all("DO-NOT-LEAK" not in r.text for r in refused)
    assert "key" in refused[2].json()["detail"]
    assert len(client.get("/api/providers").json()) == 1
    created = client.post("/api/providers", json={"name": "X", "kind": "anthropic",
                                                  "api_key": f"  {SECRET}  "}).json()
    patched = client.patch(f"/api/providers/{created['id']}", headers=OWN, json={"api_key": "bad\tkey"})
    assert patched.status_code == 422 and "bad" not in patched.text


def test_model_names_cannot_carry_control_characters(client):
    local = client.get("/api/providers").json()[0]
    bad = client.patch(f"/api/providers/{local['id']}", headers=OWN, json={"default_model": "m\nx"})
    assert bad.status_code == 422
    fine = client.patch(f"/api/providers/{local['id']}", headers=OWN,
                        json={"default_model": "DeepSeek-v4-Pro (Model Studio - Singapore)"})
    assert fine.status_code == 200


def test_a_new_role_keeps_the_model_it_was_given(two_models):
    client, _, _, provider = two_models([], [])
    created = client.post("/api/roles", json={
        "name": "Fast reviewer", "tools": ["read_file"], "provider_id": provider["id"],
        "model_id": "tiny"})
    assert created.status_code == 201, created.text
    assert (created.json()["provider_id"], created.json()["model_id"]) == (provider["id"], "tiny")
    assert client.post("/api/roles", json={
        "name": "Other", "tools": ["read_file"], "provider_id": "nope"}).status_code == 422


def test_any_provider_can_be_made_the_default(two_models, wait_run, project_dir):
    client, default, fast, provider = two_models([], [text("fast reply")])
    made = client.post(f"/api/providers/{provider['id']}/default")
    assert made.status_code == 200
    assert [p["name"] for p in client.get("/api/providers").json()] == ["Fast", "Local"]
    assert client.get("/api/health").json()["provider_name"] == "Fast"
    cid, run_id = start(client, project_dir)
    assert wait_run(client, cid, run_id)["agents"][0]["provider_name"] == "Fast"
    assert client.post("/api/providers/nope/default").status_code == 404


def test_health_does_not_call_a_provider_out_of_reach_when_only_its_default_is_off_the_list(
    make_client,
):
    client, _ = make_client([])
    local = client.get("/api/providers").json()[0]
    held = client.patch(f"/api/providers/{local['id']}", headers=OWN, json={
        "models": [{"name": "another-model"}], "only_listed": True})
    assert held.status_code == 200, held.text
    health = client.get("/api/health").json()
    assert (health["model_reachable"], health["not_listed"]) == (False, True)
    assert "another-model" in health["error"]


# --- Anthropic: the workspace a key belongs to ------------------------------------------

WORKSPACE = "wrkspc_01TESTworkspace"


def test_an_anthropic_workspace_is_checked_like_any_setting():
    from app.providers import check_options

    assert check_options("anthropic", {"workspace_id": WORKSPACE}, True) == {
        "workspace_id": WORKSPACE}
    assert check_options("anthropic", {"workspace_id": f"  {WORKSPACE}\n"}, True) == {
        "workspace_id": WORKSPACE}
    assert check_options("anthropic", {"workspace_id": "x" * 100}, True) == {
        "workspace_id": "x" * 100}
    # none, or an empty one, is no setting at all
    for nothing in (None, {}, {"workspace_id": None}, {"workspace_id": ""},
                    {"workspace_id": "   "}):
        assert check_options("anthropic", nothing, True) is None
    for bad in ("has space", "x" * 101, "line\nbreak", "tab\there", "bell\x07", "café",
                "zero​width", 5, True, ["wrkspc"], {"id": "wrkspc"}):
        with pytest.raises(ValueError, match="workspace"):
            check_options("anthropic", {"workspace_id": bad}, True)
    # this kind has no other setting
    for other in ({"offline": True}, {"provider_type": "openai"},
                  {"workspace_id": WORKSPACE, "max_prompt_tokens": 5}):
        with pytest.raises(ValueError, match="unknown setting"):
            check_options("anthropic", other, True)
    # and no other kind has this one
    for kind in ("openai_compat", "claude_cli", "codex_cli", "qoder_cli", "agy_cli"):
        with pytest.raises(ValueError):
            check_options(kind, {"workspace_id": WORKSPACE}, True)
    with pytest.raises(ValueError, match="unknown setting"):
        check_options("copilot_cli", {"workspace_id": WORKSPACE}, True)


def test_an_anthropic_provider_keeps_its_workspace_and_hands_it_to_its_client(client, settings):
    from app.db.models import Provider
    from app.providers import Providers

    made = client.post("/api/providers", json={
        "name": "Claude API", "kind": "anthropic", "api_key": SECRET,
        "default_model": "claude-sonnet-5-5", "options": {"workspace_id": f" {WORKSPACE} "}})
    assert made.status_code == 201, made.text
    provider = made.json()
    assert provider["options"] == {"workspace_id": WORKSPACE}
    url = f"/api/providers/{provider['id']}"
    # changing something else leaves it where it is
    for other in ({"base_url": "https://proxy.example.com"}, {"default_model": "claude-opus-5"},
                  {"api_key": SECRET + "2"}, {"name": "Claude"}):
        changed = client.patch(url, headers=OWN, json=other)
        assert changed.status_code == 200, changed.text
        assert changed.json()["options"] == {"workspace_id": WORKSPACE}, other
    # one that could not go into a request is refused, and the old one stays
    for bad in ("has space", "x" * 101, "line\nbreak"):
        refused = client.patch(url, headers=OWN, json={"options": {"workspace_id": bad}})
        assert refused.status_code == 422 and "workspace" in refused.json()["detail"]
    assert client.patch(url, headers=OWN, json={"options": {"offline": True}}).status_code == 422
    assert client.get("/api/providers").json()[-1]["options"] == {"workspace_id": WORKSPACE}
    # the client built for it is given it
    with client.app.state.session_factory() as session:
        row = session.get(Provider, provider["id"])
        built = Providers(settings)._build(row, "claude-sonnet-5-5")
    assert built._workspace == WORKSPACE
    # it can be changed, and taken away again: empty, or no settings at all
    assert client.patch(url, headers=OWN, json={"options": {"workspace_id": "wrkspc_other"}}).json()[
        "options"] == {"workspace_id": "wrkspc_other"}
    assert client.patch(url, headers=OWN, json={"options": {"workspace_id": ""}}).json()["options"] is None
    client.patch(url, headers=OWN, json={"options": {"workspace_id": WORKSPACE}})
    assert client.patch(url, headers=OWN, json={"options": None}).json()["options"] is None
    with client.app.state.session_factory() as session:
        row = session.get(Provider, provider["id"])
        assert Providers(settings)._build(row, "m")._workspace is None
    # another kind is still refused it
    local = client.get("/api/providers").json()[0]
    assert client.patch(f"/api/providers/{local['id']}", headers=OWN, json={
        "options": {"workspace_id": WORKSPACE}}).status_code == 422
    assert client.post("/api/providers", json={
        "name": "Other", "kind": "openai_compat", "base_url": "http://127.0.0.1:9/v1",
        "options": {"workspace_id": WORKSPACE}}).status_code == 422


def test_agents_are_never_shown_a_providers_workspace(client):
    from app.providers import list_providers
    from app.team import describe, guide

    client.post("/api/providers", json={
        "name": "Claude API", "kind": "anthropic", "api_key": SECRET, "for_agents": True,
        "note": "good at reviews", "models": [{"name": "claude-sonnet-5-5", "note": "quick"}],
        "options": {"workspace_id": WORKSPACE}})
    with client.app.state.session_factory() as session:
        entries = guide(list_providers(session))
    told = describe(entries)
    assert "Claude API" in told and "good at reviews" in told
    assert WORKSPACE not in told and "workspace" not in told.lower()
    assert WORKSPACE not in repr(entries)


# --- Anthropic: the models a key can use ------------------------------------------------


@pytest.fixture
def anthropic_app(settings_env):
    """An app whose provider "Claude API" speaks to a stand-in for the Anthropic API."""
    import httpx2

    from app.model_anthropic import AnthropicClient

    opened = []

    def make(handler, **provider):
        asked = []

        def counted(request):
            asked.append(request)
            return handler(request)

        stand_in = AnthropicClient("https://api.test", SECRET, None,
                                   transport=httpx2.MockTransport(counted))
        app = create_app(load_settings(settings_env), model=ScriptedModel([]),
                         clients={"Claude API": stand_in})
        client = TestClient(app, base_url="http://127.0.0.1:8790")
        client.__enter__()
        opened.append(client)
        made = client.post("/api/providers", json={
            "name": "Claude API", "kind": "anthropic", "api_key": SECRET, **provider})
        assert made.status_code == 201, made.text
        return client, made.json(), asked

    yield make
    for client in opened:
        client.__exit__(None, None, None)


# The catalogue's names for Anthropic, offered between the user's list and the key's.
KNOWN = [row["name"] for row in models_for("anthropic")]


def _listing(*ids):
    import httpx2

    return lambda request: httpx2.Response(200, content=json.dumps({
        "data": [{"type": "model", "id": name} for name in ids], "has_more": False}))


def test_an_anthropic_provider_lists_the_models_its_key_can_use(anthropic_app):
    client, provider, asked = anthropic_app(
        _listing("claude-opus-5", "claude-sonnet-5-5", "claude-haiku-4-5"))
    url = f"/api/providers/{provider['id']}/models"
    # the catalogue's names come before what the key lists (slice 59c)
    assert client.get(url).json() == {"models": list(dict.fromkeys(
        [*KNOWN, "claude-opus-5", "claude-sonnet-5-5", "claude-haiku-4-5"])), "note": None}
    assert [(request.method, request.url.path) for request in asked] == [("GET", "/v1/models")]
    # the user's own list comes first, and a name in both is there once
    client.patch(f"/api/providers/{provider['id']}", headers=OWN, json={
        "models": [{"name": "mine"}, {"name": "claude-sonnet-5-5", "note": "quick"}]})
    offered = list(dict.fromkeys(
        ["mine", "claude-sonnet-5-5", *KNOWN, "claude-opus-5", "claude-haiku-4-5"]))
    assert client.get(url).json() == {"models": offered, "note": None}
    # "Only these models" stops no list: listing runs no model
    client.patch(f"/api/providers/{provider['id']}", headers=OWN, json={"only_listed": True})
    assert len(client.get(url).json()["models"]) == len(offered)


def test_an_anthropic_list_that_cannot_be_had_is_empty_and_says_why_without_the_key(
    anthropic_app
):
    import httpx2

    def refused(request):
        # a server that repeats what it was sent
        return httpx2.Response(401, content=json.dumps({"error": {
            "message": f"invalid x-api-key: {request.headers['x-api-key']}"}}))

    client, provider, asked = anthropic_app(refused)
    url = f"/api/providers/{provider['id']}/models"
    answer = client.get(url)
    assert answer.status_code == 200 and answer.json()["models"] == KNOWN
    assert "401" in answer.json()["note"] and "[key]" in answer.json()["note"]
    assert SECRET not in answer.text
    # the user's own list is still offered, next to the reason
    client.patch(f"/api/providers/{provider['id']}", headers=OWN, json={"models": [{"name": "mine"}]})
    answer = client.get(url)
    assert answer.json()["models"] == ["mine", *KNOWN] and "401" in answer.json()["note"]
    assert SECRET not in answer.text


def test_without_a_key_an_anthropic_provider_asks_nobody_for_a_list(anthropic_app):
    client, provider, asked = anthropic_app(_listing("claude-opus-5"))
    client.patch(f"/api/providers/{provider['id']}", headers=OWN, json={"api_key": ""})
    url = f"/api/providers/{provider['id']}/models"
    answer = client.get(url).json()
    assert answer["models"] == KNOWN and "key" in answer["note"]  # the catalogue's only
    assert asked == []
    # with a list of the user's own there is nothing left to say
    client.patch(f"/api/providers/{provider['id']}", headers=OWN, json={"models": [{"name": "mine"}]})
    assert client.get(url).json() == {"models": ["mine", *KNOWN], "note": None}
    assert asked == []


def test_the_client_asked_for_the_list_is_built_from_the_provider_as_it_is_kept(settings):
    from app.db.models import Provider
    from app.model_anthropic import AnthropicClient
    from app.providers import Providers

    row = Provider(id="p", name="Claude API", kind="anthropic", api_key=SECRET,
                   base_url="https://proxy.example.com", only_listed=True,
                   models=[{"name": "mine", "note": None}],
                   options={"workspace_id": WORKSPACE})
    lister = Providers(settings).lister(row)
    assert type(lister) is AnthropicClient
    assert (lister._base, lister._key, lister._workspace) == (
        "https://proxy.example.com", SECRET, WORKSPACE)
    assert lister._headers() == {"x-api-key": SECRET, "anthropic-version": "2023-06-01",
                                 "anthropic-workspace-id": WORKSPACE}
