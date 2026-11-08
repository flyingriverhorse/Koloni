"""K-bilgi-klasor: a folder on this machine as a knowledge ("folder: <its full path>"), learned as a
repository is with the folder itself, read in place, for the clone: counted in Python before
anything of it is read or kept - no link or junction followed, nothing run in it, its `.git` never
read - its code scanned and kept as text in the project, its guide written, Learn more going on
with the next code files. Nothing is written into the folder. Only the user adds one, on the
Knowledge page; a path that is no folder, a link, a place KOLONİ never opens, the home's settings
or the project itself is refused. The most files and MB a repository or a folder may hold are the
user's to set, app-wide (Settings › The app)."""

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import git, knowledge, schemas, workspace
from tests.test_chat_flow import text
from tests.test_chat_teams_scenarios import OWN
from tests.test_knowledge_page import _pid
from tests.test_repo_knowledge import learn
from tests.test_spawn import begin, call, step

FILES = {
    "README.md": "# Mylib\nAdd with `add()`.",
    "docs/use.md": "## Use\n`add(1, 2)` is 3.",
    "main.py": "from core import add\n\n\ndef run():\n    return add(1, 2)\n",
    "core.py": "def add(a, b):\n    return a + b\n",
    "node_modules/big/index.js": "export const x = 1\n",
}
KEPT = Path(".koloni", "knowledge", "mylib", "code")


@pytest.fixture(autouse=True)
def home(monkeypatch, tmp_path):
    """A home of the test's own: the test's folders lie in the real one's AppData."""
    fake = tmp_path / "home"
    fake.mkdir()
    monkeypatch.setattr(workspace, "_home", lambda: fake)
    return fake


@pytest.fixture
def mylib(tmp_path) -> Path:
    top = tmp_path / "mylib"
    for rel, body in FILES.items():
        (top / rel).parent.mkdir(parents=True, exist_ok=True)
        (top / rel).write_text(body, encoding="utf-8")
    return top


def kept(top: Path | str, root: Path | None = None, **more) -> dict:
    return knowledge.checked({"topic": "Mylib", "sources": [f"folder: {top}"], "max_pages": 50,
                              "max_usd": 0.5, "learn_with": None, **more},
                             by_user=True, root=str(root) if root else None)


def listing(top: Path) -> dict[str, int]:
    """Every entry under it, with its time: what learning must not change."""
    return {str(one.relative_to(top)): one.lstat().st_mtime_ns for one in top.rglob("*")}


def test_a_folder_is_learned_in_place_as_a_repository_and_nothing_is_written_into_it(
        project_dir, mylib, monkeypatch):
    known = kept(mylib, project_dir)
    assert known["sources"] == [f"folder: {mylib.resolve()}"]
    assert knowledge.is_repo(known) and not knowledge.reads_web(known)
    assert knowledge.web_tools(known) == set() and not knowledge.learns_itself(known)
    before = listing(mylib)
    record, asked = learn(project_dir, known)
    read = [one["source"] for one in record["pages"] if one["read"]]
    assert read == ["README.md", "docs/use.md", "main.py", "core.py"]
    assert record["code"]["in_guide"] == ["main.py", "core.py"] and len(asked) == 2
    files = project_dir / KEPT / "files"
    assert (files / "core.py.md").read_text(encoding="utf-8") == FILES["core.py"]
    assert not (files / "node_modules").exists()
    assert "a folder KOLONİ read" in knowledge.brief(str(project_dir), known)
    # A learning that fails as it keeps writes nothing into it either.
    monkeypatch.setattr(knowledge, "_swapped", lambda *a: (_ for _ in ()).throw(OSError("held")))
    with pytest.raises(knowledge.LearnError, match="could not be read or kept"):
        learn(project_dir, known)
    assert listing(mylib) == before and mylib.is_dir()


