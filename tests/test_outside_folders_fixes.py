"""Slice 41's review round: what an independent review found open about folders outside
the project, each held shut. A user's secrets here are a fake home's (USERPROFILE), in the
test's own folder: nothing of this machine's is looked at."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.workspace import Workspace, WorkspaceError, opened, outside_folder
from tests.keyed import NO_ORIGIN
from tests.test_agent_writes import wait_status, write
from tests.test_chat_flow import text
from tests.test_claude_native import claude_app  # noqa: F401  (a fixture)
from tests.test_native_agent import native_app  # noqa: F401  (a fixture)
from tests.test_outside_folders_scenarios import conversation, converse, project, read
from tests.test_spawn import spawn
from tests.test_trigger_scenarios import finished, results, run_now, setup, trigger

ORIGIN = "http://127.0.0.1:8790"


@pytest.fixture
def other(tmp_path):
    folder = tmp_path / "other"
    folder.mkdir()
    (folder / "notes.md").write_text("other notes\n", encoding="utf-8")
    return folder


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A fake home with a key in its .ssh and a token in gh's settings."""
    home = tmp_path / "Users" / "me"
    (home / ".ssh").mkdir(parents=True)
    (home / ".ssh" / "id_test").write_text("SECRETLINE\n", encoding="utf-8")
    (home / ".config" / "gh").mkdir(parents=True)
    (home / ".config" / "gh" / "hosts.yml").write_text("oauth_token: SECRETLINE\n")
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("APPDATA", str(home / "AppData" / "Roaming"))
    return home


def pending(client, cid, name="read_file"):
    snap = wait_status(client, cid, "waiting_approval")
    return next(t for t in snap["tool_calls"] if t["name"] == name and t["status"] == "pending")


# --- C1: a folder that holds a place never opened is never opened ---------------------------


def test_a_folder_that_holds_a_secret_is_not_listed_nor_walked_into(home, project_dir):
    for holder in (home, home.parent, home / ".config"):
        with pytest.raises(WorkspaceError, match="never opened"):
            outside_folder(str(holder))
    # and should one get on a list by another way, a search in it does not go in there
    (home.parent / "shared.txt").write_text("SECRETLINE too, but not a secret")
    ws = Workspace(project_dir, also=[home.parent])
    walked = [str(path) for path in ws._walk(home.parent)]
    assert walked == [str(home.parent / "shared.txt")]  # nothing of the home, which holds .ssh


# --- I1: a hard link outside the project is not read, nor searched ---------------------------


def test_a_hard_link_outside_the_project_is_not_read_nor_searched(tmp_path, project_dir, other):
    hidden = tmp_path / "hidden.txt"
    hidden.write_text("SECRETLINE\n", encoding="utf-8")
    os.link(hidden, other / "h.txt")
    ws = Workspace(project_dir, also=[other])
    with pytest.raises(WorkspaceError, match="hard link"):
        ws.read_text(str(other / "h.txt"))
    assert ws.search("SECRETLINE", str(other)) == ([], False, 0, [])


# --- I2: the outside card is decided from the app's own page --------------------------------


def test_the_outside_card_is_decided_only_from_the_apps_own_page(make_client, project_dir, other):
    client, _model = make_client([read(other / "notes.md"), text("ok")])
    cid, _run_id = converse(client, project(client, project_dir), mode="full_auto")
    asked = pending(client, cid)
    refused = client.post(f"/api/tool-calls/{asked['id']}/approve", json={"scope": "folder"},
                          headers=NO_ORIGIN)
    assert refused.status_code == 403
    assert pending(client, cid)["id"] == asked["id"]                 # still waiting
    assert conversation(client, cid)["also_in"] == []


# --- I3: a project file named from a copy by its full path ---------------------------------


