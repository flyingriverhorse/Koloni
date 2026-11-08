"""An agent whose model is a CLI session: KOLONİ records and runs every tool it asks for."""

import json
import sqlite3
import sys
import time
from pathlib import Path

import pytest
from alembic import command

from app.config import load_settings
from app.main import create_app
from app.model_session import ClaudeSessionClient
from app.roles import BROWSER
from tests.fakes import ScriptedModel
from tests.keyed import TestClient
from tests.test_agent_writes import wait_status
from tests.test_board import written
from tests.test_chat_flow import text
from tests.test_migration_0002 import _config
from tests.test_model_cli import gone
from tests.test_questions import OWN
from tests.test_spawn import reported, role_id, spawn

FAKE = [sys.executable, str(Path(__file__).with_name("fake_session_cli.py"))]


@pytest.fixture
def session_app(settings_env, tmp_path):
    """An app whose provider "Session" is a stand-in CLI following a script."""
    opened = []
    record = tmp_path / "record.json"
    plan = tmp_path / "plan.json"

    def make(script, default_steps=(), **more):
        plan.write_text(json.dumps({"record": str(record), "script": script, **more}),
                        encoding="utf-8")
        cli = ClaudeSessionClient(launcher=FAKE, timeout=30, env={"FAKE_CLI_PLAN": str(plan)})
        default = ScriptedModel(
            default_steps if isinstance(default_steps, dict) else list(default_steps), model_id="big-model")
        app = create_app(load_settings(settings_env), model=default, clients={"Session": cli})
        client = TestClient(app, base_url="http://127.0.0.1:8790")
        client.__enter__()
        opened.append(client)
        provider = client.post("/api/providers", json={"name": "Session", "kind": "claude_cli"})
        assert provider.status_code == 201, provider.text
        return client, provider.json(), default

    def rescript(script, **more):
        plan.write_text(json.dumps({"record": str(record), "script": script, **more}),
                        encoding="utf-8")

    make.rescript = rescript
    make.record = lambda: json.loads(record.read_text(encoding="utf-8"))
    yield make
    for client in opened:
        client.__exit__(None, None, None)


def start(client, project_dir, provider, mode="full_auto", content="what does it print?"):
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(f"/api/conversations/{cid}",
                 json={"permission_mode": mode, "provider_id": provider["id"] if provider else None,
                       "lead_hands_code": False},  # (the Lead writes itself: slice 48 off)
                 headers=OWN)  # a level is raised only from the app's own page
    run = client.post(f"/api/conversations/{cid}/messages", json={"content": content}).json()["run"]
    return cid, run["id"]


def test_a_session_turn_is_recorded_like_any_other(session_app, wait_run, project_dir):
    client, provider, default = session_app([
        {"say": "Let me look."},
        {"call": "read_file", "args": {"path": "hello.py"}},
        {"say": "It prints hi."},
    ])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)

    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    user, first, last = snap["messages"]
    assert (first["content"], last["content"]) == ("Let me look.", "It prints hi.")
    assert {first["status"], last["status"]} == {"complete"}
    (call,) = snap["tool_calls"]
    # the call hangs off the message the model wrote before making it
    assert (call["name"], call["status"], call["message_id"]) == ("read_file", "succeeded", first["id"])
    assert "print('hi')" in call["result"]
    agent = snap["agents"][0]
    assert (agent["provider_name"], agent["status"]) == ("Session", "completed")
    assert (agent["input_tokens"], agent["output_tokens"]) == (500, 40)
    assert (snap["runs"][0]["input_tokens"], snap["runs"][0]["output_tokens"]) == (500, 40)
    assert len(default.calls) == 0  # nothing went to the other model

    seen = session_app.record()
    assert "print('hi')" in seen["results"][0]["content"][0]["text"]  # the CLI got the result
    assert seen["tools"] == ["list_dir", "read_file", "search", "view_image", "write_file",
                             "edit_file",
                             "run_command", *BROWSER, "diagram_image", "show", "web_search", "http_request",
                             "spawn_agent", "create_role", "add_skill", "ask_user",
                             "ask_folder", "ask_secret", "message_agent", "open_room", "discuss",
                             "read_backlog",
                             "add_task", "change_task", "assess_task", "plan_away",
                             "propose_trigger", "post_note", "read_notes", "remember", "recall",
                             "recall_output"]
    document = json.loads(seen["stdin"][seen["stdin"].index("\n\n{") + 2:])
    assert "You are the Orchestrator (the role 'Lead') agent" in document["instructions"]
    assert document["conversation"] == [{"role": "user", "content": "what does it print?"}]


def test_a_change_waits_for_approval_and_the_cli_waits_with_it(session_app, wait_run, project_dir):
    client, provider, _ = session_app([
        {"call": "write_file", "args": {"path": "n.txt", "content": "new\n"}}, {"say": "Written."}])
    cid, run_id = start(client, project_dir, provider, mode="ask")
    snap = wait_status(client, cid, "waiting_approval")
    change = snap["file_changes"][0]
    assert change["status"] == "proposed" and not (project_dir / "n.txt").exists()
    assert snap["messages"][-1]["content"] == ""  # a call with nothing said before it
    client.post(f"/api/file-changes/{change['id']}/approve")
    snap = wait_run(client, cid, run_id)
    assert (project_dir / "n.txt").read_bytes() == b"new\n"
    assert session_app.record()["results"][0]["content"][0]["text"].startswith("applied: n.txt")
    # (Under the answer, KOLONİ's line on where the work is: B-205.)
    assert [m["content"] for m in snap["messages"][-2:]] == [
        "Written.", "In the project: n.txt (+1 −0)."]


