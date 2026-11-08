"""Slice 97: an MCP server starts in a folder agents do not write in, and one that runs a file
from a project - which agents can change - is started only once the user says so, for that
file as it is."""

import json
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path

import pytest
from alembic import command

from app import mcp_client
from app.config import REPO_ROOT, load_settings, mcp_base
from app.tools import MAX_QUESTION_CHARS
from app.workspace import _kept_out, not_a_project
from tests import test_trigger_scenarios as unattended
from tests.test_agent_writes import wait_status
from tests.test_chat_flow import text
from tests.test_mcp_scenarios import (
    FAKE,
    LONG,
    ORIGIN,
    READ,
    calls,
    events,
    give,
    mark,
    server,
)
from tests.test_migration_0002 import _config
from tests.test_spawn import begin, call, step

ASKED = "from your project, which agents can change. Start it anyway?"


def in_project(client, tmp_path, project_dir):
    """The stand-in server copied into the project, as `python tools/server.py` would run it,
    added and read with the user's yes; returns it, its record, the script, the address
    that reads it and the files the user said yes to."""
    client.headers["Origin"] = ORIGIN
    assert client.post("/api/projects", json={"root_path": str(project_dir)}).status_code in (200, 201)
    script = project_dir / "tools" / "server.py"
    script.parent.mkdir()
    shutil.copyfile(FAKE[1], script)
    record, plan = tmp_path / "record.jsonl", tmp_path / "plan.json"
    plan.write_text(json.dumps({"record": str(record)}), encoding="utf-8")
    made = client.post("/api/mcp-servers", json={
        "name": "fake", "command": [sys.executable, str(script)],
        "env": {"FAKE_MCP_PLAN": str(plan)}}).json()
    url = f"/api/mcp-servers/{made['id']}/read"
    # asked first: nothing started, the file named with what it holds
    asked = client.post(url).json()
    assert list(asked["in_project"]) == [str(script.resolve())]
    assert asked["server"]["read_at"] is None and events(record, "start") == []
    started = client.post(url, json={"in_project": asked["in_project"]}).json()
    assert started["in_project"] is None and len(started["server"]["tools"]) > 0
    assert len(events(record, "start")) == 1
    record.write_text("", encoding="utf-8")
    # trusted (slice 92), as server() does: these tests are of the start card, not the watch
    trusting = client.patch(f"/api/mcp-servers/{made['id']}", json={"trusted": True})
    assert trusting.status_code == 200 and trusting.json()["trusted"], trusting.text
    return made, record, script, url, asked["in_project"]


def under(path, folder):
    return Path(path).resolve().is_relative_to(Path(folder).resolve())


def test_a_server_starts_in_kolonis_own_folder_and_a_global_command_is_not_asked_about(
    make_client, wait_run, project_dir, tmp_path
):
    client, _ = make_client([step(call("fake__where", {})), text("done")])
    _made, record, _ = server(client, tmp_path, free=True)           # FAKE: outside every project
    give(client, "Lead", "fake")
    cid, run_id = begin(client, project_dir, mode="full_auto")
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert calls(snap)["fake__where"][0] == "succeeded" and snap["questions"] == []
    home = client.app.state.settings.mcp_home
    # npm and uv look no further up than the start folder's own settings
    assert (home / "package.json").read_text(encoding="utf-8").strip() == '{"private": true}'
    assert (home / "uv.toml").read_text(encoding="utf-8") == ""
    (start,) = events(record, "start")
    # neither the project nor the system's temp folder (npm looks in the folders above it)
    for started in (*READ["fake"], start):
        assert under(started["cwd"], home) and started["files"] == []
        assert not under(started["cwd"], project_dir)


def test_reading_a_project_script_asks_once_and_asks_again_when_it_changes(
    make_client, project_dir, tmp_path
):
    client, _ = make_client([])
    _made, record, script, url, files = in_project(client, tmp_path, project_dir)
    # remembered: read again without asking
    assert client.post(url).json()["in_project"] is None and len(events(record, "start")) == 1
    record.write_text("", encoding="utf-8")
    with script.open("a", encoding="utf-8") as changed:
        changed.write("# an agent was here\n")
    asked = client.post(url).json()["in_project"]
    assert list(asked) == list(files) and asked != files and events(record, "start") == []
    # a yes to the file as it was before is no yes to it now
    assert client.post(url, json={"in_project": files}).json()["in_project"] == asked
    assert events(record, "start") == []


