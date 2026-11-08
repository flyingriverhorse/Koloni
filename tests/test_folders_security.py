"""Slice 75's security review, made tests: what a broad listed folder holds stays closed (KOLONİ's
own checkout, a place never opened, a secret beside it, by any name), a folder named in a message
never becomes writable where it is to be read only, a command that names such a folder is asked
about, a read's card never opens a folder to changes - and the migration goes up and down."""

import functools
import os
import sqlite3
import subprocess
import sys
from pathlib import Path, PurePosixPath

import pytest
from alembic import command

from app import copies, model_native, workspace
from app.commands import search_reason, secret_files
from app.config import REPO_ROOT
from app.tools import ToolError, plan_write
from app.workspace import NUL_IN_PATH, Workspace, WorkspaceError, not_a_project, opened
from tests.test_agent_commands import cmd
from tests.test_agent_writes import wait_status, write
from tests.test_chat_flow import text
from tests.test_claude_native import claude_app  # noqa: F401 - a fixture
from tests.test_claude_native import start as claude_start
from tests.test_folders import ORIGIN, ask_folder, lists, start
from tests.test_migration_0002 import _config
from tests.test_outside_folders_scenarios import conversation, project, read
from tests.test_project_files import _short
from tests.test_spawn import call, step


@pytest.fixture
def desk(tmp_path, monkeypatch):
    """A broad folder holding a place never opened (a KOLONİ runtime, by KOLONI_RUNTIME_ROOT, which a
    search made in a process of its own sees as well) with a secret beside that place."""
    desk = tmp_path / "desk"
    kol = desk / "kol"
    (kol / "runtime").mkdir(parents=True)
    (kol / "runtime" / "koloni.db").write_text("DB\n", encoding="utf-8")
    (kol / ".env").write_text("KOLONI_MODEL_API_KEY=sk-secret\n", encoding="utf-8")
    (kol / "app").mkdir()
    (kol / "app" / "notes.md").write_text("plain\n", encoding="utf-8")
    monkeypatch.setenv("KOLONI_RUNTIME_ROOT", str(kol / "runtime"))
    return desk


def full_auto(client, pid):
    return start(client, pid, mode="full_auto")


# --- critical 1: what a listed folder holds ----------------------------------------------------


def test_a_secret_beside_a_place_never_opened_is_not_read_searched_or_written(
    make_client, wait_run, project_dir, desk
):
    env = desk / "kol" / ".env"
    client, _model = make_client([
        read(env, "r"),
        step(call("search", {"pattern": "sk-secret|plain", "path": str(desk)}, "s")),
        write(str(env), "KOLONI_MODEL_API_KEY=x\n", id="w"),
        write(str(desk / "kol" / "app" / ".env.local"), "x\n", id="w2"),
        text("ok")])
    pid = project(client, project_dir, also_in=[str(desk)])
    cid, run_id = full_auto(client, pid)
    got, found, wrote, wrote_too = wait_run(client, cid, run_id)["tool_calls"]
    assert got["status"] == "failed" and "secret" in got["result"]
    assert "notes.md" in found["result"] and "sk-secret" not in found["result"]
    assert wrote["status"] == "failed" and wrote_too["status"] == "failed"
    assert env.read_text(encoding="utf-8") == "KOLONI_MODEL_API_KEY=sk-secret\n"
    assert not (desk / "kol" / "app" / ".env.local").exists()


@pytest.mark.skipif(Path(os.path.expanduser("~")).is_relative_to(REPO_ROOT.parent),
                    reason="the checkout's folder holds the home folder, rightly never listed")
def test_koloni_s_own_checkout_under_a_listed_folder_is_never_opened(
    make_client, wait_run, project_dir
):
    probe = REPO_ROOT / "app" / "_probe75_never_written.py"
    client, _model = make_client([
        read(REPO_ROOT / "README.md", "r"),
        write(str(probe), "pwn\n", id="w1"),
        write(str(REPO_ROOT / "README.md"), "pwn\n", id="w2"),
        step(call("list_dir", {"path": str(REPO_ROOT.parent)}, "l")),
        text("ok")])
    pid = project(client, project_dir, also_in=[str(REPO_ROOT.parent)])
    cid, run_id = full_auto(client, pid)
    try:
        got, wrote, wrote_too, listed = wait_run(client, cid, run_id)["tool_calls"]
    finally:
        probe.unlink(missing_ok=True)
    for refused in (got, wrote, wrote_too):
        assert refused["status"] == "failed" and "never opened" in refused["result"], refused
    assert listed["status"] == "succeeded" and REPO_ROOT.name not in listed["result"]
    assert "pwn" not in (REPO_ROOT / "README.md").read_text(encoding="utf-8")


