"""GitHub Copilot CLI as a provider: a session with KOLONİ's tools, on your own model server."""

import json
import sqlite3
import sys
from pathlib import Path

import pytest
from alembic import command

from app.agent.tiers_mixin import REFUSED_LAST
from app.config import load_settings
from app.main import create_app
from app.model_session import ClaudeSessionClient, CopilotSessionClient
from tests.fakes import ScriptedModel
from tests.keyed import TestClient
from tests.test_migration_0002 import _config

FAKE = [sys.executable, str(Path(__file__).with_name("fake_copilot_cli.py"))]
KEY = "sk-secret-123"
SERVER = {"base_url": "http://localhost:8080/v1", "api_key": KEY, "default_model": "qwen-local",
          "options": {"max_prompt_tokens": 70000, "max_output_tokens": 8000}}
# Copilot's model server and key are set only from the app's own page.
PAGE = {"Origin": "http://127.0.0.1:8790"}


@pytest.fixture
def client(app):
    with TestClient(app, base_url="http://127.0.0.1:8790", headers=PAGE) as page:
        yield page


@pytest.fixture
def copilot_app(settings_env, tmp_path):
    opened = []
    record, plan = tmp_path / "record.json", tmp_path / "plan.json"

    def make(script, **more):
        plan.write_text(json.dumps({"record": str(record), "script": script, **more}),
                        encoding="utf-8")
        cli = CopilotSessionClient(
            None, "qwen-local", timeout=30, launcher=FAKE, env={"FAKE_CLI_PLAN": str(plan)},
            base_url=SERVER["base_url"], api_key=KEY, options=SERVER["options"])
        app = create_app(load_settings(settings_env), model=ScriptedModel([]),
                         clients={"Copilot": cli})
        client = TestClient(app, base_url="http://127.0.0.1:8790", headers=PAGE)
        client.__enter__()
        opened.append(client)
        made = client.post("/api/providers", json={
            "name": "Copilot", "kind": "copilot_cli", **SERVER})
        assert made.status_code == 201, made.text
        return client, made.json()

    make.record = lambda: json.loads(record.read_text(encoding="utf-8"))
    yield make
    for client in opened:
        client.__exit__(None, None, None)


def start(client, project_dir, provider, mode="full_auto"):
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    # (and Copilot is the Lead that writes here: K-48 refuses one that hands code on)
    client.patch(f"/api/conversations/{cid}",
                 json={"permission_mode": mode, "provider_id": provider["id"],
                       "lead_hands_code": False},
                 headers={"Origin": "http://127.0.0.1:8790"})  # a level is raised from the app's page
    run = client.post(f"/api/conversations/{cid}/messages",
                      json={"content": "what does it print?"}).json()["run"]
    return cid, run["id"]


def test_a_copilot_turn_runs_with_kolonis_tools_on_your_own_model_server(
    copilot_app, wait_run, project_dir
):
    client, provider = copilot_app([
        {"call": "read_file", "args": {"path": "hello.py"}, "before": "Let me look."},
        {"say": "It prints hi."}], model="qwen-as-served")
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert [(t["name"], t["status"], t["origin"]) for t in snap["tool_calls"]] == [
        ("read_file", "succeeded", "koloni")]
    assert [m["content"] for m in snap["messages"] if m["role"] == "assistant"] == [
        "Let me look.", "It prints hi."]
    lead = snap["agents"][0]
    # what it counted is nothing, and the model is the one it said it used
    assert (lead["input_tokens"], lead["output_tokens"]) == (None, None)
    assert (lead["provider_name"], lead["model_id"]) == ("Copilot", "qwen-as-served")

    seen = copilot_app.record()
    argv = seen["argv"]
    assert "print('hi')" in seen["results"][0]["content"][0]["text"]
    assert "-p" not in argv and "what does it print?" in seen["stdin"]  # the prompt, on stdin
    assert "--allow-all-tools" not in argv
    assert argv[argv.index("--allow-tool") + 1] == "koloni"
    offered = argv[argv.index("--available-tools") + 1:]
    assert offered[:3] == ["koloni-list_dir", "koloni-read_file", "koloni-search"]
    assert all(name.startswith("koloni-") for name in offered)
    for flag in ("--disable-builtin-mcps", "--no-custom-instructions", "--no-ask-user"):
        assert flag in argv
    env = seen["env"]
    assert env["COPILOT_PROVIDER_BASE_URL"] == "http://localhost:8080/v1"
    assert env["COPILOT_MODEL"] == "qwen-local" and env["COPILOT_PROVIDER_TYPE"] == "openai"
    assert env["COPILOT_PROVIDER_MAX_PROMPT_TOKENS"] == "70000"
    assert env["COPILOT_PROVIDER_MAX_OUTPUT_TOKENS"] == "8000"
    assert env["COPILOT_OFFLINE"] == "true"
    # the key goes in the environment only, and the CLI is told to keep it out of its output
    assert env["COPILOT_PROVIDER_API_KEY"] == KEY and KEY not in json.dumps(argv)
    assert "--secret-env-vars=COPILOT_PROVIDER_API_KEY" in argv
    # a home of its own, empty when it started and gone when it ended
    assert seen["home_was_empty"] and not Path(env["COPILOT_HOME"]).exists()
    assert KEY not in json.dumps(snap) and KEY not in json.dumps(provider)


