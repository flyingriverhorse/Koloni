"""K-buyuk-proje, third slice: the copy of an agent that works in one part of a project holds only
that part, the project root's own files and the usual links. The rest is read in the project, by
full path, and never changed from the copy; Take in, behind and refresh see only what the copy
holds - a part left out of it is never a deletion."""

import json
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import select

from app import copies
from app.config import load_settings
from app.db.models import Agent
from app.db.session import make_engine, make_session_factory
from app.main import create_app
from tests.conftest import Gate
from tests.fakes import Script, ScriptedExecutor, ScriptedModel
from tests.keyed import TestClient
from tests.test_chat_flow import text
from tests.test_claim_scenarios import ORIGIN, calls, write
from tests.test_claude_native import claude_app  # noqa: F401  (a fixture)
from tests.test_copy_later_scenarios import again
from tests.test_copy_runner import card_of, here, kept_folders
from tests.test_native_copies import begin
from tests.test_parallel import until
from tests.test_project_map import _link, _put
from tests.test_spawn import call, step

SECRET = "TOKEN=sk-web-secret-123"
VENV = "..\\.venv\\Scripts\\python.exe -m pytest"


def mono(root: Path) -> Path:
    """Three parts (core, web, docs), root config and the repository's .venv at the root."""
    return _put(root, {
        "pyproject.toml": "[tool.pytest.ini_options]\n", "conftest.py": "", ".gitignore": "*.log\n",
        "core/pyproject.toml": "", "core/pkg/a.py": "A = 1\n", "core/tests/test_a.py": "",
        "web/package.json": json.dumps({"scripts": {"test": "vitest run"}}),
        "web/notes.txt": "web notes", "web/.env": SECRET, "docs/guide.md": "guide",
        ".venv/Scripts/python.exe": "",
    })


@pytest.fixture
def project(tmp_path: Path) -> Path:
    return mono(tmp_path / "repo").resolve()


@pytest.fixture
def runtime(tmp_path: Path) -> Path:
    return tmp_path / "runtime"


def held(copy: copies.Copy) -> list[str]:
    return sorted(p.relative_to(copy.root).as_posix() for p in copy.root.rglob("*")
                  if p.is_file() and ".venv" not in p.parts)


def test_a_part_copy_holds_only_its_part_the_root_files_and_the_links(project, runtime):
    copy = copies.make(project, runtime, "a1", part="core/")
    assert held(copy) == [".gitignore", "conftest.py", "core/pkg/a.py", "core/pyproject.toml",
                          "core/tests/test_a.py", "pyproject.toml"]
    assert list(copy.links) == [".venv"] and (copy.root / ".venv" / "Scripts" / "python.exe").exists()
    assert copy.part == "core/" and copy.left == ("docs/", "web/") and not copy.git
    # An agent without a part: the whole project, as before.
    whole = copies.make(project, runtime, "a2")
    assert "web/notes.txt" in held(whole) and whole.part is None and whole.left == ()


def test_take_in_offers_only_what_the_copy_holds_never_a_part_left_out_as_deleted(project, runtime):
    copy = copies.make(project, runtime, "a1", part="core/")
    (copy.root / "core" / "pkg" / "a.py").write_text("A = 2\n", encoding="utf-8")
    (copy.root / "pyproject.toml").write_text("[tool.ruff]\n", encoding="utf-8")
    # A command's doing outside the part: shown, never taken (`NOT_IN_PART`).
    _put(copy.root, {"web/made.py": "x", "docs/guide.md": "theirs"})
    assert copy.changes() == [("core/pkg/a.py", "changed", "ready"),
                              ("docs/guide.md", "changed", "left_out"),
                              ("pyproject.toml", "changed", "ready"),
                              ("web/made.py", "new", "left_out")]
    # So is a file at the root named like another part's folder.
    shutil.rmtree(copy.root / "web")
    (copy.root / "web").write_text("a file", encoding="utf-8")
    assert not copy.holds("web") and ("web", "new", "left_out") in copy.changes()