def test_the_checkout_itself_is_listed_nowhere(client, project_dir):
    refused = lists(client, project_dir, read_in=[str(REPO_ROOT / "app")])
    assert refused.status_code == 422 and "never opened" in refused.text


def variants(place):
    p = str(place)
    return [p + r"\koloni.db", p.upper() + r"\koloni.db", p + r".\koloni.db",
            p + r" \koloni.db", p + r"::$INDEX_ALLOCATION\koloni.db",
            p + r":$I30:$INDEX_ALLOCATION\koloni.db", p + r"\koloni.db::$DATA",
            p + r"\koloni.db.", p.replace("\\", "/") + "/koloni.db",
            str(place.parent / "app" / ".." / place.name / "koloni.db"), p + r"\new.txt",
            p + r"::$INDEX_ALLOCATION\new.txt"]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows' names")
def test_a_place_never_opened_in_a_listed_folder_is_closed_by_any_name(project_dir, desk):
    place = desk / "kol" / "runtime"
    ws = Workspace(project_dir, also=[desk])
    for named in variants(place):
        with pytest.raises(WorkspaceError):
            ws.resolve(named)
    made = subprocess.run(["cmd", "/c", "mklink", "/J", str(desk / "door"), str(place)],
                          capture_output=True, text=True)
    if made.returncode == 0:  # through a junction in the listed folder too
        with pytest.raises(WorkspaceError):
            ws.resolve(str(desk / "door" / "koloni.db"))
    assert "runtime" not in [name for name, _kind, _size in ws.list_dir(str(desk / "kol"))]
    assert ".env" not in [name for name, _kind, _size in ws.list_dir(str(desk / "kol"))]


@pytest.fixture
def checkout(project_dir, monkeypatch):
    """KOLONİ's own checkout, with its runtime, in a project folder (the Desktop holding it,
    which `_kept_out` lets be a project) - under a long name, which has an 8.3 one."""
    kol = project_dir / "Skyulf-Agent-checkout"
    (kol / "app").mkdir(parents=True)
    (kol / "runtime" / "data").mkdir(parents=True)
    (kol / "app" / "workspace.py").write_text("ours\n", encoding="utf-8")
    (kol / "runtime" / "data" / "x.txt").write_text("ours\n", encoding="utf-8")
    (project_dir / "notes.md").write_bytes(b"plain\n")
    monkeypatch.setattr("app.config.REPO_ROOT", kol)
    # (A cache of its own: the real one never holds the fake checkout's places.)
    monkeypatch.setattr(workspace, "_places", functools.cache(workspace._places.__wrapped__))
    return kol


def test_koloni_s_own_checkout_in_a_project_is_never_opened_by_any_name(project_dir, checkout):
    ws = Workspace(project_dir)
    named = [f"{checkout.name}/app/workspace.py", f"{checkout.name}/app/new.py",
             str(checkout / "runtime" / "new.txt"), f"x/../{checkout.name}/app/workspace.py"]
    # In another case, or with a trailing dot: the checkout where the disk says so (Windows);
    # where it tells them apart (Linux), another folder - the project's own (`_cased`).
    upper, dotted = project_dir / checkout.name.upper(), Path(f"{checkout}.")
    assert sys.platform != "win32" or upper.exists() and dotted.exists()
    named += [f"{upper.name}/runtime/data/x.txt"] * upper.exists()
    named += [f"{checkout.name}./app/workspace.py"] * dotted.exists()
    if short := _short(checkout):
        named += [f"{short}/app/workspace.py", f"{short}/app/new.py"]
    try:  # a link to it in the project (Windows lets few users make one)
        os.symlink(checkout, project_dir / "door", target_is_directory=True)
        named += ["door/app/workspace.py", "door/app/new.py"]
    except OSError:
        assert sys.platform == "win32"
    for one in named:
        with pytest.raises(WorkspaceError, match="is never opened: it is KOLONİ's own"):
            ws.resolve(one)
        with pytest.raises(ToolError, match="never opened"):
            plan_write(ws, "write_file", {"path": one, "content": "pwn\n"})
    with pytest.raises(ToolError, match="never opened"):
        plan_write(ws, "edit_file", {"path": named[0], "old_string": "ours", "new_string": "pwn"})
    # A file of the project's own beside it is as before; the checkout is neither listed nor
    # searched.
    assert ws.read_text("notes.md") == "plain\n"
    assert plan_write(ws, "write_file", {"path": "notes.md", "content": "more\n"}).path == "notes.md"
    assert checkout.name not in [name for name, _kind, _size in ws.list_dir(".")]
    assert [found[0] for found in ws._search_here("ours|plain")[0]] == ["notes.md"]


