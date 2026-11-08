"""Secret files and variables are kept from commands (slices 103-105, the user's decision of
24 October: a project setting, on by default). Written before the code.

A command that was approved, or ran at Full auto, may read a file it never names
(`python x.py` opening `.env`) and sees its environment (`GITHUB_TOKEN`). The card sees only
the command's text: here the files are covered where the command runs (Copilot's sandbox,
Docker's mounts), and secret variables are not handed on at all.
"""

import asyncio
import json
import sqlite3
import tempfile

import pytest
from alembic import command

from app import commands
from app.agent import sandbox_denied
from app.config import load_settings
from app.db.models import Project
from app.executors import executor_for
from app.executors.docker import DockerExecutor, docker_argv
from app.executors.host import HostExecutor
from app.model_agy import AgyClient
from app.model_native import ClaudeNativeClient, CodexNativeClient, CopilotNativeClient
from tests.fakes import Script, ScriptedExecutor
from tests.test_agent_commands import cmd
from tests.test_chat_flow import start_in_mode, text
from tests.test_copilot_agent import copilot_native, start  # noqa: F401  (a fixture)
from tests.test_docker_executor import mounts
from tests.test_host_executor import py
from tests.test_migration_0002 import _config

OWN = {"Origin": "http://127.0.0.1:8790"}
AT = "2026-10-24 00:00:00"


def made(root, *paths):
    for path in paths:
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text("x", encoding="utf-8")


# --- which files: one walk ------------------------------------------------------------------


def test_the_secret_files_are_each_one_in_the_folder_and_a_secret_folder_as_itself(tmp_path):
    made(tmp_path, ".env", "config/.env.local", "keys/id_rsa", ".ssh/id_ed25519",
         ".ssh/known_hosts", "node_modules/pkg/.env", ".venv/lib/x.pem", ".git/config",
         "src/.env.example", "app.py",
         # a CA bundle installed in a venv by any name is no secret: denied, HTTPS breaks
         "venv/Lib/site-packages/certifi/cacert.pem", "env/lib/site-packages/x/cacert.pem")
    commands._held.clear()
    root = tmp_path.resolve()
    assert sorted(commands.secret_files(root)) == [".env", ".ssh", "config/.env.local",
                                                   "keys/id_rsa"]
    assert commands.secret_held(root) == ".env"  # the search card's walk is the same one


# --- which variables ----------------------------------------------------------------------------


def test_a_secret_variable_is_known_by_its_name():
    names = ["GITHUB_TOKEN", "OPENAI_API_KEY", "DB_PASSWORD", "AUTH_URL", "PATH", "APP_ID"]
    assert [name for name in names if commands.secret_name(name)] == [
        "GITHUB_TOKEN", "OPENAI_API_KEY", "DB_PASSWORD"]


def test_every_secret_variable_is_held_back_but_those_the_user_passes_and_never_kolonis():
    env = {"GITHUB_TOKEN": "a", "OPENAI_API_KEY": "b", "KOLONI_MODEL_API_KEY": "c", "PATH": "d"}
    assert commands.held_back(env) == ["GITHUB_TOKEN", "OPENAI_API_KEY"]
    assert commands.held_back(env, " github_token , ") == ["OPENAI_API_KEY"]
    assert commands.held_back(env, "KOLONI_MODEL_API_KEY") == ["GITHUB_TOKEN", "OPENAI_API_KEY"]


def test_a_session_a_file_or_a_helper_is_named_not_held_back_though_its_value_is_masked():
    held = ["AWS_SESSION_TOKEN", "GITHUB_TOKEN", "NPM_TOKEN", "OPENAI_API_KEY"]
    named = ["DBUS_SESSION_BUS_ADDRESS", "SESSION_MANAGER", "XDG_SESSION_TYPE", "WT_SESSION",
             "DB_PASSWORD_FILE", "GIT_CREDENTIAL_HELPER", "GOOGLE_APPLICATION_CREDENTIALS"]
    assert commands.held_back(dict.fromkeys(held + named, "x" * 20)) == held
    assert commands.secret_name("WT_SESSION")  # (what such a one prints is still masked)


def test_a_way_into_a_program_the_user_is_signed_in_to_is_held_back_whatever_its_name():
    # KOLONİ started from a VS Code or Claude Code terminal: `$GIT_ASKPASS` or `git credential
    # fill` over the IPC handle would hand an injected command the user's GitHub credential
    handles = ["CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_SSE_PORT", "COPILOT_DEBUG_NONCE",
               "GIT_ASKPASS", "SSH_ASKPASS", "SSH_AUTH_SOCK", "VSCODE_GIT_ASKPASS_MAIN",
               "VSCODE_GIT_ASKPASS_NODE", "VSCODE_GIT_IPC_HANDLE", "VSCODE_INJECTION"]
    env = dict.fromkeys([*handles, "PATH", "GIT_CREDENTIAL_HELPER", "DOCKER_HOST"], "x")
    assert commands.held_back(env) == handles
    assert commands.held_back(env, "SSH_AUTH_SOCK") == [h for h in handles if h != "SSH_AUTH_SOCK"]


