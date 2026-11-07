"""Codex in native mode: it works with its own tools; KOLONİ records what it does and
gives it the tools to work with other agents and the user."""

import json
import sqlite3
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command

from app import copies
from app.board import PUSHED
from app.config import load_settings
from app.main import create_app
from app.model_client import ToolCallRequest
from app.model_native import CodexNativeClient
from tests.fakes import ScriptedModel
from tests.keyed import TestClient
from tests.test_agent_writes import wait_status
from tests.test_board import written
from tests.test_chat_flow import text
from tests.test_migration_0002 import _config
from tests.test_model_cli import gone
from tests.test_parallel import until
from tests.test_questions import OWN
from tests.test_spawn import reported, role_id, spawn

FAKE = [sys.executable, str(Path(__file__).with_name("fake_codex_app_server.py"))]


@pytest.fixture
def native_app(settings_env, tmp_path):
    opened = []
    record = tmp_path / "record.json"
    plan = tmp_path / "plan.json"

    def write_plan(script, **more):
        plan.write_text(json.dumps({"record": str(record), "script": script, **more}),
                        encoding="utf-8")

    def make(script, default_steps=(), timeout=30, **more):
        write_plan(script, **more)
        cli = CodexNativeClient(launcher=FAKE, timeout=timeout, env={"FAKE_CLI_PLAN": str(plan)})
        default = ScriptedModel(
            default_steps if isinstance(default_steps, dict) else list(default_steps), model_id="big-model")
        app = create_app(load_settings(settings_env), model=default, clients={"Codex": cli})
        client = TestClient(app, base_url="http://127.0.0.1:8790")
        client.__enter__()
        opened.append(client)
        provider = client.post("/api/providers", json={
            "name": "Codex", "kind": "codex_cli", "mode": "native"})
        assert provider.status_code == 201, provider.text
        return client, provider.json(), default

    make.rescript = write_plan
    make.record = lambda: json.loads(record.read_text(encoding="utf-8"))
    yield make
    for client in opened:
        client.__exit__(None, None, None)


@pytest.fixture
def wait_run(wait_run):
    """Every turn here starts the stand-in Codex, a Python process (2-4 s a test alone): under
    load a turn ran past the usual five seconds. A timeout given still wins."""
    return lambda client, cid, run_id, timeout=30.0: wait_run(client, cid, run_id, timeout)


def start(client, project_dir, provider, mode="full_auto", content="fix the greeting"):
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    # (and Codex is the Lead that writes here: K-48 refuses one that hands code on)
    client.patch(f"/api/conversations/{cid}",
                 json={"permission_mode": mode, "provider_id": provider["id"] if provider else None,
                       "lead_hands_code": False},
                 headers={"Origin": "http://127.0.0.1:8790"})  # a level is raised from the app's page
    run = client.post(f"/api/conversations/{cid}/messages", json={"content": content}).json()["run"]
    return cid, run["id"]


def test_what_codex_does_with_its_own_tools_is_recorded_as_its_own(
    native_app, wait_run, project_dir
):
    client, provider, default = native_app([
        {"say": "I will fix it."},
        {"write": "hello.py", "content": "print('hello')\n"}, {"pause": 0.3},
        {"run": "python hello.py", "output": "hello\n", "exit": 0}, {"pause": 0.3},
        {"write": "notes/new.txt", "content": "done\n"}, {"pause": 0.3},
        {"say": "Fixed and checked."},
    ])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)

    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert [m["content"] for m in snap["messages"][1:] if m["content"]] == [
        "I will fix it.", "Fixed and checked.",
        "In the project: hello.py and notes/new.txt: +2 −1 in all."]  # (B-205: KOLONİ's line)
    agent = snap["agents"][0]
    assert (agent["provider_name"], agent["status"]) == ("Codex", "completed")
    assert (agent["input_tokens"], agent["output_tokens"]) == (4000, 120)

    edit, run, add = snap["tool_calls"]
    assert [(t["name"], t["status"], t["origin"]) for t in snap["tool_calls"]] == [
        ("edit_file", "succeeded", "cli"), ("run_command", "succeeded", "cli"),
        ("write_file", "succeeded", "cli")]
    assert json.loads(edit["arguments"]) == {"path": "hello.py"}
    assert "exit code 0" in run["result"] and "hello" in run["result"]

    changed, created = snap["file_changes"]
    assert (changed["path"], changed["kind"], changed["status"], changed["origin"]) == (
        "hello.py", "modify", "applied", "cli")
    assert "-print('hi')" in changed["diff"] and "+print('hello')" in changed["diff"]
    assert (created["path"], created["kind"], created["origin"]) == ("notes/new.txt", "create", "cli")
    (ran,) = snap["commands"]
    assert (ran["command"], ran["status"], ran["exit_code"], ran["output"], ran["origin"]) == (
        "python hello.py", "exited", 0, "hello\n", "cli")
    assert ran["started_at"] and ran["ended_at"]
    # where its shell stood is on record only as the CLI said it: Codex's approval request
    # names its cwd (the root here, "."); one that says none (Claude Code) stays None
    assert ran["cwd"] == "."
    assert (project_dir / "hello.py").read_bytes() == b"print('hello')\n"
    assert len(default.calls) == 0

    seen = native_app.record()
    argv = seen["argv"]
    assert argv[-1] == "app-server" and "exec" not in argv
    # it asks before every command and patch, in a thread nothing is kept of
    thread = seen["thread"]
    assert (thread["approvalPolicy"], thread["sandbox"], thread["ephemeral"]) == (
        "untrusted", "workspace-write", True)
    assert Path(thread["cwd"]) == project_dir  # it works in the project
    assert Path(seen["cwd"]) == project_dir
    assert "--disable" not in argv  # its own tools are what it works with here
    # each was asked about, and allowed at Full auto
    assert [(a["method"], a["answer"]) for a in seen["answers"]] == [
        ("item/fileChange/requestApproval", {"decision": "accept"}),
        ("item/commandExecution/requestApproval", {"decision": "accept"}),
        ("item/fileChange/requestApproval", {"decision": "accept"})]
    document = json.loads(seen["stdin"][seen["stdin"].index("\n\n{") + 2:])
    assert document["conversation"] == [{"role": "user", "content": "fix the greeting"}]
    # it is told where the project is: its sandbox may start its shell somewhere else
    assert f'The project folder is "{project_dir}".' in seen["stdin"]
    assert "go there first" in seen["stdin"]


def test_a_change_codex_made_can_be_reverted(native_app, wait_run, project_dir):
    client, provider, _ = native_app([{"write": "hello.py", "content": "print('hello')\n"}])
    cid, run_id = start(client, project_dir, provider)
    change = wait_run(client, cid, run_id)["file_changes"][0]
    reverted = client.post(f"/api/file-changes/{change['id']}/revert")
    assert reverted.status_code == 200 and reverted.json()["status"] == "reverted"
    assert (project_dir / "hello.py").read_bytes() == b"print('hi')\n"


def test_native_codex_runs_below_full_auto_now_that_it_asks(native_app, wait_run, project_dir):
    # (At Ask its change is shown first: tests/test_codex_app_server_scenarios.py.)
    client, provider, _ = native_app([{"write": "hello.py", "content": "x"}])
    cid, run_id = start(client, project_dir, provider, mode="auto_edit")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert [c["status"] for c in snap["file_changes"]] == ["applied"]
    assert (project_dir / "hello.py").read_bytes() == b"x"