def test_a_root_file_the_project_turned_into_a_folder_is_no_change_of_the_copy(project, runtime):
    copy = copies.make(project, runtime, "a1", part="core/")
    (project / "conftest.py").unlink()
    _put(project, {"conftest.py/x.py": ""})  # (the user's, since: not the part copy's)
    assert copy.changes() == []


def test_behind_and_refresh_ignore_the_other_parts(project, runtime):
    copy = copies.make(project, runtime, "a1", part="core/")
    _put(project, {"core/pkg/a.py": "A = 3\n", "web/notes.txt": "new", "web/new.txt": "n",
                   "docs/more.md": "m", "README.md": "root"})
    assert sorted(copy.behind()) == ["README.md", "core/pkg/a.py"]
    assert not copy.refresh("web/notes.txt") and not copy.refresh("web/new.txt")
    assert not (copy.root / "web").exists()
    assert copy.refresh("core/pkg/a.py") and copy.refresh("README.md")
    assert copy.changes() == []


def test_the_other_parts_are_read_in_the_project_never_what_the_copy_holds(
        project, runtime, tmp_path):
    copy = copies.make(project, runtime, "a1", part="core/")
    elsewhere = _put(tmp_path / "elsewhere", {"x.txt": "x"})
    _link(elsewhere, project / "web" / "out")
    _link(project / "core", project / "web" / "core")
    try:
        assert copy.left_out(project / "web" / "notes.txt") and copy.left_out(project / "web")
        assert copy.left_out(project / "docs" / "guide.md")
        assert copy.left_out(project / "web" / ".env")  # (by name refused: `Workspace.resolve`)
        assert not copy.left_out(project / "core" / "pkg" / "a.py")
        assert not copy.left_out(project / "web" / "core" / "pkg" / "a.py")  # (the copy's)
        assert not copy.left_out(project / "web" / "out" / "x.txt")  # (out of the project)
        assert not copy.left_out(project / "pyproject.toml") and not copy.left_out(project)
        assert not copy.left_out(project / ".venv" / "Scripts" / "python.exe")
    finally:
        copies._unlink(project / "web" / "out")
        copies._unlink(project / "web" / "core")


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_a_part_over_the_caps_is_copied_as_git_tracks_it(project, runtime, monkeypatch):
    _put(project, {".gitignore": "core/data/\n", "core/data/big.csv": "a,b\n"})
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    subprocess.run(["git", "add", "-A"], cwd=project, check=True)
    monkeypatch.setattr(copies, "MAX_FILES", 6)
    copy = copies.make(project, runtime, "a1", part="core/")
    assert held(copy) == [".gitignore", "conftest.py", "core/pkg/a.py", "core/pyproject.toml",
                          "core/tests/test_a.py", "pyproject.toml"]
    assert copy.git and copy.part == "core/" and copy.left == ("core/", "docs/", "web/")
    assert copy.left_out(project / "core" / "data" / "big.csv")
    assert copy.left_out(project / "web" / "notes.txt")


def forge(copy: copies.Copy, **said) -> None:
    note = copy.root.parent / copies.BASE_FILE
    found = json.loads(note.read_text(encoding="utf-8"))
    note.write_text(json.dumps({**found, **said}), encoding="utf-8")


def test_a_restart_keeps_the_part_and_a_forged_note_changes_nothing(project, runtime):
    copy = copies.make(project, runtime, "a1", part="core/")
    again = copies.load(project, runtime, "a1", part="core/")
    assert again.part == "core/" and again.base == copy.base and again.changes() == []
    # The agent rewrote the note: a part of its own, and another part's files as if held.
    real = copies.digest(project / "web" / "notes.txt")
    files = {**{copy.names[k]: v for k, v in copy.base.items()}, "web/notes.txt": real}
    for part in (None, "web/", "core/pkg/", "../web/", 7):
        forge(copy, part=part, files=files)
        kept = copies.kept(project, runtime, "a1", copy.root, [], part="core/")
        assert kept.part == "core/" and "web/notes.txt" not in kept.names, part
        assert kept.changes() == [], part  # (never "web/notes.txt", "deleted", "ready")
    # The records are the only word on the part: a whole copy is never narrowed by the note.
    forge(copy, part="core/")
    assert copies.load(project, runtime, "a1").part is None
    # One with nothing to say what it was made from is held to its part all the same.
    (copy.root.parent / copies.BASE_FILE).unlink()
    kept = copies.kept(project, runtime, "a1", copy.root, ["web/notes.txt"], part="core/")
    assert kept.two_way and kept.part == "core/" and kept.changes() == []


