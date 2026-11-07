"""K-cli-llama: Claude Code and Codex on the user's own model server (llama-server), with the
stand-in CLIs and a stand-in server that only lists its model."""

import http.server
import json
import socket
import sys
import threading
from pathlib import Path

import pytest

import app.catalog
from app.config import load_settings
from app.db.models import Provider
from app.limits import account
from app.main import create_app
from app.model_cli import ClaudeCliClient, CodexCliClient
from app.model_client import OwnStop
from app.model_native import ClaudeNativeClient, CodexNativeClient
from app.model_session import ClaudeSessionClient
from app.providers import Providers
from tests.fakes import ScriptedModel
from tests.keyed import TestClient
from tests.test_claude_native import FAKE as FAKE_NATIVE
from tests.test_model_cli import FAKE, step
from tests.test_session_agent import FAKE as FAKE_SESSION
from tests.test_session_agent import start
from tests.test_usage_scenarios import usage

pytestmark = pytest.mark.anyio

MODEL = "Qwen3-0.6B"
PLANTED = "sk-ant-test-DO-NOT-LEAK"
OWN = {"Origin": "http://127.0.0.1:8790"}  # (an address is set from the app's own page only)
KEYS = ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "OPENAI_API_KEY", "CODEX_API_KEY",
        "CODEX_ACCESS_TOKEN", "CLAUDE_CODE_USE_BEDROCK")
# What a started CLI was given, as the stand-ins record it.
DUMP = ("import json, os; print(json.dumps({n: os.environ.get(n) for n in ("
        "'ANTHROPIC_BASE_URL', 'ANTHROPIC_AUTH_TOKEN', 'CLAUDE_CONFIG_DIR', 'CODEX_HOME', "
        "'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC', " + ", ".join(map(repr, KEYS)) + ")}))")


@pytest.fixture
def llama():
    """A model server on this machine that lists its one model: its OpenAI-compatible address."""

    class Models(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            listed = self.path == "/v1/models"
            body = json.dumps({"data": [{"id": MODEL}]}).encode() if listed else b"{}"
            self.send_response(200 if listed else 404)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Models)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/v1"
    server.shutdown()
    server.server_close()


@pytest.fixture
def keys(monkeypatch):
    """The user's own sign-ins, as they could be in KOLONİ's environment."""
    for name in KEYS:
        monkeypatch.setenv(name, PLANTED)


def closed_port() -> int:
    with socket.socket() as free:
        free.bind(("127.0.0.1", 0))
        return free.getsockname()[1]


def made(kind, tmp_path, server, **plan):
    record, planned = tmp_path / "record.json", tmp_path / "plan.json"
    planned.write_text(json.dumps({"record": str(record), **plan}), encoding="utf-8")
    env = {"FAKE_CLI_PLAN": str(planned), "CODEX_HOME": str(tmp_path)}  # (not the user's)
    client = kind(model=MODEL, timeout=20.0, launcher=FAKE, env=env, server=server,
                  homes=tmp_path / "homes")
    return client, record


def kolonis_empty_home(tmp_path, home: str | None) -> bool:
    """Whether a CLI's home is one of KOLONİ's own, made for it, with nothing of the user's."""
    return home is not None and Path(home).parent == tmp_path / "homes" and Path(home).is_dir()


# Each CLI's own sign-ins: the ones it would send to the address it is pointed at.
SIGN_INS = {"claude": ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK"),
            "codex": ("OPENAI_API_KEY", "CODEX_API_KEY", "CODEX_ACCESS_TOKEN")}


def nothing_of_the_users(told: dict, command: str) -> bool:
    return not any(told[name] for name in SIGN_INS[command])


def settings_of(server: str) -> list[str]:
    named = "model_providers.koloni_local"
    return ["-c", "model_provider='koloni_local'", "-c", f"{named}.name='koloni_local'",
            "-c", f"{named}.base_url='{server}'", "-c", f"{named}.wire_api='responses'"]


def holds(argv: list[str], part: list[str]) -> bool:
    return any(argv[at:at + len(part)] == part for at in range(len(argv)))