def test_codex_reaches_other_agents_and_the_user_through_koloni(
    native_app, wait_run, project_dir
):
    client, provider, default = native_app(
        [{"koloni": "ask_user", "args": {"question": "Strict or lenient?",
                                         "options": ["strict", "lenient"]}},
         {"koloni": "spawn_agent", "args": {"role": "Reviewer", "task": "Review hello.py"}},
         {"say": "All done."}],
        default_steps=[text("Looks fine.")])
    local = client.get("/api/providers").json()[0]
    client.patch(f"/api/roles/{role_id(client, 'Reviewer')}", json={"provider_id": local["id"]})
    cid, run_id = start(client, project_dir, provider)
    snap = wait_status(client, cid, "waiting_approval")
    question = snap["questions"][0]
    assert question["status"] == "pending" and question["agent_id"] == snap["agents"][0]["id"]
    client.post(f"/api/questions/{question['id']}/answer", json={"answer": "strict"}, headers=OWN)
    snap = wait_run(client, cid, run_id)

    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    asked, spawned = snap["tool_calls"]
    # KOLONİ's own tools are KOLONİ's records, once each
    assert [(t["name"], t["status"], t["origin"]) for t in snap["tool_calls"]] == [
        ("ask_user", "succeeded", "koloni"), ("spawn_agent", "succeeded", "koloni")]
    assert [a["provider_name"] for a in snap["agents"]] == ["Codex", "Local"]
    assert [m["kind"] for m in snap["channel_messages"]] == ["task", "report"]
    seen = native_app.record()
    # nothing else is offered
    assert seen["tools"] == [
        "spawn_agent", "create_role", "ask_user", "ask_folder", "message_agent", "discuss",
        "read_backlog", "add_task", "change_task", "assess_task", "plan_away", "post_note",
        "read_notes",
        "remember", "recall", "recall_output"]
    assert [reported(r["content"][0]["text"]) for r in seen["results"]] == [
        "The user answered: strict", "Reviewer finished.\n\nLooks fine."]


def test_other_tools_of_its_own_are_noted(native_app, wait_run, project_dir):
    client, provider, _ = native_app([
        {"mcp": {"server": "sonarqube", "tool": "scan", "arguments": {"path": "."},
                 "result": "2 issues"}},
        {"mcp": {"server": "sonarqube", "tool": "scan", "error": "token expired"}},
        {"web": "python print"},
        # (A write outside the project is asked about now, as Claude Code's is.)
        {"delete": "hello.py"},
    ])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    calls = [(t["name"], t["status"], t["origin"]) for t in snap["tool_calls"]]
    assert calls == [
        ("sonarqube__scan", "succeeded", "cli"), ("sonarqube__scan", "failed", "cli"),
        ("web_search", "succeeded", "cli"), ("delete_file", "succeeded", "cli")]
    assert "hello.py" in snap["tool_calls"][3]["result"]
    assert snap["tool_calls"][0]["result"] == "2 issues"
    assert "token expired" in snap["tool_calls"][1]["result"]
    # what KOLONİ knew the deleted file held is kept, so it can be put back
    (gone,) = snap["file_changes"]
    assert (gone["path"], gone["kind"], gone["status"], gone["origin"]) == (
        "hello.py", "delete", "applied", "cli")
    assert "-print('hi')" in gone["diff"]
    assert client.post(f"/api/file-changes/{gone['id']}/revert").json()["status"] == "reverted"
    assert (project_dir / "hello.py").read_bytes() == b"print('hi')\n"