def test_a_sub_agent_in_a_copy_naming_a_project_file_in_full_is_told_to_use_its_copy(
    make_client, wait_run, project_dir
):
    client, _model = make_client({
        "Lead": [spawn("Coder", "change two files"), text("done")],
        "Coder": [write("a.txt", "a\n", "w1"),               # its copy is made here
                  write(str(project_dir / "hello.py"), "print('x')\n", "w2"),
                  text("wrote")],
    })
    cid, run_id = converse(client, project(client, project_dir), mode="full_auto")
    snap = wait_run(client, cid, run_id)
    (named,) = [t for t in snap["tool_calls"] if "hello.py" in t["arguments"]]
    assert named["status"] == "failed" and "relative to your working copy" in named["result"]
    assert (project_dir / "hello.py").read_text(encoding="utf-8") == "print('hi')\n"


# --- I4 and M7: what "Allow this folder" opens is on the card -------------------------------


def test_the_card_names_the_folder_and_a_new_folder_is_allowed_once_only(
    make_client, wait_run, project_dir, other
):
    client, _model = make_client([read(other / "notes.md", "r1"),
                                  write(str(other / "new" / "x.md"), "x\n", "w"), text("ok")])
    cid, run_id = converse(client, project(client, project_dir), mode="full_auto")
    first = pending(client, cid)
    assert first["outside_folder"] == str(other)
    client.post(f"/api/tool-calls/{first['id']}/approve", json={"scope": "once"},
                headers={"Origin": ORIGIN})
    second = pending(client, cid, "write_file")
    assert second["outside_folder"] is None                   # not there yet: nothing to open
    client.post(f"/api/tool-calls/{second['id']}/approve", json={"scope": "folder"},
                headers={"Origin": ORIGIN})
    wait_run(client, cid, run_id)
    assert (other / "new" / "x.md").read_text(encoding="utf-8") == "x\n"
    assert conversation(client, cid)["also_in"] == []         # allowed that once


# --- M4: an unattended write outside goes by where it really is ------------------------------


@pytest.mark.skipif(sys.platform != "win32", reason="junctions are Windows'")
def test_an_unattended_write_through_a_link_into_a_listed_folders_git_is_refused(
    make_client, wait_run, project_dir, other
):
    """By its name an ordinary file; where it really is, one of git's hooks."""
    (other / ".git" / "hooks").mkdir(parents=True)
    made = subprocess.run(["cmd", "/c", "mklink", "/J", str(other / "door"), str(other / ".git")],
                          capture_output=True, text=True)
    if made.returncode != 0:
        pytest.skip(made.stderr)
    client, _model, pid, cid = setup(make_client, project_dir, {"Lead": [
        write(str(other / "door" / "hooks" / "pre-commit"), "x", "w"), text("ok")]})
    assert client.patch(f"/api/projects/{pid}", json={"also_in": [str(other)]}).status_code == 200
    made = trigger(client, pid, cid, permissions={"write": True, "commands": [], "agents": 0})
    snap = finished(client, wait_run, cid, run_now(client, made["id"]))
    ((_name, status, _said),) = results(snap, snap["runs"][-1]["id"])
    assert status == "denied" and not (other / ".git" / "hooks" / "pre-commit").exists()


# --- I7: an agent is told where else it works -----------------------------------------------


def test_the_agent_is_told_the_folders_it_also_works_in(make_client, wait_run, project_dir, other):
    client, model = make_client([text("ok"), text("ok")])
    pid = project(client, project_dir)
    cid, run_id = converse(client, pid)
    wait_run(client, cid, run_id)
    assert "also work in" not in model.calls[0][0]["content"]  # (none: as it always was)
    # (the chat's own list since slice 86b: its folder's is a new chat's)
    client.patch(f"/api/conversations/{cid}", json={"also_in": [str(other)]},
                 headers={"Origin": ORIGIN})
    run = client.post(f"/api/conversations/{cid}/messages", json={"content": "again"}).json()
    wait_run(client, cid, run["run"]["id"])
    assert f"You also work in these folders outside the project, as you do in it: {other}" in (
        model.calls[1][0]["content"])


# --- I6: Codex is given the folders too ------------------------------------------------------


