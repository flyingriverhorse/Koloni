"""Native Copilot headless (slice 89c): every permission request of its own is answered by
KOLONİ (`AgentRunner._approve`), as Codex's are (89a); what it does is on record as with
`-p`; it is never started with leave for every tool of its own (`--allow-all-tools`)."""

import json
import time
from pathlib import Path

import pytest

from app import raw
from app.agent.tiers_mixin import REFUSED_LAST
from app.model_native import _files, _heredoc_patch
from app.workspace import SECRET_CARD
from tests.test_agent_writes import wait_status
from tests.test_agents_teams_scenarios import patch_role, spawn
from tests.test_chat_flow import text
from tests.test_claude_native import NOBODY, nothing_was_asked, unattended
from tests.test_codex_app_server_scenarios import ADD_B, heredoc, proposed, watched
from tests.test_copilot_agent import copilot_native, start  # noqa: F401  (a fixture)
from tests.test_secret_read import next_pending
from tests.test_spawn import begin, step

ORIGIN = {"Origin": "http://127.0.0.1:8790"}
APPROVE, REJECT = "approve-once", "reject"
ACCOUNT = ("someone-on-github", "someone@example.com")
UNASKED = "ran without KOLONİ being asked (GitHub Copilot CLI's own rules)"


def answers(copilot_native):  # noqa: F811
    return [(a["kind"], a["result"]["kind"]) for a in copilot_native.record()["answers"]]


def hello(project_dir):
    return (project_dir / "hello.py").read_text(encoding="utf-8")


# --- 1. Ask: a command is a card -----------------------------------------------------------


def test_at_ask_copilots_command_is_a_card_and_runs_once_approved(
    copilot_native, wait_run, project_dir  # noqa: F811
):
    client, provider = copilot_native([
        {"shell": "pytest -q", "output": "2 passed", "touches": {"ran.txt": "x"}},
        {"say": "Tests pass."}])
    cid, run_id = start(client, project_dir, provider, mode="ask")
    asked = wait_status(client, cid, "waiting_approval")["commands"][0]
    assert (asked["status"], asked["command"], asked["origin"]) == ("proposed", "pytest -q", "cli")
    assert not (project_dir / "ran.txt").exists()  # nothing ran before the yes
    assert client.post(f"/api/commands/{asked['id']}/approve", json={}).status_code == 200
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert answers(copilot_native) == [("shell", APPROVE)]
    (done,) = snap["commands"]  # one record: the card is the command
    assert (done["status"], done["exit_code"]) == ("exited", 0)
    assert done["output"].strip() == "2 passed"
    assert (project_dir / "ran.txt").exists()


def test_at_ask_a_rejected_command_is_rejected_and_never_runs(
    copilot_native, wait_run, project_dir  # noqa: F811
):
    client, provider = copilot_native([
        {"shell": "pytest -q", "touches": {"ran.txt": "x"}}, {"say": "Left it."}])
    cid, run_id = start(client, project_dir, provider, mode="ask")
    asked = wait_status(client, cid, "waiting_approval")["commands"][0]
    assert client.post(f"/api/commands/{asked['id']}/reject").status_code == 200
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed"  # a rejection carries the turn on
    assert answers(copilot_native) == [("shell", REJECT)]
    assert not (project_dir / "ran.txt").exists()
    assert [c["status"] for c in snap["commands"]] == ["rejected"]
    assert [(t["name"], t["status"]) for t in snap["tool_calls"]] == [("run_command", "denied")]


# --- 2. Full auto: only what is asked at every level is a card ------------------------------


def test_at_full_auto_an_ordinary_command_is_approved_unasked(
    copilot_native, wait_run, project_dir  # noqa: F811
):
    client, provider = copilot_native([{"shell": "pytest -q", "output": "ok"}, {"say": "ok"}])
    statuses = watched(client)
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert answers(copilot_native) == [("shell", APPROVE)]
    nothing_was_asked(snap, statuses)
    assert [c["status"] for c in snap["commands"]] == ["exited"]