@pytest.mark.anyio
async def test_a_command_on_this_machine_gets_no_secret_variable_but_one_passed(
        tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_not_for_a_command")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-passed-on-purpose")
    script = py("import os; print(sorted(k for k in os.environ if k in "
                "('GITHUB_TOKEN', 'OPENAI_API_KEY')), bool(os.environ.get('PATH')))", tmp_path)
    for passed, seen in ((None, "[] True"), ("OPENAI_API_KEY", "['OPENAI_API_KEY'] True")):
        running = await HostExecutor(passed).start("k1", script, tmp_path)
        output = "".join([chunk async for chunk in running])
        await asyncio.wait_for(running.wait(), 20)
        assert output.strip() == seen


def test_a_command_is_told_which_secret_variables_were_held_back(
        make_client, wait_run, project_dir, monkeypatch):
    monkeypatch.setenv("SHIELD_TEST_TOKEN", "a-value-never-said")
    executor = ScriptedExecutor([Script(["ok\n"])])
    client, _ = make_client([cmd("pytest -q"), text("done")], executor=executor)
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    said = wait_run(client, cid, run_id)["tool_calls"][0]["result"]
    held = said.splitlines()[-1]
    assert held.startswith("(secret variables held back from this command: ")
    assert "SHIELD_TEST_TOKEN" in held and held.endswith(
        " - the user can pass one in Settings › This project › Commands and secrets)")
    assert "a-value-never-said" not in said


# --- the setting ------------------------------------------------------------------------------


def test_the_setting_is_on_for_a_new_project_and_only_the_user_changes_it(
        client, project_dir, monkeypatch):
    monkeypatch.setenv("SHIELD_TEST_TOKEN", "a-value-never-said")
    project = client.post("/api/projects", json={"root_path": str(project_dir)}).json()
    assert (project["hide_secrets"], project["pass_env"]) == (True, None)
    assert "SHIELD_TEST_TOKEN" in project["held_env"]
    assert "a-value-never-said" not in json.dumps(project)
    url = f"/api/projects/{project['id']}"
    # a command an agent runs against the app's address says nothing of where it is from
    for change in ({"hide_secrets": False}, {"pass_env": "SHIELD_TEST_TOKEN"}):
        assert client.patch(url, json=change).status_code == 403
    changed = client.patch(url, json={"hide_secrets": False, "pass_env": "SHIELD_TEST_TOKEN"},
                           headers=OWN).json()
    assert (changed["hide_secrets"], changed["pass_env"]) == (False, "SHIELD_TEST_TOKEN")
    assert "SHIELD_TEST_TOKEN" not in changed["held_env"]
    assert client.patch(url, json={"pass_env": " "}, headers=OWN).json()["pass_env"] is None


def test_migration_0070_hides_secrets_in_every_project_there_was_and_goes_back(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0069")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO projects (id, name, root_path, created_at) "
                     f"VALUES ('p', 'p', 'C:/p', '{AT}')")
    command.upgrade(cfg, "0070")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT hide_secrets, pass_env FROM projects").fetchall() == [
            (1, None)]
    command.downgrade(cfg, "0069")
    with sqlite3.connect(db) as conn:
        names = {row[1] for row in conn.execute("PRAGMA table_info(projects)")}
        assert not {"hide_secrets", "pass_env"} & names
        assert conn.execute("SELECT id FROM projects").fetchall() == [("p",)]


# --- 104: Docker ------------------------------------------------------------------------------


def test_in_docker_each_secret_file_is_an_empty_one_and_a_secret_folder_an_empty_folder(
        tmp_path):
    root, empty = tmp_path / "p", tmp_path / "runtime" / "empty"
    made(root, ".env", ".ssh/id_rsa")
    hidden = (root / ".env", root / ".ssh")
    argv = docker_argv("n", "alpine", root, root, False, "ls", hidden=hidden, empty=empty)
    assert mounts(argv) == [
        f"{root}:/workspace",
        f"{empty / 'file'}:/workspace/.env:ro",
        f"{empty / 'folder'}:/workspace/.ssh:ro",
    ]