def test_its_git_is_never_read_nor_run(project_dir, mylib, monkeypatch, tmp_path):
    marker = tmp_path / "ran"
    (mylib / ".git" / "hooks").mkdir(parents=True)
    (mylib / ".git" / "config").write_text(
        f"[core]\n\tfsmonitor = cmd /c echo x > {marker}\n\thooksPath = hooks\n", encoding="utf-8")
    (mylib / ".git" / "secret.md").write_text("# not read", encoding="utf-8")

    def refused(*args, **kwargs):
        raise AssertionError("git ran")

    monkeypatch.setattr(git, "run", refused)
    monkeypatch.setattr(git, "fed_to", refused)
    monkeypatch.setattr(subprocess, "Popen", refused)
    record, _asked = learn(project_dir, kept(mylib, project_dir))
    assert not [one for one in record["pages"] if ".git" in one["source"]]
    assert not marker.exists()
    everything = "".join(one.read_text(encoding="utf-8", errors="replace")
                         for one in (project_dir / ".koloni").rglob("*") if one.is_file())
    assert "fsmonitor" not in everything and "not read" not in everything


@pytest.mark.skipif(sys.platform != "win32", reason="a junction is Windows' own")
def test_a_junction_in_it_is_not_followed_and_one_is_no_folder_to_add(project_dir, mylib,
                                                                      tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "far.md").write_text("# far away", encoding="utf-8")
    (outside / "far.py").write_text("def far():\n    pass\n", encoding="utf-8")
    subprocess.run(["cmd", "/c", "mklink", "/J", str(mylib / "linked"), str(outside)], check=True,
                   capture_output=True)
    record, _asked = learn(project_dir, kept(mylib, project_dir))
    assert not [one for one in record["pages"] if "far" in one["source"]]
    assert not list((project_dir / KEPT).rglob("far*"))
    subprocess.run(["cmd", "/c", "mklink", "/J", str(tmp_path / "via"), str(mylib)], check=True,
                   capture_output=True)
    with pytest.raises(ValueError, match="link or a junction"):
        kept(tmp_path / "via")


@pytest.mark.skipif(sys.platform == "win32", reason="a symbolic link needs an admin on Windows")
def test_a_symlink_in_it_is_not_followed(project_dir, mylib, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "far.md").write_text("# far away", encoding="utf-8")
    os.symlink(outside, mylib / "linked")
    os.symlink(mylib, tmp_path / "via")
    record, _asked = learn(project_dir, kept(mylib, project_dir))
    assert not [one for one in record["pages"] if "far" in one["source"]]
    with pytest.raises(ValueError, match="link or a junction"):
        kept(tmp_path / "via")


@pytest.mark.parametrize("cap", ["files", "bytes"])
def test_a_folder_over_its_caps_is_refused_before_anything_is_kept(project_dir, mylib,
                                                                   monkeypatch, cap):
    if cap == "files":
        for n in range(20):
            (mylib / "many" / f"{n}.txt").parent.mkdir(exist_ok=True)
            (mylib / "many" / f"{n}.txt").write_text("", encoding="utf-8")
        monkeypatch.setattr(knowledge, "MAX_CLONE_FILES", 10)
    else:
        (mylib / "big.bin").write_bytes(b"x" * 80_000)
        monkeypatch.setattr(knowledge, "MAX_CLONE_BYTES", 64 * 1024)
    # (node_modules/ is not counted: 6 entries, a few bytes, before these.)
    with pytest.raises(knowledge.LearnError, match="nothing of it is read"):
        learn(project_dir, kept(mylib, project_dir))
    assert not (project_dir / KEPT).exists()
    assert not (project_dir / KEPT.parent / "pages").exists()


def test_learn_more_goes_on_with_the_next_code_files(project_dir, tmp_path):
    top = tmp_path / "five"
    top.mkdir()
    (top / "README.md").write_text("# Five", encoding="utf-8")
    for n in range(1, 6):
        (top / f"m{n}.py").write_text(f"def f{n}():\n    return {n}\n", encoding="utf-8")
    known = kept(top, project_dir, max_code_files=2)
    learned = [learn(project_dir, known)[0]["code"]["in_guide"] for _ in range(3)]
    assert [len(one) for one in learned] == [2, 4, 5]


