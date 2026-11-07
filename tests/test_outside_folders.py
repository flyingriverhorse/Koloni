"""Slice 41's own pieces, beside its acceptance set (`test_outside_folders_scenarios`): the
workspace's way out of the project, the folders a message names, and what only takes a
folder off a conversation's list."""

import json
import os
import sqlite3
from pathlib import Path

import pytest
from alembic import command as alembic

from app.workspace import Outside, Workspace, WorkspaceError, named_folders, opened, outside_folder
from tests.test_agent_writes import wait_status
from tests.test_chat_flow import text
from tests.test_migration_0002 import _config
from tests.test_spawn import call, spawn, step
from tests.test_trigger_scenarios import NOBODY, finished, results, run_now, setup, trigger

ORIGIN = "http://127.0.0.1:8790"
HOME = Path(os.path.expanduser("~"))  # the real one: what a test makes of Path.home() is not


@pytest.fixture
def other(tmp_path):
    folder = tmp_path / "other"
    folder.mkdir()
    (folder / "notes.md").write_text("other notes\n", encoding="utf-8")
    return folder


def test_a_path_is_in_the_project_in_a_listed_folder_or_outside(project_dir, other):
    ws = Workspace(project_dir)
    # an absolute path into the project is the project's, and named as it always was
    assert ws.rel(ws.resolve(str(project_dir / "hello.py"))) == "hello.py"
    with pytest.raises(Outside) as outside:
        ws.resolve(str(other / "notes.md"))
    assert outside.value.folder == other                    # a file's folder is what is asked
    with pytest.raises(Outside) as outside:
        ws.resolve("../other")
    assert outside.value.folder == other                    # a folder is its own
    listed = Workspace(project_dir, also=[other])
    assert listed.rel(listed.resolve(str(other / "notes.md"))) == str(other / "notes.md")
    # the search runs in a process of its own: it is given the list too
    matches, _, _, _ = listed.search("other", str(other))
    assert matches == [(str(other / "notes.md"), 1, "other notes")]


def test_what_is_never_opened_is_refused_whatever_the_list_says(project_dir, tmp_path):
    drive_root = Path(tmp_path.anchor)
    ws = Workspace(project_dir, also=[drive_root, HOME])     # (no list can hold these)
    for path in (str(HOME / ".ssh" / "koloni-test-none"), str(drive_root / "koloni-x.txt"),
                 str(HOME / "koloni-test-none.md"),
                 "\\\\host\\share\\x" if os.name == "nt" else "//host/share/x"):
        with pytest.raises(WorkspaceError, match="never opened"):
            ws.resolve(path)


def test_a_file_in_the_home_folder_is_refused_for_its_folder():
    # B-194 (live): it was "'…\\koloni-test-none.md' is never opened: it holds …\\.claude"
    with pytest.raises(WorkspaceError, match=r"never opened: its folder .* holds "):
        opened(str(HOME / "koloni-test-none.md"))


@pytest.mark.parametrize("bad", ["relative", "\\\\host\\share", str(HOME / ".aws")])
def test_a_folder_for_the_list_is_absolute_local_and_openable(bad):
    with pytest.raises(WorkspaceError):
        outside_folder(bad)


def test_the_folders_a_message_names(tmp_path, other):
    spaced = tmp_path / "with space"
    spaced.mkdir()
    message = (
        f"Fix {other / 'notes.md'}, then look in `{spaced}`. Not {HOME / '.ssh' / 'x'}, "
        f"not {tmp_path.anchor}x.txt, not {tmp_path / 'gone' / 'deeper'}, nor src/app.py."
    )
    assert named_folders(message) == [other, spaced]


@pytest.mark.skipif(os.name == "nt", reason="paths from the root are named on Linux and macOS")
def test_what_is_no_folder_from_the_root_in_a_message(other):
    # (a URL's, one inside a word or a relative path, the root's own file, the system's /proc)
    message = (f"see https:/{other} or x{other}, ./{other.name}, ../{other.name}, ~/x, "
               f"/x.txt, /proc/self/environ and `{other}`")
    assert named_folders(message) == [other]


