"""K-copilot-giris: Copilot on the user's own GitHub sign-in, no token. Measured on Copilot
1.0.103 (24 Oct 2026): in an empty COPILOT_HOME, with no COPILOT_* / GH_* / GITHUB_* variable
and no token, `auth.getStatus` said `isAuthenticated: true, authType: "gh-cli"` - and whose
account it is in its `statusMessage`, which is never kept, logged or shown."""

import json
import logging
import sys

import pytest

import app.limits
from app.api.providers import NOT_SIGNED_IN
from app.config import load_settings
from app.limits import copilot_signed_in  # (the reader itself: conftest stands it in)
from app.main import create_app
from app.model_native import CopilotNativeClient
from app.model_session import CopilotSessionClient
from tests.fakes import ScriptedModel
from tests.keyed import TestClient
from tests.test_copilot_agent import FAKE, HEADLESS, start

ORIGIN = {"Origin": "http://127.0.0.1:8790"}
LOGIN = "someone-on-github"  # what the stand-in says of whose account it is


def plan(tmp_path, monkeypatch, **more):
    record, given = tmp_path / "record.json", tmp_path / "plan.json"
    given.write_text(json.dumps({"record": str(record), "script": [], **more}), encoding="utf-8")
    monkeypatch.setenv("FAKE_CLI_PLAN", str(given))
    return record


@pytest.fixture
def users_own_shell(monkeypatch):
    """The user's own Copilot and GitHub set-up in the shell KOLONİ was started from."""
    monkeypatch.setenv("COPILOT_GITHUB_TOKEN", "the user's own")
    monkeypatch.setenv("GH_TOKEN", "ghp_the_users_own")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_the_users_own_too")


def run_once(settings_env, client_of, project_dir, wait_run):
    app = create_app(load_settings(settings_env), model=ScriptedModel([]),
                     clients={"Copilot": client_of})
    with TestClient(app, base_url="http://127.0.0.1:8790") as client:
        made = client.post("/api/providers", json={
            "name": "Copilot", "kind": "copilot_cli", "default_model": "gpt-x",
            "mode": "native" if isinstance(client_of, CopilotNativeClient) else "session"})
        assert made.status_code == 201, made.text
        cid, run_id = start(client, project_dir, made.json())
        return wait_run(client, cid, run_id)["runs"][0]


def test_a_copilot_session_without_a_token_runs_in_an_empty_home_by_the_users_sign_in(
    settings_env, tmp_path, wait_run, project_dir, monkeypatch, users_own_shell
):
    record = plan(tmp_path, monkeypatch, script=[{"say": "hello"}])
    cli = CopilotSessionClient(None, "gpt-x", timeout=30, launcher=FAKE, options={})
    run = run_once(settings_env, cli, project_dir, wait_run)
    assert run["status"] == "completed", run["error"]
    seen = json.loads(record.read_text(encoding="utf-8"))
    assert sorted(seen["env"]) == ["COPILOT_HOME"] and seen["github_tokens"] == []
    assert seen["home_was_empty"]
    argv = seen["argv"]
    assert argv[argv.index("--model") + 1] == "gpt-x"
    assert not any(one.startswith("--secret-env-vars") for one in argv)


def test_native_copilot_without_a_token_runs_in_an_empty_home_by_the_users_sign_in(
    settings_env, tmp_path, wait_run, project_dir, monkeypatch, users_own_shell
):
    record = plan(tmp_path, monkeypatch, script=[{"say": "hello"}])
    cli = CopilotNativeClient(None, "gpt-x", timeout=30, launcher=HEADLESS, options={})
    run = run_once(settings_env, cli, project_dir, wait_run)
    assert run["status"] == "completed", run["error"]
    seen = json.loads(record.read_text(encoding="utf-8"))
    assert sorted(seen["env"]) == ["COPILOT_HOME"] and seen["github_tokens"] == []
    assert seen["home_was_empty"]
    assert not any(one.startswith("--secret-env-vars") for one in seen["argv"])


@pytest.mark.anyio
async def test_copilot_is_asked_only_whether_it_is_signed_in_and_nothing_of_whom(
    tmp_path, monkeypatch, users_own_shell
):
    record = plan(tmp_path, monkeypatch)
    told = await copilot_signed_in(None, None, 20, launcher=HEADLESS)
    assert told == {"isAuthenticated": True, "authType": "gh-cli"}
    seen = json.loads(record.read_text(encoding="utf-8"))
    assert seen["status_asked"] == {} and "create" not in seen and "prompt" not in seen
    assert sorted(seen["env"]) == ["COPILOT_HOME"] and seen["home_was_empty"]
    plan(tmp_path, monkeypatch, signed_in=False)
    assert await copilot_signed_in(None, None, 20, launcher=HEADLESS) == {
        "isAuthenticated": False, "authType": None}


def test_the_providers_check_says_whether_copilot_is_signed_in_and_never_as_whom(
    settings_env, tmp_path, monkeypatch, caplog, users_own_shell
):
    async def asked(executable, token, timeout):  # the reader, on the stand-in
        return await copilot_signed_in(executable, token, timeout, launcher=HEADLESS)

    caplog.set_level(logging.DEBUG)
    monkeypatch.setattr(app.limits, "copilot_signed_in", asked)
    plan(tmp_path, monkeypatch)
    cli = CopilotSessionClient(None, None, timeout=30, launcher=FAKE, options={})
    app_ = create_app(load_settings(settings_env), model=ScriptedModel([]),
                      clients={"Copilot": cli})
    with TestClient(app_, base_url="http://127.0.0.1:8790") as client:
        # (Its command found on this machine: any program that is there.)
        made = client.post("/api/providers", headers=ORIGIN, json={
            "name": "Copilot", "kind": "copilot_cli", "executable": sys.executable}).json()
        seen = client.get(f"/api/providers/{made['id']}/availability", headers=ORIGIN)
        assert seen.json()["signed_in"] is True
        tested = client.post(f"/api/providers/{made['id']}/test", headers=ORIGIN)
        assert tested.json()["ok"] is True, tested.text
        answers = [seen.text, tested.text]

        plan(tmp_path, monkeypatch, signed_in=False)
        seen = client.get(f"/api/providers/{made['id']}/availability", headers=ORIGIN).json()
        assert seen["signed_in"] is False and seen["sign_in"]["command"] == "gh auth login"
        tested = client.post(f"/api/providers/{made['id']}/test", headers=ORIGIN).json()
        assert (tested["ok"], tested["error"]) == (False, NOT_SIGNED_IN)
        assert "gh auth login" in NOT_SIGNED_IN
    # Whose account it is: in no answer, no log line, nothing KOLONİ keeps.
    assert not any(LOGIN in text for text in answers) and LOGIN not in caplog.text
    runtime = tmp_path / "runtime"
    assert not any(LOGIN.encode() in path.read_bytes()
                   for path in runtime.rglob("*") if path.is_file())