def test_codex_is_given_the_folders_as_writable_roots(native_app, wait_run, project_dir, other):  # noqa: F811
    client, provider, _ = native_app([{"say": "Looked."}])
    pid = project(client, project_dir, also_in=[str(other)])
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(f"/api/conversations/{cid}", json={
        "permission_mode": "full_auto", "provider_id": provider["id"]}, headers={"Origin": ORIGIN})
    run = client.post(f"/api/conversations/{cid}/messages", json={"content": "look"}).json()
    wait_run(client, cid, run["run"]["id"])
    # (as --add-dir was, in its turn/start since slice 89a)
    assert native_app.record()["turn"]["sandboxPolicy"]["writableRoots"] == [str(other)]


# --- C2 and I5: Claude Code's own reads and writes outside the project ------------------------


def native(client, provider, project_dir, mode, **patch):
    pid = project(client, project_dir, **patch)
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(f"/api/conversations/{cid}", json={
        "permission_mode": mode, "provider_id": provider["id"]}, headers={"Origin": ORIGIN})
    run = client.post(f"/api/conversations/{cid}/messages", json={"content": "go"}).json()
    return cid, run["run"]["id"]


def test_claude_codes_own_read_of_a_secret_is_refused_and_elsewhere_asked(
    claude_app, wait_run, project_dir, other, home  # noqa: F811
):
    client, provider, _ = claude_app([
        {"tool": "Read", "input": {"file_path": str(home / ".ssh" / "id_test")}},
        {"tool": "Read", "input": {"file_path": str(other / "notes.md")}},
        {"say": "done"}], model="claude-sonnet-5-5")
    cid, run_id = native(client, provider, project_dir, "full_auto")
    asked = pending(client, cid)                    # the second: asked, at Full auto too
    assert asked["outside_folder"] == str(other)
    client.post(f"/api/tool-calls/{asked['id']}/approve", json={"scope": "once"},
                headers={"Origin": ORIGIN})
    wait_run(client, cid, run_id)
    verdicts = [v["behavior"] for v in claude_app.record()["asked"]]
    assert verdicts == ["deny", "allow"]
    assert "never opened" in claude_app.record()["asked"][0]["message"]


@pytest.mark.parametrize("mode", ["ask", "auto_edit"])
def test_claude_codes_write_in_a_listed_folder_is_on_record_and_asked_as_the_level_says(
    claude_app, wait_run, project_dir, other, mode  # noqa: F811
):
    target = str(other / "notes.md")
    client, provider, _ = claude_app([
        {"tool": "Write", "input": {"file_path": target, "content": "new\n"},
         "write": [target, "new\n"]},
        {"say": "done"}], model="claude-sonnet-5-5")
    cid, run_id = native(client, provider, project_dir, mode, also_in=[str(other)])
    if mode == "ask":
        change = wait_status(client, cid, "waiting_approval")["file_changes"][0]
        assert change["status"] == "proposed"
        assert client.post(f"/api/file-changes/{change['id']}/approve").status_code == 200
    snap = wait_run(client, cid, run_id)
    (change,) = snap["file_changes"]
    assert (Path(change["path"]), change["status"]) == (other / "notes.md", "applied")
    assert "+new" in change["diff"] and (other / "notes.md").read_text() == "new\n"
    assert not [t for t in snap["tool_calls"] if t["status"] == "pending"]


@pytest.mark.skipif(sys.platform != "win32", reason="junctions are Windows'")
def test_the_card_names_where_a_link_really_leads(make_client, project_dir, other, tmp_path):
    beyond = tmp_path / "beyond"
    beyond.mkdir()
    (beyond / "b.md").write_text("b\n", encoding="utf-8")
    made = subprocess.run(["cmd", "/c", "mklink", "/J", str(other / "door"), str(beyond)],
                          capture_output=True, text=True)
    if made.returncode != 0:
        pytest.skip(made.stderr)
    client, _model = make_client([read(other / "door" / "b.md"), text("ok")])
    cid, _run_id = converse(client, project(client, project_dir), mode="full_auto")
    assert pending(client, cid)["outside_folder"] == str(beyond)