def test_only_what_was_counted_is_read_kept_or_sent(project_dir, mylib, monkeypatch):
    """Hidden, build and dependency folders (in any case), a file in the cloud alone and one made
    after the count: none of them scanned, kept, read or sent to the model."""
    for rel in (".hidden/mod.py", ".hidden/notes.md", "build/out.md", "dist/x.py",
                "target/t.md", ".next/n.md", "Node_Modules/m.md", "cloud.md", "cloud.py"):
        (mylib / rel).parent.mkdir(parents=True, exist_ok=True)
        body = b"LEAKED = 1\n" if rel.endswith(".py") else b"# LEAKED\n"
        (mylib / rel).write_bytes(body.ljust(4242) if rel.startswith("cloud") else body)
    # (Windows' cloud marks stood in for: a file of 4242 bytes is in the cloud alone.)
    monkeypatch.setattr(knowledge, "_cloud_only", lambda facts: facts.st_size == 4242)
    counted = knowledge._counted

    def then_more(*args):
        found = counted(*args)
        (mylib / "late.md").write_text("# LEAKED late", encoding="utf-8")
        (mylib / "late.py").write_text("LEAKED = 2\n", encoding="utf-8")
        return found

    monkeypatch.setattr(knowledge, "_counted", then_more)
    record, asked = learn(project_dir, kept(mylib, project_dir))
    assert [one["source"] for one in record["pages"]] == [
        "README.md", "docs/use.md", "main.py", "core.py"]
    assert record["code"]["scanned"] == 2
    sent = str(asked)
    kept_text = "".join(one.read_text(encoding="utf-8", errors="replace")
                        for one in (project_dir / ".koloni").rglob("*") if one.is_file())
    assert "LEAKED" not in sent and "LEAKED" not in kept_text
    # (A learning stopped at its time reads no file more.)
    with pytest.raises(knowledge.LearnError, match="stopped"):
        knowledge._files(str(mylib), ".", 10, None, ".md", None, {"stopped": True})


def test_the_cloud_marks_are_windows_three():
    for marks, cloud in ((0x400000, True), (0x40000, True), (0x1000, True), (0x20, False)):
        assert knowledge._cloud_only(SimpleNamespace(st_file_attributes=marks)) is cloud
    assert not knowledge._cloud_only(SimpleNamespace())  # (off Windows)


# --- what may be added ---------------------------------------------------------------------------