def test_a_tool_of_its_own_ends_the_session(copilot_app, wait_run, project_dir):
    client, provider = copilot_app([{"own": "powershell"}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id, timeout=15)  # not the minute the tool would take
    run = snap["runs"][0]
    assert run["status"] == "failed"
    assert "used a tool of its own (powershell)" in run["error"]


def test_an_error_from_copilot_fails_the_turn_without_the_key(
    copilot_app, wait_run, project_dir
):
    client, provider = copilot_app([{"error": f"401 from the model server (key {KEY})"}])
    cid, run_id = start(client, project_dir, provider)
    run = wait_run(client, cid, run_id)["runs"][0]
    assert run["status"] == "failed" and "401 from the model server" in run["error"]
    assert KEY not in run["error"]


def test_a_crash_is_reported_without_the_key(copilot_app, wait_run, project_dir):
    client, provider = copilot_app([{"exit": 3, "stderr": f"fatal: bad credentials {KEY}"}])
    cid, run_id = start(client, project_dir, provider)
    run = wait_run(client, cid, run_id)["runs"][0]
    assert run["status"] == "failed" and "exited with code 3" in run["error"]
    assert "bad credentials" in run["error"] and KEY not in run["error"]


def test_a_model_the_cli_refuses_is_switched_off_on_its_list(copilot_app, wait_run, project_dir):
    # B-396 (live): 'Error: Model "gpt-6.1-sol" from --model flag is not available.'
    client, provider = copilot_app([{"exit": 1, "stderr": (
        'Error: Model "qwen-local" from --model flag is not available.')}])
    assert client.patch(f"/api/providers/{provider['id']}", json={
        "models": [{"name": "qwen-local", "tier": "balanced"}]}).status_code == 200
    cid, run_id = start(client, project_dir, provider)
    assert "from --model flag is not available" in wait_run(client, cid, run_id)["runs"][0]["error"]
    (row,) = next(p for p in client.get("/api/providers").json()
                  if p["id"] == provider["id"])["models"]
    assert (row["enabled"], row["off_why"]) == (
        False, "Copilot refused it: not available on your account" + REFUSED_LAST)


def test_copilot_that_never_says_what_it_starts_with_is_not_served(
    copilot_app, wait_run, project_dir
):
    client, provider = copilot_app([{"say": "hello"}], no_tools_event=True)
    cid, run_id = start(client, project_dir, provider)
    run = wait_run(client, cid, run_id)["runs"][0]
    assert run["status"] == "failed" and "did not say which tools" in run["error"]


# --- the provider and its settings ------------------------------------------------


def test_copilot_provider_settings_are_checked_and_the_key_stays_put(client):
    made = client.post("/api/providers", json={"name": "Copilot", "kind": "copilot_cli", **SERVER})
    assert made.status_code == 201, made.text
    body = made.json()
    assert (body["mode"], body["has_key"], body["base_url"]) == (
        "session", True, "http://localhost:8080/v1")
    assert body["options"] == {
        "provider_type": "openai", "max_prompt_tokens": 70000, "max_output_tokens": 8000,
        "offline": True}
    assert "api_key" not in body and KEY not in made.text

    bad = [
        {"options": {"provider_type": "banana"}},
        {"options": {"max_prompt_tokens": 0}},
        {"options": {"max_output_tokens": "many"}},
        {"options": {"something_else": 1}},
        {"base_url": "localhost:8080"},
        {"mode": "step"},
    ]
    for more in bad:
        refused = client.post("/api/providers", json={
            "name": "X", "kind": "copilot_cli", **{**SERVER, **more}})
        assert refused.status_code == 422, (more, refused.text)
        assert KEY not in refused.text

    patched = client.patch(f"/api/providers/{body['id']}", json={
        "options": {"provider_type": "anthropic", "offline": False}})
    assert patched.status_code == 200, patched.text
    assert patched.json()["options"] == {
        "provider_type": "anthropic", "max_prompt_tokens": None, "max_output_tokens": None,
        "offline": False}
    # options mean nothing for another kind of provider
    local = client.get("/api/providers").json()[0]
    assert local["options"] is None
    assert client.patch(f"/api/providers/{local['id']}",
                        json={"options": {"offline": True}}).status_code == 422


def test_model_names_are_offered_where_they_can_be_known(client, monkeypatch):
    from app.api import providers as api

    asked = []

    async def listed(base_url, key):
        asked.append((base_url, key))
        return ["qwen-a", "qwen-b"]

    monkeypatch.setattr(api, "served_models", listed)
    copilot = client.post("/api/providers", json={
        "name": "Copilot", "kind": "copilot_cli", **SERVER}).json()
    claude = client.post("/api/providers", json={"name": "CC", "kind": "claude_cli"}).json()
    codex = client.post("/api/providers", json={"name": "Cx", "kind": "codex_cli"}).json()
    names = lambda p: client.get(f"/api/providers/{p['id']}/models").json()  # noqa: E731
    assert names(copilot) == {"models": ["qwen-a", "qwen-b"], "note": None}
    assert asked == [("http://localhost:8080/v1", KEY)]
    # the catalogue's names first (slice 59c), then the CLI's documented ones, each once
    assert names(claude)["models"] == ["fable", "best", "opus", "sonnet", "haiku", "opusplan"]
    # Codex lists none itself: the catalogue's own Codex names, and no "type the name"
    assert names(codex) == {"models": ["gpt-6-astra", "gpt-6.1-sol", "gpt-6-sol", "gpt-6-luna"],
                            "note": None}

    async def down(base_url, key):
        raise api.ModelUnavailable(f"model server unreachable ({key})")

    monkeypatch.setattr(api, "served_models", down)
    answer = client.get(f"/api/providers/{copilot['id']}/models")
    assert answer.status_code == 200 and answer.json()["models"] == []
    assert "unreachable" in answer.json()["note"] and KEY not in answer.text


def test_migration_0011_and_back(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0010")
    command.upgrade(cfg, "head")
    with sqlite3.connect(db) as conn:
        assert "options" in [row[1] for row in conn.execute("PRAGMA table_info(providers)")]
    command.downgrade(cfg, "0010")
    with sqlite3.connect(db) as conn:
        assert "options" not in [row[1] for row in conn.execute("PRAGMA table_info(providers)")]


# --- the model a CLI says it used ---------------------------------------------------


def test_the_model_claude_code_reports_is_the_one_on_record(
    settings_env, tmp_path, wait_run, project_dir
):
    fake = [sys.executable, str(Path(__file__).with_name("fake_session_cli.py"))]
    record, plan = tmp_path / "record.json", tmp_path / "plan.json"
    plan.write_text(json.dumps({"record": str(record), "script": [{"say": "hello"}],
                                "model": "claude-sonnet-5-5"}), encoding="utf-8")
    cli = ClaudeSessionClient(launcher=fake, timeout=30, env={"FAKE_CLI_PLAN": str(plan)})
    app = create_app(load_settings(settings_env), model=ScriptedModel([]),
                     clients={"Session": cli})
    with TestClient(app, base_url="http://127.0.0.1:8790", headers=PAGE) as client:
        provider = client.post("/api/providers", json={
            "name": "Session", "kind": "claude_cli"}).json()
        cid, run_id = start(client, project_dir, provider)
        snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert snap["agents"][0]["model_id"] == "claude-sonnet-5-5"
    assert snap["runs"][0]["model_id"] == "claude-sonnet-5-5"


# --- trying a CLI provider out ------------------------------------------------------


def test_a_cli_provider_can_be_tried_with_one_short_run(copilot_app):
    client, provider = copilot_app([{"say": "ok"}], model="qwen-as-served")
    # Without being asked to, the check never runs the CLI: that would spend the plan.
    plain = client.post(f"/api/providers/{provider['id']}/test").json()
    assert (plain["ok"], plain["model_id"], plain["reply"]) == (True, "qwen-local", None)
    tried = client.post(f"/api/providers/{provider['id']}/test?run=true").json()
    assert tried == {"ok": True, "model_id": "qwen-as-served", "tools_supported": True,
                     "error": None, "reply": "ok", "model_from": None}
    asked = copilot_app.record()
    assert "Reply with the single word" in asked["stdin"]
    assert asked["argv"][-1] == "koloni-none"  # tried with no tools at all


def test_trying_a_cli_provider_reports_what_went_wrong_without_the_key(copilot_app):
    client, provider = copilot_app([{"error": f"model not found (key {KEY})"}])
    tried = client.post(f"/api/providers/{provider['id']}/test?run=true").json()
    assert tried["ok"] is False and "model not found" in tried["error"]
    assert tried["reply"] is None and KEY not in json.dumps(tried)


# --- review fixes ---------------------------------------------------------------------


def test_copilot_settings_in_kolonis_own_environment_do_not_reach_the_cli(
    copilot_app, wait_run, project_dir, monkeypatch
):
    # The user may have Copilot set up for themselves in the shell KOLONİ was started from.
    monkeypatch.setenv("COPILOT_ALLOW_ALL", "true")
    monkeypatch.setenv("COPILOT_PROVIDER_BEARER_TOKEN", "their-other-token")
    monkeypatch.setenv("COPILOT_PROVIDER_API_KEY_COMMAND", "print-a-key")
    monkeypatch.setenv("COPILOT_PROVIDER_WIRE_MODEL", "another-model")
    monkeypatch.setenv("COPILOT_PROVIDER_HEADERS", "X-Tenant: theirs")
    monkeypatch.setenv("GH_TOKEN", "ghp_theirs")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_theirs_too")
    client, provider = copilot_app([{"say": "hello"}])
    cid, run_id = start(client, project_dir, provider)
    assert wait_run(client, cid, run_id)["runs"][0]["status"] == "completed"
    seen = copilot_app.record()
    env = seen["env"]
    assert sorted(env) == [
        "COPILOT_HOME", "COPILOT_MODEL", "COPILOT_OFFLINE", "COPILOT_PROVIDER_API_KEY",
        "COPILOT_PROVIDER_BASE_URL", "COPILOT_PROVIDER_MAX_OUTPUT_TOKENS",
        "COPILOT_PROVIDER_MAX_PROMPT_TOKENS", "COPILOT_PROVIDER_TYPE"]
    assert seen["github_tokens"] == []


def test_a_key_cut_in_two_by_a_long_error_does_not_leak_its_tail(
    copilot_app, wait_run, project_dir
):
    client, provider = copilot_app([
        {"exit": 3, "stderr": "bad credentials " + KEY + "x" * 294}])
    cid, run_id = start(client, project_dir, provider)
    error = wait_run(client, cid, run_id)["runs"][0]["error"]
    assert "exited with code 3" in error
    assert "secret" not in error and "et-123" not in error


def test_a_request_for_a_tool_that_is_not_kolonis_ends_the_session(
    copilot_app, wait_run, project_dir
):
    client, provider = copilot_app([{"request": "powershell"}])
    cid, run_id = start(client, project_dir, provider)
    run = wait_run(client, cid, run_id, timeout=15)["runs"][0]
    assert run["status"] == "failed"
    assert "asked for a tool of its own (powershell)" in run["error"]


def test_copilot_is_added_without_a_token_or_a_model_server(client):
    # The user's own GitHub sign-in (gh's) is Copilot's then: no token is asked for.
    made = client.post("/api/providers", json={"name": "Copilot", "kind": "copilot_cli"})
    assert made.status_code == 201, made.text
    assert (made.json()["base_url"], made.json()["has_key"]) == (None, False)
    served = client.post("/api/providers", json={
        "name": "Copilot 2", "kind": "copilot_cli", **SERVER}).json()
    # taking the address and the key away leaves it on the user's own sign-in
    taken = client.patch(f"/api/providers/{served['id']}", json={"base_url": "", "api_key": ""})
    assert taken.status_code == 200 and taken.json()["has_key"] is False


def test_copilot_on_a_github_account_runs_with_a_token_and_a_home_of_its_own(
    settings_env, tmp_path, wait_run, project_dir, monkeypatch
):
    monkeypatch.setenv("GH_TOKEN", "ghp_from_the_shell")  # the user's own, not to be used
    token = "ghp_secret_token_456"
    record, plan = tmp_path / "record.json", tmp_path / "plan.json"
    plan.write_text(json.dumps({"record": str(record), "model": "gpt-from-github", "script": [
        {"call": "read_file", "args": {"path": "hello.py"}},
        {"exit": 3, "stderr": f"quota exceeded for {token}"}]}), encoding="utf-8")
    cli = CopilotSessionClient(None, "gpt-x", timeout=30, launcher=FAKE,
                               env={"FAKE_CLI_PLAN": str(plan)}, api_key=token, options={})
    app = create_app(load_settings(settings_env), model=ScriptedModel([]),
                     clients={"Copilot": cli})
    with TestClient(app, base_url="http://127.0.0.1:8790", headers=PAGE) as client:
        made = client.post("/api/providers", json={
            "name": "Copilot", "kind": "copilot_cli", "api_key": token,
            "default_model": "gpt-x"})
        assert made.status_code == 201, made.text
        body = made.json()
        # no model server: nothing to be offline from GitHub with
        assert (body["base_url"], body["has_key"], body["options"]["offline"]) == (
            None, True, False)
        assert token not in made.text
        listed = client.get(f"/api/providers/{body['id']}/models").json()
        # GitHub's models as the catalogue knows them (models.dev's)
        from app.catalog import models_for

        known = [row["name"] for row in models_for("copilot_cli")]
        assert listed == {"models": known, "note": None}
        cid, run_id = start(client, project_dir, body)
        run = wait_run(client, cid, run_id)["runs"][0]
    assert "exited with code 3" in run["error"] and token not in run["error"]
    seen = json.loads(record.read_text(encoding="utf-8"))
    env, argv = seen["env"], seen["argv"]
    assert sorted(env) == ["COPILOT_GITHUB_TOKEN", "COPILOT_HOME"]
    assert env["COPILOT_GITHUB_TOKEN"] == token and seen["github_tokens"] == []
    assert seen["home_was_empty"]  # none of the user's plugins, skills, hooks or MCP servers
    assert argv[argv.index("--model") + 1] == "gpt-x"
    assert "--secret-env-vars=COPILOT_GITHUB_TOKEN" in argv and token not in json.dumps(argv)
    assert argv[argv.index("--allow-tool") + 1] == "koloni" and "--allow-all-tools" not in argv
    assert "--available-tools" in argv


def test_offline_is_on_unless_it_was_switched_off_and_survives_other_changes(client):
    made = client.post("/api/providers", json={
        "name": "Copilot", "kind": "copilot_cli", **SERVER}).json()
    assert made["options"]["offline"] is True
    off = client.patch(f"/api/providers/{made['id']}", json={
        "options": {**SERVER["options"], "offline": False}}).json()
    assert off["options"]["offline"] is False
    # a change that says nothing about it leaves it as it was set
    renamed = client.patch(f"/api/providers/{made['id']}", json={
        "options": {"max_prompt_tokens": 50000}}).json()
    assert renamed["options"] == {
        "provider_type": "openai", "max_prompt_tokens": 50000, "max_output_tokens": None,
        "offline": False}


def test_a_model_server_that_answers_oddly_is_a_note_not_a_crash(client, monkeypatch):
    import httpx2

    from app import model_client

    made = client.post("/api/providers", json={
        "name": "Copilot", "kind": "copilot_cli", **SERVER}).json()

    def odd(request):
        return httpx2.Response(200, json=["not", "an", "object"])

    real = model_client.OpenAICompatClient.__init__

    def with_transport(self, *args, **kwargs):
        real(self, *args, **{**kwargs, "transport": httpx2.MockTransport(odd)})

    monkeypatch.setattr(model_client.OpenAICompatClient, "__init__", with_transport)
    answer = client.get(f"/api/providers/{made['id']}/models")
    assert answer.status_code == 200
    assert answer.json()["models"] == [] and answer.json()["note"]


def test_only_the_agent_whose_cli_spoke_gets_the_reported_model(
    settings_env, tmp_path, wait_run, project_dir
):
    from tests.test_chat_flow import text
    from tests.test_spawn import role_id, spawn

    record, plan = tmp_path / "record.json", tmp_path / "plan.json"
    plan.write_text(json.dumps({"record": str(record), "script": [{"say": "Looks fine."}],
                                "model": "qwen-as-served"}), encoding="utf-8")
    cli = CopilotSessionClient(
        None, "qwen-local", timeout=30, launcher=FAKE, env={"FAKE_CLI_PLAN": str(plan)},
        base_url=SERVER["base_url"], options={})
    default = ScriptedModel([spawn("Reviewer", "Review hello.py"), text("done")],
                            model_id="big-model")
    app = create_app(load_settings(settings_env), model=default, clients={"Copilot": cli})
    with TestClient(app, base_url="http://127.0.0.1:8790", headers=PAGE) as client:
        provider = client.post("/api/providers", json={
            "name": "Copilot", "kind": "copilot_cli", **SERVER}).json()
        client.patch(f"/api/roles/{role_id(client, 'Reviewer')}",
                     json={"provider_id": provider["id"]})
        pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
        cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
        run = client.post(f"/api/conversations/{cid}/messages",
                          json={"content": "review"}).json()["run"]
        snap = wait_run(client, cid, run["id"])
    assert [a["model_id"] for a in snap["agents"]] == ["big-model", "qwen-as-served"]
    assert snap["runs"][0]["model_id"] == "big-model"  # the lead's, not its sub-agent's


# --- Copilot working natively (slice 12; headless, asking first, since 89c) ---------------

# Headless when started so; the session-mode stand-in otherwise (the provider's talker).
HEADLESS = [sys.executable, str(Path(__file__).with_name("fake_copilot_headless.py"))]


@pytest.fixture
def copilot_native(settings_env, tmp_path):
    from app.model_native import CopilotNativeClient

    opened = []
    record, plan = tmp_path / "record.json", tmp_path / "plan.json"

    def write_plan(script, **more):
        plan.write_text(json.dumps({"record": str(record), "script": script, **more}),
                        encoding="utf-8")

    def make(script, default_steps=(), timeout=30, **more):
        write_plan(script, **more)
        cli = CopilotNativeClient(
            None, "qwen-local", timeout=timeout, launcher=HEADLESS,
            env={"FAKE_CLI_PLAN": str(plan)},
            base_url=SERVER["base_url"], api_key=KEY, options=SERVER["options"])
        app = create_app(load_settings(settings_env),
                         model=ScriptedModel(list(default_steps)), clients={"Copilot": cli})
        client = TestClient(app, base_url="http://127.0.0.1:8790", headers=PAGE)
        client.__enter__()
        opened.append(client)
        made = client.post("/api/providers", json={
            "name": "Copilot", "kind": "copilot_cli", "mode": "native", **SERVER})
        assert made.status_code == 201, made.text
        return client, made.json()

    make.rescript = write_plan
    make.record = lambda: json.loads(record.read_text(encoding="utf-8"))
    yield make
    for client in opened:
        client.__exit__(None, None, None)


def test_copilot_works_natively_and_what_it_did_is_on_record(
    copilot_native, wait_run, project_dir
):
    client, provider = copilot_native([
        {"say": "I will fix it."},
        {"read": "hello.py", "result": "print('hi')"},
        {"write": "hello.py", "content": "print('hello')\n"},
        {"shell": "python hello.py", "output": "hello"},
        {"say": "Fixed and checked."}], model="qwen-as-served")
    assert provider["mode"] == "native"
    cid, run_id = start(client, project_dir, provider)  # full_auto
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert (project_dir / "hello.py").read_text() == "print('hello')\n"
    assert [(t["name"], t["status"], t["origin"]) for t in snap["tool_calls"]] == [
        ("copilot__view", "succeeded", "cli"), ("edit_file", "succeeded", "cli"),
        ("run_command", "succeeded", "cli")]
    change = snap["file_changes"][0]
    assert (change["path"], change["status"], change["origin"]) == ("hello.py", "applied", "cli")
    assert "+print('hello')" in change["diff"]
    ran = snap["commands"][0]
    assert (ran["command"], ran["status"], ran["exit_code"], ran["origin"]) == (
        "python hello.py", "exited", 0, "cli")
    assert ran["output"].strip() == "hello"
    lead = snap["agents"][0]
    assert lead["model_id"] == "qwen-as-served" and lead["input_tokens"] is None
    assert (lead["nano_aiu"], lead["premium_requests"]) == (None, None)  # it said nothing
    seen = copilot_native.record()
    argv = seen["argv"]
    # headless, asking first (slice 89c): never with leave for every tool of its own
    assert "--allow-all-tools" not in argv and "--available-tools" not in argv
    assert argv[-5:] == ["--headless", "--no-auto-update", "--log-level", "error", "--stdio"]
    assert seen["create"]["requestPermission"] is True
    assert seen["create"]["workingDirectory"] == str(project_dir)
    assert seen["create"]["model"] == "qwen-local"
    assert seen["create"]["mcpServers"]["koloni"]["tools"] == ["*"]
    assert "what does it print?" in seen["prompt"]  # the turn, as session.send's prompt
    # B-389: a change is made with its edit tool, not a patch sent as a command
    assert "To change a file, use your own file edit tool" in seen["prompt"]
    assert seen["cwd"] == str(project_dir)  # in the project, not a scratch folder
    assert seen["home_was_empty"] and KEY not in json.dumps(seen["argv"])
    assert "spawn_agent" in seen["tools"] and "read_file" not in seen["tools"]
    assert "ask_folder" in seen["tools"]  # (K-75-kalan: a folder asked for on the same card)
    assert "approve" not in seen["tools"]  # it asks over its own protocol, never by a tool


def test_native_copilot_runs_at_every_level_now_that_it_asks_first(
    copilot_native, wait_run, project_dir
):
    client, provider = copilot_native([{"say": "hello"}])
    cid, run_id = start(client, project_dir, provider, mode="ask")
    run = wait_run(client, cid, run_id)["runs"][0]
    assert run["status"] == "completed", run["error"]


# Its session.usage_checkpoint's counts, trimmed to what is read (1.0.103 `-p`, 5 Nov 2026).
LUNA = {"inputTokens": 22674, "outputTokens": 36, "cacheReadTokens": 0,
        "cacheWriteTokens": 22671, "reasoningTokens": 29}


def test_native_copilot_puts_the_tokens_it_reports_on_record(
    copilot_native, wait_run, project_dir
):
    # Each checkpoint is its session's total so far: the last stands, its models summed.
    first = {"totalPremiumRequests": 1,
             "accountingSnapshot": {"modelMetrics": {"gpt-6-luna": {"usage": LUNA}}}}
    last = {"totalPremiumRequests": 2, "totalNanoAiu": 448558500, "accountingSnapshot": {"modelMetrics": {
        "gpt-6-luna": {"usage": {**LUNA, "inputTokens": 45400, "outputTokens": 70,
                                 "cacheReadTokens": 22671}},
        "claude-haiku-4.5": {"usage": {"inputTokens": 1000, "outputTokens": 30}}}}}
    client, provider = copilot_native([{"say": "OK"}], usage=[first, last])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    lead = snap["agents"][0]
    assert (lead["input_tokens"], lead["output_tokens"]) == (46400, 100)
    assert (lead["cache_read_tokens"], lead["cache_write_tokens"]) == (22671, 22671)
    assert (lead["nano_aiu"], lead["premium_requests"]) == (448558500, 2)


def test_copilot_with_p_its_talker_too_puts_the_tokens_it_reports_on_record(
    copilot_app, wait_run, project_dir
):
    # (The checkpoint above was measured with `-p`: in a discussion native Copilot speaks so.)
    last = {"totalPremiumRequests": 1, "totalNanoAiu": 224279250,
            "accountingSnapshot": {"modelMetrics": {"gpt-6-luna": {"usage": LUNA}}}}
    client, provider = copilot_app([{"say": "OK"}], usage=[{"totalPremiumRequests": 0}, last])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    lead = snap["agents"][0]
    assert (lead["input_tokens"], lead["output_tokens"]) == (22674, 36)
    assert (lead["cache_read_tokens"], lead["cache_write_tokens"]) == (0, 22671)
    assert (lead["nano_aiu"], lead["premium_requests"]) == (224279250, 1)


def test_in_a_discussion_native_copilot_speaks_as_a_session():
    from app.model_native import CopilotNativeClient

    native = CopilotNativeClient(None, "m", timeout=5, base_url="http://x/v1")
    assert isinstance(native.talker(), CopilotSessionClient)


def test_native_copilot_reports_a_crash_without_the_key(copilot_native, wait_run, project_dir):
    client, provider = copilot_native([
        {"exit": 3, "stderr": "401 Incorrect API key: " + KEY + "x" * 290}])
    cid, run_id = start(client, project_dir, provider)
    error = wait_run(client, cid, run_id)["runs"][0]["error"]
    assert "exited with code 3" in error
    assert "secret" not in error and "et-123" not in error


def test_native_copilot_reports_its_own_error_without_the_key(
    copilot_native, wait_run, project_dir
):
    client, provider = copilot_native([{"error": f"model server said no (key {KEY})"}])
    cid, run_id = start(client, project_dir, provider)
    error = wait_run(client, cid, run_id)["runs"][0]["error"]
    assert "model server said no" in error and KEY not in error


def test_copilots_exit_code_is_read_from_its_trailer_only():
    from app.model_native import CopilotNativeClient

    translate = CopilotNativeClient(None, "m", base_url="http://x/v1")._translator({"c1"})
    translate({"type": "tool.execution_start", "data": {
        "toolCallId": "c1", "toolName": "powershell", "arguments": {"command": "run"}}})
    *_, done = translate({"type": "tool.execution_complete", "data": {
        "toolCallId": "c1", "success": True, "result": {"content": (
            "job completed with exit code 0\nFAILED\n<shellId: 2 completed with exit code 1>")}}})
    item = done["item"]
    assert item["unasked"] is False  # it was asked about
    assert item["exit_code"] == 1
    assert item["aggregated_output"] == "job completed with exit code 0\nFAILED\n"


def test_always_run_rules_cannot_be_stretched_with_a_wrapper():
    from app.commands import is_allowed, suggest_prefix

    for wrapped in ("PYTHONPATH=. pytest -q", "env X=1 pytest", "timeout 5 pytest",
                    "xargs rm", "sudo pytest", "nohup pytest"):
        assert suggest_prefix(wrapped) == "", wrapped
    assert not is_allowed("PYTHONPATH=. rm -rf src", ["PYTHONPATH=."])
    assert not is_allowed("env X=1 rm -rf src", ["env"])
    assert is_allowed("pytest -q tests", ["pytest"])


def test_a_copilot_command_with_no_exit_code_fails_only_once_it_is_over():
    # B-377: no code from a command run to its end is no success; one still at work is not known.
    from app.model_native import CopilotNativeClient

    def ended(arguments, said):
        translate = CopilotNativeClient(None, "m", base_url="http://x/v1")._translator({"c1"})
        translate({"type": "tool.execution_start", "data": {
            "toolCallId": "c1", "toolName": "powershell", "arguments": arguments}})
        *_, done = translate({"type": "tool.execution_complete", "data": {
            "toolCallId": "c1", "success": True, "result": {"content": said}}})
        return done["item"]["status"]

    assert ended({"command": "pytest"}, "cut off") == "failed"
    assert ended({"command": "npm run dev", "mode": "async"}, "started") == "completed"
    assert ended({"command": "pytest"}, "12 passed so far\n<shellId: 4> still running") == "completed"
    assert ended({"command": "pytest"}, "ok\n<shellId: 12 completed with exit code 0>") == "completed"


# Its levels, as `copilot --help` names them (CLI 1.0.105, 6 Nov 2026): --reasoning-effort, with
# none for KOLONİ's off; every model the same (what one does with a level it lacks: not measured).
@pytest.mark.anyio
async def test_copilot_is_given_its_level_flag_only_when_a_level_is_asked(tmp_path):
    from app import catalog

    record, plan = tmp_path / "record.json", tmp_path / "plan.json"
    plan.write_text(json.dumps({"record": str(record), "script": [{"say": "ok"}]}),
                    encoding="utf-8")
    cli = CopilotSessionClient(None, "gpt-x", timeout=30, launcher=FAKE,
                               env={"FAKE_CLI_PLAN": str(plan)}, options={})
    levels = ("off", "low", "medium", "high", "xhigh", "max")
    assert (await cli.info()).efforts == levels
    assert tuple(catalog.facts("copilot_cli", None, "gpt-x")[0]["efforts"]) == levels

    async def quiet(_text):
        pass

    async def no_tool(_name, _arguments):
        return True, ""

    for effort, sent in ((None, None), ("off", "none"), ("high", "high")):
        await cli.run_session("gpt-x", [{"role": "user", "content": "hi"}], [], no_tool, quiet,
                              effort=effort)
        argv = json.loads(record.read_text(encoding="utf-8"))["argv"]
        assert argv[:2] == ["--reasoning-effort", sent] if sent else (
            "--reasoning-effort" not in argv)


def test_native_copilot_starts_its_headless_server_at_the_level_asked(tmp_path):
    from app.model_native import CopilotNativeClient

    native = CopilotNativeClient(None, "gpt-x", options={})
    line = native._native_arguments(tmp_path, tmp_path / "bridge.json")
    assert native.efforts == CopilotSessionClient.efforts
    assert native._leveled(line, None) == line
    assert native._leveled(line, "off") == ["--reasoning-effort", "none", *line]
    assert native._leveled(line, "high")[:2] == ["--reasoning-effort", "high"]
    assert line[-5:] == ["--headless", "--no-auto-update", "--log-level", "error", "--stdio"]


# Measured 7 Nov 2026 (CLI 1.0.105): `--model auto --reasoning-effort medium` fails at once.
@pytest.mark.anyio
async def test_copilot_auto_is_sent_no_level_as_a_session_or_natively(tmp_path):
    from app.model_native import CopilotNativeClient

    record, plan = tmp_path / "record.json", tmp_path / "plan.json"
    plan.write_text(json.dumps({"record": str(record), "script": [{"say": "ok"}]}),
                    encoding="utf-8")
    cli = CopilotSessionClient(None, "auto", timeout=30, launcher=FAKE,
                               env={"FAKE_CLI_PLAN": str(plan)}, options={})
    assert cli.level_named and (await cli.info()).efforts == ()

    async def quiet(_text):
        pass

    async def no_tool(_name, _arguments):
        return True, ""

    await cli.run_session("auto", [{"role": "user", "content": "hi"}], [], no_tool, quiet,
                          effort="medium")
    assert "--reasoning-effort" not in json.loads(record.read_text(encoding="utf-8"))["argv"]
    native = CopilotNativeClient(None, "auto", options={})
    line = native._native_arguments(tmp_path, tmp_path / "bridge.json")
    assert native.level_named and native.efforts == ()
    assert native._leveled(line, "medium") == line
    # Another model still gets its level; auto on a server of one's own is that server's name.
    assert CopilotNativeClient(None, "gpt-x", options={})._leveled(line, "medium")[:2] == [
        "--reasoning-effort", "medium"]
    served = CopilotSessionClient(None, "auto", base_url="http://127.0.0.1:8080/v1", options={})
    assert not served.level_named and served._leveled(["-p"], "low")[:2] == [
        "--reasoning-effort", "low"]
