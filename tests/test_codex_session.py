"""Codex as one session per agent (7 Nov 2026): its app-server with its own tools off and
KOLONİ's whole tool set over the bridge. Its patch tool, which no flag switches off, is
declined and it is told to write with KOLONİ's tools; it is held as the other session CLIs
are, not as a CLI with tools of its own."""

import json
import sys
from pathlib import Path

import pytest

from app.agent import AgentRunner
from app.agent.cards import _needs_its_tools, needs_full_auto, outside_a_copy
from app.config import load_settings
from app.db.models import Provider
from app.main import create_app
from app.model_native import PATCH_REFUSED, CodexNativeClient, CodexSessionClient
from app.providers import mode_of, works_with_own_tools
from tests.fakes import ScriptedModel
from tests.keyed import TestClient
from tests.test_native_agent import start

FAKE = [sys.executable, str(Path(__file__).with_name("fake_codex_app_server.py"))]
PATCH = "item/fileChange/requestApproval"
ASK_MCP = "mcpServer/elicitation/request"


@pytest.fixture
def codex_session(settings_env, tmp_path):
    """An app whose provider "Codex" runs as a session: the stand-in app-server following a
    script, with a Codex home of the user's that has an MCP server of their own."""
    opened = []
    record, plan, home = tmp_path / "record.json", tmp_path / "plan.json", tmp_path / "codex"
    home.mkdir()
    (home / "config.toml").write_text('[mcp_servers.theirs]\ncommand = "theirs"\n',
                                      encoding="utf-8")

    def make(script, **more):
        plan.write_text(json.dumps({"record": str(record), "script": script, **more}),
                        encoding="utf-8")
        cli = CodexSessionClient(launcher=FAKE, timeout=30,
                                 env={"FAKE_CLI_PLAN": str(plan), "CODEX_HOME": str(home)})
        app = create_app(load_settings(settings_env), model=ScriptedModel([]),
                         clients={"Codex": cli})
        client = TestClient(app, base_url="http://127.0.0.1:8790")
        client.__enter__()
        opened.append(client)
        provider = client.post("/api/providers", json={
            "name": "Codex", "kind": "codex_cli", "mode": "session"})
        assert provider.status_code == 201, provider.text
        assert provider.json()["mode"] == "session"
        return client, provider.json()

    make.record = lambda: json.loads(record.read_text(encoding="utf-8"))
    yield make
    for client in opened:
        client.__exit__(None, None, None)


@pytest.fixture
def wait_run(wait_run):
    return lambda client, cid, run_id, timeout=30.0: wait_run(client, cid, run_id, timeout)


def answers(record):
    return [(a["method"], a["answer"]) for a in record["answers"]]


