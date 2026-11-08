"""Slice 86b, backend half: a chat's extra folders are its own, a new chat starts with its
folder's defaults, ask_folder's "This time" is that agent's only, and a chat with no folder
reads a file the user names on their word, once. Written before the code.

Design: `tasarim/specs/2026-10-23-dilim-86-klasorler-design.md`, §1, §3, §6 step 2 and §6b
("Klasörsüz sohbette dosya").
"""

import json
import os
import sqlite3
from pathlib import Path

from alembic import command

from tests.test_agent_writes import wait_status
from tests.test_chat_flow import text
from tests.test_folders import ORIGIN, ask_folder, shelf, start  # noqa: F401  (a fixture)
from tests.test_migration_0002 import _config
from tests.test_outside_folders_scenarios import conversation, project, read
from tests.test_plain_chat_scenarios import plain, say
from tests.test_spawn import call, step

AT = "2026-10-24 10:00:00"


def approve(client, call_id, scope="once"):
    done = client.post(f"/api/tool-calls/{call_id}/approve", json={"scope": scope},
                       headers=ORIGIN)
    assert done.status_code == 200, done.text


# --- a chat's own folders --------------------------------------------------------------------


def test_a_new_chat_starts_with_its_folders_defaults_and_keeps_its_own_after(
    make_client, wait_run, project_dir, shelf, tmp_path  # noqa: F811
):
    other = tmp_path / "other"
    other.mkdir()
    client, _model = make_client([read(shelf / "notes.md"), text("ok")])
    pid = project(client, project_dir, read_in=[str(shelf)], also_in=[str(other)])
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    assert conversation(client, cid)["read_in"] == [str(shelf)]
    assert conversation(client, cid)["also_in"] == [str(other)]
    # The folder's defaults changed later are a later chat's: this one keeps its own.
    client.patch(f"/api/projects/{pid}", json={"read_in": []}, headers=ORIGIN)
    assert conversation(client, cid)["read_in"] == [str(shelf)]
    run = client.post(f"/api/conversations/{cid}/messages", json={"content": "go"}).json()
    (tool,) = wait_run(client, cid, run["run"]["id"])["tool_calls"]
    assert tool["status"] == "succeeded" and "shelf notes" in tool["result"]


def test_a_default_taken_off_one_chat_is_closed_to_its_agents_only(
    make_client, project_dir, shelf  # noqa: F811
):
    client, _model = make_client([read(shelf / "notes.md"), text("ok")])
    pid = project(client, project_dir, read_in=[str(shelf)])
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(f"/api/conversations/{cid}", json={"read_in": []}, headers=ORIGIN)
    assert conversation(client, cid)["read_in"] == []
    client.post(f"/api/conversations/{cid}/messages", json={"content": "go"})
    (tool,) = wait_status(client, cid, "waiting_approval")["tool_calls"]
    assert tool["status"] == "pending"  # asked about again, as any folder outside
    other = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    assert conversation(client, other)["read_in"] == [str(shelf)]


def test_a_folder_to_read_in_is_taken_off_from_the_apps_own_page_only(
    client, project_dir, shelf  # noqa: F811
):
    # Taken off, one to read in inside one to write in would be written in.
    pid = project(client, project_dir, also_in=[str(shelf)], read_in=[str(shelf / "inner")])
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    refused = client.patch(f"/api/conversations/{cid}", json={"read_in": []})
    assert refused.status_code == 403
    assert conversation(client, cid)["read_in"] == [str(shelf / "inner")]
    # One to write in is anybody's to take off: that only narrows it.
    done = client.patch(f"/api/conversations/{cid}", json={"also_in": []})
    assert done.status_code == 200 and done.json()["also_in"] == []


