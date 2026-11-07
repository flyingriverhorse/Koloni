"""Slice 75 beyond its acceptance set: how the lists add up, a command in a folder to read in
only, ask_folder's card, and what the native CLIs are given."""

import json
import os
from pathlib import Path

import pytest

from app.agent import NATIVE_FOLDER_CARD
from tests.test_agent_commands import cmd
from tests.test_agent_writes import wait_status, write
from tests.test_chat_flow import text
from tests.test_claude_native import claude_app  # noqa: F401  (a fixture)
from tests.test_native_agent import native_app  # noqa: F401  (a fixture)
from tests.test_outside_folders_scenarios import conversation, project, read
from tests.test_spawn import call, step

ORIGIN = {"Origin": "http://127.0.0.1:8790"}


@pytest.fixture
def shelf(tmp_path):
    folder = tmp_path / "shelf"
    (folder / "inner").mkdir(parents=True)
    (folder / "notes.md").write_text("shelf notes\n", encoding="utf-8")
    return folder


def ask_folder(path, access, why="to read the shared notes", id="a"):
    return step(call("ask_folder", {"path": str(path), "access": access, "why": why}, id))


def start(client, pid, mode="full_auto"):
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(f"/api/conversations/{cid}", json={"permission_mode": mode,
                 "lead_hands_code": False}, headers=ORIGIN)
    run = client.post(f"/api/conversations/{cid}/messages", json={"content": "go"}).json()
    return cid, run["run"]["id"]


# --- the lists ---------------------------------------------------------------------------------


def lists(client, project_dir, **patch):
    """A project's folder lists set as given: the answer, refused or not."""
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    return client.patch(f"/api/projects/{pid}", headers=ORIGIN, json=patch)


def test_a_network_path_is_refused_in_the_lists(client, project_dir):
    network = "\\\\server\\share" if os.name == "nt" else "//server/share"
    refused = lists(client, project_dir, read_in=[network])
    assert refused.status_code == 422 and "network" in refused.text


def test_a_write_folder_inside_a_read_folder_is_written_in(make_client, wait_run, project_dir,
                                                         shelf):
    client, _model = make_client([write(str(shelf / "inner" / "out.md"), "x\n"), text("ok")])
    pid = project(client, project_dir, read_in=[str(shelf)], also_in=[str(shelf / "inner")])
    cid, run_id = start(client, pid)
    snap = wait_run(client, cid, run_id)
    assert snap["tool_calls"][0]["status"] == "succeeded"
    assert (shelf / "inner" / "out.md").read_text(encoding="utf-8") == "x\n"


def test_a_command_run_in_a_folder_to_read_in_is_asked_for_at_full_auto(make_client, project_dir,
                                                                        shelf):
    client, _model = make_client([cmd("echo hi", cwd=str(shelf)), text("ok")])
    pid = project(client, project_dir, read_in=[str(shelf)])
    cid, _run_id = start(client, pid)
    snap = wait_status(client, cid, "waiting_approval")
    (tool,) = snap["tool_calls"]
    assert tool["name"] == "run_command" and tool["status"] == "pending"


def test_an_agent_is_told_the_folders_to_read_in(make_client, wait_run, project_dir, shelf):
    client, model = make_client([text("ok")])
    pid = project(client, project_dir, read_in=[str(shelf)])
    cid, run_id = start(client, pid)
    wait_run(client, cid, run_id)
    assert f"You may also read in these folders outside the project: {shelf}" in (
        model.calls[0][0]["content"])


# --- ask_folder --------------------------------------------------------------------------------