def test_in_docker_a_secret_in_a_linked_folder_is_covered_where_that_is_mounted(tmp_path):
    project, copy = tmp_path / "p", tmp_path / "runtime" / "copies" / "a1" / "tree"
    empty = tmp_path / "runtime" / "empty"
    made(project, "venv/.env")
    argv = docker_argv("n", "alpine", copy, copy, False, "ls", {"venv": project / "venv"},
                       hidden=(project / "venv" / ".env",), empty=empty)
    assert mounts(argv)[-1] == f"{empty / 'file'}:/workspace/venv/.env:ro"


@pytest.mark.anyio
async def test_docker_covers_the_secrets_it_walks_and_none_with_the_setting_off(
        monkeypatch, tmp_path):
    from app.executors import docker

    project, empty = tmp_path / "p", tmp_path / "runtime" / "empty"
    made(project, ".env", "node_modules/pkg/.env", "app.py")
    ran = []

    async def fine(argv, timeout):
        return 0, "27.0"

    async def spawn(*argv, **given):
        ran.append(list(argv))

    monkeypatch.setattr(docker, "_exec", fine)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    docker.forget_status()
    commands._held.clear()
    await DockerExecutor(project, "alpine", False, empty).start("k1", "ls", project)
    assert mounts(ran[0]) == [f"{project}:/workspace", f"{empty / 'file'}:/workspace/.env:ro"]
    assert (empty / "file").read_bytes() == b"" and list((empty / "folder").iterdir()) == []
    await DockerExecutor(project, "alpine", False).start("k2", "ls", project)
    assert mounts(ran[1]) == [f"{project}:/workspace"]
    docker.forget_status()


def test_executor_for_hands_on_the_projects_setting(tmp_path):
    project = Project(id="p", name="p", root_path=str(tmp_path), exec_location="docker",
                      docker_image="alpine", docker_network=False, hide_secrets=True,
                      pass_env="OPENAI_API_KEY")
    runtime = tmp_path / "runtime"  # the app's, never the checkout's
    assert executor_for("host", project, runtime)._pass_env == "OPENAI_API_KEY"
    assert executor_for("docker", project, runtime)._empty == runtime / "empty"
    project.hide_secrets = False
    assert executor_for("docker", project, runtime)._empty is None


# --- 103: the CLIs' own processes -------------------------------------------------------------


@pytest.mark.parametrize(("make", "login"), [
    (ClaudeNativeClient, "ANTHROPIC_API_KEY"),
    (CodexNativeClient, "OPENAI_API_KEY"),
    (CopilotNativeClient, None),  # its own sign-in variables were never handed on
    (lambda: AgyClient(reads=False), None),
])
def test_each_cli_keeps_its_own_sign_in_and_none_of_the_other_secrets(make, login, monkeypatch):
    for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "SHIELD_TEST_TOKEN", "MY_PASSWORD"):
        monkeypatch.setenv(name, "a-value")
    monkeypatch.setenv("PLAIN_SETTING", "kept")
    env = make()._inherited()
    assert env["PLAIN_SETTING"] == "kept" and "PATH" in {name.upper() for name in env}
    assert "SHIELD_TEST_TOKEN" not in env and "MY_PASSWORD" not in env
    assert [name for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY") if name in env] == (
        [login] if login else [])
    assert "SHIELD_TEST_TOKEN" in make()._inherited("SHIELD_TEST_TOKEN")


def test_claude_code_keeps_its_own_settings_and_no_cli_an_editors_handle(monkeypatch):
    # (set here: conftest takes every held-back name out of a test's environment)
    for name in ("CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_MESSAGING_TOKEN", "VSCODE_GIT_IPC_HANDLE",
                 "CLAUDE_CODE_SSE_PORT", "CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_SESSION_ID"):
        monkeypatch.setenv(name, "a-value")
    claude, codex = ClaudeNativeClient()._inherited(), CodexNativeClient()._inherited()
    assert [name for name in claude if name.startswith(("CLAUDE_CODE_", "VSCODE_"))] == [
        "CLAUDE_CODE_USE_BEDROCK"]
    assert not [name for name in codex if name.startswith(("CLAUDE_CODE_", "VSCODE_"))]


# --- 105: Copilot's sandbox -------------------------------------------------------------------


def test_from_a_copy_copilots_sandbox_denies_the_projects_secret_files_too(
        tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "temp"))  # (no run's bridge file)
    project, copy, data = tmp_path / "p", tmp_path / "copies" / "a1" / "tree", tmp_path / "data"
    made(project, ".env", "app.py")
    made(copy, "keys/id_rsa", "app.py")
    commands._held.clear()
    homes, logins = tmp_path / "agy-home", tmp_path / "cli-homes"
    assert sandbox_denied(copy, project, data, homes, logins) == (
        str(copy / "keys" / "id_rsa"), str(project / ".env"), str(data), str(logins))
    assert sandbox_denied(project, project, data, homes, logins) == (
        str(project / ".env"), str(data), str(logins))


