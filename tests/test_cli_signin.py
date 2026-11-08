"""K-codex-ev + K-claude-hesap: a Claude Code or Codex provider may sign in with a folder of its
own (`sign_in`: "koloni"), so several accounts run side by side. Stand-in CLIs only: no real
`claude` or `codex` is started, and no real home folder is looked at."""

import json
import shlex
import sys
import time
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

import pytest

from app.agent import sandbox_denied
from app.commands import names_secret
from app.config import load_settings
from app.db.models import Provider
from app.limits import CLI_HOMES, Limits, account, claude_turn, cli_home, of_session
from app.model_cli import ClaudeCliClient, CodexCliClient
from app.model_native import ClaudeNativeClient, CodexNativeClient
from app.model_session import ClaudeSessionClient
from app.providers import Providers, check_options
from app.workspace import Workspace, WorkspaceError
from tests.test_chat_flow import text
from tests.test_cli_llama import DUMP, KEYS, PLANTED, nothing_of_the_users
from tests.test_folders import start
from tests.test_model_cli import FAKE
from tests.test_outside_folders_scenarios import project, read

ORIGIN = {"Origin": "http://127.0.0.1:8790"}
KOLONI = {"sign_in": "koloni"}
A, B = "a" * 32, "b" * 32  # (ids as KOLONİ makes them)


@pytest.fixture
def keys(monkeypatch):
    """The user's own sign-ins, as they could be in KOLONİ's environment."""
    for name in KEYS:
        monkeypatch.setenv(name, PLANTED)