def test_asked_for_to_read_and_approved_it_is_read_in_and_written_in_only_when_asked(
    make_client, project_dir, shelf
):
    client, _model = make_client([ask_folder(shelf, "read"), read(shelf / "notes.md"),
                                  write(str(shelf / "out.md"), "x\n", id="w"), text("ok")])
    pid = project(client, project_dir)
    cid, _run_id = start(client, pid)
    snap = wait_status(client, cid, "waiting_approval")
    (asked,) = snap["tool_calls"]
    assert asked["name"] == "ask_folder" and asked["status"] == "pending"
    assert client.post(f"/api/tool-calls/{asked['id']}/approve", json={"scope": "folder"},
                       headers=ORIGIN).status_code == 200
    snap = wait_status(client, cid, "waiting_approval")       # the write, at Full auto
    assert [t["status"] for t in snap["tool_calls"]] == ["succeeded", "succeeded", "pending"]
    assert "shelf notes" in snap["tool_calls"][1]["result"]
    assert conversation(client, cid)["read_in"] == [str(shelf)]
    assert conversation(client, cid)["also_in"] == []
    assert not (shelf / "out.md").exists()


def test_asked_for_and_denied_nothing_is_added(make_client, wait_run, project_dir, shelf):
    client, _model = make_client([ask_folder(shelf, "write"), text("ok")])
    pid = project(client, project_dir)
    cid, run_id = start(client, pid)
    (asked,) = wait_status(client, cid, "waiting_approval")["tool_calls"]
    client.post(f"/api/tool-calls/{asked['id']}/reject", headers=ORIGIN)
    snap = wait_run(client, cid, run_id)
    assert snap["tool_calls"][0]["status"] == "denied"
    assert conversation(client, cid)["also_in"] == conversation(client, cid)["read_in"] == []


def test_asked_for_to_write_a_bare_yes_is_this_time_and_puts_nothing_on_a_list(
    make_client, wait_run, project_dir, shelf
):
    client, _model = make_client([ask_folder(shelf, "write"),
                                  write(str(shelf / "out.md"), "x\n", id="w"), text("ok")])
    pid = project(client, project_dir)
    cid, run_id = start(client, pid)
    (asked,) = wait_status(client, cid, "waiting_approval")["tool_calls"]
    client.post(f"/api/tool-calls/{asked['id']}/approve", headers=ORIGIN)  # a bare yes
    snap = wait_run(client, cid, run_id)
    assert snap["tool_calls"][1]["status"] == "succeeded"  # at Full auto, as in the project
    assert (shelf / "out.md").read_text(encoding="utf-8") == "x\n"
    assert conversation(client, cid)["also_in"] == conversation(client, cid)["read_in"] == []


@pytest.mark.parametrize("path", [Path.home() / ".ssh", "\\\\server\\share", "relative/x"])
def test_a_folder_never_opened_is_refused_without_a_card(make_client, wait_run, project_dir, path):
    client, _model = make_client([ask_folder(path, "read"), text("ok")])
    pid = project(client, project_dir)
    cid, run_id = start(client, pid)
    snap = wait_run(client, cid, run_id)
    (tool,) = snap["tool_calls"]
    assert tool["status"] == "failed" and tool["outside_folder"] is None
    assert conversation(client, cid)["read_in"] == []


def test_a_folder_already_open_is_not_asked_for(make_client, wait_run, project_dir, shelf):
    client, _model = make_client([ask_folder(shelf / "inner", "read"), text("ok")])
    pid = project(client, project_dir, also_in=[str(shelf)])
    cid, run_id = start(client, pid)
    (tool,) = wait_run(client, cid, run_id)["tool_calls"]
    assert tool["status"] == "succeeded" and "already" in tool["result"]


def test_the_lead_and_the_planner_have_ask_folder(client):
    roles = {role["name"]: role["tools"] for role in client.get("/api/roles").json()}
    assert "ask_folder" in roles["Lead"] and "ask_folder" in roles["Planner"]
    assert "ask_folder" not in roles["Coder"]