def test_at_full_auto_a_command_and_a_read_of_a_secret_are_cards(
    copilot_native, wait_run, project_dir  # noqa: F811
):
    (project_dir / ".env").write_text("TOKEN=x\n", encoding="utf-8")
    client, provider = copilot_native([
        {"shell": "type .env", "output": "TOKEN=x"}, {"read": ".env", "result": "TOKEN=x"},
        {"read": "hello.py"}, {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)
    asked = wait_status(client, cid, "waiting_approval")["commands"][0]
    assert (asked["command"], asked["status"]) == ("type .env", "proposed")
    client.post(f"/api/commands/{asked['id']}/reject")
    # its own view tool reading the secret waits on the card KOLONİ's read_file has (slice 88)
    card = next_pending(client, cid, set())
    assert card["name"] == "read_file" and card["why_asked"] == SECRET_CARD
    client.post(f"/api/tool-calls/{card['id']}/reject", headers=ORIGIN)
    wait_run(client, cid, run_id)
    # (hello.py is read without a card)
    assert answers(copilot_native) == [("shell", REJECT), ("read", REJECT), ("read", APPROVE)]


# --- 3. Full auto: a write that stands over later turns is a card -----------------------------


def test_at_full_auto_a_write_to_a_workflow_is_a_card_and_claude_md_or_an_ordinary_one_is_not(
    copilot_native, wait_run, project_dir  # noqa: F811
):
    # (As 1.0.91 asks, with no fileEdits: each card is a question with its diff. K-fullauto-
    # sorma 2: an instruction file alone is no card at Full auto; a workflow still is.)
    client, provider = copilot_native([
        {"write": "hello.py", "content": "print('hello')\n"},
        {"write": ".github/workflows/x.yml", "content": "on: push\n"},
        {"write": "CLAUDE.md", "content": "# rules\n"}, {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)
    asked = question(client, cid, 1)
    assert hello(project_dir) == "print('hello')\n"  # the ordinary one: unasked
    assert ".github/workflows/x.yml" in asked["question"] and "+on: push" in asked["question"]
    assert not (project_dir / ".github").exists()
    client.post(f"/api/questions/{asked['id']}/answer", json={"answer": "Deny"}, headers=ORIGIN)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert len(snap["questions"]) == 1  # (CLAUDE.md: no card)
    assert answers(copilot_native) == [("write", APPROVE), ("write", REJECT), ("write", APPROVE)]
    assert not (project_dir / ".github").exists()
    assert (project_dir / "CLAUDE.md").read_text(encoding="utf-8") == "# rules\n"
    assert sorted(c["path"] for c in snap["file_changes"]) == ["CLAUDE.md", "hello.py"]


def question(client, cid, number):
    """The conversation's `number`th question, once it is asked."""
    for _ in range(500):
        questions = client.get(f"/api/conversations/{cid}").json()["questions"]
        if len(questions) >= number:
            return questions[number - 1]
        time.sleep(0.02)
    raise AssertionError(f"question {number} was never asked")


# --- 4. KOLONİ's own MCP tools are let through; every other kind is rejected ------------------


def test_kolonis_own_tools_are_approved_once(copilot_native, wait_run, project_dir):  # noqa: F811
    client, provider = copilot_native([{"koloni": "read_notes"}, {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert answers(copilot_native) == [("mcp", APPROVE)]
    assert copilot_native.record()["results"][0] is not None  # it ran, by KOLONİ's own rules


def test_every_other_kind_of_request_is_rejected_and_on_record(
    copilot_native, wait_run, project_dir  # noqa: F811
):
    client, provider = copilot_native([
        {"ask": {"kind": "url", "url": "https://example.com", "intention": "Fetch"},
         "tool": "web_fetch"},
        {"ask": {"kind": "mcp", "serverName": "github", "toolName": "t", "toolTitle": "t",
                 "readOnly": True}, "tool": "github-t"},
        {"ask": {"kind": "memory", "action": "store", "subject": "s", "fact": "f"},
         "tool": "store_memory"},
        {"ask": {"kind": "custom-tool", "toolName": "x"}, "tool": "x"},
        # a write that would also move or change another file than the one it names
        {"write": "hello.py", "content": "x\n",
         "edits": [{"before": {"path": "hello.py", "content": "print('hi')\n"},
                    "after": {"path": "moved.py", "content": "x\n"}}]},
        # the same tool asked about again: the second time is not answered yes
        {"shell": "pytest -q", "twice": True},
        # a request of its own over JSON-RPC: answered with an error, never left waiting
        {"request": "userInput.request", "params": {"question": "?"}},
        {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert answers(copilot_native) == [
        ("url", REJECT), ("mcp", REJECT), ("memory", REJECT), ("custom-tool", REJECT),
        ("write", REJECT), ("shell", APPROVE), ("shell", REJECT)]
    assert hello(project_dir) == "print('hi')\n"
    (reply,) = copilot_native.record()["replies"]
    assert "error" in reply["answer"]
    declined = [t for t in snap["tool_calls"] if t["status"] == "denied"]
    assert len(declined) == 7 and all("KOLONİ" in t["result"] for t in declined)
    # what was asked about and rejected did not run unasked
    assert not [t for t in snap["tool_calls"] if UNASKED in (t["result"] or "")]


def test_a_rejected_tool_it_never_says_is_done_does_not_hold_off_the_silence_limit(
    copilot_native, wait_run, project_dir  # noqa: F811
):
    client, provider = copilot_native([
        {"ask": {"kind": "url", "url": "https://example.com", "intention": "Fetch"},
         "tool": "web_fetch", "no_complete": True}, {"pause": 6}, {"say": "ok"}], timeout=2)
    cid, run_id = start(client, project_dir, provider)
    run = wait_run(client, cid, run_id, timeout=20)["runs"][0]
    assert run["status"] == "failed" and "sent nothing for 2 seconds" in run["error"]


# --- 5. A turn nobody is watching ----------------------------------------------------------


def test_unattended_copilot_is_refused_what_its_trigger_does_not_allow_and_nobody_is_asked(
    copilot_native, wait_run, project_dir  # noqa: F811
):
    client, provider = copilot_native([
        {"shell": "pytest -q", "output": "ok"},
        {"shell": "pytest -q && echo x", "touches": {"ran.txt": "x"}},
        {"write": "hello.py", "content": "changed\n"}, {"say": "done"}])
    snap, run, statuses = unattended(
        client, project_dir, provider, "full_auto", wait_run, commands=["pytest -q"])
    assert run["status"] == "completed", run
    assert answers(copilot_native) == [("shell", APPROVE), ("shell", REJECT), ("write", REJECT)]
    assert hello(project_dir) == "print('hi')\n" and not (project_dir / "ran.txt").exists()
    assert [(t["name"], t["status"]) for t in snap["tool_calls"]] == [
        ("run_command", "succeeded"), ("run_command", "denied"), ("edit_file", "denied")]
    assert all(NOBODY in t["result"] for t in snap["tool_calls"][1:])
    nothing_was_asked(snap, statuses)


# --- 6. What it did is on record as before; whose account it is, nowhere ---------------------


def test_what_copilot_does_is_on_record_and_its_account_is_nowhere(
    copilot_native, wait_run, project_dir  # noqa: F811
):
    client, provider = copilot_native([
        {"say": "I will fix it."}, {"read": "hello.py", "result": "print('hi')"},
        {"write": "hello.py", "content": "print('hello')\n"},
        {"shell": "python hello.py", "output": "hello", "exit": 0},
        {"say": "Fixed."}], model="qwen-as-served")
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert [m["content"] for m in snap["messages"][1:] if m["content"]] == [
        "I will fix it.", "Fixed.", "In the project: hello.py (+1 −1)."]  # (B-205: KOLONİ's line)
    assert [(t["name"], t["status"], t["origin"]) for t in snap["tool_calls"]] == [
        ("copilot__view", "succeeded", "cli"), ("edit_file", "succeeded", "cli"),
        ("run_command", "succeeded", "cli")]
    (change,) = snap["file_changes"]
    assert (change["path"], change["kind"], change["status"]) == ("hello.py", "modify", "applied")
    assert "+print('hello')" in change["diff"]
    (ran,) = snap["commands"]
    assert (ran["command"], ran["status"], ran["exit_code"]) == ("python hello.py", "exited", 0)
    agent = snap["agents"][0]
    assert agent["model_id"] == "qwen-as-served" and agent["input_tokens"] is None
    kept = raw.read(agent["id"])
    for where in (json.dumps(snap), json.dumps(kept)):
        assert not [one for one in ACCOUNT if one in where]
        assert "session-state" not in where  # where it keeps its sessions: not read, not kept


# --- 7. A start that goes wrong: never `-p`, never --allow-all-tools ------------------------


def test_a_copilot_that_cannot_be_asked_first_is_stopped_with_its_version(
    copilot_native, wait_run, project_dir, tmp_path  # noqa: F811
):
    starts = tmp_path / "starts.jsonl"
    client, provider = copilot_native([])
    for handshake, why in (("ping", "not ready"), ("version", "protocol 2"),
                           ("create", "unknown field mcpServers")):
        starts.unlink(missing_ok=True)
        copilot_native.rescript([{"write": "hello.py", "content": "x"}], handshake=handshake,
                                starts=str(starts))
        cid, run_id = start(client, project_dir, provider)
        run = wait_run(client, cid, run_id)["runs"][0]
        assert run["status"] == "failed"
        assert "GitHub Copilot CLI 1.0.91-fake could not be asked before it acts" in run["error"]
        assert why in run["error"] and "run it as a session instead" in run["error"]
        started = [json.loads(line) for line in starts.read_text("utf-8").splitlines()]
        # (its version first: a measured one is asked nothing more, K-cli-surface)
        assert [argv[-1] for argv in started] == ["--version", "--stdio", "--version"]
        assert not [argv for argv in started if "-p" in argv or "--allow-all-tools" in argv]
        assert hello(project_dir) == "print('hi')\n"


def test_a_model_not_on_the_account_is_named_as_the_cause(
    copilot_native, wait_run, project_dir  # noqa: F811
):
    """B-176: the turn says the model is the cause, and nothing of a session. R166: as soon as
    Copilot refuses - its fake stays alive and silent after, so a KOLONİ that waited on it would
    reach its silence limit (60 s here) long after wait_run's 20."""
    client, provider = copilot_native([{"write": "hello.py", "content": "x"}], handshake="model",
                                      timeout=60)
    # B-396: on its list, it is switched off with why - no tier offers it again
    assert client.patch(f"/api/providers/{provider['id']}", json={
        "models": [{"name": "qwen-local", "tier": "balanced"}]}).status_code == 200
    cid, run_id = start(client, project_dir, provider)
    run = wait_run(client, cid, run_id)["runs"][0]
    assert run["status"] == "failed"
    assert run["error"] == "Copilot can't use qwen-local on your account: pick another model"
    assert copilot_native.record()["create"]["model"] == "qwen-local"
    assert hello(project_dir) == "print('hi')\n"
    (row,) = next(p for p in client.get("/api/providers").json()
                  if p["id"] == provider["id"])["models"]
    assert (row["enabled"], row["off_why"]) == (
        False, f"{provider['name']} refused it: not available on your account" + REFUSED_LAST)


def test_a_sub_agent_on_a_model_not_on_the_account_switches_it_off_and_moves_on(
    copilot_native, wait_run, project_dir  # noqa: F811
):
    """B-396 (R194, live): a Coder on native Copilot, refused its model at session.create -
    switched off with why, and the role's next model takes the job."""
    client, provider = copilot_native(
        [{"write": "hello.py", "content": "x"}], handshake="model", timeout=60,
        default_steps=[step(spawn("Coder")), text("done"), text("fixed")])
    assert client.patch(f"/api/providers/{provider['id']}", json={"for_agents": True, "models": [
        {"name": "qwen-local", "tier": "balanced", "agents": True}]}).status_code == 200
    local = next(p for p in client.get("/api/providers").json() if p["id"] != provider["id"])
    assert patch_role(client, "Coder", models=[
        {"provider_id": provider["id"], "model_id": "qwen-local"},
        {"provider_id": local["id"], "model_id": "fake-model"}]).status_code == 200
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    coder = wait_run(client, cid, run_id)["agents"][1]
    assert (coder["provider_name"], coder["status"]) == ("Local", "completed")
    assert coder["chosen_why"] == (
        "Coder moved from Copilot to Local, the role's 2nd choice: Copilot can't use qwen-local "
        "on your account: pick another model.")
    (row,) = next(p for p in client.get("/api/providers").json()
                  if p["id"] == provider["id"])["models"]
    assert (row["enabled"], row["off_why"]) == (
        False, "Copilot refused it: not available on your account" + REFUSED_LAST)
    assert hello(project_dir) == "print('hi')\n"


def test_a_copilot_that_never_answers_is_stopped(copilot_native, wait_run, project_dir):  # noqa: F811
    client, provider = copilot_native([], timeout=2, handshake="silent")
    cid, run_id = start(client, project_dir, provider)
    run = wait_run(client, cid, run_id, timeout=20)["runs"][0]
    assert run["status"] == "failed" and "could not be asked before it acts" in run["error"]
    assert "did not answer for 2 seconds" in run["error"]


# --- 8. What it did without being asked is said to have been ---------------------------------


def test_a_tool_copilot_ran_without_asking_is_marked_so(
    copilot_native, wait_run, project_dir  # noqa: F811
):
    client, provider = copilot_native([
        {"shell": "Get-ChildItem", "output": "hello.py", "unasked": True},
        {"write": "hello.py", "content": "changed\n", "unasked": True},
        {"read": "hello.py", "unasked": True}, {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed"  # the turn goes on
    assert answers(copilot_native) == []
    (ran,) = [t for t in snap["tool_calls"] if t["name"] == "run_command"]
    assert UNASKED in ran["result"]
    assert [t for t in snap["tool_calls"] if t["name"] == "edit_file"
            and UNASKED in (t["result"] or "") and "hello.py" in t["result"]]
    (view,) = [t for t in snap["tool_calls"] if t["name"] == "copilot__view"]
    assert UNASKED in view["result"]


# --- 9. Its session is made with only the tools KOLONİ can judge (fix round) ---------------

BUILT_IN = ["powershell", "read_powershell", "stop_powershell", "list_powershell", "view",
            "create", "edit"]


def test_its_session_has_only_the_tools_koloni_judges_and_none_of_its_own_set_up(
    copilot_native, wait_run, project_dir  # noqa: F811
):
    client, provider = copilot_native([{"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)
    wait_run(client, cid, run_id)
    made = copilot_native.record()["create"]
    given = made["availableTools"]
    assert given[:len(BUILT_IN)] == BUILT_IN
    # KOLONİ's own tools, by the names Copilot gives an MCP server's tools
    ours = given[len(BUILT_IN):]
    assert ours and all(name.startswith("koloni-") for name in ours)
    assert "koloni-spawn_agent" in ours and "koloni-approve" not in ours
    for left_out in ("grep", "glob", "task", "web_fetch", "web_search", "sql", "skill"):
        assert left_out not in given
    # none of a repository's own hooks, config or skills, and no folder beyond its own
    assert (made["enableFileHooks"], made["enableConfigDiscovery"], made["enableSkills"]) == (
        False, False, False)
    assert "additionalDirectories" not in made


def test_a_request_a_hook_of_its_own_answered_stops_the_run(
    copilot_native, wait_run, project_dir  # noqa: F811
):
    client, provider = copilot_native([
        {"write": "hello.py", "content": "changed\n", "hooked": True}, {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)
    run = wait_run(client, cid, run_id)["runs"][0]
    assert run["status"] == "failed" and "a hook of Copilot's own" in run["error"]


def test_an_answer_it_did_not_take_stops_the_run(
    copilot_native, wait_run, project_dir  # noqa: F811
):
    client, provider = copilot_native([{"shell": "pytest -q", "unapplied": True},
                                       {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)
    run = wait_run(client, cid, run_id)["runs"][0]
    assert run["status"] == "failed" and "did not take KOLONİ's answer" in run["error"]


def test_a_turn_that_ends_aborted_is_not_a_success(
    copilot_native, wait_run, project_dir  # noqa: F811
):
    client, provider = copilot_native([{"say": "ok"}], aborted=True)
    cid, run_id = start(client, project_dir, provider)
    run = wait_run(client, cid, run_id)["runs"][0]
    assert run["status"] == "failed" and "aborted" in run["error"]


# --- 10. What a write is asked about is what its fileEdits say ------------------------------
# (1.0.91 sends no fileEdits - measured 24 Oct 2026 - and is asked about with its diff, as
# above; these are of a version that does.)


def test_the_content_asked_about_is_its_file_edit_not_its_new_file_contents(
    copilot_native, wait_run, project_dir  # noqa: F811
):
    # (An empty newFileContents is not a deletion: what it will hold is in fileEdits.)
    client, provider = copilot_native([
        {"write": "notes.txt", "content": "kept\n", "contents": "", "edits": True},
        {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider, mode="ask")
    card = proposed(client, cid, "notes.txt")
    assert "+kept" in card["diff"]
    client.post(f"/api/file-changes/{card['id']}/approve")
    wait_run(client, cid, run_id)
    assert (project_dir / "notes.txt").read_text(encoding="utf-8") == "kept\n"


def test_a_deletion_is_asked_about_as_one(copilot_native, wait_run, project_dir):  # noqa: F811
    client, provider = copilot_native([{"delete": "hello.py", "edits": True}, {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider, mode="ask")
    question = wait_status(client, cid, "waiting_approval")["questions"][0]
    assert "hello.py" in question["question"] and "delete" in question["question"]
    client.post(f"/api/questions/{question['id']}/answer", json={"answer": "Deny"},
                headers=ORIGIN)
    wait_run(client, cid, run_id)
    assert answers(copilot_native) == [("write", REJECT)]
    assert hello(project_dir) == "print('hi')\n"


def test_without_file_edits_a_write_elsewhere_than_it_names_is_rejected(
    copilot_native, wait_run, project_dir  # noqa: F811
):
    client, provider = copilot_native([
        {"write": "hello.py", "content": "x\n", "resolved": "other.py"},
        {"write": "hello.py", "content": "x\n",
         "diff": "--- a/hello.py\n+++ b/moved.py\n@@ -1 +1 @@\n-print('hi')\n+x"},
        # its own name in the diff's headers, and no fileEdits: asked about with its diff
        {"write": "hello.py", "content": "x\n",
         "diff": "--- a/hello.py\n+++ b/hello.py\n@@ -1 +1 @@\n-print('hi')\n+x"},
        {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert answers(copilot_native) == [("write", REJECT), ("write", REJECT), ("write", APPROVE)]
    declined = [t for t in snap["tool_calls"] if t["status"] == "denied"]
    assert len(declined) == 2 and all("another file" in t["result"] for t in declined)


def test_a_command_it_says_runs_outside_the_project_is_a_card_even_at_full_auto(
    copilot_native, wait_run, project_dir, tmp_path  # noqa: F811
):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    client, provider = copilot_native([{"shell": "pytest -q", "cwd": str(elsewhere)},
                                       {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)
    (asked,) = wait_status(client, cid, "waiting_approval")["commands"]
    assert asked["status"] == "proposed"
    client.post(f"/api/commands/{asked['id']}/reject")
    wait_run(client, cid, run_id)
    assert answers(copilot_native) == [("shell", REJECT)]


# --- 11. What a command says it touches is judged as a read or write of it -------------------
# (1.0.91 says no resolvedWorkingDirectory; it says possiblePaths, measured 24 Oct 2026.)


def test_a_command_naming_a_secret_outside_or_a_standing_file_is_a_card_at_full_auto(
    copilot_native, wait_run, project_dir, tmp_path  # noqa: F811
):
    (project_dir / ".env").write_text("TOKEN=x\n", encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    client, provider = copilot_native([
        {"shell": "Get-Content .env", "paths": [".env"]},
        {"shell": "Get-ChildItem x", "paths": [str(elsewhere / "x")]},
        {"shell": "echo on > .github/x.yml", "paths": [".github/x.yml"], "redirect": True},
        {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)
    for number, why in enumerate(("secret", "outside", "later turns")):
        for _ in range(500):
            waiting = [c for c in client.get(f"/api/conversations/{cid}").json()["commands"]
                       if c["status"] == "proposed"]
            if waiting:
                break
            time.sleep(0.02)
        (card,) = waiting
        client.post(f"/api/commands/{card['id']}/reject")
        calls = client.get(f"/api/conversations/{cid}").json()["tool_calls"]
        assert why in json.loads(calls[number]["arguments"])["reason"], calls[number]
    wait_run(client, cid, run_id)
    assert answers(copilot_native) == [("shell", REJECT)] * 3
    assert not (project_dir / ".github").exists()


def test_at_auto_edit_copilots_read_only_word_can_only_make_a_command_asked(
    copilot_native, wait_run, project_dir  # noqa: F811
):
    """K-copilot-ayristirma: a command KOLONİ takes for a read is asked once Copilot says it
    is not read-only; Copilot's "read-only" never lets one through that KOLONİ would ask."""
    client, provider = copilot_native([
        {"shell": "Get-Content hello.py", "readonly": True},
        {"shell": "python fix.py", "readonly": True},
        {"shell": "Get-Content hello.py", "readonly": False},
        {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider, mode="auto_edit")
    for command in ("python fix.py", "Get-Content hello.py"):
        for _ in range(500):
            waiting = [c for c in client.get(f"/api/conversations/{cid}").json()["commands"]
                       if c["status"] == "proposed"]
            if waiting:
                break
            time.sleep(0.02)
        (card,) = waiting
        assert card["command"] == command
        client.post(f"/api/commands/{card['id']}/reject")
    wait_run(client, cid, run_id)
    assert answers(copilot_native) == [("shell", APPROVE), ("shell", REJECT), ("shell", REJECT)]


def test_a_command_naming_only_ordinary_paths_runs_unasked_at_full_auto(
    copilot_native, wait_run, project_dir  # noqa: F811
):
    client, provider = copilot_native([
        {"shell": "python hello.py > out.txt", "paths": ["hello.py", "out.txt"],
         "redirect": True}, {"say": "ok"}])
    statuses = watched(client)
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert answers(copilot_native) == [("shell", APPROVE)]
    nothing_was_asked(snap, statuses)


def test_unattended_a_command_naming_a_secret_is_refused_though_its_trigger_allows_it(
    copilot_native, wait_run, project_dir  # noqa: F811
):
    (project_dir / ".env").write_text("TOKEN=x\n", encoding="utf-8")
    client, provider = copilot_native([
        {"shell": "pytest -q", "paths": [".env"]}, {"say": "done"}])
    snap, run, statuses = unattended(
        client, project_dir, provider, "full_auto", wait_run, commands=["pytest -q"])
    assert answers(copilot_native) == [("shell", REJECT)]
    assert NOBODY in snap["tool_calls"][0]["result"]
    nothing_was_asked(snap, statuses)


# --- 12. Asking to go outside its sandbox is a card at every level (K-sandbox-disari) -----------


def test_at_full_auto_a_command_or_a_read_asking_to_leave_its_sandbox_is_a_card(
    copilot_native, wait_run, project_dir  # noqa: F811
):
    client, provider = copilot_native([
        {"shell": "pytest -q", "bypass": "the sandbox blocked it"},
        {"read": "hello.py", "bypass": "outside the readable paths"}, {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)
    (asked,) = wait_status(client, cid, "waiting_approval")["commands"]
    assert asked["status"] == "proposed"
    client.post(f"/api/commands/{asked['id']}/reject")
    read = question(client, cid, 1)
    assert "outside the readable paths" in read["question"]
    client.post(f"/api/questions/{read['id']}/answer", json={"answer": "Deny"}, headers=ORIGIN)
    snap = wait_run(client, cid, run_id)
    assert answers(copilot_native) == [("shell", REJECT), ("read", REJECT)]
    call = json.loads(snap["tool_calls"][0]["arguments"])
    assert call["reason"] == "the sandbox blocked it"


def test_unattended_asking_to_leave_its_sandbox_is_refused_though_its_trigger_allows_it(
    copilot_native, wait_run, project_dir  # noqa: F811
):
    client, provider = copilot_native([
        {"shell": "pytest -q", "bypass": "the sandbox blocked it"},
        {"read": "hello.py", "bypass": "outside the readable paths"}, {"say": "done"}])
    snap, run, statuses = unattended(
        client, project_dir, provider, "full_auto", wait_run, commands=["pytest -q"])
    assert answers(copilot_native) == [("shell", REJECT), ("read", REJECT)]
    assert all(NOBODY in call["result"] for call in snap["tool_calls"])
    nothing_was_asked(snap, statuses)


def test_a_command_with_no_exit_code_is_no_success_and_a_python_its_sandbox_kept_is_blocked(
    copilot_native, wait_run, project_dir  # noqa: F811
):
    # B-377 (live): ".venv\Scripts\python.exe -m unittest" printed uv's trampoline error, Copilot
    # gave no exit code, and KOLONİ had the run "succeeded, no exit code reported".
    trampoline = ("uv trampoline failed to spawn Python child process: permission denied "
                  "(os error 5)")
    client, provider = copilot_native([
        {"shell": "python -m unittest", "output": trampoline, "no_code": True},
        {"shell": "pytest -q", "output": "cut off", "no_code": True}, {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    blocked, quiet = [t for t in snap["tool_calls"] if t["name"] == "run_command"]
    assert blocked["status"] == quiet["status"] == "failed"
    assert blocked["result"].startswith(
        "no exit code reported, blocked: Copilot's sandbox could not start Python: run tests "
        "with a sub-agent or in session mode\nuv trampoline failed"), blocked
    assert quiet["result"].startswith("no exit code reported\ncut off")
    assert [c["status"] for c in snap["commands"]] == ["blocked", "exited"]


# --- 10. A patch it sends as a PowerShell command (B-389, R184) ------------------------------


def here_string(body, before="", after="", opening="@'", end="'@"):
    """The form R184 saw from Copilot native in PowerShell, unshortened in its head and tail."""
    return f"{before}{opening}\n*** Begin Patch\n{body}\n*** End Patch\n{end} | apply_patch{after}"


UPDATE_HELLO = "*** Update File: hello.py\n@@\n-print('hi')\n+print('hello')"


def test_a_powershell_here_string_piped_to_apply_patch_is_a_patch():
    changes = _heredoc_patch(here_string(UPDATE_HELLO), "C:/p", powershell=True)
    assert [(Path(p).name, how, diff) for p, how, diff in _files(changes)] == [
        ("hello.py", "update", "@@\n-print('hi')\n+print('hello')\n")]
    # PowerShell reads CRLF as one line break: the same lines, the same patch.
    assert _heredoc_patch(here_string(UPDATE_HELLO).replace("\n", "\r\n"), "C:/p",
                          powershell=True) == changes
    # (A quote in the patch is nothing to PowerShell's here-string - in bash it would end it.)
    assert _heredoc_patch(here_string(UPDATE_HELLO), "C:/p") is None
    assert _heredoc_patch(heredoc(ADD_B), "C:/p", powershell=True) is None


@pytest.mark.parametrize("command", [
    here_string(ADD_B, before="cd ..; "),                 # more before it
    here_string(ADD_B, after="; Remove-Item -Recurse x"),  # a second command
    here_string(ADD_B, after="\nrm -rf build"),           # more after it
    here_string(ADD_B, opening='@"', end='"@'),           # double-quoted: $(...) would run
    here_string(ADD_B + "\n'@ | Out-Null\nrm -rf build\n+x"),   # a line ends it early
    here_string(ADD_B + "\n  '@\nrm x\n+x"),
    here_string(ADD_B + "\n\u2019@\nrm x\n+x"),           # a typographic quote is one to it
    here_string(ADD_B + "\r'@\nrm x\n+x"),                # a lone CR
    here_string(ADD_B + "\u2028'@\nrm x\n+x"),            # a break only Unicode calls one
    here_string(ADD_B, after="\u2028"),                   # a blank only Unicode calls one
    here_string("*** Update File: a.py\n@@\n *** Add File: x.py\n+x"),   # a hidden header
    here_string("*** Add File: ../b.py\n+x"),             # out of the folder it runs in
    here_string("*** Add File: C:/b.py\n+x"),             # a whole path
])
def test_only_a_whole_single_quoted_here_string_to_apply_patch_is_a_patch(command):
    assert _heredoc_patch(command, "C:/p", powershell=True) is None


def test_at_auto_edit_copilots_powershell_patch_is_taken_as_a_patch_without_a_card(
    copilot_native, wait_run, project_dir  # noqa: F811
):
    client, provider = copilot_native([
        {"shell": here_string(UPDATE_HELLO), "touches": {"hello.py": "print('hello')\n"}},
        {"say": "Patched."}])
    statuses = watched(client)
    cid, run_id = start(client, project_dir, provider, mode="auto_edit")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert answers(copilot_native) == [("shell", APPROVE)]
    nothing_was_asked(snap, statuses)
    assert snap["commands"] == []  # on record as the patch it is, not a command
    assert [(t["name"], t["status"]) for t in snap["tool_calls"]] == [("edit_file", "succeeded")]
    assert [(f["path"], f["status"]) for f in snap["file_changes"]] == [("hello.py", "applied")]
    assert hello(project_dir) == "print('hello')\n"


def test_a_powershell_patch_copilot_asks_to_run_outside_its_sandbox_stays_a_command_card(
    copilot_native, wait_run, project_dir  # noqa: F811
):
    # (Its shell still starts: what makes a command a card at every level makes this one.)
    client, provider = copilot_native([
        {"shell": here_string(ADD_B), "touches": {"b.py": "x"}, "bypass": "outside the sandbox"},
        {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)  # full_auto
    asked = wait_status(client, cid, "waiting_approval")["commands"][0]
    assert asked["command"] == here_string(ADD_B) and asked["status"] == "proposed"
    client.post(f"/api/commands/{asked['id']}/reject")
    wait_run(client, cid, run_id)
    assert answers(copilot_native) == [("shell", REJECT)] and not (project_dir / "b.py").exists()


def test_copilots_powershell_patch_with_a_second_command_stays_a_command_card(
    copilot_native, wait_run, project_dir  # noqa: F811
):
    command = here_string(UPDATE_HELLO, after="; Remove-Item build")
    client, provider = copilot_native([
        {"shell": command, "touches": {"hello.py": "x"}}, {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider, mode="auto_edit")
    asked = wait_status(client, cid, "waiting_approval")["commands"][0]
    assert (asked["command"], asked["status"]) == (command, "proposed")
    client.post(f"/api/commands/{asked['id']}/reject")
    wait_run(client, cid, run_id)
    assert answers(copilot_native) == [("shell", REJECT)] and hello(project_dir) != "x"


def test_a_rejected_powershell_patch_writes_nothing_and_closes_its_card(
    copilot_native, wait_run, project_dir  # noqa: F811
):
    client, provider = copilot_native([
        {"shell": here_string(ADD_B), "touches": {"b.py": "x"}}, {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider, mode="ask")
    card = proposed(client, cid, "b.py")
    assert "+print('b')" in card["diff"]
    client.post(f"/api/file-changes/{card['id']}/reject")
    snap = wait_run(client, cid, run_id)
    assert answers(copilot_native) == [("shell", REJECT)] and not (project_dir / "b.py").exists()
    assert [(f["path"], f["status"]) for f in snap["file_changes"]] == [("b.py", "rejected")]
    assert snap["commands"] == []
    assert not [t for t in snap["tool_calls"] if t["status"] in ("pending", "running")]


# --- 11. The security review's probes (rev-r183): each stays a command ----------------------

UPDATE_A = "*** Update File: a.py\n@@\n"
# Each a line inside the patch, with a command after it that would run if the line ended it.
ENDS = ["\t'@", "\u00a0'@", "\u200b'@", "\ufeff'@", "\uff07@", "\u2032@", "\u2018@", "\u2019@",
        "\u201a@", "\u201b@", "\u201c@", "'\ufe6b", "'\uff20", "x\x85'@", "x\x0c'@", "x\x0b'@",
        "x\u2028'@", "x\x1c'@", "x\x1f'@", "x\x03", "x\x1a", "\x1b[201~", "x\x00", "x\x7f",
        "x\x08", "x\r'@"]
# A path a card would name otherwise than it is written, or that is no plain file in the folder.
ODD = ["b.py:evil", ".:evil", r".git.\hooks\pre-commit", r".git \config", "CON", "sub/NUL.txt",
       r"\\srv\share\x", "C:x", r"\x", "~/x", "$env:USERPROFILE/x", ".../x", ".. /x",
       ". ./x", "..:s/x", r"\\?\C:\x", "//?/C:/x", "a/..\t/x", "..\u00a0/x", "... /x",
       "  ../x", "AGENTS.md\u00a0", "AGENTS.md\u3000", "AGENTS.md\u2003", "AGENTS.md\x85"]


@pytest.mark.parametrize("line", ENDS)
def test_a_line_that_could_end_the_here_string_or_reach_a_console_stays_a_command(line):
    command = here_string(UPDATE_A + line + "\n Remove-Item -Recurse src")
    assert _heredoc_patch(command, "C:/p", powershell=True) is None


@pytest.mark.parametrize("path", ODD)
def test_an_odd_path_in_a_patch_stays_a_command_in_either_shell(path):
    for body in (f"*** Add File: {path}\n+x", f"*** Update File: a.py\n*** Move to: {path}\n@@\n+x"):
        assert _heredoc_patch(here_string(body), "C:/p", powershell=True) is None, body
        assert _heredoc_patch(heredoc(body), "C:/p") is None, body


@pytest.mark.parametrize("command", [
    here_string(ADD_B, after=" # x"), here_string(ADD_B, after=" `\nrm x"),
    here_string(ADD_B, after="; rm x"), here_string(ADD_B, after=" | iex"),
    here_string(ADD_B, after=" --% & calc"), here_string(ADD_B, before="& { "),
    here_string(ADD_B).replace("| apply_patch", "| iex"),
    here_string(ADD_B).replace("| apply_patch", "|\u00a0apply_patch"),
    here_string("*** Update File: a.py\n@@\n+x\n*** End of File"),
])
def test_anything_around_or_in_place_of_apply_patch_stays_a_command(command):
    assert _heredoc_patch(command, "C:/p", powershell=True) is None


@pytest.mark.parametrize("char", ["\x03", "\x1a", "\x1b", "\x00", "\x7f"])
def test_a_bash_heredoc_with_a_control_character_stays_a_command(char):
    assert _heredoc_patch(heredoc(f"{UPDATE_A} x{char}\n rm -rf src"), "C:/p") is None


def test_a_plain_patch_still_is_one_in_either_shell():
    assert _heredoc_patch(here_string(UPDATE_A + "+\tx"), "C:/p", powershell=True)
    assert _heredoc_patch(heredoc(UPDATE_A + "+\tx"), "C:/p")


@pytest.mark.parametrize("before", ["Set-Location sub", "cd ..", "Push-Location sub",
                                    "function apply_patch { calc }", "Set-Alias apply_patch calc",
                                    r"$env:PATH = 'C:\x;' + $env:PATH", r". .\setup.ps1",
                                    r".venv\Scripts\Activate.ps1", r".\setup.ps1",
                                    "& ./setup.ps1", "using module ./m.psm1",
                                    "Import-Module ./m.psm1", "ipmo m"])
def test_after_a_command_that_may_move_copilots_shell_a_patch_is_asked_as_a_command(
    copilot_native, wait_run, project_dir, before  # noqa: F811
):
    # (Review: its shell is one session - where it is, or what apply_patch is, may have changed.)
    client, provider = copilot_native([
        {"shell": before}, {"shell": here_string(ADD_B), "touches": {"b.py": "x"}},
        {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)  # full_auto: commands run unasked
    snap = wait_run(client, cid, run_id)
    assert [c["command"] for c in snap["commands"]] == [before, here_string(ADD_B)]


@pytest.mark.parametrize("shell_type", [None, "cmd"])
def test_a_here_string_in_a_shell_not_said_to_be_powershell_stays_a_command(
    copilot_native, wait_run, project_dir, shell_type  # noqa: F811
):
    client, provider = copilot_native([
        {"shell": here_string(ADD_B), "touches": {"b.py": "x"}, "shell_type": shell_type},
        {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider, mode="auto_edit")
    asked = wait_status(client, cid, "waiting_approval")["commands"][0]
    assert asked["command"] == here_string(ADD_B)
    client.post(f"/api/commands/{asked['id']}/reject")
    wait_run(client, cid, run_id)


@pytest.mark.parametrize(("shell_type", "patch"), [(None, False), ("powershell", False),
                                                    ("bash", True)])
def test_copilots_bash_heredoc_is_a_patch_only_where_its_shell_is_bash(
    copilot_native, wait_run, project_dir, shell_type, patch  # noqa: F811
):
    client, provider = copilot_native([
        {"shell": heredoc(ADD_B), "touches": {"b.py": "print('b')\n"},
         "shell_type": shell_type}, {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)  # full_auto
    snap = wait_run(client, cid, run_id)
    assert [c["command"] for c in snap["commands"]] == ([] if patch else [heredoc(ADD_B)])
    assert "write_file" in [t["name"] for t in snap["tool_calls"]]  # (asked, or changed by it)