async def test_claude_code_goes_to_the_servers_messages_with_a_stand_in_token_and_no_key(
    tmp_path, llama, keys
):
    client, record = made(ClaudeCliClient, tmp_path, llama)
    result, _ = await step(client)
    told = json.loads(record.read_text(encoding="utf-8"))
    # Its Anthropic API is beside the OpenAI one (llama-server's /v1/messages): no /v1 twice.
    assert told["sign_in"]["base_url"] == llama.removesuffix("/v1")
    assert told["sign_in"]["placeholder"] is True
    assert nothing_of_the_users(told["sign_in"], "claude")
    assert kolonis_empty_home(tmp_path, told["sign_in"]["CLAUDE_CONFIG_DIR"])
    assert told["sign_in"]["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] == "1"
    assert holds(told["argv"], ["--model", MODEL])
    # What it used is real and is kept; the stand-in also reported total_cost_usd, never read.
    assert (result.input_tokens, result.output_tokens) == (100, 7)
    assert not hasattr(result, "cost")


async def test_codex_is_given_the_server_as_a_responses_provider_and_no_key(
    tmp_path, llama, keys
):
    (tmp_path / "config.toml").write_text("[mcp_servers.mine]\ncommand = 'x'\n", "utf-8")
    client, record = made(CodexCliClient, tmp_path, llama)
    await step(client)
    told = json.loads(record.read_text(encoding="utf-8"))
    assert holds(told["argv"], settings_of(llama))
    assert holds(told["argv"], ["--model", MODEL])
    assert nothing_of_the_users(told["sign_in"], "codex")
    assert told["sign_in"]["base_url"] is None  # (Claude Code's alone)
    # Not the CODEX_HOME it was given: KOLONİ's own, with no stored login, profile or provider
    # of the user's - whose MCP servers are then not there to switch off.
    assert kolonis_empty_home(tmp_path, told["sign_in"]["CODEX_HOME"])
    assert not any("mcp_servers.mine" in one for one in told["argv"])


def test_native_codex_gets_the_server_before_its_app_server_and_talkers_keep_it(tmp_path):
    server = "http://127.0.0.1:8180/v1"
    native = CodexNativeClient(env={"CODEX_HOME": str(tmp_path)}, server=server)
    argv = native._native_arguments(tmp_path, tmp_path / "b.json")
    assert argv[-1] == "app-server" and holds(argv, settings_of(server))
    assert holds(argv, ["-c", "features.multi_agent=false"])  # B-304: no sub-agents of its own
    assert holds(argv, ["-c", "features.plugins=false"])  # B-312: nor the user's own plugins
    assert native.talker().server == server
    assert ClaudeNativeClient(server=server).talker().server == server
    # Claude Code there loads no settings at all, not the project's either.
    claude = ClaudeNativeClient(server=server)._native_arguments(tmp_path, tmp_path / "b.json")
    assert holds(claude, ["--setting-sources", ""])
    # On its own sign-in: none of it.
    assert "model_provider='koloni_local'" not in CodexNativeClient(
        env={"CODEX_HOME": str(tmp_path)})._native_arguments(tmp_path, tmp_path / "b.json")


async def test_a_server_that_is_not_running_is_refused_before_the_cli_starts(tmp_path):
    down = f"http://127.0.0.1:{closed_port()}/v1"
    client, record = made(ClaudeCliClient, tmp_path, down)
    with pytest.raises(OwnStop, match="start your local model server first"):
        await step(client)
    assert not record.exists()
    with pytest.raises(OwnStop, match="start your local model server first"):
        await client.info()  # the Models page's Check and the banner say it too


@pytest.mark.parametrize(("kind", "mode", "built"), [
    ("claude_cli", "session", ClaudeSessionClient), ("claude_cli", "step", ClaudeCliClient),
    ("claude_cli", "native", ClaudeNativeClient), ("codex_cli", "step", CodexCliClient),
    ("codex_cli", "native", CodexNativeClient)])
def test_every_way_of_running_is_built_on_the_providers_server(settings_env, kind, mode, built):
    provider = Provider(id="p", name="Local CLI", kind=kind, mode=mode,
                        base_url="http://127.0.0.1:8180/v1")
    client = Providers(load_settings(settings_env))._build(provider, MODEL)
    assert isinstance(client, built) and client.server == provider.base_url
    assert client.on_limits is None  # nothing it says is of the user's plan


async def test_native_claude_code_codex_and_their_talkers_are_started_with_nothing_of_the_users(
    tmp_path, llama, keys
):
    native = ClaudeNativeClient(server=llama, homes=tmp_path / "homes")
    codex = CodexNativeClient(server=llama, homes=tmp_path / "homes")
    for client in (native, native.talker(), codex, codex.talker()):
        # (As `run_native` starts it: with the secret variables a project passes as well.)
        started, _job = await client._start([sys.executable, "-c", DUMP], False, tmp_path,
                                      {"ANTHROPIC_API_KEY": PLANTED, "CODEX_API_KEY": PLANTED})
        told = json.loads((await started.communicate())[0])
        assert nothing_of_the_users(told, client.command), client
        home = told["CLAUDE_CONFIG_DIR" if client.command == "claude" else "CODEX_HOME"]
        assert kolonis_empty_home(tmp_path, home), client


@pytest.mark.parametrize("kind", ["claude_cli", "codex_cli"])
def test_only_an_address_on_this_machine_or_the_lan_is_taken_and_never_a_key(client, kind):
    def add(address, **more):
        return client.post("/api/providers", headers=OWN, json={
            "name": f"{kind} {address}", "kind": kind, "base_url": address, **more})

    added = add("http://127.0.0.1:8180/v1/", api_key="sk-real")
    assert added.status_code == 201, added.text
    assert (added.json()["base_url"], added.json()["has_key"]) == ("http://127.0.0.1:8180/v1", False)
    for nearby in ("http://192.168.1.20:8080/v1", "http://localhost:8080/v1",
                   "http://[::1]:8080/v1", "http://[fd00::5]:8080/v1"):
        assert add(nearby).status_code == 201, nearby
    for elsewhere in ("https://api.anthropic.com", "http://example.com:8080/v1",
                      "http://8.8.8.8:8080/v1", "http://[2001:4860::8888]:8080/v1",
                      "http://0.0.0.0:8080/v1", "http://[::]:8080/v1",
                      "http://169.254.169.254/v1", "http://240.0.0.1:8080/v1",
                      "http://127.0.0.1:99999/v1", "http://127.0.0.1:8080",
                      "http://127.0.0.1:8080/v1'", "http://user:pw@127.0.0.1:8080/v1",
                      "http://127.0.0.1:8080/v1?k=1", "http://127.0.0.\u0661:8080/v1"):
        assert add(elsewhere).status_code == 422, elsewhere
    # Not an agent's to point elsewhere (a command against the app's address).
    by_command = client.post("/api/providers", json={
        "name": f"{kind} by a command", "kind": kind, "base_url": "http://127.0.0.1:8180/v1"})
    assert by_command.status_code == 403
    moved = client.patch(f"/api/providers/{added.json()['id']}",
                         json={"base_url": "http://192.168.1.9:8080/v1"})
    assert moved.status_code == 403
    # Taken off again: on the user's own sign-in.
    patched = client.patch(f"/api/providers/{added.json()['id']}", json={"base_url": ""},
                           headers=OWN)
    assert patched.status_code == 200 and patched.json()["base_url"] is None


def test_claude_codes_own_setup_never_goes_with_a_model_server(client):
    told = client.post("/api/providers", headers=OWN, json={
        "name": "Claude local", "kind": "claude_cli", "mode": "native",
        "base_url": "http://127.0.0.1:8180/v1", "options": {"own_setup": True}})
    assert told.status_code == 422 and "cannot go with a model server" in told.text
    own = client.post("/api/providers", headers=OWN, json={
        "name": "Claude mine", "kind": "claude_cli", "mode": "native",
        "options": {"own_setup": True}}).json()
    moved = client.patch(f"/api/providers/{own['id']}", headers=OWN,
                         json={"base_url": "http://127.0.0.1:8180/v1"})
    assert moved.status_code == 422


def test_its_models_are_the_servers_and_its_sign_in_is_not_asked(client, llama, monkeypatch):
    async def never(kind, executable, home=None):
        raise AssertionError("the CLI's own sign-in was asked")

    monkeypatch.setattr(app.catalog, "installed", lambda kind, executable: True)
    monkeypatch.setattr(app.catalog, "signed_in", never)
    monkeypatch.setattr(app.catalog, "status", never)
    for kind in ("claude_cli", "codex_cli"):
        added = client.post("/api/providers", headers=OWN, json={
            "name": f"{kind} local", "kind": kind, "base_url": llama}).json()
        # Not Claude Code's own aliases (sonnet, opus...): what the server serves.
        assert client.get(f"/api/providers/{added['id']}/models").json()["models"] == [MODEL]
        seen = client.get(f"/api/providers/{added['id']}/availability")
        assert seen.status_code == 200 and seen.json().get("signed_in") is None


def test_its_room_is_not_the_users_plan(llama):
    # One command, one sign-in: the real Claude Code's limit is not the local one's (with_room,
    # plan_used and every reading go by `account`).
    real = Provider(id="real", name="Claude Code", kind="claude_cli")
    local = Provider(id="local", name="Claude local", kind="claude_cli", base_url=llama)
    assert account(real) == ("claude_cli", None) and account(local) == ("local",)


def test_a_session_on_the_local_server_counts_tokens_and_never_money(
    settings_env, tmp_path, llama, keys, project_dir, wait_run
):
    record, planned = tmp_path / "record.json", tmp_path / "plan.json"
    planned.write_text(json.dumps({"record": str(record), "script": [{"say": "hi"}]}),
                       encoding="utf-8")
    cli = ClaudeSessionClient(launcher=FAKE_SESSION, timeout=30, server=llama,
                              env={"FAKE_CLI_PLAN": str(planned)}, homes=tmp_path / "homes")
    app = create_app(load_settings(settings_env), model=ScriptedModel([]),
                     clients={"Local Claude": cli})
    with TestClient(app, base_url="http://127.0.0.1:8790") as client:
        client.headers["Origin"] = "http://127.0.0.1:8790"
        provider = client.post("/api/providers", json={
            "name": "Local Claude", "kind": "claude_cli", "base_url": llama})
        assert provider.status_code == 201, provider.text
        cid, run_id = start(client, project_dir, provider.json())
        assert wait_run(client, cid, run_id)["runs"][0]["status"] == "completed"
        # The stand-in reports total_cost_usd 1.0, as Claude Code does on a local model too;
        # and a price is set for the very model its row names, so a row priced like a
        # service's would have a cost.
        (row,) = usage(client)["by_model"]
        price = {"model_id": row["model_id"], "input": 3, "output": 15, "currency": "USD"}
        assert client.put("/api/prices", json=price).status_code == 200
        (row,) = usage(client)["by_model"]
        assert row["input_tokens"] and row["cost"] is None
    told = json.loads(record.read_text(encoding="utf-8"))["sign_in"]
    assert (told["base_url"], told["placeholder"]) == (llama.removesuffix("/v1"), True)
    assert not any(told[name] for name in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN",
                                            "CLAUDE_CODE_USE_BEDROCK"))
    assert kolonis_empty_home(tmp_path, told["CLAUDE_CONFIG_DIR"])