def test_a_folder_is_added_to_a_chat_from_the_apps_own_page_only_and_as_it_really_is(
    client, project_dir, shelf  # noqa: F811
):
    pid = project(client, project_dir)
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    given = str(shelf / "inner" / "..")
    refused = client.patch(f"/api/conversations/{cid}", json={"read_in": [given]})
    assert refused.status_code == 403
    done = client.patch(f"/api/conversations/{cid}", json={"read_in": [given]}, headers=ORIGIN)
    assert done.status_code == 200, done.text
    assert done.json()["read_in"] == [str(shelf)]
    # Read & write: in both lists it is one to write in.
    done = client.patch(f"/api/conversations/{cid}", json={"also_in": [str(shelf)]},
                        headers=ORIGIN)
    assert done.json()["also_in"] == [str(shelf)] and done.json()["read_in"] == []
    system = "C:\\Windows" if os.name == "nt" else "/etc"
    never = client.patch(f"/api/conversations/{cid}", json={"read_in": [system]},
                         headers=ORIGIN)
    assert never.status_code == 422 and "never opened" in never.text


def test_the_project_is_never_an_extra_folder_of_its_own_chat_or_of_itself(
    client, project_dir
):
    """B-93: "+ Add a folder" listed the project itself as one to read in."""
    (project_dir / "sub").mkdir()
    pid = project(client, project_dir)
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    for folder in (project_dir, os.path.join(project_dir, "sub", "..", "sub")):
        for where, name in ((f"/api/conversations/{cid}", "read_in"),
                            (f"/api/projects/{pid}", "also_in")):
            refused = client.patch(where, json={name: [str(folder)]}, headers=ORIGIN)
            assert refused.status_code == 422 and "project's own folder" in refused.text
            # (by the entry as it was given: the one to take off)
            assert json.dumps(str(folder))[1:-1] in refused.text
    assert conversation(client, cid)["read_in"] == []
    # The folder that holds it is one (slice 75): a copy's agent is refused the project's files
    # through it, at work (`OF_THE_PROJECT`).
    inner = project(client, project_dir / "sub")  # (a project in a folder KOLONİ opens)
    chat = client.post(f"/api/projects/{inner}/conversations").json()["id"]
    done = client.patch(f"/api/conversations/{chat}", json={"also_in": [str(project_dir)]},
                        headers=ORIGIN)
    assert done.status_code == 200 and done.json()["also_in"] == [str(project_dir)]


def test_the_folders_page_keeps_only_the_places_never_opened(client):
    shown = client.get("/api/folders").json()
    assert set(shown) == {"never"} and shown["never"]
    assert client.put("/api/folders", json={"also_in": [], "read_in": []},
                      headers=ORIGIN).status_code == 405


# --- ask_folder: "Add to this chat" and "This time" ------------------------------------------


def test_this_time_lets_that_agent_read_there_and_puts_nothing_on_the_chat(
    make_client, wait_run, project_dir, shelf  # noqa: F811
):
    client, _model = make_client([ask_folder(shelf, "read"), read(shelf / "notes.md"),
                                  text("ok"), read(shelf / "notes.md", "r2"), text("ok")])
    pid = project(client, project_dir)
    cid, run_id = start(client, pid)
    (asked,) = wait_status(client, cid, "waiting_approval")["tool_calls"]
    approve(client, asked["id"], "once")
    snap = wait_run(client, cid, run_id)
    assert "this agent" in snap["tool_calls"][0]["result"]
    assert snap["tool_calls"][1]["status"] == "succeeded"
    assert conversation(client, cid)["read_in"] == conversation(client, cid)["also_in"] == []
    # The next turn's Lead is another agent: it asks again.
    client.post(f"/api/conversations/{cid}/messages", json={"content": "again"})
    snap = wait_status(client, cid, "waiting_approval")
    assert [t["name"] for t in snap["tool_calls"] if t["status"] == "pending"] == ["read_file"]


def test_the_project_itself_is_never_asked_for_and_take_in_is_said_instead(
    make_client, wait_run, project_dir
):
    """B-96: a Lead offered to ask for write access to the project, round its Take in."""
    client, _model = make_client([ask_folder(project_dir, "write"),
                                  ask_folder(project_dir / "sub", "write", id="b"), text("ok")])
    (project_dir / "sub").mkdir()
    pid = project(client, project_dir)
    cid, run_id = start(client, pid, mode="ask")
    calls = wait_run(client, cid, run_id)["tool_calls"]
    assert [t["status"] for t in calls] == ["failed", "failed"]  # nobody was asked
    assert all("you work there already" in t["result"] and "Take in" in t["result"]
               for t in calls)
    assert conversation(client, cid)["also_in"] == []