# --- in a turn ------------------------------------------------------------------------------


def started(make_client, root, scripts, executor):
    client, model = make_client(scripts, executor=executor)
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(root)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    assert client.patch(f"/api/conversations/{cid}", json={
        "permission_mode": "full_auto", "spawn_approval": "never", "spawn_max_parallel": 2,
    }).status_code == 200
    run = client.post(f"/api/conversations/{cid}/messages", json={"content": "go"}).json()["run"]
    return client, model, cid, run["id"]


def spawn(folder, id="s", task="do it"):
    return call("spawn_agent", {"role": "Coder", "task": task, "folder": folder}, id)


def test_a_sub_agent_in_a_part_works_reads_the_rest_and_takes_in_only_its_part(
        make_client, wait_run, project):
    p = project.as_posix()
    executor = ScriptedExecutor([Script(["ok\n"], writes={"../web/made.py": "x"})])
    client, _model, cid, run_id = started(make_client, project, {
        "Lead": [step(spawn("core")), text("done")],
        "Coder": [step(write("core/pkg/a.py", "A = 2\n")),
                  step(call("run_command", {"command": VENV}, "c")),
                  step(call("read_file", {"path": f"{p}/web/notes.txt"}, "r1")),
                  step(call("read_file", {"path": f"{p}/web/.env"}, "r2")),
                  step(call("read_file", {"path": "web/notes.txt"}, "r3")),
                  step(call("list_dir", {"path": f"{p}/web"}, "l1")),
                  step(call("search", {"pattern": "notes", "path": f"{p}/web"}, "f1")),
                  step(call("search", {"pattern": "sk-web", "path": f"{p}/web"}, "f2")),
                  step(write("web/x.txt", "x", "w2")),
                  step(write(f"{p}/web/notes.txt", "x", "w3")), text("did it")],
    }, executor)
    snap = wait_run(client, cid, run_id, timeout=15)
    assert snap["runs"][0]["status"] == "completed"
    (made, notice), (other, why), (direct, refused) = calls(snap, "Coder", "write_file")
    assert made == "succeeded" and 'holds only your part "core/"' in notice
    assert "(docs/, web/)" in notice and "read_file, list_dir or search" in notice
    assert other == "failed" and 'not in this copy: it holds only "core/"' in why
    assert direct == "failed" and "is a file of the project itself" in refused
    # The root's .venv, from the part, in the copy.
    ((command, cwd),) = executor.started
    assert command == VENV and Path(cwd).resolve() == (here(client, snap) / "core").resolve()
    (read, secret, relative) = calls(snap, "Coder", "read_file")
    assert read == ("succeeded", read[1]) and "web notes" in read[1]
    assert secret[0] == "failed" and "secret" in secret[1] and SECRET not in secret[1]
    assert relative[0] == "failed" and 'it holds only "core/"' in relative[1]
    assert f"full path, under {project}" in relative[1]
    ((listed, names),) = calls(snap, "Coder", "list_dir")
    (searched, found), (_status, keyed) = calls(snap, "Coder", "search")
    assert SECRET not in keyed and "sk-web-secret" not in keyed, keyed
    assert listed == "succeeded" and "notes.txt" in names
    assert searched == "succeeded" and "notes.txt" in found
    # Taken in: its part's change alone - the command's file in another part is shown, not
    # taken, and keeps the copy for the user; nothing the copy left out is a deletion.
    (merge,) = snap["merges"]
    assert merge["status"] == "kept" and merge["kept_in"]
    assert {f["path"]: (f["state"], f["note"]) for f in merge["files"]} == {
        "core/pkg/a.py": ("applied", None), "web/made.py": ("left_out", copies.NOT_IN_PART)}
    ((_status, told),) = calls(snap, "Lead", "spawn_agent")
    assert f"web/made.py ({copies.NOT_IN_PART})" in told
    assert (project / "core" / "pkg" / "a.py").read_text(encoding="utf-8") == "A = 2\n"
    assert not (project / "web" / "made.py").exists() and not (project / "web" / "x.txt").exists()
    assert (project / "web" / "notes.txt").read_text(encoding="utf-8") == "web notes"
    assert (project / "docs" / "guide.md").exists()