def test_an_agent_is_asked_before_a_changed_project_script_starts_at_every_level(
    make_client, wait_run, project_dir, tmp_path
):
    client, _ = make_client({
        "Lead": [step(call("fake__echo", {"text": "hi"}, "e1")),
                 step(call("spawn_agent", {"role": "Coder", "task": "look"}, "s1")),
                 text("done")],
        "Coder": [step(call("fake__echo", {"text": "again"}, "e2")), text("looked")]})
    made, record, script, *_ = in_project(client, tmp_path, project_dir)
    mark(client, made, echo="free")                       # not even one never asked about
    give(client, "Lead", "fake")
    give(client, "Coder", "fake")
    with script.open("a", encoding="utf-8") as changed:
        changed.write("# an agent was here\n")
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    (question,) = wait_status(client, cid, "waiting_approval")["questions"]
    assert question["leave"] and question["options"] == ["Start it", "Don't start"]
    assert str(script.resolve()) in question["question"] and ASKED in question["question"]
    assert events(record, "start") == []
    client.post(f"/api/questions/{question['id']}/answer", json={"answer": "Start it"})
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    # the Coder's own process of it started without a second card: the yes is remembered
    assert [t["status"] for t in snap["tool_calls"] if t["name"] == "fake__echo"] == [
        "succeeded", "succeeded"]
    assert len(snap["questions"]) == 1 and len(events(record, "start")) == 2


def test_a_no_starts_nothing_and_stands_for_the_rest_of_the_turn(
    make_client, wait_run, project_dir, tmp_path
):
    client, _ = make_client([step(call("fake__echo", {"text": "hi"}, "e1")),
                             step(call("fake__echo", {"text": "again"}, "e2")), text("done")])
    made, record, script, *_ = in_project(client, tmp_path, project_dir)
    mark(client, made, echo="free")
    give(client, "Lead", "fake")
    script.write_text(script.read_text(encoding="utf-8") + "# changed\n", encoding="utf-8")
    cid, run_id = begin(client, project_dir, mode="full_auto")
    question = wait_status(client, cid, "waiting_approval")["questions"][0]
    client.post(f"/api/questions/{question['id']}/answer", json={"answer": "Don't start"})
    snap = wait_run(client, cid, run_id, timeout=LONG)
    echoes = [(t["status"], t["result"]) for t in snap["tool_calls"] if t["name"] == "fake__echo"]
    assert len(echoes) == 2 and all(s == "denied" and "said not to start" in r for s, r in echoes)
    assert len(snap["questions"]) == 1 and events(record, "start") == []  # one card, no start


def test_no_project_script_server_starts_in_a_turn_nobody_watches(
    make_client, wait_run, project_dir, tmp_path
):
    client, model, pid, cid = unattended.setup(
        make_client, project_dir,
        [step(call("fake__echo", {"text": "hi"})), text("I could not.")],
        permission_mode="full_auto")
    made, record, script, *_ = in_project(client, tmp_path, project_dir)
    mark(client, made, echo="free")
    give(client, "Lead", "fake")
    script.write_text(script.read_text(encoding="utf-8") + "# changed\n", encoding="utf-8")
    run_id = unattended.run_now(client, unattended.trigger(client, pid, cid)["id"])
    snap = unattended.finished(client, wait_run, cid, run_id, timeout=LONG)
    assert calls(snap)["fake__echo"][0] != "succeeded" and snap["questions"] == []
    assert events(record, "start") == []


