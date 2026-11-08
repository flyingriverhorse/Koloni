"""B-306: Qoder natively, over Claude Code's control protocol - the fake Claude Code CLI stands
in for qodercli, whose protocol is not measured. It asks first, or it is stopped."""

import json

import pytest

from app import model_native
from app.config import load_settings
from app.main import create_app
from app.model_client import OwnStop
from app.model_native import QoderNativeClient
from app.model_session import QoderSessionClient
from tests.fakes import ScriptedModel
from tests.keyed import TestClient
from tests.test_agent_writes import wait_status
from tests.test_claude_native import BASH, FAKE, WRITE, hello, start

# None of Claude Code's own extras: not measured on Qoder.
CLAUDE_ONLY = ("--agents", "--json-schema", "--settings", "--plugin-dir", "--add-dir",
               "--disable-slash-commands", "--verbose", "--effort", "--disallowedTools")


@pytest.fixture
def qoder_app(settings_env, tmp_path, project_dir):
    opened = []
    record, plan = tmp_path / "record.json", tmp_path / "plan.json"

    def make(script, **more):
        script = json.loads(json.dumps(script).replace("PROJECT", project_dir.as_posix()))
        plan.write_text(json.dumps({"record": str(record), "script": script,
                                    "version": "1.1.51", **more}), encoding="utf-8")
        cli = QoderNativeClient(launcher=FAKE, model="Qwen3.8-Flash", timeout=30,
                                env={"FAKE_CLI_PLAN": str(plan)})
        app = create_app(load_settings(settings_env), model=ScriptedModel([]),
                         clients={"Qoder": cli})
        client = TestClient(app, base_url="http://127.0.0.1:8790")
        client.__enter__()
        opened.append(client)
        provider = client.post("/api/providers", json={
            "name": "Qoder", "kind": "qoder_cli", "mode": "native"})
        assert provider.status_code == 201, provider.text
        return client, provider.json()

    make.record = lambda: json.loads(record.read_text(encoding="utf-8"))
    yield make
    for client in opened:
        client.__exit__(None, None, None)


def test_qoder_asks_before_it_writes_on_its_own_line(qoder_app, wait_run, project_dir):
    client, provider = qoder_app([WRITE, {"say": "Fixed."}])
    cid, run_id = start(client, project_dir, provider, "ask")
    change = wait_status(client, cid, "waiting_approval")["file_changes"][0]
    assert client.post(f"/api/file-changes/{change['id']}/approve").status_code == 200
    run = wait_run(client, cid, run_id)["runs"][0]
    assert run["status"] == "completed", run["error"]
    assert hello(project_dir) == "print('hello')\n"
    seen = qoder_app.record()
    argv = seen["argv"]
    assert argv[argv.index("--permission-prompt-tool") + 1] == "stdio"
    assert argv[argv.index("--permission-mode") + 1] == "default"
    assert argv[argv.index("--setting-sources") + 1] == ""
    assert argv[argv.index("-m") + 1] == "Qwen3.8-Flash"
    assert "--strict-mcp-config" in argv and "--disallowed-tools" in argv
    assert "mcp__koloni__spawn_agent" in [
        argv[i + 1] for i, one in enumerate(argv) if one == "--allowed-tools"]
    assert not [one for one in CLAUDE_ONLY if one in argv]
    assert list(seen["init"]["request"]["hooks"]) == ["PreToolUse"]  # (no Stop hook, 89m)


def test_a_tool_qoder_runs_without_asking_stops_the_run(qoder_app, wait_run, project_dir):
    client, provider = qoder_app([{**BASH, "unhooked": True}, WRITE, {"say": "done"}])
    cid, run_id = start(client, project_dir, provider, "full_auto")
    snap = wait_run(client, cid, run_id, timeout=15)
    run = snap["runs"][0]
    assert run["status"] == "failed"
    assert "Qoder ran a command without KOLONİ being asked" in run["error"]
    assert "pytest" not in run["error"]  # (never the command's words: they could hold a token)
    assert hello(project_dir) == "print('hi')\n"  # nothing after it ran
    assert qoder_app.record()["asked"] == []


def test_a_tool_qoder_runs_unasked_that_fails_stops_the_run_too(qoder_app, wait_run, project_dir):
    client, provider = qoder_app([{**BASH, "unhooked": True, "error": "Exit code 1"}, WRITE,
                                  {"say": "done"}])
    cid, run_id = start(client, project_dir, provider, "full_auto")
    run = wait_run(client, cid, run_id, timeout=15)["runs"][0]
    assert run["status"] == "failed" and "without KOLONİ being asked" in run["error"]
    assert hello(project_dir) == "print('hi')\n"