def test_copilots_sandbox_denies_the_keys_to_the_other_runs_tool_servers(tmp_path, monkeypatch):
    # B-304: a CLI run's bridge file and agy's door each hold one.
    temp, homes = tmp_path / "temp", tmp_path / "agy-home"
    monkeypatch.setattr(tempfile, "tempdir", str(temp))
    made(temp, "koloni-cli-other/bridge.json", "koloni-cli-other/mcp.json", "koloni-cli-gone/x")
    made(homes, "agy-x/.gemini/config/koloni-door.json", "agy-x/.gemini/config/hooks.json")
    project, data = tmp_path / "p", tmp_path / "data"
    made(project, "app.py")
    commands._held.clear()
    assert sandbox_denied(project, project, data, homes, tmp_path / "cli-homes") == (
        str(data), str(tmp_path / "cli-homes"), str(temp / "koloni-cli-other" / "bridge.json"),
        str(homes / "agy-x" / ".gemini" / "config" / "koloni-door.json"))


def setting(client, project_dir, **change):
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    if change:
        assert client.patch(f"/api/projects/{pid}", json=change, headers=OWN).status_code == 200


def test_copilots_commands_run_in_its_sandbox_with_the_secret_files_denied(
        copilot_native, wait_run, project_dir, settings_env, monkeypatch, tmp_path):  # noqa: F811
    # (another run's bridge file, B-304, in a temp folder of the test's own)
    temp = tmp_path / "temp"
    made(temp, "koloni-cli-other/bridge.json")
    monkeypatch.setattr(tempfile, "tempdir", str(temp))
    made(project_dir, ".env", ".ssh/id_rsa")
    commands._held.clear()
    monkeypatch.setenv("SHIELD_TEST_TOKEN", "a-value")
    monkeypatch.setenv("SHIELD_PASSED_TOKEN", "a-value")
    client, provider = copilot_native([
        {"shell": "python hello.py", "output": "hi", "sandboxed": True}, {"say": "done"}])
    outside = project_dir.parent / "shared"
    outside.mkdir()
    setting(client, project_dir, pass_env="SHIELD_PASSED_TOKEN", also_in=[str(outside)])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    seen = copilot_native.record()
    assert seen["sandbox_asked"] is True
    data = str(load_settings(settings_env).db_path.parent)
    logins = str(load_settings(settings_env).runtime_root / "cli-homes")
    # (a folder it also works in is one its commands may write in: the sandbox denies it else)
    assert seen["create"]["sandboxConfig"] == {
        "enabled": True, "allowBypass": False, "sandboxMcpServers": False,
        "addCurrentWorkingDirectory": True, "userPolicy": {"filesystem": {
            "deniedPaths": [str(project_dir / ".env"), str(project_dir / ".ssh"), data, logins,
                            str(temp / "koloni-cli-other" / "bridge.json")],
            "readwritePaths": [str(outside.resolve())]}}}
    # the record says it ran in the sandbox; the card does not
    assert snap["tool_calls"][0]["result"].startswith("exit code 0, sandboxed")
    # and its process (so its commands) has the passed secret, not the other one
    assert "SHIELD_PASSED_TOKEN" in seen["names"] and "SHIELD_TEST_TOKEN" not in seen["names"]


@pytest.mark.parametrize("support", [
    {"supported": False, "reason": "no ProcessContainer", "capabilities": []},
    {"supported": True, "capabilities": [{"name": "denied_paths", "supported": False}]},
    "unknown",  # a Copilot older than the sandbox: no such method
])
def test_a_copilot_that_cannot_sandbox_runs_and_says_so(
        copilot_native, wait_run, project_dir, support):  # noqa: F811
    client, provider = copilot_native([{"say": "done"}], sandbox=support)
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert "sandboxConfig" not in copilot_native.record()["create"]
    note = snap["tool_calls"][0]
    assert (note["name"], note["result"]) == (
        "copilot__sandbox",
        "Copilot cannot sandbox commands on this machine: secret files are not hidden from them")


def test_with_the_setting_off_copilot_is_not_sandboxed_or_asked(
        copilot_native, wait_run, project_dir):  # noqa: F811
    client, provider = copilot_native([{"say": "done"}])
    setting(client, project_dir, hide_secrets=False)
    cid, run_id = start(client, project_dir, provider)
    assert wait_run(client, cid, run_id)["runs"][0]["status"] == "completed"
    seen = copilot_native.record()
    assert "sandbox_asked" not in seen and "sandboxConfig" not in seen["create"]