def test_a_native_turn_on_the_local_server_is_started_with_nothing_of_the_users(
    settings_env, tmp_path, llama, keys, project_dir, wait_run
):
    record, planned = tmp_path / "record.json", tmp_path / "plan.json"
    planned.write_text(json.dumps({"record": str(record), "script": [{"say": "done"}]}),
                       encoding="utf-8")
    cli = ClaudeNativeClient(launcher=FAKE_NATIVE, timeout=30, server=llama,
                             env={"FAKE_CLI_PLAN": str(planned)}, homes=tmp_path / "homes")
    app = create_app(load_settings(settings_env), model=ScriptedModel([]),
                     clients={"Claude local": cli})
    with TestClient(app, base_url="http://127.0.0.1:8790") as client:
        client.headers["Origin"] = "http://127.0.0.1:8790"
        provider = client.post("/api/providers", json={
            "name": "Claude local", "kind": "claude_cli", "mode": "native", "base_url": llama})
        assert provider.status_code == 201, provider.text
        cid, run_id = start(client, project_dir, provider.json())
        assert wait_run(client, cid, run_id)["runs"][0]["status"] == "completed"
    told = json.loads(record.read_text(encoding="utf-8"))
    assert holds(told["argv"], ["--setting-sources", ""])
    signed = told["sign_in"]
    assert (signed["base_url"], signed["placeholder"]) == (llama.removesuffix("/v1"), True)
    assert not any(signed[name] for name in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN",
                                              "CLAUDE_CODE_USE_BEDROCK"))
    assert kolonis_empty_home(tmp_path, signed["CLAUDE_CONFIG_DIR"])
    assert signed["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] == "1"