def test_a_conversations_folder_to_read_in_is_changed_from_the_apps_own_page_only(
    make_client, wait_run, project_dir, shelf
):
    client, _model = make_client([ask_folder(shelf, "read"), text("ok")])
    pid = project(client, project_dir)
    cid, run_id = start(client, pid)
    (asked,) = wait_status(client, cid, "waiting_approval")["tool_calls"]
    client.post(f"/api/tool-calls/{asked['id']}/approve", json={"scope": "folder"}, headers=ORIGIN)
    wait_run(client, cid, run_id)
    refused = client.patch(f"/api/conversations/{cid}",
                           json={"read_in": [str(shelf), "C:\\other"]})
    assert refused.status_code == 403
    assert conversation(client, cid)["read_in"] == [str(shelf)]
    assert client.patch(f"/api/conversations/{cid}", json={"read_in": []}).status_code == 403
    client.patch(f"/api/conversations/{cid}", json={"read_in": []}, headers=ORIGIN)
    assert conversation(client, cid)["read_in"] == []


# --- the native CLIs ---------------------------------------------------------------------------


def native(client, provider, project_dir, mode, **patch):
    pid = project(client, project_dir, **patch)
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(f"/api/conversations/{cid}", json={
        "permission_mode": mode, "provider_id": provider["id"], "lead_hands_code": False},
        headers=ORIGIN)
    run = client.post(f"/api/conversations/{cid}/messages", json={"content": "go"}).json()
    return cid, run["run"]["id"]


def added(argv):
    return [argv[i + 1] for i, word in enumerate(argv) if word == "--add-dir"]


def test_claude_code_reads_a_folder_to_read_in_unasked_and_asks_to_write_there(
    claude_app, wait_run, project_dir, shelf, tmp_path  # noqa: F811
):
    other = tmp_path / "other"
    other.mkdir()
    client, provider, _ = claude_app([
        {"tool": "Read", "input": {"file_path": str(shelf / "notes.md")}},
        {"tool": "Write", "input": {"file_path": str(shelf / "out.md"),
                                                 "content": "x"}},
        {"say": "done"}])
    cid, run_id = native(client, provider, project_dir, "full_auto", read_in=[str(shelf)],
                         also_in=[str(other)])
    snap = wait_status(client, cid, "waiting_approval")
    (asked,) = [t for t in snap["tool_calls"] if t["status"] == "pending"]
    assert asked["name"] == "edit_file" and "out.md" in asked["arguments"]
    client.post(f"/api/tool-calls/{asked['id']}/reject", headers=ORIGIN)
    wait_run(client, cid, run_id)
    record = claude_app.record()
    assert [said["behavior"] for said in record["asked"]] == ["allow", "deny"]
    # Only the folder to write in is handed over: in one it is given it may write unasked.
    assert added(record["argv"]) == [str(other)]


def test_codex_is_given_only_the_folder_to_write_in_and_told_of_the_one_to_read_in(
    native_app, wait_run, project_dir, shelf, tmp_path  # noqa: F811
):
    other = tmp_path / "other"
    other.mkdir()
    client, provider, _ = native_app([{"say": "Looked."}])
    cid, run_id = native(client, provider, project_dir, "full_auto", read_in=[str(shelf)],
                         also_in=[str(other)])
    wait_run(client, cid, run_id)
    seen = native_app.record()
    # Only the folder to write in is made writable for it; a command of it is asked about.
    assert seen["turn"]["sandboxPolicy"] == {"type": "workspaceWrite",
                                             "writableRoots": [str(other)]}
    document = json.loads(seen["stdin"][seen["stdin"].index("\n\n{") + 2:])
    assert f"You may also read in these folders outside the project: {shelf}" in (
        document["instructions"])


# --- a broad folder that holds a place never opened (the Desktop holding KOLONİ's runtime) ----