# --- re-review: "~" is the home folder, as Claude Code reads it; Glob's pattern is a path ----


def test_claude_codes_tilde_paths_are_judged_as_the_home_they_name(
    claude_app, wait_run, project_dir, home  # noqa: F811
):
    (home / "work").mkdir()
    client, provider, _ = claude_app([
        {"tool": "Read", "input": {"file_path": "~/.ssh/id_test"}},
        {"tool": "Grep", "input": {"pattern": "S", "path": r"~\.ssh"}},
        {"tool": "Glob", "input": {"pattern": f"{home.as_posix()}/.ssh/*"}},
        {"tool": "Glob", "input": {"pattern": "~/.ssh/*"}},
        {"tool": "Write", "input": {"file_path": "~/.ssh/authorized_keys",
                                                "content": "key"}},
        {"tool": "Read", "input": {"file_path": "~/work/notes.md"}},
        {"say": "done"}], model="claude-sonnet-5-5")
    cid, run_id = native(client, provider, project_dir, "full_auto")
    asked = pending(client, cid)                    # the last: a folder that may be opened
    assert asked["outside_folder"] == str(home / "work")
    client.post(f"/api/tool-calls/{asked['id']}/reject", headers={"Origin": ORIGIN})
    wait_run(client, cid, run_id)
    verdicts = claude_app.record()["asked"]
    assert [v["behavior"] for v in verdicts] == ["deny"] * 6, verdicts
    assert all("never opened" in v["message"] for v in verdicts[:5]), verdicts
    assert not (project_dir / "~").exists()


def test_a_glob_is_judged_from_its_own_path_and_braces_end_its_folder(
    claude_app, wait_run, project_dir, home, tmp_path  # noqa: F811
):
    (tmp_path / "Users" / "x").mkdir(parents=True)
    client, provider, _ = claude_app([
        # the pattern climbs out of its path, not out of the project
        {"tool": "Glob", "input": {"path": str(tmp_path / "Users" / "x"),
                                                "pattern": "../me/.ssh/*"}},
        # braces pick names as wildcards do: the folder is what comes before them
        {"tool": "Glob", "input": {"pattern": f"{home.as_posix()}/{{.ssh,a}}/id_test"}},
        {"say": "done"}], model="claude-sonnet-5-5")
    cid, run_id = native(client, provider, project_dir, "full_auto")
    wait_run(client, cid, run_id)
    verdicts = claude_app.record()["asked"]
    assert [v["behavior"] for v in verdicts] == ["deny", "deny"], verdicts
    assert all("never opened" in v["message"] for v in verdicts), verdicts


def test_a_path_with_a_root_and_no_drive_is_never_opened(home):
    drive = home.drive  # "C:" on Windows; the form below names a place there with no drive
    with pytest.raises(WorkspaceError):
        opened(f"\\??\\{drive}{(home / '.ssh' / 'id_test').as_posix()[len(drive):]}")
    with pytest.raises(WorkspaceError):
        opened(f"\\?\\{drive}\\x")


@pytest.mark.parametrize("mode", ["ask", "full_auto"])
def test_codex_is_given_the_listed_folders_at_every_level_now_that_it_asks(
    native_app, wait_run, project_dir, other, mode  # noqa: F811
):
    client, provider, _ = native_app([{"say": "Looked."}])
    pid = project(client, project_dir, also_in=[str(other)])
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(f"/api/conversations/{cid}", json={
        "permission_mode": mode, "provider_id": provider["id"]}, headers={"Origin": ORIGIN})
    run = client.post(f"/api/conversations/{cid}/messages", json={"content": "look"}).json()
    snap = wait_run(client, cid, run["run"]["id"])
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    # (each command and patch of it is asked about since slice 89a, there too)
    assert native_app.record()["turn"]["sandboxPolicy"]["writableRoots"] == [str(other)]