def test_claude_code_s_own_write_to_koloni_s_checkout_in_the_project_is_refused(
    claude_app, wait_run, project_dir, checkout  # noqa: F811
):
    pwn = {"tool": "Write", "input": {
        "file_path": f"PROJECT/{checkout.name}/app/workspace.py", "content": "pwn\n"},
        "write": [f"{checkout.name}/app/workspace.py", "pwn\n"], "result": "File updated"}
    client, provider, _ = claude_app([pwn, {"say": "done"}])
    cid, run_id = claude_start(client, project_dir, provider, "full_auto")
    snap = wait_run(client, cid, run_id)
    assert (checkout / "app" / "workspace.py").read_text(encoding="utf-8") == "ours\n"
    assert any("never opened" in (one["result"] or "") for one in snap["tool_calls"]), snap


def test_claude_code_s_own_read_of_koloni_s_checkout_in_the_project_is_refused(
    claude_app, wait_run, project_dir, checkout  # noqa: F811
):
    look = {"tool": "Read", "input": {"file_path": f"PROJECT/{checkout.name}/runtime/data/x.txt"},
            "result": "ours"}
    client, provider, _ = claude_app([look, {"say": "done"}])
    cid, run_id = claude_start(client, project_dir, provider, "full_auto")
    snap = wait_run(client, cid, run_id)
    (refused,) = [one for one in snap["tool_calls"] if "x.txt" in one["arguments"]]
    assert refused["status"] == "failed" and "never opened" in refused["result"], refused


def test_claude_code_s_own_search_over_koloni_s_checkout_in_the_project_is_refused(
    claude_app, wait_run, project_dir, checkout  # noqa: F811
):
    # KOLONİ's checkout, or a folder in it, is no project; a folder that holds it may be one.
    assert not_a_project(checkout) and not_a_project(checkout / "app")
    assert not_a_project(project_dir) is None
    (project_dir / "sub").mkdir()
    steps = [{"tool": "Grep", "input": {"pattern": "sk-1"}, "result": "leaked"},
             {"tool": "Glob", "input": {"pattern": "**/*.py", "path": "PROJECT"}, "result": "leaked"},
             {"tool": "Grep", "input": {"pattern": "sk-2", "path": f"PROJECT/{checkout.name}/app"},
              "result": "leaked"},
             {"tool": "Grep", "input": {"pattern": "sk-3", "path": "PROJECT/sub"}, "result": "none"},
             {"tool": "Glob", "input": {"pattern": "sub/**/*.py"}, "result": "none"},
             {"say": "done"}]
    client, provider, _ = claude_app(steps)
    cid, run_id = claude_start(client, project_dir, provider, "full_auto")
    snap = wait_run(client, cid, run_id)
    refused = [one for one in snap["tool_calls"] if one["status"] in ("failed", "denied")]
    assert len(refused) == 3, snap["tool_calls"]
    assert all("never opened" in one["result"] for one in refused), refused
    assert "search a narrower folder" in refused[0]["result"]
    assert not [one for one in refused if "sk-3" in one["arguments"] or "sub/" in one["arguments"]]


def test_koloni_s_own_checkout_in_a_project_is_a_secret_to_a_search_and_never_copied(
    project_dir, checkout
):
    (checkout / ".env").write_text("KOLONI_MODEL_API_KEY=sk-secret\n", encoding="utf-8")
    login = checkout / "runtime" / "cli-homes" / "p1" / ".credentials.json"
    login.parent.mkdir(parents=True)
    login.write_text("{}", encoding="utf-8")
    places = set(Workspace(project_dir).koloni_places())
    assert {checkout.name, f"{checkout.name}/runtime"} <= places
    assert places <= set(secret_files(project_dir))
    assert search_reason("grep -r sk- .", project_dir)
    files, _links, _size = copies._scan(project_dir)
    assert files == ["hello.py", "notes.md"]