def test_add_to_this_chat_puts_it_on_the_chats_list_with_its_access(
    make_client, wait_run, project_dir, shelf  # noqa: F811
):
    client, _model = make_client([ask_folder(shelf, "write"), text("ok")])
    pid = project(client, project_dir)
    cid, run_id = start(client, pid)
    (asked,) = wait_status(client, cid, "waiting_approval")["tool_calls"]
    approve(client, asked["id"], "folder")
    wait_run(client, cid, run_id)
    assert conversation(client, cid)["also_in"] == [str(shelf)]


# --- a file in a chat with no folder ---------------------------------------------------------


def test_a_plain_chat_reads_a_file_the_user_names_once_on_their_word(
    make_client, wait_run, shelf  # noqa: F811
):
    client, model = make_client([read(shelf / "inner" / ".." / "notes.md"), text("ok")])
    cid = plain(client, permission_mode="full_auto")
    run_id = say(client, cid, f"summarise {shelf / 'notes.md'}")
    (asked,) = wait_status(client, cid, "waiting_approval")["tool_calls"]
    # The card says where the path really leads, as the user knows it.
    assert asked["status"] == "pending" and asked["outside_folder"] == str(shelf / "notes.md")
    assert "no folder" in asked["why_asked"]
    approve(client, asked["id"], "folder")  # (no folder is put anywhere, whatever is sent)
    (tool,) = wait_run(client, cid, run_id)["tool_calls"]
    assert tool["status"] == "succeeded" and "shelf notes" in tool["result"]
    assert conversation(client, cid)["read_in"] == conversation(client, cid)["also_in"] == []
    assert "read_file" in [t["function"]["name"] for t in model.tool_args[0]]


def test_a_plain_chat_lists_a_folder_once_and_asks_again_next_time(
    make_client, wait_run, shelf  # noqa: F811
):
    client, _model = make_client([step(call("list_dir", {"path": str(shelf)}, "l")),
                                  read(shelf / "notes.md"), text("ok")])
    cid = plain(client)
    run_id = say(client, cid)
    (listed,) = wait_status(client, cid, "waiting_approval")["tool_calls"]
    approve(client, listed["id"])
    snap = wait_status(client, cid, "waiting_approval")
    assert "notes.md" in snap["tool_calls"][0]["result"]
    assert snap["tool_calls"][1]["status"] == "pending"  # the file in it: asked again
    client.post(f"/api/tool-calls/{snap['tool_calls'][1]['id']}/reject", headers=ORIGIN)
    assert wait_run(client, cid, run_id)["tool_calls"][1]["status"] == "denied"


def test_a_plain_chat_never_reads_a_secret_a_place_never_opened_or_a_path_by_halves(
    make_client, wait_run, shelf, tmp_path  # noqa: F811
):
    (shelf / ".env").write_text("KEY=TOPSECRET\n", encoding="utf-8")
    # (the root a plain read is judged against, made by somebody: still never opened)
    rooted = tmp_path / "runtime" / "no-folder" / "x.txt"
    rooted.parent.mkdir(parents=True)
    rooted.write_text("TOPSECRET\n", encoding="utf-8")
    # (a hard link: refused before the card, not after the user's yes)
    os.link(shelf / "notes.md", shelf / "twin.md")
    client, model = make_client([
        step(call("read_file", {"path": str(shelf / ".env")}, "s"),
             call("read_file", {"path": "C:\\Windows\\win.ini"}, "w"),
             call("read_file", {"path": "notes.md"}, "rel"),
             call("write_file", {"path": str(shelf / "x.md"), "content": "x"}, "x"),
             call("read_file", {"path": str(rooted)}, "root"),
             call("read_file", {"path": str(shelf / "twin.md")}, "twin")),
        text("done")])
    cid = plain(client, permission_mode="full_auto")
    snap = wait_run(client, cid, say(client, cid))
    assert [t["status"] for t in snap["tool_calls"]] == ["failed"] * 6
    assert "hard link" in snap["tool_calls"][5]["result"]
    assert "TOPSECRET" not in json.dumps(snap) and "TOPSECRET" not in json.dumps(model.calls)
    assert not (shelf / "x.md").exists()


