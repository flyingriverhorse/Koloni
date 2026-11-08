"""Slice 48 beside its acceptance set: who may switch the Lead's hand-off off, and a Lead
that cannot hand code on keeps writing it."""

import pytest

from app.agent import LEAD_COMMAND
from app.model_native import CLAUDE_NEVER, CLAUDE_WRITES, WRITE_BLOCKED, _as_exec, _Asked
from app.roles import ALL_TOOLS
from tests.test_agent_writes import wait_status
from tests.test_chat_flow import text
from tests.test_claude_native import claude_app  # noqa: F401  (a fixture)
from tests.test_copilot_agent import copilot_native  # noqa: F401  (a fixture)
from tests.test_native_agent import native_app  # noqa: F401  (a fixture)
from tests.test_parallel import until
from tests.test_spawn import begin, call, role_id, spawn, step
from tests.test_trigger_scenarios import finished, results, run_now, setup, trigger

WRITE = step(call("write_file", {"path": "made.txt", "content": "x"}, "w"))


def lead_on(client, project_dir, provider):
    """A turn of a Lead on a CLI, at Full auto, with the hand-off on as in a new conversation."""
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    assert client.patch(f"/api/conversations/{cid}", json={
        "permission_mode": "full_auto", "provider_id": provider["id"]},
        headers={"Origin": "http://127.0.0.1:8790"}).status_code == 200
    run = client.post(f"/api/conversations/{cid}/messages", json={"content": "fix it"}).json()
    return cid, run["run"]["id"]


def test_only_the_apps_own_page_switches_it_off(make_client, project_dir):
    client, _model = make_client([])
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    url = f"/api/conversations/{client.post(f'/api/projects/{pid}/conversations').json()['id']}"
    # tek-ev: a project's chat follows its project's - the chat's own PATCH is refused it
    assert client.request("PATCH", url, json={"lead_hands_code": False}, headers=OWN).status_code == 422
    # an agent's command against the app's address cannot give the Lead its write tools
    assert client.patch(f"/api/projects/{pid}", json={"lead_work": "itself"}).status_code == 403
    assert client.patch(f"/api/projects/{pid}", json={"lead_work": "itself"},
                        headers=OWN).status_code == 200
    assert client.get(url).json()["conversation"]["lead_hands_code"] is False


def test_a_trigger_that_may_open_no_agent_has_its_lead_write(make_client, wait_run, project_dir):
    """A trigger from before the setting (write, no agents) still gets its job done."""
    client, model, pid, cid = setup(make_client, project_dir, {"Lead": [WRITE, text("done")]})
    made = trigger(client, pid, cid, permissions={"write": True, "commands": [], "agents": 0})
    run_id = run_now(client, made["id"])
    snap = finished(client, wait_run, cid, run_id, timeout=20)
    assert snap["conversation"]["lead_hands_code"] is True
    assert [(name, status) for name, status, _ in results(snap, run_id)] == [
        ("write_file", "succeeded")]
    assert "hand every change to files" not in model.calls[0][0]["content"].lower()
    assert (project_dir / "made.txt").read_text(encoding="utf-8") == "x"


def test_a_lead_that_may_open_no_sub_agent_writes(make_client, wait_run, project_dir):
    client, model = make_client([WRITE, text("done")])
    client.headers["Origin"] = "http://127.0.0.1:8790"
    lead = [tool for tool in ALL_TOOLS if tool != "spawn_agent"]
    assert client.patch(f"/api/roles/{role_id(client, 'Lead')}",
                        json={"tools": lead}).status_code == 200
    cid, run_id = begin(client, project_dir, mode="full_auto")
    snap = wait_run(client, cid, run_id)
    assert snap["conversation"]["lead_hands_code"] is True
    assert [(c["name"], c["status"]) for c in snap["tool_calls"]] == [("write_file", "succeeded")]
    assert "hand every change to files" not in model.calls[0][0]["content"].lower()