def test_another_parts_take_in_brings_nothing_into_a_part_copy(make_client, wait_run, project):
    # (Which Coder gets which part is a race: each makes a file in its own part's folder.)
    gate, made = Gate(), Script(["ok\n"], writes={"made.txt": "x"})
    client, _model, cid, run_id = started(make_client, project, {
        "Lead": [step(spawn("core", "s1"), spawn("web", "s2")), text("done")],
        "Coder": [step(call("run_command", {"command": "make"}, "c")), gate.step(text("done"))],
        "Coder 2": [step(call("run_command", {"command": "make"}, "c")), text("done")],
    }, ScriptedExecutor([made, made]))
    gate.wait_partial()
    snap = until(client, cid, lambda s: [m["status"] for m in s["merges"]] == ["applied"])
    (theirs,) = [part for part in ("core", "web") if (project / part / "made.txt").exists()]
    (mine,) = {"core", "web"} - {theirs}
    held = here(client, snap, "Coder")
    assert (held / mine / "made.txt").exists() and not (held / theirs).exists()
    gate.release()
    snap = wait_run(client, cid, run_id, timeout=15)
    assert sorted(f["path"] for m in snap["merges"] for f in m["files"]) == [
        "core/made.txt", "web/made.txt"]


def test_after_a_restart_a_forged_note_offers_no_other_parts_file_as_deleted(settings_env, project):
    gate = Gate()  # (closed while its Coder is at work: its copy is kept)
    app_ = create_app(load_settings(settings_env), model=ScriptedModel({
        "Lead": [step(spawn("core")), text("done")],
        "Coder": [step(write("core/pkg/a.py", "A = 2\n")), gate.step(text("done"))]}))
    with TestClient(app_, base_url="http://127.0.0.1:8790") as client:
        client.headers["Origin"] = ORIGIN
        pid = client.post("/api/projects", json={"root_path": str(project)}).json()["id"]
        cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
        assert client.patch(f"/api/conversations/{cid}", json={
            "permission_mode": "full_auto", "spawn_approval": "never"}).status_code == 200
        client.post(f"/api/conversations/{cid}/messages", json={"content": "go"})
        gate.wait_partial()
    gate.release()
    (folder,) = kept_folders(settings_env)
    with make_session_factory(make_engine(load_settings(settings_env).db_path))() as s:
        assert [a.copy.get("parts") for a in s.scalars(select(Agent)) if a.copy] == [
            {str(folder / copies.TREE): "core/"}]
    # The agent's command rewrote the note: another part's file as held.
    note = folder / copies.BASE_FILE
    found = json.loads(note.read_text(encoding="utf-8"))
    found["files"]["web/notes.txt"] = copies.digest(project / "web" / "notes.txt")
    note.write_text(json.dumps(found), encoding="utf-8")
    with again(settings_env) as client:
        card = card_of(client, cid)
        assert {f["path"]: f["state"] for f in card["files"]} == {"core/pkg/a.py": "ready"}