@pytest.fixture
def desk(tmp_path, monkeypatch):
    """A folder that holds a place KOLONİ never opens: here a KOLONİ runtime (KOLONI_RUNTIME_ROOT),
    which a search made in a process of its own sees as well."""
    desk = tmp_path / "desk"
    (desk / "runtime").mkdir(parents=True)
    (desk / "runtime" / "keys.md").write_text("SECRETLINE\n", encoding="utf-8")
    (desk / "work").mkdir()
    (desk / "notes.md").write_text("desk notes SECRETLINE-free\n", encoding="utf-8")
    (desk / "work" / "plan.md").write_text("the plan\n", encoding="utf-8")
    monkeypatch.setenv("KOLONI_RUNTIME_ROOT", str(desk / "runtime"))
    return desk


def test_a_folder_that_holds_a_place_never_opened_can_be_listed_but_not_the_place(
    client, project_dir, desk
):
    done = lists(client, project_dir, read_in=[str(desk)])
    assert done.status_code == 200, done.text
    for bad in (desk / "runtime", desk / "runtime" / "inner"):
        (desk / "runtime" / "inner").mkdir(exist_ok=True)
        refused = lists(client, project_dir, read_in=[str(bad)])
        assert refused.status_code == 422 and "never opened" in refused.text


@pytest.mark.parametrize("bad", [Path.home(), Path.home().parent, Path(Path.home().anchor)])
def test_the_home_a_folder_that_holds_it_and_a_drive_root_are_never_listed(
    client, project_dir, bad
):
    assert lists(client, project_dir, read_in=[str(bad)]).status_code == 422


def test_in_such_a_folder_the_tools_pass_the_place_by(make_client, wait_run, project_dir, desk):
    client, _model = make_client([
        step(call("search", {"pattern": "SECRETLINE|plan", "path": str(desk)}, "s")),
        step(call("list_dir", {"path": str(desk)}, "l")),
        read(desk / "notes.md", "r1"),
        read(desk / "runtime" / "keys.md", "r2"),
        text("done")])
    pid = project(client, project_dir, read_in=[str(desk)])
    cid, run_id = start(client, pid)
    search, listed, notes, keys = wait_run(client, cid, run_id)["tool_calls"]
    assert search["status"] == "succeeded" and "plan.md" in search["result"]
    assert "keys.md" not in search["result"]
    assert "runtime" not in listed["result"] and "work" in listed["result"]
    assert notes["status"] == "succeeded" and "desk notes" in notes["result"]
    assert keys["status"] == "failed" and "never opened" in keys["result"]


def test_a_folder_named_in_the_users_message_may_hold_such_a_place(make_client, wait_run,
                                                                   project_dir, desk):
    client, _model = make_client([text("ok")])
    pid = project(client, project_dir)
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    run = client.post(f"/api/conversations/{cid}/messages",
                      json={"content": f"look in {desk} and {desk / 'runtime'}"},
                      headers=ORIGIN).json()
    wait_run(client, cid, run["run"]["id"])
    assert conversation(client, cid)["read_in"] == [str(desk)]


def test_asked_for_such_a_folder_is_carded_and_the_place_in_it_refused(make_client, wait_run,
                                                                       project_dir, desk):
    client, _model = make_client([ask_folder(desk / "runtime", "read", id="a1"),
                                  ask_folder(desk, "read", id="a2"), text("ok")])
    pid = project(client, project_dir)
    cid, _run_id = start(client, pid)
    snap = wait_status(client, cid, "waiting_approval")
    refused, asked = snap["tool_calls"]
    assert refused["status"] == "failed" and refused["outside_folder"] is None
    assert asked["status"] == "pending" and asked["outside_folder"] == str(desk)