def test_what_counts_as_a_file_of_a_project(tmp_path):
    project = tmp_path / "proj"
    (project / ".venv" / "Scripts").mkdir(parents=True)
    script, python = project / "server.py", project / ".venv" / "Scripts" / "python.exe"
    script.write_text("print()\n", encoding="utf-8")
    python.write_bytes(b"MZ")
    found = mcp_client.in_project
    # a global command, a relative path, and a folder given as the server's data: none
    assert found(FAKE, [project]) == {}
    assert found([sys.executable, "server.py", str(project)], [project]) == {}
    # a script by its full path, or as a flag's value; an interpreter from the project
    assert list(found([sys.executable, str(script)], [project])) == [str(script.resolve())]
    assert list(found([sys.executable, f"--app={script}"], [project])) == [str(script.resolve())]
    assert list(found([str(python), "-m", "srv"], [project])) == [str(python.resolve())]
    # a folder is code as an interpreter's first argument (node ./mcp), not as another's data
    assert list(found(["node", str(project)], [project])) == [str(project.resolve())]
    assert found(["npx", "-y", "server-filesystem", str(project)], [project]) == {}
    # KOLONİ's own code in a listed folder that holds it is not the project's
    assert found([sys.executable, FAKE[1]], [REPO_ROOT.parent]) == {}


def test_migration_0112_and_back(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0111")
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO mcp_servers (id, name, command, env, tools, created_at) VALUES "
            "('s', 'fake', '[\"python\"]', '{}', '[]', '2026-10-28 10:00:00')")
    command.upgrade(cfg, "0112")
    with sqlite3.connect(db) as conn:
        # a server from before was said yes to for no file
        assert conn.execute("SELECT trusted_files FROM mcp_servers").fetchall() == [("{}",)]
    command.downgrade(cfg, "0111")
    with sqlite3.connect(db) as conn:
        assert "trusted_files" not in [r[1] for r in conn.execute("PRAGMA table_info(mcp_servers)")]
        assert conn.execute("SELECT name FROM mcp_servers").fetchall() == [("fake",)]


def test_in_ask_mode_the_call_is_asked_about_and_then_the_start(
    make_client, wait_run, project_dir, tmp_path
):
    client, _ = make_client([step(call("fake__echo", {"text": "hi"})), text("done")])
    _made, record, script, *_ = in_project(client, tmp_path, project_dir)
    give(client, "Lead", "fake")
    script.write_text(script.read_text(encoding="utf-8") + "# changed\n", encoding="utf-8")
    cid, run_id = begin(client, project_dir, mode="ask")
    first = wait_status(client, cid, "waiting_approval")["questions"][0]
    assert first["options"] == ["Allow", "Deny"]
    client.post(f"/api/questions/{first['id']}/answer", json={"answer": "Allow"})
    # the second card of the same call, KOLONİ's own too, waits by itself
    deadline = time.monotonic() + LONG
    while len(asked := client.get(f"/api/conversations/{cid}").json()["questions"]) < 2:
        assert time.monotonic() < deadline
        time.sleep(0.05)
    second = next(q for q in asked if q["id"] != first["id"])
    assert second["status"] == "pending" and ASKED in second["question"]
    assert events(record, "start") == []
    client.post(f"/api/questions/{second['id']}/answer", json={"answer": "Start it"})
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert calls(snap)["fake__echo"][0] == "succeeded" and len(events(record, "start")) == 1


# --- the fix round: where it starts, and what counts as the project's code -------------------


@pytest.mark.skipif(sys.platform != "win32", reason="off Windows the cache's folder is a shortcut")
def test_no_folder_above_where_servers_start_can_be_a_project():
    home = load_settings({"KOLONI_RUNTIME_ROOT": str(REPO_ROOT / "runtime")}).mcp_home
    assert home.is_relative_to(mcp_base()) and mcp_base().parent.name == "KOLONI"
    # npm and uv look in every folder above it: no agent's project, no folder listed for one
    for folder in (home, *home.parents):
        assert not_a_project(folder) is not None, folder
        assert _kept_out(folder) is not None, folder


def test_leftover_start_folders_are_swept_at_the_start(make_client, settings_env):
    left = Path(settings_env["KOLONI_MCP_HOME"]) / "koloni-mcp-left"
    left.mkdir(parents=True)
    (left / "x").write_text("x", encoding="utf-8")
    make_client([])
    assert not left.exists()