def test_a_qoder_tool_koloni_does_not_know_by_name_is_a_card_below_full_auto(
    qoder_app, wait_run, project_dir
):
    client, provider = qoder_app([
        {"tool": "run_shell_command", "input": {"command": "cat .env"}, "result": "K=v"},
        {"say": "done"}])
    cid, run_id = start(client, project_dir, provider, "auto_edit")
    question = wait_status(client, cid, "waiting_approval")["questions"][0]
    assert "run_shell_command" in question["question"]
    client.post(f"/api/questions/{question['id']}/answer", json={"answer": "Deny"},
                headers={"Origin": "http://127.0.0.1:8790"})
    wait_run(client, cid, run_id)
    assert [one["behavior"] for one in qoder_app.record()["asked"]] == ["deny"]


def test_at_full_auto_a_qoder_tool_koloni_does_not_know_by_name_is_still_a_card(
    qoder_app, wait_run, project_dir
):
    """K-fullauto-sorma 2 review (B-306): an unknown name may be a shell, a write or the
    network past every check - a card at Full auto too, until Qoder's tool names are measured."""
    client, provider = qoder_app([
        {"tool": "run_shell_command", "input": {"command": "echo hi"}, "result": "hi"},
        {"say": "done"}])
    cid, run_id = start(client, project_dir, provider, "full_auto")
    question = wait_status(client, cid, "waiting_approval")["questions"][0]
    assert "run_shell_command" in question["question"]
    client.post(f"/api/questions/{question['id']}/answer", json={"answer": "Allow"},
                headers={"Origin": "http://127.0.0.1:8790"})
    wait_run(client, cid, run_id)
    assert [one["behavior"] for one in qoder_app.record()["asked"]] == ["allow"]


@pytest.mark.parametrize("answer, said", [("silent", "did not answer for 1 seconds"),
                                          ("error", "unknown hook event")])
def test_a_qoder_that_does_not_answer_initialize_is_stopped_before_its_prompt(
    qoder_app, wait_run, project_dir, monkeypatch, answer, said
):
    monkeypatch.setattr(model_native, "START_SECONDS", 1)
    client, provider = qoder_app([WRITE], initialize=answer)
    cid, run_id = start(client, project_dir, provider, "full_auto")
    run = wait_run(client, cid, run_id, timeout=15)["runs"][0]
    assert run["status"] == "failed" and "could not be asked before it acts" in run["error"]
    assert said in run["error"]
    assert qoder_app.record()["stdin"] == "" and hello(project_dir) == "print('hi')\n"


def test_no_secret_variable_reaches_qodercli(qoder_app, wait_run, project_dir, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-not-for-qoder")
    client, provider = qoder_app([{"say": "done"}])
    cid, run_id = start(client, project_dir, provider, "full_auto")
    assert wait_run(client, cid, run_id)["runs"][0]["status"] == "completed"
    assert qoder_app.record()["sign_in"]["ANTHROPIC_API_KEY"] is False


def test_a_read_only_role_starts_qoder_without_its_write_and_shell_tools(tmp_path):
    argv = QoderNativeClient()._native_arguments(tmp_path, tmp_path / "b.json", ("write", "run"))
    off = {argv[i + 1] for i, one in enumerate(argv) if one == "--disallowed-tools"}
    assert {"Write", "Edit", "MultiEdit", "NotebookEdit", "Bash", "PowerShell"} <= off
    assert "Read" not in off


def test_a_project_with_qoder_settings_of_its_own_is_not_run_natively(tmp_path):
    (tmp_path / ".qoder").mkdir()
    (tmp_path / ".qoder" / "settings.local.json").write_text("{}", encoding="utf-8")
    with pytest.raises(OwnStop, match="Run it as a session instead"):
        QoderNativeClient()._native_arguments(tmp_path, tmp_path / "b.json")


def test_a_qoder_that_does_not_take_the_hook_is_never_prompted(qoder_app, wait_run, project_dir):
    client, provider = qoder_app([WRITE], hooks_applied=False)
    cid, run_id = start(client, project_dir, provider, "full_auto")
    run = wait_run(client, cid, run_id, timeout=15)["runs"][0]
    assert run["status"] == "failed"
    assert "Qoder 1.1.51 could not be asked before it acts" in run["error"]
    assert qoder_app.record()["stdin"] == "" and hello(project_dir) == "print('hi')\n"


def test_qoder_natively_is_built_and_speaks_as_its_session(settings):
    from app.db.models import Provider
    from app.providers import Providers

    row = Provider(id="q", name="Qoder", kind="qoder_cli", mode="native")
    built = Providers(settings).client(row, None)
    assert type(built) is QoderNativeClient
    assert type(built.talker()) is QoderSessionClient
    assert built._leveled(["-p"], "off") == ["--reasoning-effort", "none", "-p"]