def test_a_claude_code_lead_is_started_without_its_own_writes(
    claude_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _ = claude_app([{"say": "looked"}])
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    assert client.patch(f"/api/conversations/{cid}", json={
        "permission_mode": "full_auto", "provider_id": provider["id"]},
        headers={"Origin": "http://127.0.0.1:8790"}).status_code == 200
    run = client.post(f"/api/conversations/{cid}/messages", json={"content": "go"}).json()["run"]
    wait_run(client, cid, run["id"], timeout=20)
    argv = claude_app.record()["argv"]
    # (beside those never given: slice 89b)
    assert set(argv[argv.index("--disallowedTools") + 1].split(",")) == {
        *CLAUDE_WRITES, *CLAUDE_NEVER}


def test_a_codex_lead_that_hands_code_on_is_refused_its_own_patch(
    native_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _ = native_app([
        {"write": "hello.py", "content": "print('hello')\n"},
        {"write": "other.py", "content": "x = 1\n", "thread": "thr_own_agent"},
        {"say": "Handed it on."}], timeout=10)
    cid, run_id = lead_on(client, project_dir, provider)
    snap = wait_run(client, cid, run_id, timeout=30)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert snap["conversation"]["lead_hands_code"] is True
    refused = [c for c in snap["tool_calls"] if c["name"] == "edit_file"]
    assert [c["status"] for c in refused] == ["denied", "denied"]
    assert "call spawn_agent" in refused[0]["result"]
    # B-197: its decision carries no reason - KOLONİ's reaches Codex's turn, before the no (its
    # turn may end after it), saying whose it was; not into a thread of its own agents'.
    record = native_app.record()
    (steer,) = record["steers"]
    told = steer["input"][0]["text"]
    assert "your own Edit to " in told and "hello.py" in told and "not a sub-agent's" in told
    assert told.endswith("(KOLONİ's words - not the user's.)")
    assert [a["steers_before"] for a in record["answers"]] == [1, 1]
    assert "'hi'" in (project_dir / "hello.py").read_text(encoding="utf-8")
    assert not snap["file_changes"]


def test_a_copilot_lead_that_hands_code_on_is_refused_its_own_write(
    copilot_native, wait_run, project_dir  # noqa: F811
):
    client, provider = copilot_native([
        {"write": "hello.py", "content": "print('hello')\n"}, {"say": "Handed it on."}])
    cid, run_id = lead_on(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    (refused,) = [c for c in snap["tool_calls"] if c["name"] == "edit_file"]
    assert refused["status"] == "denied" and "call spawn_agent" in refused["result"]
    assert (project_dir / "hello.py").read_text(encoding="utf-8") == "print('hi')\n"


def test_what_a_codex_leads_command_wrote_is_kept_as_its_own_and_it_is_told_once(
    native_app, wait_run, project_dir  # noqa: F811
):
    # K-48: it writes with a command, not its patch tool - the command has run, and it stands
    client, provider, _ = native_app([
        {"run": "Set-Content hello.py x", "output": "",
         "touches": {"hello.py": "x\n", "new.txt": "y\n"}},
        {"await_steer": True},
        {"run": "Set-Content more.txt z", "output": "", "touches": {"more.txt": "z\n"}},
        {"say": "Handed it on."}], timeout=10)
    cid, run_id = lead_on(client, project_dir, provider)
    snap = wait_run(client, cid, run_id, timeout=30)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert (project_dir / "hello.py").read_text(encoding="utf-8") == "x\n"
    assert (project_dir / "new.txt").is_file() and (project_dir / "more.txt").is_file()
    lead = snap["agents"][0]["id"]
    assert sorted((c["path"], c["status"], c["agent_id"]) for c in snap["file_changes"]) == [
        ("hello.py", "applied", lead), ("more.txt", "applied", lead), ("new.txt", "applied", lead)]
    wrote = [c for c in snap["tool_calls"] if c["name"] in ("edit_file", "write_file")]
    assert len(wrote) == 3 and all(c["status"] == "succeeded" and c["result"].startswith(
        f"{LEAD_COMMAND}: ") for c in wrote)
    # once a turn: told of its first command's files, not again of its second's
    (steer,) = native_app.record()["steers"]
    told = steer["input"][0]["text"]
    assert '"hello.py", "new.txt"' in told and "call spawn_agent with role Coder" in told


def test_a_lead_its_cli_does_not_hear_is_told_with_its_next_tool_result(
    native_app, wait_run, project_dir  # noqa: F811
):
    # (Codex refuses the steer here, as when its turn is over: KOLONİ's note waits for it)
    client, provider, _ = native_app([
        {"run": "Set-Content hello.py x", "output": "", "touches": {"hello.py": "x\n"}},
        {"pause": 0.5}, {"say": "Handed it on."}], timeout=10, steer="reject")
    cid, run_id = lead_on(client, project_dir, provider)
    snap = wait_run(client, cid, run_id, timeout=30)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    (note,) = [m for m in snap["messages"] if "Your own command changed" in (m["content"] or "")]
    assert note["from_agent_id"] is None and '"hello.py"' in note["content"]


def test_what_the_user_saves_while_a_lead_works_stays(
    native_app, wait_run, project_dir, tmp_path  # noqa: F811
):
    # (the user's editor while the Lead works: nothing is taken back)
    go = tmp_path / "go"
    # The stand-in says nothing while it holds for `go` (and for KOLONİ's steer), and KOLONİ
    # ends a CLI silent for `timeout`: at 10 s a loaded machine could end the turn before the
    # test saw the first command done. Above this test's own waits (20 s, then 30 s) the hold
    # ends when the test says, never by the clock. Its steer comes at the look after either
    # command: under load the first's look comes after the user's saves and puts them down to
    # it (`_look`'s guess) - then it is read while the second is asked about, and still counts.
    client, provider, _ = native_app([
        {"run": "dir", "output": ""}, {"wait_for": str(go)},
        {"run": "Set-Content lead.txt x", "output": "", "touches": {"lead.txt": "x\n"}},
        {"await_steer": True}, {"say": "Handed it on."}], timeout=60)
    cid, run_id = lead_on(client, project_dir, provider)
    until(client, cid, lambda s: any(c["name"] == "run_command" and c["status"] == "succeeded"
                                     for c in s["tool_calls"]), timeout=20)
    (project_dir / "hello.py").write_text("print('mine')\n", encoding="utf-8")
    (project_dir / "mine.txt").write_text("new\n", encoding="utf-8")
    go.touch()
    snap = wait_run(client, cid, run_id, timeout=30)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert (project_dir / "hello.py").read_text(encoding="utf-8") == "print('mine')\n"
    assert (project_dir / "mine.txt").read_text(encoding="utf-8") == "new\n"
    assert (project_dir / "lead.txt").read_text(encoding="utf-8") == "x\n"


def opens_a_codex(client, project_dir, provider, role):
    """A turn whose Lead (the scripted model) hands code on and opens `role` on Codex."""
    client.patch(f"/api/roles/{role_id(client, role)}", json={"provider_id": provider["id"]},
                 headers=OWN)
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    assert client.patch(f"/api/conversations/{cid}", json={
        "permission_mode": "full_auto", "spawn_approval": "never"}, headers=OWN).status_code == 200
    run = client.post(f"/api/conversations/{cid}/messages", json={"content": "go"}).json()["run"]
    return cid, run["id"]


def test_what_a_helpers_command_wrote_is_kept(native_app, wait_run, project_dir):  # noqa: F811
    client, provider, _ = native_app(
        [{"run": "make", "output": "ok\n", "touches": {"made.txt": "by a command\n"}},
         {"say": "Made it."}],
        default_steps=[spawn("Coder", "Make the file"), text("The coder did it.")])
    cid, run_id = opens_a_codex(client, project_dir, provider, "Coder")
    snap = wait_run(client, cid, run_id, timeout=30)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert snap["conversation"]["lead_hands_code"] is True
    assert [(c["path"], c["status"]) for c in snap["file_changes"]] == [("made.txt", "applied")]
    assert (project_dir / "made.txt").read_text(encoding="utf-8") == "by a command\n"
    assert not [c for c in snap["tool_calls"] if c["status"] == "denied"]


def test_a_write_codexs_read_only_sandbox_refused_is_no_success(
    native_app, wait_run, project_dir  # noqa: F811
):
    # Measured (codex 0.164.0, Windows): refused, and still "completed" with exit code 0
    refused = ("Set-Content: Access to the path 'C:\\p\\x.txt' is denied.\r\n")
    client, provider, _ = native_app(
        [{"run": "Set-Content x.txt hi", "output": refused, "exit": 0},
         {"run": "Get-Content hello.py", "output": "print('hi')\n", "exit": 0},
         {"say": "It was refused."}],
        default_steps=[spawn("Tester", "Run it"), text("carrying on")])
    cid, run_id = opens_a_codex(client, project_dir, provider, "Tester")
    snap = wait_run(client, cid, run_id, timeout=30)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert native_app.record()["thread"]["sandbox"] == "read-only"
    ran = [(c["status"], c["result"]) for c in snap["tool_calls"] if c["name"] == "run_command"]
    assert ran[0][0] == "failed" and f"exit code 0, {WRITE_BLOCKED}" in ran[0][1]
    assert ran[1] == ("succeeded", "exit code 0\nprint('hi')")
    # (and its own record says so, not "exit 0": the commands' list reads it)
    assert [(c["status"], c["exit_code"]) for c in snap["commands"]] == [
        ("blocked", 0), ("exited", 0)]


@pytest.mark.parametrize("command, output, blocked", [
    # PowerShell wraps its error to the console's width
    ("Set-Content x.txt hi", "Set-Content: Access to the path\r\n    'C:\\p\\x.txt' is\r\n"
     " denied.\r\n", True),
    # a refused read says the same: it is no write
    ("Get-ChildItem -Recurse", "Get-ChildItem: Access to the path 'C:\\p\\.git\\x' is denied.",
     False),
    # a test run's result is its own (the ledger counts it as one)
    ("pytest -q", "E   PermissionError: Access to the path 'x' is denied\n1 failed", False),
])
def test_what_codexs_read_only_sandbox_refused_is_told_by_its_words(command, output, blocked):
    def told(read_only=True):
        (event,) = _as_exec("item/completed", {"item": {
            "id": "i", "type": "commandExecution", "command": command, "status": "completed",
            "aggregatedOutput": output, "exitCode": 0}}, _Asked(), read_only)
        return event["item"].get("blocked")

    assert told() == (WRITE_BLOCKED if blocked else None)
    assert told(read_only=False) is None  # (not in its read-only sandbox: none of its)


def test_a_tool_koloni_does_not_know_is_asked_about_for_a_lead_that_hands_code_on(
    claude_app, wait_run, project_dir  # noqa: F811
):
    # (at Full auto it would go through: it may write, and this Lead may not)
    client, provider, _ = claude_app([
        {"tool": "mcp__filesystem__write_file", "input": {"path": "hello.py"},
         "write": ["hello.py", "broken"]}, {"say": "Asked."}])
    cid, run_id = lead_on(client, project_dir, provider)
    question = wait_status(client, cid, "waiting_approval")["questions"][0]
    assert "mcp__filesystem__write_file" in question["question"] and question["leave"] is True
    client.post(f"/api/questions/{question['id']}/answer", json={"answer": "Deny"},
                headers={"Origin": "http://127.0.0.1:8790"})
    wait_run(client, cid, run_id)
    assert (project_dir / "hello.py").read_text(encoding="utf-8") == "print('hi')\n"


# (in no tool's name: a CLI Lead makes it with its own)
DECIDES = "make a small change to files yourself (one or two files, a few lines). hand bigger"
OWN = {"Origin": "http://127.0.0.1:8790"}


def test_a_lead_that_decides_keeps_its_writes_and_is_told_when_to_hand_on(
    make_client, wait_run, project_dir
):
    client, model = make_client([WRITE, text("done")])
    cid, run_id = begin(client, project_dir, mode="full_auto", lead_work="decides")
    snap = wait_run(client, cid, run_id)
    assert snap["conversation"]["lead_work"] == "decides"
    assert snap["conversation"]["lead_hands_code"] is False
    assert [(c["name"], c["status"]) for c in snap["tool_calls"]] == [("write_file", "succeeded")]
    told = model.calls[0][0]["content"].lower()
    assert DECIDES in told and "hand every change to files" not in told


def test_a_folders_default_is_its_new_chats_and_only_the_apps_own_page_sets_it(
    make_client, project_dir
):
    client, _model = make_client([])
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    before = client.post(f"/api/projects/{pid}/conversations").json()
    assert before["lead_work"] == "delegates"
    # an agent's command against the app's address cannot give new Leads their write tools
    assert client.patch(f"/api/projects/{pid}", json={"lead_work": "itself"}).status_code == 403
    assert client.patch(f"/api/conversations/{before['id']}",
                        json={"lead_work": "decides"}).status_code == 403
    saved = client.patch(f"/api/projects/{pid}", json={"lead_work": "decides"}, headers=OWN)
    assert saved.status_code == 200 and saved.json()["lead_work"] == "decides"
    assert client.post(f"/api/projects/{pid}/conversations").json()["lead_work"] == "decides"
    # (a chat made before follows it too: tek-ev, Settings › This project)
    assert client.get(f"/api/conversations/{before['id']}").json()["conversation"][
        "lead_work"] == "decides"


def test_a_claude_code_lead_that_decides_keeps_its_writes_and_is_told_so(
    claude_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _ = claude_app([{"say": "looked"}])
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    assert client.patch(f"/api/conversations/{cid}", json={
        "permission_mode": "full_auto", "provider_id": provider["id"], "lead_work": "decides"},
        headers=OWN).status_code == 200
    run = client.post(f"/api/conversations/{cid}/messages", json={"content": "go"}).json()["run"]
    wait_run(client, cid, run["id"], timeout=20)
    record = claude_app.record()
    argv = record["argv"]
    assert not set(argv[argv.index("--disallowedTools") + 1].split(",")) & set(CLAUDE_WRITES)
    assert DECIDES in record["stdin"].lower()