def test_a_part_agent_that_goes_on_after_it_stopped_gets_its_part_copy_back(
        make_client, wait_run, project):
    """B-322 with a part: stopped at the step limit, its part copy is kept; told to go on, it is
    in that same copy again - its own change there, still only its part."""
    from tests.test_claim_scenarios import setup
    from tests.test_copy_scenarios import looping

    client, _model, cid, run_id = setup(make_client, project, {
        "Lead": [step(spawn("core")),
                 step(call("message_agent", {"to": "Coder", "message": "go on"}, "m")),
                 text("done")],
        "Coder": [step(write("core/pkg/a.py", "A = 2\n")), *looping("a")[:24],
                  step(call("read_file", {"path": "core/pkg/a.py"}, "r1")),
                  step(call("read_file", {"path": "web/notes.txt"}, "r2")),
                  step(call("edit_file", {"path": "core/pkg/a.py", "old_string": "A = 2",
                                          "new_string": "A = 3"}, "e")), text("done")],
    }, permission_mode="ask")
    snap = until(client, cid, lambda s: "pending" in [m["status"] for m in s["merges"]],
                 timeout=20)
    (own, other) = calls(snap, "Coder", "read_file")
    assert own[0] == "succeeded" and "A = 2" in own[1]  # (its kept copy, not a new one)
    assert other[0] == "failed" and 'it holds only "core/"' in other[1]
    assert sorted(m["status"] for m in snap["merges"]) == ["discarded", "pending"]
    card = next(m for m in snap["merges"] if m["status"] == "pending")
    assert [f["path"] for f in card["files"]] == ["core/pkg/a.py"]
    assert client.post(f"/api/merges/{card['id']}/approve").status_code == 200
    wait_run(client, cid, run_id)
    assert (project / "core" / "pkg" / "a.py").read_text(encoding="utf-8") == "A = 3\n"
    assert (project / "web" / "notes.txt").read_text(encoding="utf-8") == "web notes"


# --- security review round --------------------------------------------------------------------


def test_a_kept_part_card_keeps_its_part_when_the_agent_goes_on_in_another_copy(
        settings_env, project):
    """The part is on the agent's record by tree: a later copy of the same agent - here of
    another part, as one gone on with in a later turn may be - does not change the kept
    card's, and a restart keeps the folder with its work."""
    from tests.test_copy_scenarios import looping

    gate = Gate()
    app_ = create_app(load_settings(settings_env), model=ScriptedModel({
        "Lead": [step(spawn("core")), gate.step(step(
            call("message_agent", {"to": "Coder", "message": "go on"}, "m"))), text("done")],
        "Coder": [step(write("core/pkg/a.py", "A = 2\n")), *looping("a")[:24],
                  step(write("web/notes.txt", "W", "w2")), text("done")]}))
    with TestClient(app_, base_url="http://127.0.0.1:8790") as client:
        client.headers["Origin"] = ORIGIN
        pid = client.post("/api/projects", json={"root_path": str(project)}).json()["id"]
        cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
        assert client.patch(f"/api/conversations/{cid}", json={
            "permission_mode": "ask", "spawn_approval": "never"}).status_code == 200
        client.post(f"/api/conversations/{cid}/messages", json={"content": "go"})
        gate.wait_partial()
        runner = client.app.state.runner
        runner._kept_live.clear()  # (lost, as at a restart: it goes on in a new copy)
        coder = next(a for a, c in runner._ctxs.items() if c.name == "Coder")
        runner._ctxs[coder] = replace(runner._ctxs[coder], part="web/")
        gate.release()
        snap = until(client, cid, lambda s: "pending" in [m["status"] for m in s["merges"]],
                     timeout=20)
        new = next(m for m in snap["merges"] if m["status"] == "pending")
        assert [f["path"] for f in new["files"]] == ["web/notes.txt"]
        assert client.post(f"/api/merges/{new['id']}/reject").status_code == 200
        kept = next(m for m in client.get(f"/api/conversations/{cid}").json()["merges"]
                    if m["status"] == "kept")
        assert [f["path"] for f in kept["files"]] == ["core/pkg/a.py"]
    with again(settings_env) as client:
        card = next(m for m in client.get(f"/api/conversations/{cid}").json()["merges"]
                    if m["status"] == "kept")
        assert {f["path"]: f["state"] for f in card["files"]} == {"core/pkg/a.py": "ready"}
        assert Path(card["kept_in"]).is_dir()