def test_a_change_whose_earlier_content_is_not_known_has_no_diff(
    native_app, wait_run, project_dir
):
    # Dependency folders are not read when the agent starts, so what a file there held
    # before is not known; the change is still noted.
    vendored = project_dir / "node_modules" / "pkg"
    vendored.mkdir(parents=True)
    (vendored / "a.js").write_bytes(b"old\n")
    client, provider, _ = native_app([
        {"write": "node_modules/pkg/a.js", "content": "new\n", "kind": "update"},
        {"run": "pytest", "output": "1 failed\n", "exit": 1, "no_start": True}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    edit, run = snap["tool_calls"]
    assert snap["file_changes"] == [] and "is not known" in edit["result"]
    # a failing command of its own is still a command that ran
    assert (snap["commands"][0]["status"], snap["commands"][0]["exit_code"]) == ("exited", 1)
    assert run["status"] == "succeeded" and "exit code 1" in run["result"]


def test_a_secret_codexs_own_command_prints_is_hidden_in_the_record(
    native_app, wait_run, project_dir, monkeypatch
):
    monkeypatch.setenv("DEPLOY_TOKEN", "made-up-value-0123456789")
    client, provider, _ = native_app([
        {"run": "env", "output": "DEPLOY_TOKEN=made-up-value-0123456789\nHOME=/x\n"},
        {"say": "Done."}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    stored, result = snap["commands"][0]["output"], snap["tool_calls"][0]["result"]
    assert "made-up-value" not in stored + result
    assert "DEPLOY_TOKEN=***" in stored and "HOME=/x" in result


def test_stop_ends_codex_and_settles_what_it_was_doing(native_app, wait_run, project_dir):
    client, provider, _ = native_app([
        {"say": "Running the tests."}, {"run": "pytest", "hold": 120}])
    cid, run_id = start(client, project_dir, provider)
    for _ in range(300):
        snap = client.get(f"/api/conversations/{cid}").json()
        if snap["commands"] and snap["commands"][0]["status"] == "running":
            break
        time.sleep(0.02)
    pid = native_app.record()["pid"]
    client.post(f"/api/runs/{run_id}/cancel")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "cancelled"
    # (as Claude Code's: a command KOLONİ did not run itself is not known to be killed)
    assert snap["commands"][0]["status"] == "interrupted"
    assert snap["tool_calls"][0]["status"] == "interrupted"
    assert gone(pid)


def test_a_codex_failure_fails_the_turn_and_leaves_nothing_running(
    native_app, wait_run, project_dir
):
    client, provider, _ = native_app([
        {"write": "hello.py", "content": "print('hello')\n"},
        {"error": "You have hit your usage limit"}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "failed"
    assert "usage limit" in snap["runs"][0]["error"]
    assert snap["file_changes"][0]["status"] == "applied"  # what it did before failing is on record


def test_the_next_turn_hands_codex_what_it_did_before(native_app, wait_run, project_dir):
    client, provider, _ = native_app([
        {"write": "hello.py", "content": "print('hello')\n"}, {"say": "Changed."}])
    cid, run_id = start(client, project_dir, provider)
    wait_run(client, cid, run_id)
    native_app.rescript([{"say": "Nothing more to do."}])
    second = client.post(f"/api/conversations/{cid}/messages", json={"content": "and now?"}).json()
    wait_run(client, cid, second["run"]["id"])
    seen = native_app.record()["stdin"]
    conversation = json.loads(seen[seen.index("\n\n{") + 2:])["conversation"]
    # (and before the new message, KOLONİ's record of the turn (K-gecmis-zengin) and its
    # note of it: G7)
    assert [m["role"] for m in conversation] == [
        "user", "assistant", "tool", "assistant", "user", "user", "user"]
    assert conversation[-3]["content"].endswith('- files changed: "hello.py" (+1 -1)')
    assert conversation[-2]["content"].startswith(PUSHED)
    assert conversation[1]["tool_calls"][0]["function"]["name"] == "edit_file"
    assert "hello.py" in conversation[2]["content"]


def test_codex_can_be_a_sub_agent_that_works_natively(native_app, wait_run, project_dir):
    client, provider, default = native_app(
        [{"write": "hello.py", "content": "print('hello')\n"}, {"say": "Changed the greeting."}],
        default_steps=[spawn("Coder", "Change the greeting"), text("The coder did it.")])
    client.patch(f"/api/roles/{role_id(client, 'Coder')}", json={"provider_id": provider["id"]})
    cid, run_id = start(client, project_dir, None)
    snap = wait_run(client, cid, run_id)
    lead, coder = snap["agents"]
    assert (coder["provider_name"], coder["status"], coder["report"]) == (
        "Codex", "completed", "Changed the greeting.")
    assert snap["file_changes"][0]["agent_id"] == coder["id"]
    assert reported(default.calls[1][-1]["content"]) == "Coder finished.\n\nChanged the greeting."


def test_codex_may_run_natively_and_as_a_session(client):
    native = client.post("/api/providers", json={
        "name": "Codex native", "kind": "codex_cli", "mode": "native"})
    assert native.status_code == 201 and native.json()["mode"] == "native"
    assert client.post("/api/providers", json={
        "name": "Codex", "kind": "codex_cli"}).json()["mode"] == "session"  # the default
    # Since 7 Nov 2026 a session too, its patch tool declined (`CodexSessionClient`).
    assert client.post("/api/providers", json={
        "name": "C2", "kind": "codex_cli", "mode": "session"}).json()["mode"] == "session"
    # Claude Code can: it asks KOLONİ before a tool of its own needs leave. So may Qoder, over
    # the same protocol (B-306, not yet measured: `QoderNativeClient`).
    assert client.post("/api/providers", json={
        "name": "Cl", "kind": "claude_cli", "mode": "native"}).status_code == 201
    assert client.post("/api/providers", json={
        "name": "Q", "kind": "qoder_cli", "mode": "native"}).status_code == 201
    assert client.post("/api/providers", json={
        "name": "Q2", "kind": "qoder_cli", "mode": "step"}).status_code == 422


def test_migration_0007_and_back(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0006")
    command.upgrade(cfg, "head")
    with sqlite3.connect(db) as conn:
        for table in ("tool_calls", "commands", "file_changes"):
            columns = {row[1]: row[4] for row in conn.execute(f"PRAGMA table_info({table})")}
            assert "koloni" in str(columns["origin"])
    command.downgrade(cfg, "0006")
    with sqlite3.connect(db) as conn:
        assert "origin" not in [row[1] for row in conn.execute("PRAGMA table_info(commands)")]


def test_the_diff_is_against_what_the_file_held_when_the_agent_started(
    native_app, wait_run, project_dir
):
    # Codex does not wait to be watched: by the time its change is seen the file is
    # already new. The old content comes from what KOLONİ read before it started, and
    # a second change to the same file is diffed against the first.
    # (Each change must be looked at before the next write to its file: if it is not, the
    # two are one change. A busy machine took more than 0.4 s, so the pause there is long.)
    client, provider, _ = native_app([
        {"write": "hello.py", "content": "print('hello')\n"}, {"pause": 1.5},
        {"write": "hello.py", "content": "print('hello, world')\n"}, {"pause": 0.4},
        {"write": "brand_new.py", "content": "x = 1\n"}, {"pause": 1.5},
        {"write": "brand_new.py", "content": "x = 2\n"}])
    cid, run_id = start(client, project_dir, provider)
    first, second, created, edited = wait_run(client, cid, run_id)["file_changes"]
    assert "-print('hi')" in first["diff"] and "+print('hello')" in first["diff"]
    assert "-print('hello')" in second["diff"] and "+print('hello, world')" in second["diff"]
    assert (created["kind"], edited["kind"]) == ("create", "modify")
    assert "-x = 1" in edited["diff"]


def test_two_changes_seen_as_one_are_not_recorded_twice(native_app, wait_run, project_dir):
    # Written back to back, the first change is already overwritten when it is seen.
    # The records then show the whole difference once, not a second, empty change.
    client, provider, _ = native_app([
        {"write": "hello.py", "content": "print('a')\n"},
        {"write": "hello.py", "content": "print('b')\n"}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    changes = snap["file_changes"]
    assert changes[-1]["diff"].endswith("+print('b')")
    assert all(change["additions"] + change["deletions"] > 0 for change in changes)
    assert len(snap["tool_calls"]) == 2


def test_files_a_command_changed_are_seen_even_though_codex_does_not_say_so(
    native_app, wait_run, project_dir
):
    # Codex often edits with a shell command instead of its patch tool; its event
    # stream then says only that a command ran.
    (project_dir / "old.txt").write_bytes(b"x\n")
    client, provider, _ = native_app([
        {"run": "sed -i s/hi/hello/ hello.py", "output": "", "exit": 0,
         "touches": {"hello.py": "print('hello')\n", "made.txt": "new\n"},
         "removes": ["old.txt"]},
        {"say": "Done."}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    changes = {c["path"]: c for c in snap["file_changes"]}
    assert set(changes) == {"hello.py", "made.txt", "old.txt"}
    assert changes["old.txt"]["kind"] == "delete"  # what it held is kept
    assert "-print('hi')" in changes["hello.py"]["diff"]
    assert (changes["made.txt"]["kind"], changes["made.txt"]["origin"]) == ("create", "cli")
    names = [(t["name"], json.loads(t["arguments"]).get("path")) for t in snap["tool_calls"][1:]]
    assert sorted(names, key=str) == [("delete_file", "old.txt"), ("edit_file", "hello.py"),
                                      ("write_file", "made.txt")]
    assert "a command the CLI ran" in snap["tool_calls"][1]["result"]


def test_what_was_changed_just_before_a_stop_is_still_on_record(
    native_app, wait_run, project_dir
):
    client, provider, _ = native_app([
        {"run": "long job", "hold": 120, "no_start": False}], )
    cid, run_id = start(client, project_dir, provider)
    for _ in range(300):
        snap = client.get(f"/api/conversations/{cid}").json()
        if snap["commands"] and snap["commands"][0]["status"] == "running":
            break
        time.sleep(0.02)
    (project_dir / "hello.py").write_bytes(b"print('half done')\n")  # the command's doing
    client.post(f"/api/runs/{run_id}/cancel")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "cancelled"
    assert [c["path"] for c in snap["file_changes"]] == ["hello.py"]


def test_a_native_commands_first_event_is_a_whole_command(native_app, wait_run, project_dir):
    # A client builds its command row from this event; one without an output field
    # broke the page.
    client, provider, _ = native_app([{"run": "pytest", "output": "ok\n", "exit": 0}])
    cid, run_id = start(client, project_dir, provider)
    wait_run(client, cid, run_id)
    with client.stream("GET", f"/api/conversations/{cid}/events?after=0&once=1") as r:
        frames = r.read().decode().split("\n\n")
    created = [json.loads(f.split("data: ", 1)[1]) for f in frames if "event: command.created" in f]
    assert len(created) == 1 and created[0]["output"] == "" and created[0]["origin"] == "cli"


# --- review fixes -----------------------------------------------------------------


def test_a_role_that_may_not_write_or_run_works_on_native_codex_read_only(
    native_app, wait_run, project_dir
):
    # Natively the CLI writes files and runs commands whatever KOLONİ offers it, so until
    # B-301 only a role allowed both could work that way. Now Codex is started read-only for
    # it, and what it asks to write is refused.
    client, provider, default = native_app(
        [{"write": "hello.py", "content": "print('rewritten')\n"}],
        default_steps=[spawn("Reviewer", "Review hello.py"), text("carrying on")])
    client.patch(f"/api/roles/{role_id(client, 'Reviewer')}", json={"provider_id": provider["id"]})
    cid, run_id = start(client, project_dir, None)
    snap = wait_run(client, cid, run_id)
    reviewer = snap["agents"][1]
    assert reviewer["status"] == "completed", reviewer["error"]
    assert native_app.record()["thread"]["sandbox"] == "read-only"
    assert (project_dir / "hello.py").read_bytes() == b"print('hi')\n"  # refused
    assert snap["file_changes"] == [] and snap["runs"][0]["status"] == "completed"


def test_the_first_files_of_an_empty_project_are_recorded(native_app, wait_run, tmp_path):
    empty = tmp_path / "empty"
    (empty / "node_modules").mkdir(parents=True)
    client, provider, _ = native_app([
        {"write": "app.py", "content": "print(1)\n"}, {"pause": 0.3},
        {"run": "touch", "touches": {"b.py": "x = 1\n"}}])
    cid, run_id = start(client, empty, provider)
    snap = wait_run(client, cid, run_id)
    assert [(c["path"], c["kind"]) for c in snap["file_changes"]] == [
        ("app.py", "create"), ("b.py", "create")]
    assert all("already shown" not in (t["result"] or "") for t in snap["tool_calls"])


def test_what_a_sub_agent_changed_is_not_also_put_down_to_the_native_agent(
    native_app, wait_run, project_dir
):
    from tests.test_spawn import call, step

    client, provider, default = native_app(
        [{"koloni": "spawn_agent", "args": {"role": "Coder", "task": "make a file"}},
         {"pause": 0.3}, {"run": "pytest", "output": "ok\n"}, {"say": "Done."}],
        default_steps=[step(call("write_file", {"path": "made.txt", "content": "new\n"})),
                       text("made it")],
        # (its sub-agent's report, read in a run after its turn: K-paralel-spawn)
        later_script=[{"say": "Done."}], later_when="Message from Coder")
    local = client.get("/api/providers").json()[0]
    client.patch(f"/api/roles/{role_id(client, 'Coder')}", json={"provider_id": local["id"]})
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    lead, coder = snap["agents"]
    assert [(c["path"], c["origin"], c["agent_id"]) for c in snap["file_changes"]] == [
        ("made.txt", "koloni", coder["id"])]


def test_a_command_without_a_start_event_does_not_upset_the_silence_clock(
    native_app, wait_run, project_dir
):
    client, provider, _ = native_app([
        {"run": "quick", "output": "", "no_start": True},
        {"run": "slow tests", "output": "ok\n", "hold": 5}, {"say": "Done."}], timeout=2)
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id, timeout=30)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert [c["status"] for c in snap["commands"]] == ["exited", "exited"]


def test_the_level_can_be_lowered_under_native_codex_at_work_now_that_it_asks(
    native_app, wait_run, project_dir
):
    client, provider, _ = native_app([{"run": "long job", "hold": 2}])
    cid, run_id = start(client, project_dir, provider)
    for _ in range(300):
        if client.get(f"/api/conversations/{cid}").json()["commands"]:
            break
        time.sleep(0.02)
    lowered = client.patch(f"/api/conversations/{cid}", json={"permission_mode": "ask"})
    assert lowered.status_code == 200, lowered.text
    assert wait_run(client, cid, run_id, timeout=30)["runs"][0]["status"] == "completed"


def test_many_files_changed_at_once_are_kept_in_bounds(native_app, wait_run, project_dir):
    touched = {f"gen/f{n:03}.txt": f"{n}\n" for n in range(260)}
    client, provider, _ = native_app([{"run": "generate", "touches": touched}, {"say": "Done."}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id, timeout=60)
    assert len(snap["file_changes"]) == 200
    overflow = [t for t in snap["tool_calls"] if "more files changed" in (t["result"] or "")]
    assert len(overflow) == 1 and "60 more files changed" in overflow[0]["result"]
    # one look is one step in the transcript, not hundreds of empty messages
    assert len(snap["messages"]) <= 6


def test_a_relative_path_in_an_event_is_taken_from_the_project(native_app, wait_run, project_dir):
    client, provider, _ = native_app([
        {"write": "hello.py", "content": "print('hello')\n", "relative": True}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert [c["path"] for c in snap["file_changes"]] == ["hello.py"]
    assert all("outside the project" not in (t["result"] or "") for t in snap["tool_calls"])


def test_two_messages_in_a_row_are_kept_apart(native_app, wait_run, project_dir):
    client, provider, _ = native_app([{"say": "First thought."}, {"say": "Second thought."}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert snap["messages"][-1]["content"] == "First thought.\n\nSecond thought."


def test_codex_is_asked_to_wait_for_kolonis_tools_and_to_keep_them_on(
    native_app, wait_run, project_dir
):
    client, provider, _ = native_app([{"say": "hi"}])
    cid, run_id = start(client, project_dir, provider)
    wait_run(client, cid, run_id)
    argv = native_app.record()["argv"]
    settings = [argv[i + 1] for i, a in enumerate(argv) if a == "-c"]
    assert "mcp_servers.koloni.enabled=true" in settings
    waits = [s for s in settings if s.startswith("mcp_servers.koloni.tool_timeout_sec=")]
    assert waits and int(waits[0].split("=")[1]) >= 3600  # an answer or a sub-agent takes time


def test_the_project_view_does_not_leave_the_project(tmp_path):
    from app.project_view import ProjectView

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_bytes(b"s1\n")
    root = tmp_path / "proj"
    root.mkdir()
    (root / "a.txt").write_bytes(b"a\n")
    try:
        if sys.platform == "win32":
            import _winapi

            _winapi.CreateJunction(str(outside), str(root / "link"))
        else:
            (root / "link").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("links cannot be made here")
    view = ProjectView(root)
    assert view.covers("a.txt") and not view.covers("link/secret.txt")
    (outside / "secret.txt").write_bytes(b"changed\n")
    (root / "a.txt").write_bytes(b"a2\n")
    assert [c[0] for c in view.changes()] == ["a.txt"]


def test_the_project_view_reports_from_its_second_look_on(tmp_path):
    from app.project_view import ProjectView

    view = ProjectView(tmp_path)  # nothing there yet
    (tmp_path / "new.py").write_bytes(b"x\n")
    assert view.changes() == [("new.py", None, "x\n")]
    assert view.changes() == []
    (tmp_path / "new.py").unlink()
    assert view.changes() == [("new.py", "x\n", None)]


def test_a_file_koloni_may_not_read_is_named_not_passed_over(
    native_app, wait_run, project_dir, monkeypatch
):
    # Codex's sandbox on Windows can create files the user's own account cannot open.
    from app import project_view

    real = project_view.ProjectView._read

    def locked(self, path, size):
        if path.name == "locked.txt":
            raise PermissionError(13, "Access is denied")
        return real(self, path, size)

    monkeypatch.setattr(project_view.ProjectView, "_read", locked)
    client, provider, _ = native_app([
        {"run": "make", "touches": {"locked.txt": "x\n", "open.txt": "y\n"}}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert [c["path"] for c in snap["file_changes"]] == ["open.txt"]
    noted = [t["result"] for t in snap["tool_calls"] if "locked.txt" in t["arguments"]]
    assert len(noted) == 1 and "not allowed to read it" in noted[0]


# --- agents talking (slice 8) ---------------------------------------------------


def test_native_codex_messages_a_sub_agent(native_app, wait_run, project_dir):
    client, provider, default = native_app(
        [{"koloni": "spawn_agent", "args": {"role": "Reviewer", "task": "Review hello.py"}},
         {"koloni": "message_agent", "args": {"to": "Reviewer", "message": "And the tests?"}},
         {"say": "All done."}],
        default_steps=[text("Looks fine."), text("There are none.")])
    local = client.get("/api/providers").json()[0]
    client.patch(f"/api/roles/{role_id(client, 'Reviewer')}", json={"provider_id": local["id"]})
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert [reported(r["content"][0]["text"]) for r in native_app.record()["results"]] == [
        "Reviewer finished.\n\nLooks fine.", "Reviewer replied:\n\nThere are none."]
    assert [(t["name"], t["origin"]) for t in snap["tool_calls"]] == [
        ("spawn_agent", "koloni"), ("message_agent", "koloni")]


def test_a_native_child_is_continued_by_its_parent_and_never_asked_to_answer(
    native_app, wait_run, project_dir
):
    from tests.test_spawn import call, step

    def message(to, id):
        return step(call("message_agent", {"to": to, "message": "Anything else?"}, id))

    client, provider, default = native_app(
        [{"write": "hello.py", "content": "print('hello')\n"}, {"say": "Changed the greeting."}],
        default_steps=[
            spawn("Coder", "Change the greeting", id="s1"),
            message("Coder", "m1"),            # its parent: Codex works on
            spawn("Reviewer", "Review it", id="s2"),
            message("Coder", "m2"),            # the Reviewer: Codex cannot be held to reading
            text("reviewed"),
            text("done"),
        ])
    local = client.get("/api/providers").json()[0]
    client.patch(f"/api/roles/{role_id(client, 'Coder')}", json={"provider_id": provider["id"]})
    client.patch(f"/api/roles/{role_id(client, 'Reviewer')}", json={"provider_id": local["id"]})
    cid, run_id = start(client, project_dir, None)
    snap = wait_run(client, cid, run_id, timeout=30)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    first, second = [t for t in snap["tool_calls"] if t["name"] == "message_agent"]
    assert (first["status"], first["result"]) == (
        "succeeded", "Coder replied:\n\nChanged the greeting.")
    assert second["status"] == "failed"
    assert "Coder cannot be messaged by you" in second["result"]
    assert "tools of its own" in second["result"]
    assert "Message from Lead (the agent you work for)" in native_app.record()["stdin"]
    # the Reviewer is not told it could reach the Coder
    offered = next(t["function"] for t in default.tool_args[3]
                   if t["function"]["name"] == "message_agent")
    assert "- Coder" not in offered["description"] and "- Lead" in offered["description"]


# --- agents at the same time (slice 9) --------------------------------------------


def _roles_on(client, provider, *roles):
    for role in roles:
        client.patch(f"/api/roles/{role_id(client, role)}", json={"provider_id": provider["id"]})


def _names(snap):
    return {a["name"]: a["status"] for a in snap["agents"]}


def _runs_of(path):
    """What the stand-in Codex logged of its runs (`runs`): "start" and "end", in order."""
    return [line.split()[0] for line in path.read_text().splitlines()] if path.exists() else []


def test_a_siblings_write_is_not_put_down_to_the_native_agent(
    native_app, wait_run, project_dir, gate
):
    from tests.test_spawn import call, step

    client, provider, default = native_app(
        [{"pause": 1.5}, {"say": "Nothing to change."}],
        default_steps={
            "Lead": [step(
                call("spawn_agent", {"role": "Coder", "task": "look around"}, "s1"),
                call("spawn_agent", {"role": "Writer", "task": "make a file"}, "s2"),
            ), text("done")],
            "Writer": [gate.step(step(call("write_file", {"path": "made.txt", "content": "new\n"}))),
                       text("made it")],
        })
    local = client.get("/api/providers").json()[0]
    made = client.post("/api/roles", json={
        "name": "Writer", "description": "", "instructions": "",
        "tools": ["read_file", "write_file"], "provider_id": local["id"]})
    assert made.status_code == 201, made.text
    _roles_on(client, provider, "Coder")
    cid, run_id = start(client, project_dir, None)
    gate.wait_partial()
    for _ in range(300):  # Codex is at work and has looked at the project
        if _names(client.get(f"/api/conversations/{cid}").json()).get("Coder") == "running":
            break
        time.sleep(0.02)
    time.sleep(0.5)
    gate.release()
    snap = wait_run(client, cid, run_id, timeout=30)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    by = {a["id"]: a["name"] for a in snap["agents"]}
    assert [(c["path"], c["origin"], by[c["agent_id"]]) for c in snap["file_changes"]] == [
        ("made.txt", "koloni", "Writer")]


def test_two_native_agents_each_in_a_copy_of_its_own_work_at_once(
    native_app, wait_run, project_dir, tmp_path
):
    from tests.test_spawn import call, step

    go, runs = tmp_path / "go", tmp_path / "runs.log"
    client, provider, default = native_app(
        [{"wait_for": str(go)}, {"say": "Done."}],
        default_steps={"Lead": [step(
            call("spawn_agent", {"role": "Coder", "task": "A"}, "s1"),
            call("spawn_agent", {"role": "Coder", "task": "B"}, "s2"),
        ), text("done")]}, runs=str(runs))
    _roles_on(client, provider, "Coder")
    cid, run_id = start(client, project_dir, None)
    # B-199: told apart by their copies, both CLIs are started before either may end.
    until(client, cid, lambda s: _runs_of(runs).count("start") == 2, timeout=20)
    go.write_text("")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]


def test_a_codex_leads_two_spawns_on_codex_work_at_the_same_time(
    native_app, wait_run, project_dir, tmp_path
):
    # B-199 (live, 29 Oct): a Codex Lead's Coders on Codex ran one after another, each call
    # lasting till its Coder was done. The stand-in calls KOLONİ's tools one after another.
    go = tmp_path / "go"
    client, provider, _default = native_app(
        [{"koloni": "spawn_agent", "args": {"role": "Coder", "task": "task-1"}},
         {"koloni": "spawn_agent", "args": {"role": "Coder", "task": "task-2"}},
         {"say": "Both at work."}],
        task_scripts={f"task-{n}": [{"wait_for": str(go)}, {"say": f"kid-{n} done"}]
                      for n in (1, 2)},
        later_script=[{"say": "Both done."}], later_when="Message from Coder")
    _roles_on(client, provider, "Coder")
    cid, run_id = start(client, project_dir, provider)
    until(client, cid, lambda s: _names(s) == {
        "Lead": "waiting", "Coder": "running", "Coder 2": "running"}, timeout=20)
    go.write_text("")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    coder, other = (next(x for x in snap["agents"] if x["name"] == n) for n in ("Coder", "Coder 2"))
    assert other["started_at"] < coder["ended_at"] and coder["started_at"] < other["ended_at"]
    assert snap["messages"][-1]["content"] == "Both done."


def test_a_third_codex_coder_waits_in_line_at_the_chats_two(
    native_app, wait_run, project_dir, tmp_path
):
    go = tmp_path / "go"
    client, provider, _default = native_app(
        [*({"koloni": "spawn_agent", "args": {"role": "Coder", "task": f"task-{n}"}}
           for n in (1, 2, 3)), {"say": "All at work."}],
        task_scripts={f"task-{n}": [{"wait_for": str(go)}, {"say": f"kid-{n} done"}]
                      for n in (1, 2, 3)},
        later_script=[{"say": "All done."}], later_when="Message from Coder")
    _roles_on(client, provider, "Coder")
    cid, run_id = start(client, project_dir, provider)
    until(client, cid, lambda s: _names(s) == {
        "Lead": "waiting", "Coder": "running", "Coder 2": "running", "Coder 3": "queued"},
        timeout=20)
    go.write_text("")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert set(_names(snap).values()) == {"completed"}


def test_two_native_agents_whose_copies_cannot_be_made_take_turns(
    native_app, wait_run, project_dir, monkeypatch
):
    # Both in the project, as where no copy is made: one native agent at a time there.
    from tests.test_spawn import call, step

    monkeypatch.setattr(copies, "MAX_FILES", 0)
    runs = project_dir.parent / "runs.log"
    client, provider, default = native_app(
        [{"pause": 0.8}, {"say": "Done."}],
        default_steps={"Lead": [step(
            call("spawn_agent", {"role": "Coder", "task": "A"}, "s1"),
            call("spawn_agent", {"role": "Coder", "task": "B"}, "s2"),
        ), text("done")]}, runs=str(runs))
    _roles_on(client, provider, "Coder")
    cid, run_id = start(client, project_dir, None)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert {(a["copy"] or {}).get("state") for a in snap["agents"][1:]} == {"too_big"}
    # (The stand-in writes its "end" as it exits, which may come a moment after the run is over.)
    for _ in range(250):
        if len(_runs_of(runs)) >= 4:
            break
        time.sleep(0.02)
    logged = [line.split() for line in runs.read_text(encoding="utf-8").splitlines()]
    assert [what for what, _pid, _at in sorted(logged, key=lambda one: float(one[2]))] == [
        "start", "end", "start", "end"]


def test_a_codex_lead_waits_for_a_codex_coder_whose_copy_cannot_be_made(
    native_app, wait_run, project_dir, tmp_path, monkeypatch
):
    # B-199 review: in the chat's place, it could not start while its Lead's CLI held it.
    monkeypatch.setattr(copies, "MAX_FILES", 0)
    runs = tmp_path / "runs.log"
    client, provider, _default = native_app(
        [{"koloni": "spawn_agent", "args": {"role": "Coder", "task": "task-1"}},
         {"say": "Done."}],
        task_scripts={"task-1": [{"say": "kid done"}]}, runs=str(runs))
    _roles_on(client, provider, "Coder")
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    (spawned,) = [t["result"] for t in snap["tool_calls"] if t["name"] == "spawn_agent"]
    assert spawned.startswith("Coder finished.")
    assert _runs_of(runs).count("start") == 2  # no run more of the Lead's: it waited


def test_a_codex_leads_own_command_is_not_put_down_to_its_coder_at_work_beside_it(
    native_app, wait_run, project_dir, tmp_path
):
    go, lead_go, runs = tmp_path / "go", tmp_path / "lead-go", tmp_path / "runs.log"
    client, provider, _default = native_app(
        [{"koloni": "spawn_agent", "args": {"role": "Coder", "task": "task-1"}},
         {"wait_for": str(lead_go)}, {"run": "make", "touches": {"lead.txt": "x\n"}},
         {"say": "Made it."}],
        task_scripts={"task-1": [{"wait_for": str(go)}, {"say": "kid done"}]},
        later_script=[{"say": "Read it."}], later_when="Message from Coder", runs=str(runs))
    _roles_on(client, provider, "Coder")
    cid, run_id = start(client, project_dir, provider)
    until(client, cid, lambda s: _runs_of(runs).count("start") == 2, timeout=20)
    lead_go.write_text("")  # the Lead's command, once the Coder is at work in its copy
    until(client, cid, lambda s: any(c["path"] == "lead.txt" for c in s["file_changes"]),
          timeout=20)
    go.write_text("")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    by = {a["id"]: a["name"] for a in snap["agents"]}
    assert [by[c["agent_id"]] for c in snap["file_changes"] if c["path"] == "lead.txt"] == [
        "Lead"]


def test_a_native_agent_cannot_be_left_a_note(native_app, wait_run, project_dir, gate):
    from tests.test_spawn import call, step

    client, provider, default = native_app(
        [{"pause": 1.5}, {"say": "Done."}],
        default_steps={
            "Lead": [step(
                call("spawn_agent", {"role": "Coder", "task": "A"}, "s1"),
                call("spawn_agent", {"role": "Reviewer", "task": "B"}, "s2"),
            ), text("done")],
            "Reviewer": [
                step(call("message_agent", {"to": "Coder", "message": "careful"}, "n")),
                text("reviewed")],
        })
    local = client.get("/api/providers").json()[0]
    _roles_on(client, provider, "Coder")
    _roles_on(client, local, "Reviewer")
    cid, run_id = start(client, project_dir, None)
    snap = wait_run(client, cid, run_id, timeout=30)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    left = next(t for t in snap["tool_calls"] if t["name"] == "message_agent")
    assert left["status"] == "failed" and "tools of its own" in left["result"]
    assert not [m for m in snap["messages"] if m["role"] == "agent"]


def test_a_native_agent_can_open_a_native_sub_agent(native_app, wait_run, project_dir, tmp_path):
    # Every agent here is Codex with the same script: each opens a Coder until the depth
    # limit says no. The Coder works in a copy of its own: the Lead's call is answered
    # "started" and the report read in one more run (B-199). Coder 2 shares the Coder's copy:
    # one native agent works at a time there, so the Coder's call waits for the report.
    runs = tmp_path / "runs.log"
    client, provider, default = native_app(
        [{"koloni": "spawn_agent", "args": {"role": "Coder", "task": "go deeper"}},
         {"say": "Done."}], runs=str(runs),
        later_script=[{"say": "Read it."}], later_when="Message from Coder")
    client.patch(f"/api/roles/{role_id(client, 'Coder')}", json={"provider_id": None})
    # (B-385: its sub-agents run on its CLI, which the user opens to agents)
    assert client.patch(f"/api/providers/{provider['id']}", json={"for_agents": True},
                        headers={"Origin": "http://127.0.0.1:8790"}).status_code == 200
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id, timeout=40)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert _names(snap) == {"Lead": "completed", "Coder": "completed", "Coder 2": "completed"}
    assert all(a["provider_name"] == "Codex" for a in snap["agents"])
    # One run of the CLI each, and one more of the Lead's alone to read its Coder's report.
    assert [line.split()[0] for line in runs.read_text().splitlines()].count("start") == 4
    spawned = [t["result"] for t in snap["tool_calls"] if t["name"] == "spawn_agent"]
    assert any(one.startswith("Coder 2 finished.") for one in spawned), spawned
    assert snap["messages"][-1]["content"] == "Read it."


def test_what_a_sub_agents_command_made_is_not_put_down_to_its_native_parent(
    native_app, wait_run, project_dir
):
    from tests.test_spawn import call, step

    client, provider, default = native_app(
        [{"koloni": "spawn_agent", "args": {"role": "Coder", "task": "make files"}},
         {"say": "Done."}],
        default_steps=[
            step(call("run_command", {"command": "echo x > side.txt"}, "c")),
            step(call("write_file", {"path": "made.txt", "content": "new\n"}, "w")),
            text("made them")])
    local = client.get("/api/providers").json()[0]
    _roles_on(client, local, "Coder")
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id, timeout=30)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert (project_dir / "side.txt").exists()
    by = {a["id"]: a["name"] for a in snap["agents"]}
    # Both are the Coder's, taken in from its copy. side.txt has a diff since B-324: `>` in
    # Windows PowerShell wrote UTF-16, taken in whole with no diff and so with no record.
    assert [(c["path"], c["origin"], by[c["agent_id"]]) for c in snap["file_changes"]] == [
        ("made.txt", "koloni", "Coder"), ("side.txt", "koloni", "Coder")]


def test_what_koloni_wrote_for_another_agent_is_no_native_change_however_the_look_met_it(
    tmp_path
):
    # (A Linux runner: the Lead's last look read the project while its Coder's files were
    # being taken in, and put made.txt down to the Lead.)
    import asyncio
    from functools import partial

    from app.agent.observe_mixin import ObserveMixin

    async def nothing(*_args):
        pass

    runner = SimpleNamespace(_wrote_for={}, _native_in={}, seen_in_project=nothing, _watches={})
    runner._still_wrote_for = partial(ObserveMixin._still_wrote_for, runner)
    looks = partial(ObserveMixin._native_looks, runner)
    (tmp_path / "made.txt").write_bytes(b"new\n")
    ctx = SimpleNamespace(folder=str(tmp_path), root=str(tmp_path), model=None, tools=[])
    took = {"made.txt", "gone.txt"}
    found = [("made.txt", None, "new\n"), ("gone.txt", "old\n", None)]

    def recorded():
        return ObserveMixin._record_found(runner, ctx, None, list(found), "changed by the CLI")

    asyncio.run(ObserveMixin._seen_by_watchers(runner, ctx, took))
    assert runner._wrote_for == {}  # no native agent looks there: nothing to keep
    looks(ctx.root, 1)
    asyncio.run(ObserveMixin._seen_by_watchers(runner, ctx, took))
    assert recorded() == set()
    # Once it holds anything else, it is no longer KOLONİ's write.
    here = str(tmp_path.resolve())
    assert not runner._still_wrote_for(here, ("made.txt", "new\n", "mine\n"))
    assert list(runner._wrote_for) == [(here, "gone.txt")]
    # Its last look had, nothing of it is held over to a later turn: there a native agent
    # that removes gone.txt (the user made it again meanwhile) is on record for it.
    looks(ctx.root, -1)
    assert runner._wrote_for == {} and runner._native_in == {}
    looks(ctx.root, 1)
    assert not runner._still_wrote_for(here, ("gone.txt", "again\n", None))


# --- discussions (slice 10) ---------------------------------------------------------


def test_native_codex_speaks_in_a_discussion_step_by_step_and_then_works_natively_again(
    settings_env, tmp_path, wait_run, project_dir
):
    """In a discussion Codex is run one step at a time with its own tools off; told to
    carry on afterwards, it is the native CLI again."""
    from tests.test_model_cli import FAKE as STEP_FAKE
    from tests.test_spawn import call, step

    native_plan, record = tmp_path / "native.json", tmp_path / "record.json"
    native_plan.write_text(json.dumps({"record": str(record), "script": [
        {"write": "hello.py", "content": "print('hello')\n"}, {"say": "Changed it."}]}),
        encoding="utf-8")
    step_plan, step_record = tmp_path / "step.json", tmp_path / "step_record.json"
    step_plan.write_text(json.dumps({
        "record": str(step_record), "answer": {"text": "I would keep hi.", "tool_calls": []},
    }), encoding="utf-8")

    class Both(CodexNativeClient):
        def talker(self):
            from app.model_cli import CodexCliClient

            return CodexCliClient(launcher=STEP_FAKE, timeout=30,
                                  env={"FAKE_CLI_PLAN": str(step_plan)})

    cli = Both(launcher=FAKE, timeout=30, env={"FAKE_CLI_PLAN": str(native_plan)})
    default = ScriptedModel({"Lead": [
        spawn("Coder", "Change the greeting"),
        step(call("discuss", {"topic": "hi or hello?", "with": ["Coder"], "rounds": 1}, "d")),
        text("hello."),
        step(call("message_agent", {"to": "Coder", "message": "Keep hello."}, "m")),
        text("done")]}, model_id="big-model")
    app = create_app(load_settings(settings_env), model=default, clients={"Codex": cli})
    with TestClient(app, base_url="http://127.0.0.1:8790") as client:
        provider = client.post("/api/providers", json={
            "name": "Codex", "kind": "codex_cli", "mode": "native"}).json()
        client.patch(f"/api/roles/{role_id(client, 'Coder')}", json={"provider_id": provider["id"]})
        cid, run_id = start(client, project_dir, None)
        snap = wait_run(client, cid, run_id, timeout=40)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert [(p["content"], p["kind"]) for p in snap["discussion_posts"]] == [
        ("I would keep hi.", "said"), ("hello.", "said")]
    asked = json.loads(step_record.read_text(encoding="utf-8"))
    assert "--sandbox" in asked["argv"] and "read-only" in asked["argv"]  # its tools were off
    assert "You are in a discussion with Lead" in asked["stdin"]
    sent = next(t for t in snap["tool_calls"] if t["name"] == "message_agent")
    assert (sent["status"], sent["result"]) == ("succeeded", "Coder replied:\n\nChanged it.")


def test_native_codex_opens_a_discussion_and_speaks_in_it(
    settings_env, tmp_path, wait_run, project_dir
):
    """Codex at work with its own tools asks KOLONİ for a discussion. It waits in that
    call; its own turn to speak is taken one step at a time with its tools off; then the
    call returns what was said and it works on."""
    from tests.test_model_cli import FAKE as STEP_FAKE

    native_plan, record = tmp_path / "native.json", tmp_path / "record.json"
    native_plan.write_text(json.dumps({"record": str(record), "script": [
        {"koloni": "spawn_agent", "args": {"role": "Reviewer", "task": "Review hello.py"}},
        {"koloni": "discuss",
         "args": {"topic": "hi or hello?", "with": ["Reviewer"], "rounds": 1}},
        {"write": "hello.py", "content": "print('hello')\n"},
        {"say": "We agreed on hello."}]}), encoding="utf-8")
    step_plan, step_record = tmp_path / "step.json", tmp_path / "step_record.json"
    step_plan.write_text(json.dumps({
        "record": str(step_record), "answer": {"text": "Then hello it is.", "tool_calls": []},
    }), encoding="utf-8")

    class Both(CodexNativeClient):
        def talker(self):
            from app.model_cli import CodexCliClient

            return CodexCliClient(launcher=STEP_FAKE, timeout=30,
                                  env={"FAKE_CLI_PLAN": str(step_plan)})

    cli = Both(launcher=FAKE, timeout=30, env={"FAKE_CLI_PLAN": str(native_plan)})
    default = ScriptedModel(
        {"Reviewer": [text("Looks fine."), text("I would say hello.")]}, model_id="big-model")
    app = create_app(load_settings(settings_env), model=default, clients={"Codex": cli})
    with TestClient(app, base_url="http://127.0.0.1:8790") as client:
        provider = client.post("/api/providers", json={
            "name": "Codex", "kind": "codex_cli", "mode": "native"}).json()
        local = next(p for p in client.get("/api/providers").json() if p["name"] != "Codex")
        client.patch(f"/api/roles/{role_id(client, 'Reviewer')}",
                     json={"provider_id": local["id"]})
        cid, run_id = start(client, project_dir, provider)
        snap = wait_run(client, cid, run_id, timeout=40)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert [(t["name"], t["status"], t["origin"]) for t in snap["tool_calls"]
            if t["origin"] == "koloni"] == [
        ("spawn_agent", "succeeded", "koloni"), ("discuss", "succeeded", "koloni")]
    (talk,) = snap["discussions"]
    lead, reviewer = snap["agents"]
    assert (talk["status"], talk["topic"], talk["agent_id"]) == (
        "ended", "hi or hello?", lead["id"])
    assert [(p["agent_id"], p["content"], p["kind"]) for p in snap["discussion_posts"]] == [
        (reviewer["id"], "I would say hello.", "said"),
        (lead["id"], "Then hello it is.", "said")]
    # its turn to speak was not the native CLI: one step, its own tools off
    spoke = json.loads(step_record.read_text(encoding="utf-8"))
    assert "--sandbox" in spoke["argv"] and "read-only" in spoke["argv"]
    assert "You are in a discussion with Reviewer" in spoke["stdin"]
    # the native CLI was started once, got back what was said, and worked on
    seen = json.loads(record.read_text(encoding="utf-8"))
    finished, said = [r["content"][0]["text"] for r in seen["results"]]
    assert reported(finished) == "Reviewer finished.\n\nLooks fine."
    assert "I would say hello." in said and "Then hello it is." in said
    assert (project_dir / "hello.py").read_text() == "print('hello')\n"
    assert lead["status"] == "completed"


def _note_for_codex(native_app, project_dir, script, gate):
    """The Coder is Codex at work with its own tools; the Reviewer writes on the notebook
    once Codex has started. Returns the client and the turn."""
    from tests.test_spawn import call, step

    client, provider, default = native_app(
        script,
        default_steps={
            "Lead": [step(
                call("spawn_agent", {"role": "Coder", "task": "A"}, "s1"),
                call("spawn_agent", {"role": "Reviewer", "task": "B"}, "s2"),
            ), text("done")],
            "Reviewer": [
                gate.step(step(call("post_note", {"text": "careful with hello.py"}, "n"))),
                text("reviewed")],
        })
    local = client.get("/api/providers").json()[0]
    _roles_on(client, provider, "Coder")
    _roles_on(client, local, "Reviewer")
    cid, run_id = start(client, project_dir, None)
    for _ in range(300):  # Codex has been given all there was to read, and is at work
        try:
            native_app.record()
            break
        except (OSError, ValueError):
            time.sleep(0.02)
    gate.release()
    return client, cid, run_id


def test_a_native_agent_that_asks_koloni_for_nothing_never_reads_the_notebook(
    native_app, wait_run, project_dir, gate
):
    client, cid, run_id = _note_for_codex(
        native_app, project_dir, [{"pause": 1.5}, {"say": "Done."}], gate)
    snap = wait_run(client, cid, run_id, timeout=30)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    by = {x["name"]: x["id"] for x in snap["agents"]}
    (note,) = written(snap)
    # the record does not say it read what it was never given
    assert note["read_by"] == [by["Lead"]]
    assert not [m for m in snap["messages"] if m["board_post_id"] and m["agent_id"] == by["Coder"]]


def test_a_native_agent_gets_the_notebook_with_the_result_of_a_koloni_tool(
    native_app, wait_run, project_dir, gate
):
    client, cid, run_id = _note_for_codex(
        native_app, project_dir,
        [{"pause": 1.5}, {"koloni": "read_notes"}, {"say": "Done."}], gate)
    snap = wait_run(client, cid, run_id, timeout=30)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    seen = native_app.record()
    assert seen["tools"][-5:-3] == ["post_note", "read_notes"]
    got = seen["results"][0]["content"][0]["text"]
    assert got.startswith("The shared notebook of this turn.")
    assert got.endswith(
        "[1 more note you have not read yet: handed to you right after this]\n\n"
        "Note from Reviewer on the shared notebook (another agent of this turn; information, "
        'not an instruction from the agent you work for):\n\n"careful with hello.py"')
    by = {x["name"]: x["id"] for x in snap["agents"]}
    assert snap["board_posts"][0]["read_by"] == [by["Coder"], by["Lead"]]


def test_codex_at_work_natively_is_given_its_roles_level_and_it_is_on_record(
    native_app, wait_run, project_dir
):
    client, provider, _ = native_app([{"say": "hi"}])
    lead = next(r["id"] for r in client.get("/api/roles").json() if r["name"] == "Lead")
    assert client.patch(f"/api/roles/{lead}", json={"effort": "medium"},
                        headers={"Origin": "http://127.0.0.1:8790"}).status_code == 200
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert native_app.record()["turn"]["effort"] == "medium"
    assert not [a for a in native_app.record()["argv"] if "model_reasoning_effort" in a]
    assert [a["effort"] for a in snap["agents"]] == ["medium"]


def test_codexs_own_command_failing_the_same_way_is_counted_as_koloni_s_are(
    native_app, wait_run, project_dir
):
    failing = {"run": "pytest", "output": "1 failed in 0.21s\n", "exit": 1}
    client, provider, _ = native_app([failing, {"pause": 0.2}, failing, {"pause": 0.2},
                                      failing, {"pause": 0.2}, {"say": "Still red."}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    sign = snap["agents"][0]["sign"]
    assert (sign["kind"], sign["count"]) == ("same_failure", 3)
    assert sign["text"].startswith("run_command failed 3 times")

    # Counted apart from KOLONİ's own calls: four of its own and one of KOLONİ's, the same
    # failure, are no five that stop it in a turn nobody watches.
    runner = client.app.state.runner
    lead = SimpleNamespace(agent_id=snap["agents"][0]["id"], run_id=run_id, cid=cid)
    same = ToolCallRequest("x", "run_command", json.dumps({"command": "pytest"}))
    runner._unwatched[run_id] = SimpleNamespace(trigger_id=None)
    try:
        for _ in range(4):
            runner._counted(lead, "x", same, "failed", "exit code 1", own=True)
        said = runner._counted(lead, "x", same, "failed", "exit code 1")
    finally:
        runner._unwatched.pop(run_id)
    assert "Counted by KOLONİ" not in said and lead.agent_id not in runner._stuck


def test_r179_a_codex_lead_in_native_mode_at_a_chat_with_a_recipe_is_said_once_a_chat(
    native_app, wait_run, project_dir
):
    from app.agent import CODEX_NATIVE_NO_RECIPE
    from tests.test_chat_teams_scenarios import teams_of
    from tests.test_recipe_run_scenarios import made
    from tests.test_recipes_scenarios import SMALL

    client, provider, _ = native_app([{"say": "Done."}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert not [m for m in snap["messages"] if m["role"] == "koloni"]  # (no recipe: not said)
    assert client.patch(f"/api/conversations/{cid}", json={"teams_mode": "manual", "teams": [
        {"team_id": teams_of(client)["Web app"]["id"],
         "recipe_id": made(client, "Small", SMALL)["id"]}]}, headers=OWN).status_code == 200
    for _ in range(2):
        run_id = client.post(f"/api/conversations/{cid}/messages",
                             json={"content": "again"}).json()["run"]["id"]
        snap = wait_run(client, cid, run_id)
    assert [m["content"] for m in snap["messages"] if m["role"] == "koloni"] == [
        CODEX_NATIVE_NO_RECIPE]


def test_r188_a_codex_lead_in_native_mode_that_opens_the_teams_role_runs_its_recipe(
    native_app, wait_run, project_dir
):
    # R188 (live): its Docs recipe ran (writer → Reviewer, in) - the line says "often", not never.
    from app.agent import CODEX_NATIVE_NO_RECIPE
    from tests.test_chat_teams_scenarios import teams_of
    from tests.test_recipe_run_scenarios import made, row
    from tests.test_recipes_scenarios import SMALL

    client, provider, _ = native_app(
        [{"koloni": "spawn_agent", "args": {"role": "Coder", "task": "build it"}},
         {"say": "Started."}], default_steps=[text("built")],
        later_script=[{"say": "Done."}], later_when="Message from Coder")
    local = client.get("/api/providers").json()[0]
    client.patch(f"/api/roles/{role_id(client, 'Coder')}", json={"provider_id": local["id"]})
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    assert client.patch(f"/api/conversations/{cid}", json={
        "permission_mode": "full_auto", "provider_id": provider["id"], "teams_mode": "manual",
        "teams": [{"team_id": teams_of(client)["Web app"]["id"],
                   "recipe_id": made(client, "Small", SMALL)["id"]}]},
        headers=OWN).status_code == 200
    run_id = client.post(f"/api/conversations/{cid}/messages",
                         json={"content": "build it"}).json()["run"]["id"]
    snap = wait_run(client, cid, run_id)
    assert CODEX_NATIVE_NO_RECIPE in [m["content"] for m in snap["messages"]]
    assert row(snap)["steps"][0]["state"] == "done"   # (the recipe's first step, by its Coder)


def test_a_codex_that_crashes_while_its_command_runs_fails_the_turn_at_once(
    native_app, wait_run, project_dir
):
    # denetim-010 #3: its command kept the limit on silence off and a child of its own held its
    # output open: the turn waited for Stop.
    client, provider, _ = native_app([{"run": "pytest", "die": 7}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id, timeout=20)
    run = snap["runs"][0]
    assert run["status"] == "failed" and "code 7" in run["error"], run["error"]
    # (not left running: as any command still marked so when its turn is over)
    assert snap["commands"][0]["status"] == "killed"