def test_its_patch_is_declined_and_it_writes_with_kolonis_tool(codex_session, wait_run,
                                                               project_dir):
    client, provider = codex_session([
        {"say": "I will change the greeting."},
        {"write": "hello.py", "content": "print('patched')\n"},
        {"koloni": "write_file", "args": {"path": "hello.py", "content": "print('hello')\n"}},
        {"say": "Written."}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    run = snap["runs"][0]
    assert run["status"] == "completed", run["error"]
    seen = codex_session.record()
    # Its patch is declined, with why steered into its turn; KOLONİ's write goes through.
    assert answers(seen) == [(PATCH, {"decision": "decline"}),
                             (ASK_MCP, {"action": "accept", "content": {}})]
    assert PATCH_REFUSED in seen["steers"][0]["input"][0]["text"]
    assert (project_dir / "hello.py").read_text(encoding="utf-8") == "print('hello')\n"
    assert not (Path(seen["cwd"]) / "hello.py").exists()  # (nothing of its own patch)
    # On record as any session's call, under the words it said before it.
    first, last = [m for m in snap["messages"] if m["role"] == "assistant"]
    assert (first["content"], last["content"]) == ("I will change the greeting.", "Written.")
    (call,) = snap["tool_calls"]
    assert (call["name"], call["status"], call["message_id"]) == (
        "write_file", "succeeded", first["id"])
    agent = snap["agents"][0]
    assert (agent["input_tokens"], agent["output_tokens"]) == (4000, 120)
    # KOLONİ's whole tool set, not native's collaboration tools alone.
    assert {"read_file", "write_file", "edit_file", "run_command", "spawn_agent"} <= set(
        seen["tools"])
    # Started in a folder of KOLONİ's, asking before everything, told where its patch goes.
    assert Path(seen["cwd"]) != project_dir and seen["thread"]["cwd"] == seen["cwd"]
    assert (seen["thread"]["approvalPolicy"], seen["thread"]["approvalsReviewer"],
            seen["thread"]["sandbox"]) == ("untrusted", "user", "workspace-write")
    assert PATCH_REFUSED in seen["stdin"] and "temporary one of KOLONİ's" in seen["stdin"]


def test_its_own_tools_are_off_but_its_code_mode_host_and_the_users_servers_are(
        codex_session, wait_run, project_dir):
    client, provider = codex_session([{"say": "Hi."}])
    cid, run_id = start(client, project_dir, provider)
    assert wait_run(client, cid, run_id)["runs"][0]["status"] == "completed"
    argv = codex_session.record()["argv"]
    settings = [argv[i + 1] for i, one in enumerate(argv) if one == "-c"]
    for feature in ("shell_tool", "unified_exec", "view_image", "apps", "multi_agent", "js_repl",
                    "image_generation", "goals", "plugins", "skill_search", "hooks"):
        assert f"features.{feature}=false" in settings
    # Without its code-mode host no MCP tool is reached (measured): it stays on.
    assert not [one for one in argv if "code_mode_host" in one]
    assert "web_search='disabled'" in settings
    assert "mcp_servers.theirs.enabled=false" in settings  # the user's own server is off
    assert argv[-1] == "app-server"


def test_another_servers_tool_is_declined_and_the_turn_goes_on(codex_session, wait_run,
                                                               project_dir):
    client, provider = codex_session([
        {"mcp": {"server": "theirs", "tool": "fetch", "elicit": True}}, {"say": "Could not."}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert answers(codex_session.record()) == [(ASK_MCP, {"action": "decline"})]
    assert snap["messages"][-1]["content"] == "Could not."


@pytest.mark.parametrize("script, said", [
    ([{"run": "type secrets.txt"}, {"say": "Read it."}], "its shell was switched off"),
    ([{"mcp": {"server": "theirs", "tool": "fetch"}}, {"say": "Fetched."}],
     "used a tool of its own"),
])
def test_a_tool_of_its_own_at_work_ends_the_session(codex_session, wait_run, project_dir,
                                                    script, said):
    client, provider = codex_session(script)
    cid, run_id = start(client, project_dir, provider)
    run = wait_run(client, cid, run_id)["runs"][0]
    assert run["status"] == "failed" and said in run["error"]


def test_any_other_item_it_begins_ends_the_session_before_it_is_done(
        codex_session, wait_run, project_dir):
    # A tool the user's own config turns on (js_repl, say) comes as an item of its own type.
    client, provider = codex_session([{"say": "Let me run some JavaScript."},
                                      {"begin": "dynamicToolCall", "hold": 30},
                                      {"say": "Done."}])
    cid, run_id = start(client, project_dir, provider)
    run = wait_run(client, cid, run_id)["runs"][0]
    assert run["status"] == "failed"
    assert "began a tool of its own (dynamicToolCall)" in run["error"]
    assert "done" not in codex_session.record()  # ended as it began, not once it was done


def test_a_model_that_keeps_asking_for_its_patch_tool_is_stopped(codex_session, wait_run,
                                                                 project_dir):
    client, provider = codex_session(
        [{"write": f"a{n}.py", "content": "x"} for n in range(5)] + [{"say": "Gave up."}])
    cid, run_id = start(client, project_dir, provider)
    run = wait_run(client, cid, run_id)["runs"][0]
    assert run["status"] == "failed" and "asked 3 times" in run["error"]
    # Two declined; the third ends it.
    assert answers(codex_session.record()) == [(PATCH, {"decision": "decline"})] * 2


def test_it_is_held_as_a_session_cli_not_as_one_with_tools_of_its_own():
    session, native = CodexSessionClient(), CodexNativeClient()
    as_session = Provider(kind="codex_cli", mode="session")
    as_native = Provider(kind="codex_cli", mode="native")
    # Triggers, To-do, While you're away, recipe steps (`_cannot_be_held`, `team.would`).
    assert not AgentRunner._cannot_be_held(session, as_session)
    assert not works_with_own_tools(as_session)
    assert AgentRunner._cannot_be_held(native, as_native) and works_with_own_tools(as_native)
    # A comparison's side, a night's job (`outside_a_copy`); any level, any role.
    assert not outside_a_copy(session)
    assert needs_full_auto(session, "ask") is None
    assert not _needs_its_tools(session, ["read_file", "list_dir"])  # (no `looks_by_running`)


def test_session_is_codexs_default_and_a_saved_step_is_kept():
    assert mode_of(Provider(kind="codex_cli", mode=None)) == "session"
    assert mode_of(Provider(kind="codex_cli", mode="step")) == "step"


def test_an_item_whose_type_is_no_name_ends_the_session_too():
    assert "began a tool of its own" in CodexSessionClient()._unwanted({"type": ["x"]}, True)
    assert CodexSessionClient()._unwanted({"type": "agentMessage"}, True) is None


def test_its_own_sub_agent_item_ends_the_session_as_the_b415_scenario_says():
    from tests.test_b415 import STOPPED  # (B-415, live: begun with multi_agent switched off)

    assert CodexSessionClient()._unwanted({"type": "collabAgentToolCall"}, False) == STOPPED