def test_a_conversations_list_is_added_to_from_the_apps_own_page_only(make_client, project_dir,
                                                                     other):
    client, _model = make_client([])
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    refused = client.patch(f"/api/conversations/{cid}", json={"also_in": [str(other)]})
    assert refused.status_code == 403
    patched = client.patch(f"/api/conversations/{cid}", json={"also_in": [str(other)]},
                           headers={"Origin": ORIGIN})
    assert patched.status_code == 200 and patched.json()["also_in"] == [str(other)]


def test_an_unattended_turn_asks_nobody_and_does_not_go_outside(
    make_client, wait_run, project_dir, other
):
    client, _model, pid, cid = setup(make_client, project_dir, {
        "Lead": [step(call("read_file", {"path": str(other / "notes.md")}, "r")), text("ok")]})
    run_id = run_now(client, trigger(client, pid, cid)["id"])
    snap = finished(client, wait_run, cid, run_id)
    ((name, status, said),) = results(snap, run_id)
    assert status == "denied" and NOBODY in said


def test_a_change_outside_the_project_is_reverted_where_it_is(
    make_client, wait_run, project_dir, other
):
    client, _model = make_client([
        step(call("write_file", {"path": str(other / "notes.md"), "content": "new\n"}, "w")),
        text("done")])
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    client.patch(f"/api/projects/{pid}", json={"also_in": [str(other)]},
                 headers={"Origin": ORIGIN})
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(f"/api/conversations/{cid}", json={"permission_mode": "auto_edit",
                 "lead_hands_code": False},  # (the Lead writes itself: slice 48's default off)
                 headers={"Origin": ORIGIN})
    run = client.post(f"/api/conversations/{cid}/messages", json={"content": "go"}).json()
    (change,) = wait_run(client, cid, run["run"]["id"])["file_changes"]
    assert (other / "notes.md").read_text(encoding="utf-8") == "new\n"
    reverted = client.post(f"/api/file-changes/{change['id']}/revert")
    assert reverted.status_code == 200, reverted.text
    assert (other / "notes.md").read_text(encoding="utf-8") == "other notes\n"


def test_a_sub_agents_write_outside_is_asked_for_and_goes_where_it_is_not_in_its_copy(
    make_client, wait_run, project_dir, other
):
    """Its copy has none of the folders the project also works in: a write there is asked
    about, at Full auto too, and once allowed made in the folder itself."""
    client, _model = make_client({
        "Lead": [spawn("Coder", "write the notes"), text("done")],
        "Coder": [step(call("write_file", {"path": str(other / "out.md"), "content": "x\n"}, "w")),
                  text("wrote it")],
    })
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    client.patch(f"/api/projects/{pid}", json={"also_in": [str(other)]},
                 headers={"Origin": ORIGIN})
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(f"/api/conversations/{cid}", json={"permission_mode": "full_auto"},
                 headers={"Origin": ORIGIN})
    run_id = client.post(f"/api/conversations/{cid}/messages", json={"content": "go"}).json()[
        "run"]["id"]
    snap = wait_status(client, cid, "waiting_approval")
    (write,) = [t for t in snap["tool_calls"] if t["name"] == "write_file"]
    assert write["status"] == "pending"
    assert client.post(f"/api/tool-calls/{write['id']}/approve", json={"scope": "once"},
                       headers={"Origin": ORIGIN}).status_code == 200
    snap = wait_run(client, cid, run_id)
    assert (other / "out.md").read_text(encoding="utf-8") == "x\n"
    (change,) = snap["file_changes"]
    assert Path(change["path"]) == other / "out.md" and change["status"] == "applied"
    assert "out.md" not in json.dumps(snap["merges"])


def test_migration_0045_and_back(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    alembic.upgrade(cfg, "0044")
    alembic.upgrade(cfg, "0045")

    def columns(conn, table):
        return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]

    with sqlite3.connect(db) as conn:
        assert "also_in" in columns(conn, "projects") and "also_in" in columns(conn, "conversations")
        assert "outside_folder" in columns(conn, "tool_calls")
    alembic.downgrade(cfg, "0044")
    with sqlite3.connect(db) as conn:
        assert "also_in" not in columns(conn, "projects") + columns(conn, "conversations")
        assert "outside_folder" not in columns(conn, "tool_calls")