def test_a_declined_change_goes_back_to_the_cli_as_the_users_decision(
    session_app, wait_run, project_dir
):
    client, provider, _ = session_app([
        {"call": "write_file", "args": {"path": "n.txt", "content": "x"}}, {"say": "Understood."}])
    cid, run_id = start(client, project_dir, provider, mode="ask")
    change = wait_status(client, cid, "waiting_approval")["file_changes"][0]
    client.post(f"/api/file-changes/{change['id']}/reject")
    snap = wait_run(client, cid, run_id)
    result = session_app.record()["results"][0]
    assert result["isError"] is True and "not a tool error" in result["content"][0]["text"]
    assert snap["tool_calls"][0]["status"] == "denied" and not (project_dir / "n.txt").exists()


def test_a_tool_outside_the_role_is_neither_listed_nor_run(session_app, wait_run, project_dir):
    client, provider, _ = session_app([
        {"call": "write_file", "args": {"path": "x.txt", "content": "x"}}, {"say": "ok"}])
    client.patch(f"/api/roles/{role_id(client, 'Lead')}", json={"tools": ["read_file"]})
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    seen = session_app.record()
    # (show and recall_output: every agent's at its own work)
    assert seen["tools"] == ["read_file", "show", "recall_output"]
    # a tool that was not offered is refused at the door: nothing is recorded or run
    assert "write_file is not one of the tools offered here" in seen["results"][0]["content"][0]["text"]
    assert snap["tool_calls"] == [] and not (project_dir / "x.txt").exists()


def test_stop_ends_the_cli_and_settles_what_was_open(session_app, wait_run, project_dir):
    client, provider, _ = session_app([
        {"say": "Working."}, {"call": "write_file", "args": {"path": "n.txt", "content": "x"}},
        {"hang": True}])
    cid, run_id = start(client, project_dir, provider, mode="ask")
    wait_status(client, cid, "waiting_approval")
    pid = session_app.record()["pid"]
    client.post(f"/api/runs/{run_id}/cancel")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "cancelled"
    assert snap["file_changes"][0]["status"] == "rejected"
    assert snap["tool_calls"][0]["status"] == "interrupted"
    assert snap["agents"][0]["status"] == "cancelled"
    assert all(m["status"] == "complete" for m in snap["messages"])
    assert gone(pid)


def test_a_session_that_goes_on_too_long_hits_the_step_limit(session_app, wait_run, project_dir):
    script = [{"call": "list_dir"} for _ in range(30)] + [{"hang": True}]
    client, provider, _ = session_app(script)
    # (B-413: the Orchestrator's step limit is only one the user set - its role's)
    assert client.patch(f"/api/roles/{role_id(client, 'Lead')}", json={"max_steps": 8},
                        headers={"Origin": "http://127.0.0.1:8790"}).status_code == 200
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id, timeout=30)
    assert (snap["runs"][0]["status"], snap["runs"][0]["error"]) == (
        "failed", "stopped at its role's limit of 8 steps")
    assert len(snap["tool_calls"]) == 8
    assert gone(session_app.record()["pid"])