def check_turn(make_client, root, coder, ran):
    """A Coder in core/ at Full auto, in a project whose check command passes (scripted)."""
    client, model = make_client({"Lead": [step(spawn("core")), text("done")], "Coder": coder},
                                executor=ScriptedExecutor([Script(["ok\n"])] * ran))
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(root)}).json()["id"]
    assert client.patch(f"/api/projects/{pid}", json={"check_command": "check"}).status_code == 200
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(f"/api/conversations/{cid}", json={
        "permission_mode": "full_auto", "spawn_approval": "never"})
    client.post(f"/api/conversations/{cid}/messages", json={"content": "go"})
    return client, cid


def test_a_passing_check_does_not_take_a_root_file_in_unasked_from_a_part_copy(
        make_client, project):
    client, cid = check_turn(make_client, project, [
        step(write("pyproject.toml", "[tool.ruff]\n")), text("done")], ran=1)
    snap = until(client, cid, lambda s: [m["status"] for m in s["merges"]] == ["pending"],
                 timeout=15)
    (card,) = snap["merges"]
    assert card["check"]["state"] == "passed" and 'a copy of "core/" alone' in card["check"]["note"]
    assert [f["state"] for f in card["files"]] == ["ready"]
    assert (project / "pyproject.toml").read_text(encoding="utf-8").startswith("[tool.pytest")


def test_a_root_lockfile_from_a_part_copy_waits_for_the_user_and_installs_are_warned(
        make_client, project):
    client, _model, cid, _run_id = started(make_client, project, {
        "Lead": [step(spawn("core")), text("done")],
        "Coder": [step(write("core/pkg/a.py", "A = 2\n")), step(write("uv.lock", "x", "w2")),
                  text("done")]}, None)
    snap = until(client, cid, lambda s: [m["status"] for m in s["merges"]] == ["pending"],
                 timeout=15)
    found = {f["path"]: f for f in snap["merges"][0]["files"]}
    assert found["core/pkg/a.py"]["state"] == "applied" and found["uv.lock"]["state"] == "ready"
    assert "a lockfile at the project root" in found["uv.lock"]["note"]
    assert not (project / "uv.lock").exists()
    ((_made, notice), _lock) = calls(snap, "Coder", "write_file")
    assert "Do not run installs at the project root" in notice


def test_a_root_lockfile_from_a_whole_copy_waits_for_the_user_too(make_client, project):
    # K-lead-folder (R115): a Coder opened without folder ran npm install at the root of its
    # whole copy, and the root lockfile went in at Full auto. A lockfile in a part does not wait.
    client, _model, cid, _run_id = started(make_client, project, {
        "Lead": [step(spawn(None)), text("done")],
        "Coder": [step(write("core/uv.lock", "x")), step(write("package-lock.json", "{}", "w2")),
                  text("done")]}, None)
    snap = until(client, cid, lambda s: [m["status"] for m in s["merges"]] == ["pending"],
                 timeout=15)
    found = {f["path"]: f["state"] for f in snap["merges"][0]["files"]}
    assert found == {"core/uv.lock": "applied", "package-lock.json": "ready"}
    assert "from a working copy" in snap["merges"][0]["files"][1]["note"]
    assert (project / "core" / "uv.lock").exists() and not (project / "package-lock.json").exists()


def test_a_submodule_part_in_gits_list_is_held(project):
    listed = ["core", "web", "pyproject.toml", "web/x.py", "core/x.py"]
    assert copies._held(project, "core/", listed) == ["core", "pyproject.toml", "core/x.py"]


def test_a_write_refused_for_another_part_holds_no_file(make_client, project):
    gate = Gate()
    client, _model, cid, _run_id = started(make_client, project, {
        "Lead": [step(spawn("core")), text("done")],
        # (Its first write, before its copy is made: refused before the file is held.)
        "Coder": [step(write("web/x.txt", "x")), step(write("core/pkg/a.py", "A = 2\n", "w2")),
                  gate.step(text("done"))]}, None)
    gate.wait_partial()
    snap = until(client, cid, lambda s: len(calls(s, "Coder", "write_file")) == 2)
    assert calls(snap, "Coder", "write_file")[0][0] == "failed"
    assert [c["path"] for c in snap["claims"]] == ["core/pkg/a.py"]
    gate.release()