def test_a_plain_chats_prompt_says_a_named_file_is_read_on_the_users_word(
    make_client, wait_run
):
    client, model = make_client([text("hi")])
    cid = plain(client)
    wait_run(client, cid, say(client, cid))
    system = model.calls[0][0]["content"]
    assert "full path" in system and "~" in system
    # The home folder's path (the user's name on Windows) is not sent with every turn.
    assert str(Path.home()) not in system and str(Path("~").expanduser()) not in system


def test_a_plain_chat_whose_lead_cannot_read_is_not_told_it_may(make_client, wait_run):
    client, model = make_client([text("hi")])
    lead = next(r for r in client.get("/api/roles").json() if r["name"] == "Lead")
    tools = [t for t in lead["tools"] if t not in ("read_file", "list_dir")]
    assert client.patch(f"/api/roles/{lead['id']}", json={"tools": tools},
                        headers=ORIGIN).status_code == 200
    cid = plain(client)
    wait_run(client, cid, say(client, cid))
    assert "read_file" not in model.calls[0][0]["content"]


def test_a_plain_chat_reads_a_path_from_the_home_folder_written_with_a_tilde(
    make_client, wait_run, tmp_path, monkeypatch
):
    home = tmp_path / "home"
    (home / "Desktop").mkdir(parents=True)
    (home / "Desktop" / "rapor.txt").write_text("three parts\n", encoding="utf-8")
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))  # (Linux's and macOS's)
    client, _model = make_client([read(f"~{os.sep}Desktop{os.sep}rapor.txt"), text("ok")])
    cid = plain(client)
    run_id = say(client, cid)
    (asked,) = wait_status(client, cid, "waiting_approval")["tool_calls"]
    assert asked["outside_folder"] == str(home / "Desktop" / "rapor.txt")
    approve(client, asked["id"])
    (tool,) = wait_run(client, cid, run_id)["tool_calls"]
    assert tool["status"] == "succeeded" and "three parts" in tool["result"]


# --- the migration ---------------------------------------------------------------------------


def test_migration_0071_puts_every_projects_folders_into_each_project_and_its_chats(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0070")
    with sqlite3.connect(db) as conn:
        for pid, also, read_in in (("p", '["C:/w"]', '[]'), ("q", '[]', '["C:/r"]')):
            conn.execute("INSERT INTO projects (id, name, root_path, created_at, also_in, "
                         f"read_in) VALUES ('{pid}', '{pid}', 'C:/{pid}', '{AT}', '{also}', "
                         f"'{read_in}')")
        conn.execute("INSERT INTO conversations (id, project_id, title, created_at, "
                     f"updated_at, read_in) VALUES ('c', 'p', 't', '{AT}', '{AT}', '[\"C:/own\"]')")
        conn.execute("INSERT INTO conversations (id, project_id, title, created_at, "
                     f"updated_at) VALUES ('plain', NULL, 't', '{AT}', '{AT}')")
        conn.execute("INSERT INTO open_folders (path, access) VALUES ('C:/every', 'read')")
        conn.execute("INSERT INTO open_folders (path, access) VALUES ('C:/r', 'write')")
    command.upgrade(cfg, "0071")
    with sqlite3.connect(db) as conn:
        lists = {pid: (json.loads(also), json.loads(read_in)) for pid, also, read_in in
                 conn.execute("SELECT id, also_in, read_in FROM projects")}
        assert lists == {"p": (["C:/w", "C:/r"], ["C:/every"]),
                         "q": (["C:/r"], ["C:/every"])}
        chats = {cid: (json.loads(also), json.loads(read_in)) for cid, also, read_in in
                 conn.execute("SELECT id, also_in, read_in FROM conversations")}
        # What its agents could use before, it can still: its folder's and every project's.
        assert chats["c"] == (["C:/w", "C:/r"], ["C:/every", "C:/own"])
        assert chats["plain"] == ([], [])
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
        assert "open_folders" not in tables
    command.downgrade(cfg, "0070")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT count(*) FROM open_folders").fetchone() == (0,)