def test_a_cli_that_fails_fails_the_turn_with_its_reason(session_app, wait_run, project_dir):
    client, provider, _ = session_app([{"say": "Starting."}, {"exit": 3, "stderr": "not signed in"}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "failed" and "not signed in" in snap["runs"][0]["error"]
    assert snap["messages"][-1]["content"] == "Starting."  # what it said is kept


def test_the_next_turn_hands_the_cli_the_whole_conversation(session_app, wait_run, project_dir):
    client, provider, _ = session_app([
        {"say": "Let me look."}, {"call": "read_file", "args": {"path": "hello.py"}},
        {"say": "It prints hi."}])
    cid, run_id = start(client, project_dir, provider)
    wait_run(client, cid, run_id)
    session_app.rescript([{"say": "Still hi."}])
    second = client.post(f"/api/conversations/{cid}/messages", json={"content": "and now?"}).json()
    wait_run(client, cid, second["run"]["id"])
    seen = session_app.record()["stdin"]
    conversation = json.loads(seen[seen.index("\n\n{") + 2:])["conversation"]
    # (and after the turn, KOLONİ's record of it: K-gecmis-zengin)
    assert [m["role"] for m in conversation] == [
        "user", "assistant", "tool", "assistant", "user", "user"]
    assert conversation[-2]["content"].endswith('- files read: "hello.py"')
    assert conversation[1]["tool_calls"][0]["function"]["name"] == "read_file"
    assert "print('hi')" in conversation[2]["content"]
    assert conversation[-1]["content"] == "and now?"


def test_a_sub_agent_can_run_as_a_session(session_app, wait_run, project_dir):
    client, provider, default = session_app(
        [{"call": "read_file", "args": {"path": "hello.py"}}, {"say": "Looks fine."}],
        default_steps=[spawn("Reviewer", "Review hello.py"), text("The reviewer is happy.")])
    client.patch(f"/api/roles/{role_id(client, 'Reviewer')}", json={"provider_id": provider["id"]})
    cid, run_id = start(client, project_dir, None)
    snap = wait_run(client, cid, run_id)
    lead, reviewer = snap["agents"]
    assert (lead["provider_name"], reviewer["provider_name"]) == ("Local", "Session")
    assert (reviewer["status"], reviewer["report"]) == ("completed", "Looks fine.")
    read = next(t for t in snap["tool_calls"] if t["name"] == "read_file")
    assert read["agent_id"] == reviewer["id"]
    seen = session_app.record()
    # the Reviewer's own
    assert seen["tools"] == ["list_dir", "read_file", "search", "view_image", "show", "ask_user",
                             "message_agent",
                             "post_note", "read_notes", "remember", "recall",
                             "recall_output"]
    document = json.loads(seen["stdin"][seen["stdin"].index("\n\n{") + 2:])
    assert document["conversation"] == [{"role": "user", "content": "Review hello.py"}]
    assert "Reviewer sub-agent" in document["instructions"]
    assert reported(default.calls[1][-1]["content"]) == "Reviewer finished.\n\nLooks fine."


def test_a_session_lead_can_open_a_sub_agent_on_another_model(session_app, wait_run, project_dir):
    client, provider, default = session_app(
        [{"call": "spawn_agent", "args": {"role": "Reviewer", "task": "Review hello.py"}},
         {"say": "Reviewed."}],
        default_steps=[text("No problems.")])
    # the Reviewer has a model of its own; without one it would follow the conversation
    local = client.get("/api/providers").json()[0]
    client.patch(f"/api/roles/{role_id(client, 'Reviewer')}", json={"provider_id": local["id"]})
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert [a["provider_name"] for a in snap["agents"]] == ["Session", "Local"]
    assert reported(session_app.record()["results"][0]["content"][0]["text"]) == (
        "Reviewer finished.\n\nNo problems.")
    assert snap["runs"][0]["status"] == "completed"


# --- settings ---------------------------------------------------------------------


def test_each_kind_runs_the_way_it_safely_can(client):
    def add(**body):
        return client.post("/api/providers", json=body)

    claude = add(name="Claude", kind="claude_cli").json()
    assert claude["mode"] == "session"  # the default for Claude Code
    assert add(name="Claude steps", kind="claude_cli", mode="step").json()["mode"] == "step"
    assert add(name="Qoder", kind="qoder_cli").json()["mode"] == "session"
    assert add(name="Codex", kind="codex_cli").json()["mode"] == "session"
    # On a model server of the user's its session is not measured: a step there, unless chosen.
    def local(**body):  # (an address is set from the app's own page only)
        return client.post("/api/providers", headers={"Origin": "http://127.0.0.1:8790"}, json={
            "kind": "codex_cli", "base_url": "http://127.0.0.1:8080/v1", **body}).json()["mode"]

    assert local(name="Codex local") == "step"
    assert local(name="Codex local s", mode="session") == "session"
    assert client.get("/api/providers").json()[0]["mode"] is None  # an HTTP provider has none
    # A session too since 7 Nov 2026 (its patch tool declined); not reading only, agy's way.
    assert add(name="Codex session", kind="codex_cli", mode="session").json()["mode"] == "session"
    refused = add(name="Codex reads", kind="codex_cli", mode="reads")
    assert refused.status_code == 422 and "Codex" in refused.json()["detail"]
    assert add(name="Qoder steps", kind="qoder_cli", mode="step").status_code == 422
    assert client.patch(f"/api/providers/{claude['id']}", json={"mode": "step"}).json()[
        "mode"] == "step"
    assert client.patch(f"/api/providers/{claude['id']}", json={"mode": "nope"}).status_code == 422


def test_the_right_client_is_built_for_kind_and_mode(settings):
    from app.db.models import Provider
    from app.model_cli import ClaudeCliClient, CodexCliClient
    from app.model_native import CodexSessionClient
    from app.model_session import ClaudeSessionClient as Session
    from app.model_session import QoderSessionClient
    from app.providers import Providers

    providers = Providers(settings)
    cases = [("claude_cli", "session", Session), ("claude_cli", "step", ClaudeCliClient),
             ("qoder_cli", "session", QoderSessionClient), ("codex_cli", "step", CodexCliClient),
             ("codex_cli", "session", CodexSessionClient),
             ("codex_cli", "reads", CodexSessionClient)]  # a stray value runs the kind's default
    for kind, mode, expected in cases:
        row = Provider(id=f"{kind}-{mode}", name=f"{kind}-{mode}", kind=kind, mode=mode)
        assert type(providers.client(row, None)) is expected


def test_qoder_is_offered_on_the_first_start_when_installed(settings_env, tmp_path):
    settings_env["KOLONI_DETECT_CLI"] = "1"
    found = {"qodercli": str(tmp_path / "qodercli.exe"), "claude": str(tmp_path / "claude.exe")}
    app = create_app(load_settings(settings_env), model=ScriptedModel([]), which=found.get)
    with TestClient(app, base_url="http://127.0.0.1:8790") as client:
        listed = [(p["name"], p["kind"], p["mode"]) for p in client.get("/api/providers").json()]
    assert listed == [("Local", "openai_compat", None), ("Claude Code", "claude_cli", "session"),
                      ("Qoder", "qoder_cli", "session")]


QODER_KNOWN = ["Qwen3.8-Flash", "DeepSeek-v4-Pro", "Qwen-3.8-Max", "DeepSeek-v4-Flash", "Qwen-3.7-Max",
               "GLM-5.2", "Qwen-3.6-Flash"]  # catalog.json's (`qodercli --list-models`, 4 Nov)


@pytest.fixture
def qoder_app(settings_env, tmp_path):
    """An app whose provider "Qoder" is the stand-in, its `--list-models` as the plan says."""
    from app.model_session import QoderSessionClient

    opened = []
    record, plan = tmp_path / "record.json", tmp_path / "plan.json"

    def make(**more):
        plan.write_text(json.dumps({"record": str(record), **more}), encoding="utf-8")
        cli = QoderSessionClient(launcher=FAKE, env={"FAKE_CLI_PLAN": str(plan)})
        app = create_app(load_settings(settings_env), model=ScriptedModel([]),
                         clients={"Qoder": cli})
        client = TestClient(app, base_url="http://127.0.0.1:8790")
        client.__enter__()
        opened.append(client)
        made = client.post("/api/providers", json={"name": "Qoder", "kind": "qoder_cli"})
        assert made.status_code == 201, made.text
        return client, made.json()["id"]

    make.record = lambda: json.loads(record.read_text(encoding="utf-8"))
    yield make
    for client in opened:
        client.__exit__(None, None, None)


# What `qodercli --list-models` printed on the user's account (29 Oct 2026, qodercli 1.1.51).
QODER_LISTED = """MODEL
Qwen3.8-Flash
DeepSeek-Flash
DeepSeek-v4-Pro (Alibaba Cloud Model Studio - Singapore) (bailian-intl/deepseek-v4-pro-tp)
Qwen-3.8-Max (Alibaba Cloud Model Studio - Singapore) (bailian-intl/qwen3.8-max-tp)
DeepSeek-v4-Flash (Alibaba Cloud Model Studio - Singapore) (bailian-intl/deepseek-v4-flash-tp)
Qwen-3.7-Max (Alibaba Cloud Model Studio - Singapore) (bailian-intl/qwen3.7-max-tp)
GLM-5.2 (Alibaba Cloud Model Studio - Singapore) (bailian-intl/glm5.2-tp)
Qwen-3.6-Flash (Alibaba Cloud Model Studio - Singapore) (bailian-intl/qwen3.6-flash-tp)
wan2.7-image-pro (Alibaba Cloud Model Studio - Singapore / Token plan) (bailian-intl/tp/wan2.7-image-pro)
"""
QODER_NAMES = ["Qwen3.8-Flash", "DeepSeek-Flash", "DeepSeek-v4-Pro", "Qwen-3.8-Max",
               "DeepSeek-v4-Flash", "Qwen-3.7-Max", "GLM-5.2", "Qwen-3.6-Flash"]


def test_qoder_lists_the_models_its_own_cli_lists(qoder_app):
    client, provider = qoder_app(models_text=QODER_LISTED)
    listed = client.get(f"/api/providers/{provider}/models").json()
    assert listed == {"models": list(dict.fromkeys([*QODER_KNOWN, *QODER_NAMES])), "note": None}
    assert qoder_app.record()["argv"] == ["--list-models"]  # nothing else on its line
    # A listed model takes Qoder's levels (catalog.json's, the same for each of its models).
    facts = client.get(f"/api/providers/{provider}/model-facts",
                       params={"model": "DeepSeek-Flash"}).json()
    assert facts["efforts"] == ["off", "low", "medium", "high", "xhigh"]


@pytest.mark.parametrize("plan", [{"models_exit": 1, "models_text": "Qwen3.8-Flash\n"},
                                  {"models_text": "No models.\n"}, {"models_hang": True}])
def test_qoder_that_cannot_list_falls_back_to_the_catalogue_silently(qoder_app, plan,
                                                                     monkeypatch):
    import app.model_session

    monkeypatch.setattr(app.model_session, "QODER_MODELS_SECONDS", 1.0)
    client, provider = qoder_app(**plan)
    listed = client.get(f"/api/providers/{provider}/models").json()
    assert listed == {"models": QODER_KNOWN, "note": None}  # no error, nothing of its stderr


def test_qoder_not_installed_falls_back_to_the_catalogue_silently(settings_env):
    from app.model_session import QoderSessionClient

    cli = QoderSessionClient(which=lambda name: None)
    app = create_app(load_settings(settings_env), model=ScriptedModel([]), clients={"Qoder": cli})
    with TestClient(app, base_url="http://127.0.0.1:8790") as client:
        made = client.post("/api/providers", json={"name": "Qoder", "kind": "qoder_cli"}).json()
        listed = client.get(f"/api/providers/{made['id']}/models").json()
    assert listed == {"models": QODER_KNOWN, "note": None}


def test_qoders_list_gives_its_names_without_the_image_model_and_tiers_them():
    from app import catalog
    from app.model_session import qoder_models

    assert qoder_models(QODER_LISTED) == QODER_NAMES  # (no "MODEL", no wan2.7-image-pro)
    tiers = {row["name"]: row["tier"] for row in catalog.fill("qoder_cli", [], QODER_NAMES)[0]}
    assert tiers == {"Qwen3.8-Flash": "fast", "DeepSeek-Flash": "fast",
                     "DeepSeek-v4-Pro": "strongest", "Qwen-3.8-Max": "strongest",
                     "DeepSeek-v4-Flash": "fast", "Qwen-3.7-Max": "strongest",
                     "GLM-5.2": "strongest", "Qwen-3.6-Flash": "fast"}


def test_migration_0006_and_back(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0005")
    at = "2026-10-05 10:00:00"
    with sqlite3.connect(db) as conn:
        for id, kind in (("a", "claude_cli"), ("b", "codex_cli"), ("c", "openai_compat")):
            conn.execute(
                "INSERT INTO providers (id, name, kind, position, created_at, updated_at) "
                "VALUES (?, ?, ?, 0, ?, ?)", (id, id, kind, at, at))
    command.upgrade(cfg, "head")
    with sqlite3.connect(db) as conn:
        assert dict(conn.execute("SELECT id, mode FROM providers")) == {
            "a": "session", "b": "step", "c": None}
    command.downgrade(cfg, "0005")
    with sqlite3.connect(db) as conn:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(providers)")]
        assert "mode" not in columns
        assert conn.execute("SELECT count(*) FROM providers").fetchone()[0] == 3


# --- review fixes -----------------------------------------------------------------


def test_a_cli_that_dies_while_a_change_waits_leaves_nothing_open(
    session_app, wait_run, project_dir
):
    client, provider, _ = session_app([
        {"call_then_die": "write_file", "args": {"path": "n.txt", "content": "x"}, "after": 1}])
    cid, run_id = start(client, project_dir, provider, mode="ask")
    change = wait_status(client, cid, "waiting_approval")["file_changes"][0]
    snap = wait_run(client, cid, run_id, timeout=20)
    assert snap["runs"][0]["status"] == "failed" and "crashed" in snap["runs"][0]["error"]
    # nothing is left asking for a decision that can no longer be given
    assert snap["file_changes"][0]["status"] == "rejected"
    assert snap["tool_calls"][0]["status"] == "interrupted"
    assert client.post(f"/api/file-changes/{change['id']}/approve").status_code == 409
    assert not (project_dir / "n.txt").exists()


def test_a_bug_in_a_tool_fails_the_turn_with_the_bug_and_settles_the_call(
    session_app, wait_run, project_dir, monkeypatch
):
    def boom(*args):
        raise RuntimeError("database is locked")

    monkeypatch.setattr("app.agent.run_read_tool", boom)
    client, provider, _ = session_app([
        {"call": "read_file", "args": {"path": "hello.py"}}, {"hang": True}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id, timeout=20)
    assert snap["runs"][0]["status"] == "failed"
    assert "database is locked" in snap["runs"][0]["error"]
    assert snap["tool_calls"][0]["status"] == "interrupted"


def test_a_session_sub_agent_that_dies_fails_alone_and_cleanly(session_app, wait_run, project_dir):
    client, provider, default = session_app(
        [{"call_then_die": "ask_user", "args": {"question": "Strict?"}, "after": 1}],
        default_steps=[spawn("Reviewer"), text("carrying on")])
    client.patch(f"/api/roles/{role_id(client, 'Reviewer')}", json={"provider_id": provider["id"]})
    cid, run_id = start(client, project_dir, None, mode="auto_edit")
    snap = wait_run(client, cid, run_id, timeout=20)
    reviewer = snap["agents"][1]
    assert reviewer["status"] == "failed" and "crashed" in reviewer["error"]
    assert snap["questions"][0]["status"] == "cancelled"
    assert {t["status"] for t in snap["tool_calls"] if t["agent_id"] == reviewer["id"]} == {
        "interrupted"}
    assert snap["runs"][0]["status"] == "completed"  # the lead went on


def test_a_server_shutdown_in_the_middle_of_a_session_settles_it(session_app, project_dir):
    client, provider, _ = session_app([
        {"say": "Working."}, {"call": "write_file", "args": {"path": "n.txt", "content": "x"}},
        {"hang": True}])
    cid, _run_id = start(client, project_dir, provider, mode="ask")
    wait_status(client, cid, "waiting_approval")
    pid = session_app.record()["pid"]
    client.portal.call(client.app.state.runner.shutdown)
    snap = client.get(f"/api/conversations/{cid}").json()
    assert snap["runs"][0]["status"] == "interrupted"
    assert snap["file_changes"][0]["status"] == "rejected"
    assert snap["tool_calls"][0]["status"] == "interrupted"
    assert gone(pid)


def test_parallel_calls_are_all_recorded_and_run(session_app, wait_run, project_dir):
    client, provider, _ = session_app([
        {"say": "Two at once."},
        {"parallel": [{"call": "read_file", "args": {"path": "hello.py"}}, {"call": "list_dir"}]},
        {"say": "Done."}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert sorted((t["name"], t["status"]) for t in snap["tool_calls"]) == [
        ("list_dir", "succeeded"), ("read_file", "succeeded")]
    assert snap["messages"][-1]["content"] == "Done."


def test_setting_no_mode_leaves_the_mode_as_it_is(client):
    claude = client.post("/api/providers", json={
        "name": "Claude", "kind": "claude_cli", "mode": "step"}).json()
    kept = client.patch(f"/api/providers/{claude['id']}", json={"mode": None, "name": "C"}).json()
    assert kept["mode"] == "step"


# --- agents talking (slice 8) ---------------------------------------------------


def test_a_session_agent_messages_its_child(session_app, wait_run, project_dir):
    client, provider, default = session_app(
        [{"call": "spawn_agent", "args": {"role": "Reviewer", "task": "Review hello.py"}},
         {"call": "message_agent", "args": {"to": "Reviewer", "message": "And the tests?"}},
         {"say": "All reviewed."}],
        default_steps=[text("Looks fine."), text("There are none.")])
    local = next(p for p in client.get("/api/providers").json() if p["name"] != "Session")
    client.patch(f"/api/roles/{role_id(client, 'Reviewer')}", json={"provider_id": local["id"]})
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    seen = session_app.record()
    assert "message_agent" in seen["tools"]  # offered at the start, before anyone exists
    assert [reported(r["content"][0]["text"]) for r in seen["results"]] == [
        "Reviewer finished.\n\nLooks fine.", "Reviewer replied:\n\nThere are none."]
    assert default.calls[1][-1]["content"] == (
        "Message from Lead (the agent you work for):\n\nAnd the tests?")
    assert [m["kind"] for m in snap["channel_messages"]] == ["task", "report", "message", "reply"]
    assert snap["agents"][1]["report"] == "There are none."


def test_a_session_sub_agent_takes_another_turn_on_a_message(session_app, wait_run, project_dir):
    from tests.test_spawn import call, step

    client, provider, default = session_app(
        [{"say": "Looks fine."}],
        default_steps=[
            spawn("Reviewer", "Review hello.py"),
            step(call("message_agent", {"to": "Reviewer", "message": "Look again"}, "m1")),
            text("done")])
    client.patch(f"/api/roles/{role_id(client, 'Reviewer')}", json={"provider_id": provider["id"]})
    cid, run_id = start(client, project_dir, None)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert default.calls[2][-1]["content"] == "Reviewer replied:\n\nLooks fine."
    # the second run of the CLI was given the whole of the Reviewer's conversation
    document = session_app.record()["stdin"]
    assert "Message from Lead (the agent you work for)" in document and "Look again" in document
    assert "Review hello.py" in document


def test_a_session_that_dies_while_answering_leaves_its_waiting_work_alone(
    session_app, wait_run, project_dir, gate
):
    from tests.conftest import Gate
    from tests.test_spawn import call, step

    # The Lead is a CLI session whose Coder is at work (its spawn_agent returned at once,
    # K-paralel-spawn); once the Lead's CLI has ended its turn and waits for the Coder, a
    # second run of the CLI is started to answer its Coder, and that one gives up. The
    # Lead's own run after its turn reads the Coder's report.
    asks = Gate()
    client, provider, default = session_app(
        [{"call": "spawn_agent", "args": {"role": "Coder", "task": "Fix the greeting"}},
         {"say": "All done."}],
        default_steps=[
            asks.step(step(call("message_agent", {"to": "Lead", "message": "Which file?"}, "m1"))),
            gate.step(text("Went on alone.")),
        ],
        answer_script=[{"exit": 3, "stderr": "boom"}],
        later_script=[{"say": "Read it."}], later_when="Went on alone.")
    local = next(p for p in client.get("/api/providers").json() if p["name"] != "Session")
    client.patch(f"/api/roles/{role_id(client, 'Coder')}", json={"provider_id": local["id"]})
    cid, run_id = start(client, project_dir, provider)
    asks.wait_partial()
    for _ in range(400):  # (its CLI's turn over: it waits for the Coder)
        if client.get(f"/api/conversations/{cid}").json()["agents"][0]["status"] == "waiting":
            break
        time.sleep(0.02)
    asks.release()
    gate.wait_partial()
    snap = client.get(f"/api/conversations/{cid}").json()
    by_name = {t["name"]: t for t in snap["tool_calls"]}
    assert by_name["message_agent"]["status"] == "failed"
    assert by_name["spawn_agent"]["status"] == "running"
    assert [(a["name"], a["status"], a["error"]) for a in snap["agents"]] == [
        ("Lead", "waiting", None), ("Coder", "running", None)]
    gate.release()
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert [a["status"] for a in snap["agents"]] == ["completed", "completed"]


# --- agents at the same time (slice 9) --------------------------------------------


def _local(client):
    return next(p for p in client.get("/api/providers").json() if p["name"] != "Session")


def test_a_session_opens_two_sub_agents_at_once(session_app, wait_run, project_dir):
    from tests.conftest import Gate

    a, b = Gate(), Gate()
    client, provider, default = session_app(
        [{"parallel": [
            {"call": "spawn_agent", "args": {"role": "Coder", "task": "do A"}},
            {"call": "spawn_agent", "args": {"role": "Tester", "task": "do B"}}]},
         {"say": "Both started."}],
        default_steps={"Coder": [a.step(text("A done"))], "Tester": [b.step(text("B done"))]},
        later_script=[{"say": "Both done."}], later_when="B done")
    for role in ("Coder", "Tester"):
        client.patch(f"/api/roles/{role_id(client, role)}",
                     json={"provider_id": _local(client)["id"]})
    cid, run_id = start(client, project_dir, provider)
    a.wait_partial()
    b.wait_partial()  # both at work; each call was answered as it opened (K-paralel-spawn)
    for _ in range(400):  # (its CLI's turn over, it waits for them)
        snap = client.get(f"/api/conversations/{cid}").json()
        if snap["agents"][0]["status"] == "waiting":
            break
        time.sleep(0.02)
    assert {x["name"]: x["status"] for x in snap["agents"]} == {
        "Lead": "waiting", "Coder": "running", "Tester": "running"}
    a.release()
    b.release()
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    # Their reports came after, as notes, read in a run of the CLI after its turn.
    assert sorted(reported(m["content"]) for m in snap["messages"] if m["role"] == "agent") == [
        "Coder finished.\n\nA done", "Tester finished.\n\nB done"]
    assert snap["messages"][-1]["content"] == "Both done."


def test_a_note_reaches_a_session_with_its_next_result(session_app, wait_run, project_dir):
    from tests.test_spawn import call, step

    # The Reviewer is a CLI session waiting on the user; the Tester leaves it a note.
    client, provider, default = session_app(
        [{"call": "ask_user", "args": {"question": "Strict?"}}, {"say": "Reviewed."}],
        default_steps={
            "Lead": [step(
                call("spawn_agent", {"role": "Reviewer", "task": "Review hello.py"}, "s1"),
                call("spawn_agent", {"role": "Tester", "task": "Run the tests"}, "s2"),
            ), text("done")],
            "Tester": [
                step(call("message_agent", {"to": "Reviewer", "message": "tests pass"}, "n")),
                text("B done")],
        })
    client.patch(f"/api/roles/{role_id(client, 'Reviewer')}", json={"provider_id": provider["id"]})
    cid, run_id = start(client, project_dir, None, mode="auto_edit")
    for _ in range(400):
        snap = client.get(f"/api/conversations/{cid}").json()
        done = [x for x in snap["agents"] if x["name"] == "Tester" and x["status"] == "completed"]
        if done and snap["questions"]:
            break
        time.sleep(0.02)
    left = next(t for t in snap["tool_calls"] if t["name"] == "message_agent")
    assert left["result"].startswith("noted: Reviewer is at work"), left
    # K-lead-bekliyor: one that asks the user is shown "waiting", yet for a message it is at
    # work as before - not an answer turn, which would leave a CLI out of reach (`_reachable`)
    assert next(x["status"] for x in snap["agents"] if x["name"] == "Reviewer") == "waiting"
    question = snap["questions"][0]
    client.post(f"/api/questions/{question['id']}/answer", json={"answer": "yes"}, headers=OWN)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    got = session_app.record()["results"][0]["content"][0]["text"]
    assert got.startswith("The user answered: yes\n\nMessage from Tester (another agent")
    assert got.endswith("tests pass")
    note = next(m for m in snap["messages"] if m["role"] == "agent")
    assert note["delivered_at"] is not None


def _begin(client, project_dir, provider, mode, content="go", **settings):
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    patched = client.patch(f"/api/conversations/{cid}", json={
        "permission_mode": mode, "provider_id": provider["id"] if provider else None,
        "lead_hands_code": False, **settings}, headers=OWN)  # (the Lead writes: 48 off)
    assert patched.status_code == 200, patched.text
    run = client.post(f"/api/conversations/{cid}/messages", json={"content": content}).json()["run"]
    return cid, run["id"]


def test_the_turn_stops_waiting_when_the_agent_that_asked_is_gone(
    session_app, wait_run, project_dir, gate
):
    from tests.test_spawn import call, step

    # A session Reviewer asks the user and dies before the answer. Later the Lead's own
    # edit is approved: the turn is at work again, not still "waiting for approval".
    client, provider, default = session_app(
        [{"call_then_die": "ask_user", "args": {"question": "Strict?"}, "after": 1}],
        default_steps={
            "Lead": [spawn("Reviewer", "Review hello.py"),
                     step(call("write_file", {"path": "n.txt", "content": "x\n"}, "w")),
                     gate.step(text("done"))],
        })
    client.patch(f"/api/roles/{role_id(client, 'Reviewer')}", json={"provider_id": provider["id"]})
    cid, run_id = _begin(client, project_dir, None, "ask")
    for _ in range(400):
        snap = client.get(f"/api/conversations/{cid}").json()
        if snap["file_changes"]:
            break
        time.sleep(0.02)
    change = snap["file_changes"][0]
    assert client.post(f"/api/file-changes/{change['id']}/approve").status_code == 200
    gate.wait_partial()
    snap = client.get(f"/api/conversations/{cid}").json()
    assert snap["runs"][0]["status"] == "running"
    gate.release()
    assert wait_run(client, cid, run_id)["runs"][0]["status"] == "completed"


def test_an_answer_that_fails_leaves_the_sessions_own_pending_change_alone(
    session_app, wait_run, project_dir, gate
):
    from tests.test_spawn import call, step

    # The Lead, a CLI session, has asked for a sub-agent and an edit at once; the edit
    # waits for approval. Its Coder asks it something and the answering CLI dies.
    client, provider, default = session_app(
        [{"parallel": [
            {"call": "spawn_agent", "args": {"role": "Coder", "task": "Fix the greeting"}},
            {"call": "write_file", "args": {"path": "n.txt", "content": "x\n"}}]},
         {"say": "All done."}],
        default_steps={"Coder": [
            step(call("message_agent", {"to": "Lead", "message": "Which file?"}, "m1")),
            gate.step(text("Went on alone.")),
        ]},
        answer_script=[{"exit": 3, "stderr": "boom"}],
        later_script=[{"say": "Read it."}], later_when="Went on alone.")
    client.patch(f"/api/roles/{role_id(client, 'Coder')}",
                 json={"provider_id": _local(client)["id"]})
    cid, run_id = _begin(client, project_dir, provider, "ask", spawn_approval="never")
    gate.wait_partial()
    snap = client.get(f"/api/conversations/{cid}").json()
    change = snap["file_changes"][0]
    assert change["status"] == "proposed"  # nobody decided it
    write = next(t for t in snap["tool_calls"] if t["name"] == "write_file")
    assert write["status"] == "running"
    assert client.post(f"/api/file-changes/{change['id']}/approve").status_code == 200
    gate.release()
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert snap["file_changes"][0]["status"] == "applied"
    assert (project_dir / "n.txt").read_text() == "x\n"


# --- discussions (slice 10) ---------------------------------------------------------


def test_a_session_agent_speaks_in_a_discussion_with_reading_tools_only(
    session_app, wait_run, project_dir
):
    from tests.test_spawn import call, step

    # The Reviewer is a CLI session; in the discussion the CLI is started again and
    # given the shared place and nothing but tools to read with.
    client, provider, default = session_app(
        [{"say": "Looks fine."}],
        default_steps={"Lead": [
            spawn("Reviewer", "Review hello.py"),
            step(call("discuss", {"topic": "Ship it?", "with": ["Reviewer"], "rounds": 1}, "d")),
            text("Ship it."), text("done")]},
        answer_script=[{"call": "write_file", "args": {"path": "hello.py", "content": "x"}},
                       {"call": "read_file", "args": {"path": "hello.py"}},
                       {"say": "Yes, ship it."}])
    client.patch(f"/api/roles/{role_id(client, 'Reviewer')}", json={"provider_id": provider["id"]})
    cid, run_id = start(client, project_dir, None)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    seen = session_app.record()
    assert seen["tools"] == ["list_dir", "read_file", "search", "recall"]
    assert "You are in a discussion with Lead" in seen["stdin"]
    assert seen["results"][0]["isError"] is True  # the write was refused
    assert (project_dir / "hello.py").read_text() == "print('hi')\n"
    assert [(p["content"], p["passed"]) for p in snap["discussion_posts"]] == [
        ("Yes, ship it.", False), ("Ship it.", False)]


def test_a_note_on_the_notebook_reaches_a_session_with_its_next_result(
    session_app, wait_run, project_dir
):
    from tests.test_spawn import call, step

    # The Reviewer is a CLI session waiting on the user; the Tester writes on the notebook.
    client, provider, default = session_app(
        [{"call": "ask_user", "args": {"question": "Strict?"}}, {"call": "read_notes"},
         {"call": "post_note", "args": {"text": "reviewed strictly"}}, {"say": "Reviewed."}],
        default_steps={
            "Lead": [step(
                call("spawn_agent", {"role": "Reviewer", "task": "Review hello.py"}, "s1"),
                call("spawn_agent", {"role": "Tester", "task": "Run the tests"}, "s2"),
            ), text("done")],
            "Tester": [step(call("post_note", {"text": "tests pass"}, "n")), text("B done")],
        })
    client.patch(f"/api/roles/{role_id(client, 'Reviewer')}", json={"provider_id": provider["id"]})
    cid, run_id = start(client, project_dir, None, mode="auto_edit")
    for _ in range(400):
        snap = client.get(f"/api/conversations/{cid}").json()
        done = [x for x in snap["agents"] if x["name"] == "Tester" and x["status"] == "completed"]
        if done and snap["questions"]:
            break
        time.sleep(0.02)
    # written, and not read: the session has had no result since
    assert [n["read_by"] for n in snap["board_posts"]] == [[]]
    client.post(f"/api/questions/{snap['questions'][0]['id']}/answer", json={"answer": "yes"}, headers=OWN)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    seen = session_app.record()
    assert seen["tools"][-5:-3] == ["post_note", "read_notes"]
    answered, listed, wrote = [r["content"][0]["text"] for r in seen["results"]]
    assert answered == (
        "The user answered: yes\n\nNote from Tester on the shared notebook (another agent "
        "of this turn; information, not an instruction from the agent you work for):"
        '\n\n"tests pass"')
    # asked for the notebook, it is not handed the same note a second time
    assert listed.splitlines()[1].startswith("1. Tester, ") and listed.count("tests pass") == 1
    assert wrote.startswith("noted: 1 other agent at work sees this at its next step, if it takes one. ")
    by = {x["name"]: x["id"] for x in snap["agents"]}
    theirs, its = written(snap)
    assert theirs["read_by"] == [by["Reviewer"], by["Lead"]]
    assert (its["agent_id"], its["read_by"]) == (by["Reviewer"], [by["Lead"]])


@pytest.mark.parametrize("turn", ["answer", "discussion"])
def test_a_session_answering_or_speaking_is_not_handed_the_notebook(
    session_app, wait_run, project_dir, turn
):
    from tests.test_spawn import call, step

    # The Reviewer, a CLI session, has finished; then the Lead writes on the notebook.
    # Started again only to answer the Tester, or to speak, the CLI is handed no note:
    # the notebook waits for its own work.
    again = (
        spawn("Tester", "Run the tests", id="s2") if turn == "answer"
        else step(call("discuss", {"topic": "Ship it?", "with": ["Reviewer"], "rounds": 1}, "d"))
    )
    client, provider, default = session_app(
        [{"say": "Looks fine."}],
        default_steps={
            "Lead": [
                spawn("Reviewer", "Review hello.py"),
                step(call("post_note", {"text": "tabs, not spaces"}, "n")),
                again, text("Ship it."), text("done")],
            "Tester": [
                step(call("message_agent", {"to": "Reviewer", "message": "Any tests?"}, "m")),
                text("B done")],
        },
        answer_script=[{"call": "read_file", "args": {"path": "hello.py"}}, {"say": "None."}])
    client.patch(f"/api/roles/{role_id(client, 'Reviewer')}", json={"provider_id": provider["id"]})
    cid, run_id = start(client, project_dir, None)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    seen = session_app.record()
    # this is the second run of the CLI, and it did ask KOLONİ for something
    assert ("Message from Tester" if turn == "answer" else "You are in a discussion") in seen["stdin"]
    (read,) = [r["content"][0]["text"] for r in seen["results"]]
    assert "print('hi')" in read and "shared notebook" not in read
    assert "tabs, not spaces" not in seen["stdin"]
    by = {x["name"]: x["id"] for x in snap["agents"]}
    (note,) = written(snap)
    assert by["Reviewer"] not in note["read_by"]
    assert not [m for m in snap["messages"]
                if m["board_post_id"] and m["agent_id"] == by["Reviewer"]]


def test_a_claude_session_is_given_the_conversations_level_for_the_lead(
    session_app, wait_run, project_dir
):
    client, provider, _ = session_app([{"say": "It prints hi."}])
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    assert client.patch(f"/api/conversations/{cid}", json={
        "permission_mode": "full_auto", "provider_id": provider["id"], "lead_effort": "max",
    }, headers=OWN).status_code == 200
    run = client.post(f"/api/conversations/{cid}/messages", json={"content": "hi"}).json()["run"]
    snap = wait_run(client, cid, run["id"])
    argv = session_app.record()["argv"]
    assert argv[:2] == ["--effort", "max"] and argv.count("--effort") == 1
    assert [a["effort"] for a in snap["agents"]] == ["max"]