def test_uv_with_a_project_directory_is_asked_about(make_client, project_dir, tmp_path):
    client, _ = make_client([])
    client.headers["Origin"] = ORIGIN
    client.post("/api/projects", json={"root_path": str(project_dir)})
    (project_dir / "server.py").write_text("print()\n", encoding="utf-8")
    made = client.post("/api/mcp-servers", json={  # MCP's own quickstart
        "name": "weather", "command": ["uv", "--directory", str(project_dir), "run", "server.py"]})
    assert made.status_code == 201, made.text
    asked = client.post(f"/api/mcp-servers/{made.json()['id']}/read").json()
    assert list(asked["in_project"]) == [str(project_dir.resolve())]
    assert asked["server"]["read_at"] is None                   # nothing started


def test_a_changed_neighbour_of_the_script_is_asked_about_again(make_client, project_dir, tmp_path):
    client, _ = make_client([])
    _made, record, script, url, files = in_project(client, tmp_path, project_dir)
    (script.parent / "helper.py").write_text("SAYS = 1\n", encoding="utf-8")  # it imports this
    asked = client.post(url).json()["in_project"]
    assert list(asked) == list(files) and asked != files and events(record, "start") == []
    # what tools make, and packages, are not the script's neighbours
    client.post(url, json={"in_project": asked})
    (script.parent / "__pycache__").mkdir()
    (script.parent / "__pycache__" / "helper.pyc").write_bytes(b"\0")
    assert client.post(url).json()["in_project"] is None


def test_a_start_that_fails_keeps_no_yes(make_client, project_dir, tmp_path):
    client, _ = make_client([])
    client.headers["Origin"] = ORIGIN
    client.post("/api/projects", json={"root_path": str(project_dir)})
    script = project_dir / "broken.py"
    script.write_text("raise SystemExit(3)\n", encoding="utf-8")
    made = client.post("/api/mcp-servers", json={"name": "broken", "command": [
        sys.executable, str(script)]}).json()
    url = f"/api/mcp-servers/{made['id']}/read"
    asked = client.post(url).json()["in_project"]
    assert client.post(url, json={"in_project": asked}).json()["server"]["read_error"]
    assert client.post(url).json()["in_project"] == asked       # asked again


def link(at: Path, to: Path) -> None:
    if sys.platform == "win32":
        import _winapi
        _winapi.CreateJunction(str(to), str(at))
    else:
        at.symlink_to(to, target_is_directory=True)


def test_a_link_in_a_project_to_a_folder_outside_is_the_projects(tmp_path):
    project, outside = tmp_path / "proj", tmp_path / "outside"
    project.mkdir()
    outside.mkdir()
    (outside / "server.py").write_text("print()\n", encoding="utf-8")
    link(project / "tools", outside)
    found = mcp_client.in_project([sys.executable, str(project / "tools" / "server.py")], [project])
    assert list(found) == [str(project / "tools" / "server.py")] and found[str(project / "tools" / "server.py")]
    # and the other way: a link outside into the project
    link(tmp_path / "into", project)
    (project / "s.py").write_text("print()\n", encoding="utf-8")
    assert list(mcp_client.in_project([sys.executable, str(tmp_path / "into" / "s.py")], [project]))
    # a link beside the script that leads elsewhere now is a change, though nothing is read
    # behind it
    command = [sys.executable, str(project / "s.py")]
    before = mcp_client.in_project(command, [project])
    (tmp_path / "other").mkdir()
    link(project / "lib", tmp_path / "other")
    assert before != mcp_client.in_project(command, [project])


def test_uvx_from_a_project_folder_is_its_code(tmp_path):
    (tmp_path / "proj").mkdir()
    project = tmp_path / "proj"
    assert list(mcp_client.in_project(["uvx", "--from", str(project), "srv"], [project]))