def test_no_cli_is_given_such_a_folder_and_claude_code_may_not_read_in_it_itself(
    claude_app, wait_run, project_dir, desk  # noqa: F811
):
    client, provider, _ = claude_app([
        {"tool": "Read", "input": {"file_path": str(desk / "notes.md")}},
        {"tool": "Read", "input": {"file_path": str(desk / "work" / "plan.md")}},
        {"say": "done"}])
    cid, run_id = native(client, provider, project_dir, "full_auto", also_in=[str(desk)])
    wait_run(client, cid, run_id)
    record = claude_app.record()
    assert added(record["argv"]) == []
    # (KOLONİ's own tools only: a look at the folder itself would walk into the place.)
    assert [said["behavior"] for said in record["asked"]] == ["deny", "allow"]
    document = json.loads(record["stdin"][record["stdin"].index("\n\n{") + 2:])
    assert f"open to KOLONİ's own tools only, not to yours: {desk}" in document["instructions"]


# --- ask_folder for a CLI working with its own tools (K-75-kalan) ------------------------------


def said(record):
    """What KOLONİ's tools answered the CLI over MCP, as one text."""
    return json.dumps(record["results"], ensure_ascii=False)


def test_a_native_lead_asks_for_a_folder_on_the_same_card_and_reaches_it_in_that_turn(
    claude_app, wait_run, project_dir, shelf  # noqa: F811
):
    client, provider, _ = claude_app([
        {"koloni": "ask_folder", "args": {"path": str(shelf), "access": "write", "why": "notes"}},
        {"tool": "Read", "input": {"file_path": str(shelf / "notes.md")}},
        {"say": "done"}])
    cid, run_id = native(client, provider, project_dir, "full_auto")
    (asked,) = [t for t in wait_status(client, cid, "waiting_approval")["tool_calls"]
                if t["status"] == "pending"]
    assert asked["name"] == "ask_folder" and asked["outside_folder"] == str(shelf)
    # The card says its own tools work there unasked once it is the chat's.
    assert asked["why_asked"] == NATIVE_FOLDER_CARD.format(who="Claude Code")
    client.post(f"/api/tool-calls/{asked['id']}/approve", json={"scope": "folder"}, headers=ORIGIN)
    snap = wait_run(client, cid, run_id)
    record = claude_app.record()
    assert "ask_folder" in record["tools"]
    assert conversation(client, cid)["also_in"] == [str(shelf)]
    # Not handed over at its start: granted mid-turn, its read there is let through unasked.
    assert added(record["argv"]) == [] and [v["behavior"] for v in record["asked"]] == ["allow"]
    assert "Claude Code is given it as a folder of its own from its next turn" in said(record)
    assert not [t for t in snap["tool_calls"] if t["status"] == "pending"]


@pytest.mark.parametrize("where", ["profile", "local", "keys", "cli_home"])
def test_a_native_lead_is_refused_a_folder_never_opened_without_a_card(
    claude_app, wait_run, project_dir, tmp_path, monkeypatch, where  # noqa: F811
):
    local, roaming, home = tmp_path / "Local", tmp_path / "Roaming", tmp_path / "home"
    profile, keys = local / "Google/Chrome/User Data", roaming / "Microsoft/Protect"
    for folder in (profile, keys, home / ".codex"):
        folder.mkdir(parents=True)
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("APPDATA", str(roaming))
    monkeypatch.setenv("USERPROFILE", str(home))
    path = {"profile": profile, "local": local, "keys": keys, "cli_home": home / ".codex"}[where]
    client, provider, _ = claude_app([
        {"koloni": "ask_folder", "args": {"path": str(path), "access": "read", "why": "look"}},
        {"say": "done"}])
    cid, run_id = native(client, provider, project_dir, "full_auto")
    (tool,) = wait_run(client, cid, run_id)["tool_calls"]
    assert (tool["name"], tool["status"], tool["outside_folder"]) == ("ask_folder", "failed", None)
    assert "never" in tool["result"] or "holds" in tool["result"], tool["result"]
    assert conversation(client, cid)["read_in"] == []