def test_on_a_disk_with_no_case_koloni_s_checkout_is_named_in_its_own_case(
    project_dir, checkout, monkeypatch
):
    """macOS: `_cased` folds every path, and the checkout is found in any case - but named as
    it is, since a search told to leave it out (`rg -g '!name'`) matches case by case."""
    monkeypatch.setattr(workspace, "_cased", lambda path: PurePosixPath(path.as_posix().casefold()))
    ws = Workspace(project_dir)
    named = {checkout.name, f"{checkout.name}/runtime"}
    assert named <= set(ws.koloni_places()) and ws.koloni_under(project_dir) in named
    assert ws.koloni_s(project_dir / checkout.name.upper() / "app") is not None


@pytest.mark.skipif(sys.platform != "win32", reason="Windows' devices and streams")
@pytest.mark.parametrize("bad", ["hello.py:evil", "COM1.txt"])
def test_claude_code_s_own_write_to_a_device_or_a_stream_is_refused(
    claude_app, wait_run, project_dir, bad  # noqa: F811
):
    pwn = {"tool": "Write", "input": {"file_path": f"PROJECT/{bad}", "content": "pwn"},
           "write": [bad, "pwn"], "result": "File updated"}
    client, provider, _ = claude_app([pwn, {"say": "done"}])
    cid, run_id = claude_start(client, project_dir, provider, "full_auto")
    snap = wait_run(client, cid, run_id)
    assert any("is not written" in (one["result"] or "") or "never opened" in (one["result"] or "")
               for one in snap["tool_calls"]), snap
    assert "pwn" not in (project_dir / "hello.py").read_text(encoding="utf-8")


# --- critical 2: a folder named in a message ---------------------------------------------------


def test_a_file_named_in_a_folder_to_read_in_does_not_make_it_writable(make_client, wait_run,
                                                                        project_dir, tmp_path):
    shelf = tmp_path / "shelf"
    shelf.mkdir()
    (shelf / "notes.md").write_text("n\n", encoding="utf-8")
    client, _model = make_client([write(str(shelf / "out.md"), "x\n"), text("ok")])
    pid = project(client, project_dir, read_in=[str(shelf)])
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(f"/api/conversations/{cid}", json={"permission_mode": "full_auto",
                 "lead_hands_code": False}, headers=ORIGIN)
    client.post(f"/api/conversations/{cid}/messages",
                json={"content": f"look at {shelf / 'notes.md'}"}, headers=ORIGIN)
    snap = wait_status(client, cid, "waiting_approval")
    assert conversation(client, cid)["also_in"] == []
    assert snap["tool_calls"][0]["status"] == "pending"
    assert not (shelf / "out.md").exists()