def test_a_path_that_is_not_a_plain_folder_is_refused(mylib, home, tmp_path, monkeypatch):
    (home / ".ssh" / "keys").mkdir(parents=True)
    (home / ".config" / "tool").mkdir(parents=True)
    (home / "AppData" / "Local" / "x").mkdir(parents=True)
    (home / "Library" / "x").mkdir(parents=True)
    (tmp_path / "old-home" / ".ssh").mkdir(parents=True)
    (tmp_path / "other-koloni" / "data").mkdir(parents=True)
    (tmp_path / "other-koloni" / "data" / "koloni.db").write_bytes(b"")
    (tmp_path / "other-checkout" / "runtime" / "data").mkdir(parents=True)
    (tmp_path / "other-checkout" / "runtime" / "data" / "koloni.db").write_bytes(b"")
    runtime = tmp_path / "rt"
    (runtime / "data").mkdir(parents=True)
    monkeypatch.setenv("KOLONI_RUNTIME_ROOT", str(runtime))
    project = tmp_path / "outer" / "proj"
    (project / "sub").mkdir(parents=True)
    for given, said in [
        ("mylib", "full path"),
        (tmp_path / "missing", "does not exist"),
        (mylib / "core.py", "not a folder"),
        (Path(mylib.anchor), "root"),
        (home, "holds"),
        (home / ".ssh" / "keys", "settings"),
        (home / ".config" / "tool", "home's settings"),
        (home / "AppData" / "Local" / "x", "home's settings"),
        (tmp_path / "old-home" / ".ssh", "secrets"),
        (tmp_path / "other-koloni", "KOLONİ's runtime"),
        (tmp_path / "other-checkout", "KOLONİ's runtime"),
        (runtime / "data", "KOLONİ's own record"),
        (project, "use code:"),
        (project / "sub", "use code:"),
        (tmp_path / "outer", "use code:"),  # (it holds the project)
    ]:
        with pytest.raises(ValueError, match=said):
            kept(given, project)
    assert kept(mylib, project)["sources"] == [f"folder: {mylib.resolve()}"]
    # A Library of the home is macOS' settings; elsewhere a folder like any.
    monkeypatch.setattr(knowledge.sys, "platform", "darwin")
    with pytest.raises(ValueError, match="home's settings"):
        kept(home / "Library" / "x", project)
    monkeypatch.setattr(knowledge.sys, "platform", "win32")
    assert kept(home / "Library" / "x", project)["sources"] == [
        f"folder: {(home / 'Library' / 'x').resolve()}"]
    with pytest.raises(ValueError, match="no other source"):
        knowledge.checked({"topic": "Mylib", "sources": [f"folder: {mylib}", "docs"]},
                          by_user=True)


@pytest.mark.parametrize("given", ["folder: {top}", "FOLDER:{top}", "  Folder: {top}  ",
                                   "folder: {top}/missing"])
def test_only_the_user_adds_a_folder_and_an_agent_learns_nothing_of_its_path(mylib, given):
    with pytest.raises(ValueError) as refused:
        knowledge.checked({"topic": "Mylib", "sources": [given.format(top=mylib)]})
    assert str(refused.value) == knowledge.NOT_BY_AGENT


def test_an_agent_cannot_make_an_expert_of_a_folder(make_client, wait_run, project_dir, mylib):
    client, _model = make_client({"Lead": [
        step(call("create_role", {"name": "Lib expert", "tools": ["read_file", "search"],
                                  "sources": [f"folder: {mylib}"]}, "r0")),
        step(call("create_role", {"name": "Lib2 expert", "tools": ["read_file"],
                                  "sources": [f"Folder:{mylib}/nowhere"]}, "r1")),
        text("made"),
    ]})
    cid, run_id = begin(client, project_dir, mode="full_auto", content="make a lib expert")
    snap = wait_run(client, cid, run_id)
    by_id = {t["provider_call_id"]: t for t in snap["tool_calls"]}
    for one in ("r0", "r1"):
        assert by_id[one]["status"] == "failed"
        assert knowledge.NOT_BY_AGENT in by_id[one]["result"]
    names = {r["name"] for r in client.get("/api/roles").json()}
    assert not {"Lib expert", "Lib2 expert"} & names
    pid = _pid(client, project_dir)
    assert not [one for one in client.get(f"/api/projects/{pid}/knowledge").json()
                if knowledge.is_repo(one["knowledge"])]


def test_the_page_adds_it_will_not_change_it_while_it_learns_and_removes_what_it_kept(
        client, project_dir, mylib):
    pid = _pid(client, project_dir)
    body = {"topic": "Mylib", "sources": [f"folder: {mylib}"]}
    assert client.post(f"/api/projects/{pid}/knowledge", json=body).status_code == 403
    added = client.post(f"/api/projects/{pid}/knowledge", headers=OWN, json=body)
    assert added.status_code == 201, added.text
    row = added.json()
    assert row["knowledge"]["sources"] == [f"folder: {mylib.resolve()}"]
    inside = client.post(f"/api/projects/{pid}/knowledge", headers=OWN, json={
        "topic": "Self", "sources": [f"folder: {project_dir}"]})
    assert inside.status_code == 422 and "use code:" in inside.text
    known = row["knowledge"]
    knowledge.begin(str(project_dir), known)
    try:
        busy = client.put(f"/api/knowledge/{row['id']}", params={"project_id": pid}, headers=OWN,
                          json={**body, "max_code_files": 5})
        assert busy.status_code == 409
    finally:
        knowledge.end(str(project_dir), known)
    (project_dir / KEPT / "files").mkdir(parents=True)
    gone = client.delete(f"/api/knowledge/{row['id']}", params={"project_id": pid}, headers=OWN)
    assert gone.status_code == 204 and not (project_dir / KEPT).exists() and mylib.is_dir()