def test_a_native_lead_nobody_watches_is_refused_a_folder(
    claude_app, wait_run, project_dir, shelf  # noqa: F811
):
    from tests.test_claude_native import NOBODY, unattended

    client, provider, _ = claude_app([
        {"koloni": "ask_folder", "args": {"path": str(shelf), "access": "read", "why": "notes"}},
        {"say": "done"}])
    snap, _run, statuses = unattended(client, project_dir, provider, "full_auto", wait_run)
    (tool,) = snap["tool_calls"]
    assert tool["name"] == "ask_folder" and tool["status"] != "succeeded"
    assert NOBODY in said(claude_app.record()) and "waiting_approval" not in statuses


def test_a_native_agent_in_a_working_copy_is_told_no_folder_can_reach_it(
    claude_app, wait_run, project_dir, shelf  # noqa: F811
):
    from tests.test_native_copies import LEAD, begin

    client, provider, _ = claude_app([
        {"koloni": "ask_folder", "args": {"path": str(shelf), "access": "read", "why": "notes"}},
        {"say": "done"}], default_steps=LEAD)
    coder = next(r for r in client.get("/api/roles").json() if r["name"] == "Coder")
    client.patch(f"/api/roles/{coder['id']}", json={"tools": [*coder["tools"], "ask_folder"]},
                 headers=ORIGIN)
    cid, run_id = begin(client, project_dir, provider)
    snap = wait_run(client, cid, run_id, timeout=20)
    (tool,) = [t for t in snap["tool_calls"] if t["name"] == "ask_folder"]
    assert tool["status"] == "failed" and "working copy" in tool["result"]
    assert tool["outside_folder"] is None


def test_a_native_lead_is_not_promised_a_folder_no_cli_is_given(
    claude_app, wait_run, project_dir, desk  # noqa: F811
):
    client, provider, _ = claude_app([
        {"koloni": "ask_folder", "args": {"path": str(desk), "access": "write", "why": "work"}},
        {"say": "done"}])
    cid, run_id = native(client, provider, project_dir, "full_auto")
    (asked,) = [t for t in wait_status(client, cid, "waiting_approval")["tool_calls"]
                if t["status"] == "pending"]
    assert asked["why_asked"] is None  # (no CLI is given it: nothing of its own works there)
    client.post(f"/api/tool-calls/{asked['id']}/approve", json={"scope": "folder"}, headers=ORIGIN)
    wait_run(client, cid, run_id)
    assert conversation(client, cid)["also_in"] == [str(desk)]
    told = said(claude_app.record())
    assert "from its next turn" not in told and "not given it as a folder of its own" in told


@pytest.mark.parametrize("wide", ["parent", "documents", "public"])
def test_a_folder_too_wide_to_ask_for_is_refused_without_a_card(
    make_client, wait_run, tmp_path, monkeypatch, wide
):
    """What holds the project, or lies straight in the home folder or its parent (Documents,
    C:\\Users\\Public): an agent asks for a folder inside it, or the user adds it by hand.
    (A drive root's own folders, C:\\ProgramData, by the same rule: not made here - no test
    looks at a real drive's root.)"""
    home, repos = tmp_path / "users" / "me", tmp_path / "repos"
    (home / "Documents" / "notes").mkdir(parents=True)
    (tmp_path / "users" / "Public").mkdir()
    (repos / "app").mkdir(parents=True)
    (repos / "app" / "hello.py").write_text("print('hi')\n", encoding="utf-8")
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    path = {"parent": repos, "documents": home / "Documents",
            "public": tmp_path / "users" / "Public"}[wide]
    client, _model = make_client([ask_folder(path, "read"), ask_folder(
        home / "Documents" / "notes", "read", id="b"), text("ok")])
    cid, _run_id = start(client, project(client, repos / "app"))
    snap = wait_status(client, cid, "waiting_approval")
    refused, asked = snap["tool_calls"]
    assert refused["status"] == "failed" and refused["outside_folder"] is None
    assert "too wide" in refused["result"], refused["result"]
    # (A folder inside it is asked for on the card, as before.)
    assert asked["status"] == "pending" and asked["outside_folder"] == str(home / "Documents" /
                                                                             "notes")