def test_a_message_that_says_nothing_of_where_it_is_from_opens_nothing(make_client, wait_run,
                                                                        project_dir, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    client, _model = make_client([text("ok")])
    pid = project(client, project_dir)
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    run = client.post(f"/api/conversations/{cid}/messages", json={"content": f"see {other}"})
    assert run.status_code == 201
    wait_run(client, cid, run.json()["run"]["id"])
    assert conversation(client, cid)["also_in"] == []


# --- important 3 and 4: commands, and what a card opens ----------------------------------------


@pytest.mark.parametrize("named", [
    lambda shelf: f'type "{shelf}\\notes.md"',
    lambda shelf: "cat " + str(shelf).upper().replace("\\", "/") + "/notes.md",
])
def test_a_command_that_names_a_folder_to_read_in_is_asked_for_at_full_auto(
    make_client, project_dir, tmp_path, named
):
    shelf = tmp_path / "shelf"
    shelf.mkdir()
    client, _model = make_client([cmd(named(shelf)), text("ok")])
    pid = project(client, project_dir, read_in=[str(shelf)])
    cid, _run_id = full_auto(client, pid)
    (asked,) = wait_status(client, cid, "waiting_approval")["tool_calls"]
    assert asked["name"] == "run_command" and asked["status"] == "pending"
    assert asked["outside_folder"] == str(shelf)



def test_a_claude_code_command_that_names_a_folder_to_read_in_is_asked_for_at_full_auto(
    claude_app, project_dir, tmp_path  # noqa: F811
):
    shelf = tmp_path / "shelf"
    shelf.mkdir()
    bash = {"tool": "Bash", "input": {"command": f'type "{shelf}' + chr(92) + 'notes.md"'},
            "result": "n"}
    client, provider, _ = claude_app([bash, {"say": "ok"}])
    pid = project(client, project_dir, read_in=[str(shelf)])
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(f"/api/conversations/{cid}", headers=ORIGIN, json={
        "permission_mode": "full_auto", "provider_id": provider["id"], "lead_hands_code": False})
    client.post(f"/api/conversations/{cid}/messages", json={"content": "read the notes"})
    (asked,) = wait_status(client, cid, "waiting_approval")["commands"]
    assert (asked["status"], asked["origin"]) == ("proposed", "cli")


def test_a_reads_card_opens_the_folder_to_read_only(make_client, project_dir, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    (other / "notes.md").write_text("n\n", encoding="utf-8")
    client, _model = make_client([read(other / "notes.md"),
                                  write(str(other / "out.md"), "x\n", id="w"), text("ok")])
    pid = project(client, project_dir)
    cid, _run_id = full_auto(client, pid)
    (asked,) = wait_status(client, cid, "waiting_approval")["tool_calls"]
    client.post(f"/api/tool-calls/{asked['id']}/approve", json={"scope": "folder"},
                headers=ORIGIN)
    snap = wait_status(client, cid, "waiting_approval")      # the write is asked about still
    assert [t["status"] for t in snap["tool_calls"]] == ["succeeded", "pending"]
    assert conversation(client, cid)["read_in"] == [str(other)]
    assert conversation(client, cid)["also_in"] == []
    assert not (other / "out.md").exists()


# --- minor -------------------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["C:\\x\x00y", "C:\\" + "a" * 5000, "C:\\" + "a" * 40000],
                         ids=["nul", "too-long-for-windows", "too-long-for-the-list"])
def test_a_path_that_is_no_path_is_refused_not_a_server_error(client, project_dir, bad):
    assert lists(client, project_dir, also_in=[bad]).status_code == 422
    # and on a chat's own list (slice 86b)
    cid = client.post("/api/conversations", headers=ORIGIN).json()["id"]
    refused = client.patch(f"/api/conversations/{cid}", headers=ORIGIN, json={"also_in": [bad]})
    assert refused.status_code == 422


def test_ask_folder_with_a_path_that_is_no_path_is_a_tool_error(make_client, wait_run,
                                                                project_dir):
    client, _model = make_client([ask_folder("C:\\x\x00y", "read"), text("ok")])
    pid = project(client, project_dir)
    cid, run_id = full_auto(client, pid)
    (tool,) = wait_run(client, cid, run_id)["tool_calls"]
    assert tool["status"] == "failed"


@pytest.mark.parametrize("named, listed", [
    ("a\x00b", False), ("{other}/a\x00b", False), ("{other}/a\x00b", True),
    ("{other}\x00x/a.md", False)], ids=["inside", "outside", "listed", "its-folder"])
def test_a_path_with_a_nul_is_a_tool_error_never_a_card_nor_a_failed_run(
    make_client, wait_run, project_dir, tmp_path, named, listed
):
    # (3.13+ Path.resolve() no longer raises on a NUL: refused before it, on 3.12 as well)
    other = tmp_path / "other"
    other.mkdir()
    client, _model = make_client([read(named.format(other=other)), text("ok")])
    pid = project(client, project_dir, **({"read_in": [str(other)]} if listed else {}))
    cid, run_id = full_auto(client, pid)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert [(t["status"], t["result"]) for t in snap["tool_calls"]] == [
        ("failed", f"error: {NUL_IN_PATH}")]
    with pytest.raises(WorkspaceError, match=NUL_IN_PATH):
        opened(str(other / "a\x00b"))


def test_a_claude_code_write_with_a_nul_in_its_path_is_refused_and_its_session_goes_on(
    claude_app, wait_run, project_dir  # noqa: F811
):
    nul = {"tool": "Write", "input": {"file_path": "PROJECT/a\x00b.txt", "content": "x"}}
    client, provider, _ = claude_app([nul, {"say": "done"}])
    cid, run_id = claude_start(client, project_dir, provider, "full_auto")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    plugin = str(project_dir / "plugin")
    assert not model_native.only_given(
        "Read", {"file_path": plugin + "/skills/a\x00b"}, set(), plugin)


def test_migration_0060_goes_up_and_down(tmp_path):
    db = tmp_path / "m.db"
    cfg = _config(db)
    command.upgrade(cfg, "0059")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO roles (id, name, description, instructions, tools, builtin, "
                     "created_by_agent, created_at, updated_at) VALUES ('l', 'Lead', '', '', "
                     "'[\"ask_user\"]', 1, 0, '2026-10-22 10:00:00', '2026-10-22 10:00:00')")
    command.upgrade(cfg, "0060")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT tools FROM roles").fetchone() == ('["ask_user", "ask_folder"]',)
        conn.execute("INSERT INTO open_folders (path, access) VALUES ('C:/x', 'read')")
        columns = [row[1] for row in conn.execute("PRAGMA table_info(projects)")]
        assert "read_in" in columns
    command.downgrade(cfg, "0059")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT tools FROM roles").fetchone() == ('["ask_user"]',)
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
        assert "open_folders" not in tables
        assert "read_in" not in [row[1] for row in conn.execute("PRAGMA table_info(projects)")]


def test_browsers_profiles_and_windows_keys_are_never_opened_but_temp_is(tmp_path, monkeypatch):
    from app.workspace import _kept_out, never

    local, roaming = tmp_path / "Local", tmp_path / "Roaming"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("APPDATA", str(roaming))
    for secret in (local / "Google/Chrome/User Data/Default/Cookies",
                   local / "Microsoft/Edge/User Data/Default/Login Data",
                   roaming / "Mozilla/Firefox/Profiles/x/logins.json",
                   roaming / "Microsoft/Protect/S-1-5/key"):
        assert never(secret), secret
    assert _kept_out(local)  # it holds a browser's profile: no list may hold it whole
    assert never(local / "Temp" / "work") is None


def test_macos_and_linux_browsers_profiles_and_keys_are_never_opened(tmp_path, monkeypatch):
    from app.workspace import _kept_out, never

    home = tmp_path / "home"
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    mac = home / "Library/Application Support"
    for secret in (mac / "Google/Chrome/Default/Cookies", mac / "Microsoft Edge/Default/Login Data",
                   mac / "BraveSoftware/Brave-Browser/Default/Cookies",
                   mac / "Firefox/Profiles/x/logins.json", home / ".mozilla/firefox/x/key4.db",
                   home / ".config/google-chrome/Default/Cookies", home / ".config/chromium/Default",
                   home / ".config/microsoft-edge/Default", home / ".config/BraveSoftware/x",
                   home / "Library/Keychains/login.keychain-db", home / ".gnupg/private-keys-v1.d",
                   home / ".local/share/keyrings/login.keyring"):
        assert never(secret), secret
    assert _kept_out(mac)  # it holds a browser's profile: no list may hold it whole
    assert never(mac / "Code/User/settings.json") is None


@pytest.mark.skipif(sys.platform == "win32", reason="macOS's and Linux's own folders")
def test_the_system_s_own_folders_are_never_opened_on_macos_and_linux(tmp_path):
    from app.workspace import never

    for system in ("/etc/passwd", "/System/Library", "/usr/bin/env", "/bin/sh", "/sbin",
                   "/Library/Preferences"):
        assert never(Path(system)) == "it is the system's own", system
    assert never(Path("/usr")) and never(Path("/usr/lib/x"))
    assert never(Path("/usr/local/src/project")) is None  # the user's own may lie there
    assert never(tmp_path / "work") is None


def test_on_macos_a_place_never_opened_is_closed_in_any_case(tmp_path, monkeypatch):
    from app.workspace import _kept_out, never

    home = tmp_path / "home"
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(sys, "platform", "darwin")  # its disk (APFS) has no case
    assert never(home / "library/keychains/login.keychain-db")
    assert never(home / "LIBRARY/Application Support/google/CHROME/Default/Cookies")
    assert _kept_out(home / "Library/APPLICATION SUPPORT")  # it holds a browser's profile
    assert never(home / "Library/Application Support/Code") is None