# --- the limits, app-wide ------------------------------------------------------------------------


def test_the_limits_are_the_users_whole_numbers_in_range(client):
    assert client.get("/api/knowledge-limits").json() == {"max_files": 50_000, "max_mb": 300}
    assert client.put("/api/knowledge-limits", json={"max_files": 500}).status_code == 403
    for bad in ({"max_files": 99}, {"max_files": 1_000_001}, {"max_mb": 0}, {"max_mb": 10_241},
                {"max_files": "500"}, {"max_mb": 1.5}, {"max_files": None, "other": 1}):
        assert client.put("/api/knowledge-limits", json=bad, headers=OWN).status_code == 422, bad
    said = client.put("/api/knowledge-limits", json={"max_files": 500}, headers=OWN)
    assert said.json() == {"max_files": 500, "max_mb": 300}
    said = client.put("/api/knowledge-limits", json={"max_mb": 2}, headers=OWN)
    assert said.json() == {"max_files": 500, "max_mb": 2}
    assert client.get("/api/knowledge-limits").json() == {"max_files": 500, "max_mb": 2}
    # Its ranges are the learning's own (`knowledge.FILES_RANGE`, `MB_RANGE`), written again in
    # the schema: held equal here, in its fields and at the API.
    for key, (low, high) in (("max_files", knowledge.FILES_RANGE),
                             ("max_mb", knowledge.MB_RANGE)):
        bounds = {name: getattr(one, name) for one in schemas.TreeLimits.model_fields[key].metadata
                  for name in ("ge", "le") if hasattr(one, name)}
        assert bounds == {"ge": low, "le": high}, key
        for value, status in ((low - 1, 422), (low, 200), (high, 200), (high + 1, 422)):
            assert client.put("/api/knowledge-limits", json={key: value},
                              headers=OWN).status_code == status, (key, value)


def test_a_lower_limit_stops_a_learning(client, project_dir, mylib, monkeypatch):
    for n in range(120):
        (mylib / "many" / f"{n}.txt").parent.mkdir(exist_ok=True)
        (mylib / "many" / f"{n}.txt").write_text("", encoding="utf-8")
    known = kept(mylib, project_dir)
    assert learn(project_dir, known)[0]["code"]["in_guide"]  # (under the default caps)
    assert client.put("/api/knowledge-limits", json={"max_files": 100},
                      headers=OWN).status_code == 200
    with client.app.state.session_factory() as session:  # type: ignore[attr-defined]
        tree = knowledge.tree_limits(session)
    assert tree == (100, 300 * 2**20)
    with pytest.raises(knowledge.LearnError, match="over 100 files"):
        learn(project_dir, known, tree=tree)
    # A repository's free-disk check holds whatever the cap: 2 GB at least, more for a bigger one.
    monkeypatch.setattr(knowledge.shutil, "disk_usage",
                        lambda at: type("U", (), {"free": 3 * 2**30})())
    knowledge._counted(mylib, (1_000, 2**20), float("inf"))  # (no clone: no disk asked)
    with pytest.raises(knowledge.LearnError, match="less than 4 GB is free"):
        knowledge._cloned(project_dir.parent / "clone", "https://github.com/a/b",
                          float("inf"), (100, 4 * 2**30))