def test_a_projects_python_is_held_to_its_venv_and_a_big_folder_is_asked_every_time(
    tmp_path, monkeypatch
):
    project = tmp_path / "proj"
    scripts, packages = project / ".venv" / "Scripts", project / ".venv" / "Lib" / "site-packages"
    scripts.mkdir(parents=True)
    packages.mkdir(parents=True)
    python = scripts / "python.exe"
    python.write_bytes(b"MZ")
    (project / ".venv" / "pyvenv.cfg").write_text("home = C:\\Python312\n", encoding="utf-8")
    command = [str(python), "-m", "srv"]
    before = mcp_client.in_project(command, [project])
    (packages / "planted.pth").write_text("import planted\n", encoding="utf-8")  # runs at start
    after = mcp_client.in_project(command, [project])
    assert list(before) == list(after) == [str(python.resolve())] and before != after
    # an editable install (uv sync): the project's source a .pth file adds is held too
    source = project / "src" / "srv"
    source.mkdir(parents=True)
    (source / "__main__.py").write_text("print()\n", encoding="utf-8")
    (packages / "_srv.pth").write_text(f"{project / 'src'}\n", encoding="utf-8")
    editable = mcp_client.in_project(command, [project])
    (source / "__main__.py").write_text("print('planted')\n", encoding="utf-8")
    assert editable != mcp_client.in_project(command, [project])
    # past the cap, nothing is hashed: asked about every time, and the card says why
    monkeypatch.setattr(mcp_client, "MAX_TREE_FILES", 1)
    (scripts / "pip.exe").write_bytes(b"MZ")
    big = mcp_client.in_project(command, [project])
    assert big == {str(python.resolve()): None}
    assert not mcp_client.trusted(big, big) and "asked every time" in mcp_client.runs(big)


def test_a_pth_line_is_read_as_site_reads_it(tmp_path):
    project = tmp_path / "proj"
    packages = project / ".venv" / "Lib" / "site-packages"
    packages.mkdir(parents=True)
    for name in ("rel", "rooted", "skipped"):
        (project / name).mkdir()
    pth = packages / "_srv.pth"
    # relative: joined onto site-packages' folder, as `site` does (old code skipped it on every
    # version); `/x` with no drive: on that folder's drive (3.13's isabs drops it on Windows;
    # passes on 3.12 with the old code too); a comment and an import line: not folders.
    pth.write_text("\n".join([
        os.path.join("..", "..", "..", "rel"), os.path.splitdrive(project / "rooted")[1],
        f"# {project / 'skipped'}", f"import os; {project / 'skipped'}", "", "  "]) + "\n",
        encoding="utf-8")
    found = [path.resolve() for path in mcp_client._editable(pth, [project.resolve()])]
    assert found == [(project / "rel").resolve(), (project / "rooted").resolve()]


def test_a_pth_file_in_the_locales_encoding_is_read_as_site_reads_it(tmp_path, monkeypatch):
    # setuptools writes it so: not UTF-8, read in the locale's encoding (3.13's `site`)
    monkeypatch.setattr("locale.getencoding", lambda: "cp1254")
    project = tmp_path / "proj"
    packages = project / ".venv" / "Lib" / "site-packages"
    packages.mkdir(parents=True)
    (project / "kaynakşı").mkdir()
    pth = packages / "_srv.pth"
    pth.write_bytes(f"{project / 'kaynakşı'}\n".encode("cp1254"))
    assert [p.resolve() for p in mcp_client._editable(pth, [project.resolve()])] == [
        (project / "kaynakşı").resolve()]
    pth.write_bytes(f"﻿{project / 'kaynakşı'}\n".encode())  # and UTF-8, with its BOM
    assert len(mcp_client._editable(pth, [project.resolve()])) == 1


def test_a_network_or_device_path_is_never_looked_at(tmp_path, monkeypatch):
    looked = []
    monkeypatch.setattr(Path, "resolve", lambda self, *a, **k: looked.append(self) or self)
    for far in ("\\\\host\\share\\server.py", "\\\\?\\C:\\proj\\server.py", "//host/share/s.py"):
        assert mcp_client.in_project([sys.executable, far], [Path("C:/proj")]) == {}
    assert not [p for p in looked if "host" in str(p) or "?" in str(p)]


def test_a_card_names_a_few_files_within_a_questions_size():
    files = {f"C:\\proj\\{'x' * 400}{n}.py": "h" for n in range(10)}
    said = mcp_client.runs(files)
    assert "and 7 more" in said and len(said) < MAX_QUESTION_CHARS - 200