def test_a_native_cli_reading_another_part_in_its_copy_is_told_why(
        claude_app, wait_run, project_dir):  # noqa: F811
    mono(project_dir)
    lead = [step(call("spawn_agent", {"role": "Coder", "task": "do it", "folder": "core"}, "s")),
            text("done")]
    client, provider, _ = claude_app([
        {"tool": "Write", "result": "ok", "input": {"file_path": "CWD/core/pkg/a.py",
                                                    "content": "A = 2\n"},
         "write": ["core/pkg/a.py", "A = 2\n"]},
        {"tool": "Read", "input": {"file_path": "CWD/web/notes.txt"}},
        {"tool": "Write", "input": {"file_path": "CWD/web/x.txt", "content": "x"},
         "write": ["web/x.txt", "x"]},
        {"say": "Done."}], default_steps=lead)
    cid, run_id = begin(client, project_dir, provider)
    snap = wait_run(client, cid, run_id, timeout=20)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    wrote, read, other = claude_app.record()["asked"]
    assert wrote["behavior"] == "allow"
    assert read["behavior"] == "deny" and 'it holds only "core/"' in read["message"]
    assert other["behavior"] == "deny" and 'it holds only "core/"' in other["message"]


def test_a_whole_copy_after_a_part_copy_at_the_same_place_is_compared_whole(settings_env, project):
    """Its part copy taken in and gone, the agent goes on in a whole copy at the same folder:
    kept at a restart, that one's card offers its work outside core/ - no part of before."""
    lead_gate, coder_gate = Gate(), Gate()
    app_ = create_app(load_settings(settings_env), model=ScriptedModel({
        "Lead": [step(spawn("core")), lead_gate.step(step(
            call("message_agent", {"to": "Coder", "message": "go on"}, "m"))), text("done")],
        "Coder": [step(write("core/pkg/a.py", "A = 2\n")), text("core done"),
                  step(write("web/notes.txt", "W", "w2")), coder_gate.step(text("done"))]}))
    with TestClient(app_, base_url="http://127.0.0.1:8790") as client:
        client.headers["Origin"] = ORIGIN
        pid = client.post("/api/projects", json={"root_path": str(project)}).json()["id"]
        cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
        assert client.patch(f"/api/conversations/{cid}", json={
            "permission_mode": "full_auto", "spawn_approval": "never"}).status_code == 200
        client.post(f"/api/conversations/{cid}/messages", json={"content": "go"})
        lead_gate.wait_partial()
        assert (project / "core" / "pkg" / "a.py").read_text(encoding="utf-8") == "A = 2\n"
        runner = client.app.state.runner
        coder = next(a for a, c in runner._ctxs.items() if c.name == "Coder")
        runner._ctxs[coder] = replace(runner._ctxs[coder], part=None)  # (as in a later turn)
        lead_gate.release()
        coder_gate.wait_partial()
    coder_gate.release()
    with again(settings_env) as client:
        card = next(m for m in client.get(f"/api/conversations/{cid}").json()["merges"]
                    if m["status"] == "kept")
        assert {f["path"]: f["state"] for f in card["files"]} == {"web/notes.txt": "ready"}


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_what_git_ignores_made_outside_the_part_does_not_keep_the_copy(
        make_client, wait_run, project):
    _put(project, {".gitignore": "htmlcov/\n"})
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    made = Script(["ok\n"], writes={"../htmlcov/index.html": "report"})  # (a coverage run's)
    client, _model, cid, run_id = started(make_client, project, {
        "Lead": [step(spawn("core")), text("done")],
        "Coder": [step(write("core/pkg/a.py", "A = 2\n")),
                  step(call("run_command", {"command": "cov"}, "c")), text("done")]},
        ScriptedExecutor([made]))
    snap = wait_run(client, cid, run_id, timeout=15)
    (merge,) = snap["merges"]
    assert merge["status"] == "applied" and not merge["kept_in"]
    assert {f["path"]: f["note"] for f in merge["files"]}["htmlcov/index.html"] == copies.IGNORED