def status_cli(tmp_path, answer: dict, code: int = 0) -> str:
    """A stand-in Claude Code that notes the folder it was given and answers `auth status`
    with `answer` - an email and an organisation in it, as the real one's has."""
    record, script = tmp_path / "seen.jsonl", tmp_path / "claude_status.py"
    script.write_text(
        "import json, os, sys\n"
        f"open({str(record)!r}, 'a').write(json.dumps([sys.argv[1:], "
        "os.environ.get('CLAUDE_CONFIG_DIR'), 'ANTHROPIC_API_KEY' in os.environ]) + '\\n')\n"
        "if sys.argv[1:] == ['--help']:\n"
        "    print('Commands:\\n  auth   Manage authentication')\n"
        "    sys.exit(0)\n"
        f"print(json.dumps({answer!r}))\n"
        f"sys.exit({code})\n", encoding="utf-8")
    if sys.platform == "win32":
        shim = tmp_path / "claude.cmd"
        shim.write_text(f'@"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
    else:
        shim = tmp_path / "claude"
        shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n')
        shim.chmod(0o755)
    return str(shim)


def seen(tmp_path) -> list:
    return [json.loads(line) for line in (tmp_path / "seen.jsonl").read_text().splitlines()]


@pytest.mark.parametrize(("kind", "mode", "built"), [
    ("claude_cli", "session", ClaudeSessionClient), ("claude_cli", "step", ClaudeCliClient),
    ("claude_cli", "native", ClaudeNativeClient), ("codex_cli", "step", CodexCliClient),
    ("codex_cli", "native", CodexNativeClient)])
def test_every_way_of_running_gets_the_providers_own_folder_and_its_own_limits(
        settings_env, kind, mode, built):
    settings = load_settings(settings_env)
    providers = Providers(settings)
    own = Provider(id=A, name="Work", kind=kind, mode=mode, options=KOLONI)
    client = providers._build(own, None)
    folder = settings.runtime_root / CLI_HOMES / A
    assert isinstance(client, built) and client.home == folder
    # Its settings are read there too: none of the user's ~/.claude or ~/.codex.
    assert client._env[{"claude_cli": "CLAUDE_CONFIG_DIR", "codex_cli": "CODEX_HOME"}[kind]] == str(
        folder)
    if kind == "claude_cli" or mode == "native":
        assert client.on_limits.args == ((A,),)  # what its runs say is its own account's
    mine = providers._build(Provider(id="p2", name="Mine", kind=kind, mode=mode), None)
    assert mine.home is None and "CLAUDE_CONFIG_DIR" not in mine._env


@pytest.mark.anyio
async def test_it_and_its_talkers_start_in_its_folder_with_nothing_of_the_users_sign_in(
        tmp_path, keys):
    folder = tmp_path / "runtime" / CLI_HOMES / "p1"
    claude, codex = ClaudeNativeClient(home=folder), CodexNativeClient(home=folder)
    for client in (claude, claude.talker(), codex, codex.talker(), ClaudeCliClient(home=folder)):
        # (As `run_native` starts it: with the secret variables a project passes as well.)
        started, _job = await client._start([sys.executable, "-c", DUMP], False, tmp_path,
                                      {"ANTHROPIC_API_KEY": PLANTED, "CODEX_API_KEY": PLANTED})
        told = json.loads((await started.communicate())[0])
        assert nothing_of_the_users(told, client.command), client
        assert told["CLAUDE_CONFIG_DIR" if client.command == "claude" else "CODEX_HOME"] == str(
            folder)
    assert folder.is_dir()  # made at its first start


@pytest.mark.anyio
async def test_on_the_users_own_sign_in_nothing_changes(tmp_path, keys):
    started, _job = await ClaudeCliClient()._start([sys.executable, "-c", DUMP], False, tmp_path)
    told = json.loads((await started.communicate())[0])
    assert told["CLAUDE_CONFIG_DIR"] is None and told["ANTHROPIC_API_KEY"] == PLANTED


def test_the_setting_is_checked():
    assert check_options("claude_cli", KOLONI, False) == KOLONI
    assert check_options("codex_cli", KOLONI, False) == KOLONI
    assert check_options("codex_cli", {"sign_in": "own"}, False) is None
    assert check_options("claude_cli", {"own_setup": True, "sign_in": "own"}, False) == {
        "own_setup": True}
    for kind, told, server in [("claude_cli", KOLONI, True), ("codex_cli", KOLONI, True),
                               ("claude_cli", {"sign_in": "theirs"}, False),
                               ("claude_cli", {**KOLONI, "own_setup": True}, False),
                               ("codex_cli", {"own_setup": True}, False),
                               ("copilot_cli", KOLONI, False)]:
        with pytest.raises(ValueError):
            check_options(kind, told, server)


def test_each_provider_with_a_folder_is_an_account_of_its_own_and_the_users_session_is_not_it():
    one = Provider(id=A, name="Work", kind="claude_cli", options=KOLONI)
    two = Provider(id=B, name="Home", kind="claude_cli", options=KOLONI)
    mine = Provider(id="c", name="Claude Code", kind="claude_cli")
    assert (account(one), account(two), account(mine)) == ((A,), (B,), ("claude_cli", None))
    assert cli_home(Path("R"), one) == Path("R") / CLI_HOMES / A and cli_home(Path("R"), mine) is None
    limits = Limits()
    said = {"five_hour": {"used_percentage": 40, "resets_at": time.time() + 3600}}
    limits.from_session(of_session(said, datetime.now(UTC)))
    assert limits.last(mine)["windows"] and "unknown" in limits.last(one)


@pytest.mark.anyio
async def test_its_short_limits_turn_runs_in_its_folder(tmp_path, keys):
    folder = tmp_path / CLI_HOMES / "p1"
    planned, record = tmp_path / "plan.json", tmp_path / "record.json"
    planned.write_text(json.dumps({"record": str(record), "limits": {"status": "allowed"}}),
                       encoding="utf-8")
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("FAKE_CLI_PLAN", str(planned))
        assert await claude_turn(None, 20.0, launcher=FAKE, home=folder) == {"status": "allowed"}
    told = json.loads(record.read_text(encoding="utf-8"))["sign_in"]
    assert told["CLAUDE_CONFIG_DIR"] == str(folder) and not told["ANTHROPIC_API_KEY"]


def test_its_status_is_read_in_its_folder_with_its_plan_and_nothing_else_of_the_account(
        client, tmp_path, keys):
    cli = status_cli(tmp_path, {"loggedIn": True, "authMethod": "claude.ai", "subscriptionType": "max",
                                "email": "someone@example.com", "orgName": "Acme"})
    made = client.post("/api/providers", headers=ORIGIN, json={
        "name": "Work", "kind": "claude_cli", "executable": cli, "options": KOLONI}).json()
    told = client.get(f"/api/providers/{made['id']}/availability").json()
    folder = client.app.state.settings.runtime_root / CLI_HOMES / made["id"]
    assert (told["signed_in"], told["plan"]) == (True, "max")
    assert "someone@" not in json.dumps(told) and "Acme" not in json.dumps(told)
    assert [one[1:] for one in seen(tmp_path)] == [[str(folder), False]] * 2  # --help, status
    if sys.platform != "win32":  # (off Windows: one sh line, `_login`)
        assert told["login"]["command"] == (
            f"CLAUDE_CONFIG_DIR={shlex.quote(str(folder))} {shlex.quote(cli)} auth login")
        assert told["login"]["cmd"] is None  # (RunCommand's: no cmd.exe form)
        return
    # How to log in there: in the user's own PowerShell, the folder set first.
    assert told["login"]["command"] == (
        f"$env:CLAUDE_CONFIG_DIR='{folder}'; & '{cli}' auth login")
    # K-giris-cmd: and in cmd.exe, where $env: is a syntax error.
    assert told["login"]["cmd"] == f'set "CLAUDE_CONFIG_DIR={folder}"\n"{cli}" auth login'


def test_not_signed_in_there_it_says_how_to_log_in_to_that_folder(client, tmp_path):
    cli = status_cli(tmp_path, {"loggedIn": False, "authMethod": "none"}, code=1)
    made = client.post("/api/providers", headers=ORIGIN, json={
        "name": "Home", "kind": "claude_cli", "executable": cli, "options": KOLONI}).json()
    told = client.get(f"/api/providers/{made['id']}/availability").json()
    assert (told["signed_in"], told["plan"]) == (False, None)
    assert told["sign_in"] == told["login"] and "CLAUDE_CONFIG_DIR" in told["login"]["command"]
    mine = client.post("/api/providers", headers=ORIGIN, json={
        "name": "Mine", "kind": "claude_cli", "executable": cli}).json()
    theirs = client.get(f"/api/providers/{mine['id']}/availability").json()
    assert theirs["login"] is None and theirs["sign_in"]["command"] == "claude auth login"
    assert seen(tmp_path)[-1][1] is None  # the user's own: asked as before


def test_a_codex_folders_login_command_and_a_quote_in_the_path(monkeypatch):
    from app.api.providers import _login

    monkeypatch.setattr(sys, "platform", "win32")  # (Windows' forms, checked on every system)
    folder = Path("C:/K's/cli-homes/p")
    told = _login("codex_cli", None, folder)
    assert told["command"] == "$env:CODEX_HOME='" + str(folder).replace("'", "''") + "'; codex login"
    assert told["cmd"] == f'set "CODEX_HOME={folder}"\ncodex login'


def test_no_cmd_form_where_cmd_cannot_quote_the_path():
    from app.api.providers import _login

    assert "cmd" not in _login("codex_cli", None, Path("C:/a%PATH%b/p"))
    assert "cmd" not in _login("claude_cli", 'C:/x" & calc & "', Path("C:/k/p"))
    assert "cmd" not in _login("claude_cli", "C:/x\r\ncalc", Path("C:/k/p"))


def test_off_windows_the_login_is_one_sh_line(monkeypatch):
    from app.api.providers import _login

    monkeypatch.setattr(sys, "platform", "linux")
    assert _login("claude_cli", "/opt/my claude", PurePosixPath("/home/k's/p")) == {  # type: ignore[arg-type]
        "command": "CLAUDE_CONFIG_DIR='/home/k'\"'\"'s/p' '/opt/my claude' auth login",
        "docs": "https://code.claude.com/docs/en/cli-reference"}


def test_its_folder_goes_with_the_provider(client):
    made = client.post("/api/providers", headers=ORIGIN, json={
        "name": "Gone", "kind": "codex_cli", "options": KOLONI}).json()
    folder = client.app.state.settings.runtime_root / CLI_HOMES / made["id"]
    (folder / "auth.json").parent.mkdir(parents=True)
    (folder / "auth.json").write_text("{}", encoding="utf-8")
    assert client.delete(f"/api/providers/{made['id']}", headers=ORIGIN).status_code == 204
    assert not folder.exists()


def test_agents_never_reach_the_folders(settings, project_dir, tmp_path, monkeypatch):
    # (The runtime as the app has it: its folder is a place never opened, not only "outside".)
    monkeypatch.setenv("KOLONI_RUNTIME_ROOT", str(settings.runtime_root))
    login = settings.runtime_root / CLI_HOMES / "p1" / ".credentials.json"
    for named in (login, login.parent / ".claude.json", login.parent):
        with pytest.raises(WorkspaceError, match="is never opened"):
            Workspace(project_dir).resolve(str(named))
    # A command naming one is asked at every level, as a secret file is.
    assert names_secret(f"type {login}") and names_secret(f'dir "{login.parent}"')
    assert not names_secret("type notes.txt")
    # And Copilot's sandbox keeps its commands out of them.
    assert str(tmp_path / CLI_HOMES) in sandbox_denied(
        project_dir, project_dir, tmp_path / "data", tmp_path / "agy-home", tmp_path / CLI_HOMES)


def test_an_agents_read_there_is_refused_without_a_card(
        make_client, wait_run, project_dir, settings_env, monkeypatch):
    monkeypatch.setenv("KOLONI_RUNTIME_ROOT", settings_env["KOLONI_RUNTIME_ROOT"])
    login = Path(settings_env["KOLONI_RUNTIME_ROOT"]) / CLI_HOMES / "p1" / ".credentials.json"
    login.parent.mkdir(parents=True)
    login.write_text('{"token": "x"}', encoding="utf-8")
    client, _model = make_client([read(login, "r"), text("ok")])
    cid, run_id = start(client, project(client, project_dir))
    (tool,) = wait_run(client, cid, run_id)["tool_calls"]
    assert tool["status"] == "failed" and tool["why_asked"] is None
    assert "never opened" in tool["result"] and "token" not in tool["result"]


def test_a_crafted_provider_id_never_leads_out_of_the_folders(client):
    # Security review: a row restored from a backup could hold any id.
    for bad in ("..", "../../../../.claude", "C:/x", "ABCDEF0123456789abcdef0123456789"):
        assert cli_home(Path("R"), Provider(id=bad, name="x", kind="claude_cli",
                                            options=KOLONI)) is None, bad
    from types import SimpleNamespace

    from app.api.providers import delete_provider

    root = client.app.state.settings.runtime_root
    (root / "keep.txt").write_text("kept", encoding="utf-8")
    with client.app.state.session_factory() as session:
        session.add(Provider(id="..", name="Evil", kind="claude_cli", options=KOLONI))
        session.commit()
        # (As the route deletes it: its folder would be the whole runtime.)
        delete_provider("..", SimpleNamespace(app=client.app), session)  # type: ignore[arg-type]
    assert (root / "keep.txt").read_text(encoding="utf-8") == "kept"


def test_a_curly_quote_in_a_path_cannot_end_the_command(monkeypatch):
    from app.api.providers import _login

    monkeypatch.setattr(sys, "platform", "win32")  # (PowerShell's quoting, on every system)
    told = _login("codex_cli", None, Path("C:/x\u2019; calc; #"))["command"]
    assert "x\u2019\u2019; calc" in told and told.endswith("'; codex login")
