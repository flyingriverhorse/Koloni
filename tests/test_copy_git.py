"""A project too big to copy whole, in a git repository, is copied as git would track it
(K-kopya-git): what git ignores - data, models, outputs - is neither copied nor linked; the agent
is told, and reads it in the project with KOLONİ's read tools. A project small enough, one
without git, or git missing or failing: as before."""

import shutil
import subprocess
from pathlib import Path

import pytest

from app import copies, git

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
IGNORE = "data/*\n!data/.gitkeep\nmodels/\n*.log\n"


def _git(folder: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=folder, check=True, capture_output=True)


def lay_out(root: Path) -> Path:
    """Tracked files, an ignored `data/` that keeps a tracked .gitkeep, an ignored `models/`, an
    ignored top-level log."""
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "src" / "app.py").write_bytes(b"x = 1\n")
    (root / ".gitignore").write_text(IGNORE, encoding="utf-8")
    (root / "data").mkdir()
    (root / "data" / ".gitkeep").write_text("", encoding="utf-8")
    (root / "data" / "train.csv").write_text("a,b\n", encoding="utf-8")
    (root / "data" / ".env").write_text("TOKEN=x\n", encoding="utf-8")
    (root / "models").mkdir()
    (root / "models" / "m.txt").write_text("weights", encoding="utf-8")
    (root / "run.log").write_text("log", encoding="utf-8")
    return root


def repository(root: Path) -> Path:
    """The folder as a repository - and, untracked but not ignored, notes.md."""
    _git(root, "init", "-q")
    _git(root, "add", "-A")  # (tracked by the index: no commit needed)
    (root / "notes.md").write_text("new, not ignored", encoding="utf-8")
    return root


@pytest.fixture
def project(tmp_path: Path) -> Path:
    return repository(lay_out(tmp_path / "proj"))


@pytest.fixture
def runtime(tmp_path: Path) -> Path:
    return tmp_path / "runtime"


@pytest.fixture
def small(monkeypatch):
    """Caps the whole project is over and what git tracks of it is not."""
    monkeypatch.setattr(copies, "MAX_FILES", 5)


def held(copy: copies.Copy) -> list[str]:
    return sorted(p.relative_to(copy.root).as_posix() for p in copy.root.rglob("*") if p.is_file())


@needs_git
def test_a_project_big_only_by_what_git_ignores_gets_a_copy_of_what_git_tracks(
    project, runtime, small
):
    copy = copies.make(project, runtime, "a1")  # (before: TooBig, no copy at all)
    assert held(copy) == [".gitignore", "data/.gitkeep", "notes.md", "src/app.py"]
    assert copy.git and copy.links == {} and copy.left == ("data/", "models/", "run.log")
    # What the agents are told survives a restart.
    again = copies.load(project, runtime, "a1")
    assert again.git and again.left == copy.left


@needs_git
def test_a_git_project_small_enough_is_copied_whole_as_before(project, runtime):
    copy = copies.make(project, runtime, "a1")
    assert {"data/.env", "run.log", "models/m.txt"} <= set(held(copy))
    assert not copy.git and copy.left == ()
    # B-189 as before: a new file git ignores is kept out, also where the project made it too.
    (project / "out.log").write_text("theirs", encoding="utf-8")
    (copy.root / "out.log").write_text("mine", encoding="utf-8")
    assert copy.changes() == [("out.log", "new", "left_out")]
    assert not copy.left_out(project / "data" / "train.csv")  # (nothing left out to read)


@needs_git
def test_over_the_caps_without_git_answering_no_copy_is_made(project, runtime, small, monkeypatch):
    for broken in (lambda: None, lambda: "C:/no/such/git.exe"):  # missing; failing to start
        monkeypatch.setattr(git, "find", broken)
        with pytest.raises(copies.TooBig):
            copies.make(project, runtime, "a1")


def test_a_folder_that_is_no_repository_is_copied_as_before(tmp_path, runtime, monkeypatch):
    plain = lay_out(tmp_path / "plain")
    copy = copies.make(plain, runtime, "a1")
    assert "data/train.csv" in held(copy) and not copy.git
    monkeypatch.setattr(copies, "MAX_FILES", 5)
    with pytest.raises(copies.TooBig):
        copies.make(plain, runtime, "a2")


@needs_git
def test_a_subfolder_of_a_repository_over_the_caps_is_copied_as_git_tracks_it(
    tmp_path, runtime, small
):
    top = tmp_path / "mono"
    (top / "other").mkdir(parents=True)
    (top / "other" / "x.py").write_text("x", encoding="utf-8")
    sub = lay_out(top / "proj")
    repository(top)
    copy = copies.make(sub, runtime, "a1")
    assert held(copy) == [".gitignore", "data/.gitkeep", "src/app.py"] and copy.git
    assert copy.left_out(sub / "data" / "train.csv")
    with pytest.raises(git.Refused):  # (a commit there is still refused)
        git.repository(sub)


@needs_git
def test_the_project_changing_meanwhile_brings_nothing_git_ignores_into_the_copy(
    project, runtime, small, monkeypatch
):
    copy = copies.make(project, runtime, "a1")
    (project / "models" / "more.txt").write_text("x", encoding="utf-8")
    (project / "src" / "app.py").write_bytes(b"x = 2\n")
    (project / "src" / "new.py").write_text("y", encoding="utf-8")
    # (What a check brings in before it runs: `AgentRunner._check`.)
    assert copy.behind() == ["src/app.py", "src/new.py"]
    # git failing now: only the copy's own files are looked at, not all that git ignores.
    monkeypatch.setattr(git, "listed", lambda project: None)
    assert copy.behind() == ["src/app.py"]


@needs_git
def test_what_the_agent_writes_where_git_ignores_is_kept_out_or_asked_about(
    project, runtime, small
):
    copy = copies.make(project, runtime, "a1")
    (copy.root / "data" / "clean.csv").write_text("made", encoding="utf-8")  # B-189: kept out
    (copy.root / "run.log").write_text("mine", encoding="utf-8")  # the project's: not lost
    assert copy.changes() == [("data/clean.csv", "new", "left_out"),
                              ("run.log", "new", "conflict")]
    from app.agent import _merge_file

    card = _merge_file(copy, "run.log")
    assert card is not None and card["note"] == copies.NOT_HELD and card["whole"] is True


@needs_git
def test_a_submodule_or_a_repository_inside_is_copied_whole(project, runtime, monkeypatch):
    inner = project / "vendor" / "lib"
    inner.mkdir(parents=True)
    (inner / "lib.py").write_text("z", encoding="utf-8")
    _git(inner, "init", "-q")
    monkeypatch.setattr(copies, "MAX_FILES", 6)
    copy = copies.make(project, runtime, "a1")
    assert copy.git and (copy.root / "vendor" / "lib" / "lib.py").read_text(encoding="utf-8") == "z"


@needs_git
def test_what_may_be_read_in_the_project_is_judged_by_where_each_path_really_leads(
    project, runtime, small, tmp_path
):
    copy = copies.make(project, runtime, "a1")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "x.txt").write_text("x", encoding="utf-8")
    copies._link(project / "data" / "out", elsewhere)       # out of the project
    copies._link(project / "data" / "src", project / "src")  # into what the copy holds
    try:
        assert copy.left_out(project / "data" / "train.csv")
        assert copy.left_out(project / "run.log") and copy.left_out(project / "models")
        assert copy.left_out(project / "src" / ".." / "data" / "train.csv")
        assert not copy.left_out(project / "data" / ".." / "src" / "app.py")
        assert not copy.left_out(project / "data" / "out" / "x.txt")
        assert not copy.left_out(project / "data" / "src" / "app.py")
        assert not copy.left_out(project / "data" / ".gitkeep")  # the copy holds it
        assert copy.left_out(project / "data") and not copy.left_out(project / "src")
        assert copy.left_out(project / "src" / ".." / "data")
        assert not copy.left_out(project / "notes.md") and not copy.left_out(project)
        assert not copy.left_out(project / ".git" / "config")
    finally:
        copies._unlink(project / "data" / "out")
        copies._unlink(project / "data" / "src")


# --- in a turn ------------------------------------------------------------------------------


def turn(make_client, wait_run, project_dir, coder):
    from tests.test_copy_scenarios import one

    client, _model, cid, run_id = one(make_client, project_dir, coder)
    return wait_run(client, cid, run_id)


@needs_git
def test_the_agent_is_told_and_reads_what_was_left_out_but_changes_nothing_there(
    make_client, wait_run, project_dir, small
):
    from tests.test_chat_flow import text
    from tests.test_claim_scenarios import calls, write
    from tests.test_spawn import call, step

    repository(lay_out(project_dir))
    p = str(project_dir)

    def read(path, id):
        return step(call("read_file", {"path": f"{p}/{path}"}, id))

    snap = turn(make_client, wait_run, project_dir, [
        step(write("a.txt", "A")),
        read("data/train.csv", "r1"), read("run.log", "r2"), read("data/.env", "r3"),
        read("hello.py", "r4"), read("data/../hello.py", "r5"),
        step(call("list_dir", {"path": f"{p}/models"}, "l1")),
        step(call("search", {"pattern": "weights", "path": f"{p}/models"}, "s1")),
        step(write(f"{p}/data/train.csv", "changed", "w2")), text("A done")])
    (made, notice), (wrote, why) = calls(snap, "Coder", "write_file")
    assert made == "succeeded" and "some files git ignores are not in this copy" in notice
    assert "(data/, models/, run.log)" in notice and "read_file, list_dir or search" in notice
    reads = calls(snap, "Coder", "read_file")
    assert [status for status, _said in reads] == [
        "succeeded", "succeeded", "failed", "failed", "failed"], reads
    assert "a,b" in reads[0][1] and "log" in reads[1][1] and "secret" in reads[2][1]
    assert all("is a file of the project itself" in said for _status, said in reads[3:])
    ((listed, names),) = calls(snap, "Coder", "list_dir")
    ((searched, found),) = calls(snap, "Coder", "search")
    assert listed == "succeeded" and "m.txt" in names
    assert searched == "succeeded" and "weights" in found
    assert wrote == "failed" and "is a file of the project itself" in why
    assert (project_dir / "data" / "train.csv").read_text(encoding="utf-8") == "a,b\n"


@needs_git
def test_a_folder_the_copy_holds_only_part_of_is_listed_and_searched_in_the_project(
    make_client, wait_run, project_dir, small
):
    from tests.test_chat_flow import text
    from tests.test_claim_scenarios import calls, write
    from tests.test_spawn import call, step

    repository(lay_out(project_dir))  # (`data/*` with `!data/.gitkeep`: the copy has data/)
    data = f"{project_dir}/data"
    snap = turn(make_client, wait_run, project_dir, [
        step(write("a.txt", "A")),
        step(call("list_dir", {"path": data}, "l1")),
        step(call("search", {"pattern": "a,b", "path": data}, "s1")),
        step(call("list_dir", {"path": f"{project_dir}/src"}, "l2")), text("A done")])
    (listed, names), (whole, refused) = calls(snap, "Coder", "list_dir")
    ((searched, found),) = calls(snap, "Coder", "search")
    assert listed == "succeeded" and "train.csv" in names
    assert searched == "succeeded" and "train.csv" in found
    assert whole == "failed" and "is a file of the project itself" in refused  # copied whole


@needs_git
def test_through_a_listed_folder_that_holds_the_project_what_was_left_out_is_read_too(
    make_client, wait_run, tmp_path, small
):
    from tests.test_chat_flow import text
    from tests.test_claim_scenarios import calls, setup, write
    from tests.test_spawn import call, step

    project_dir = tmp_path / "desk" / "proj"
    project_dir.mkdir(parents=True)
    (project_dir / "hello.py").write_text("print('hi')\n", encoding="utf-8")
    repository(lay_out(project_dir))
    client, _model, cid, run_id = setup(make_client, project_dir, {
        "Lead": [step(call("spawn_agent", {"role": "Coder", "task": "do it"}, "s")), text("done")],
        "Coder": [step(write("a.txt", "A")),
                  step(call("read_file", {"path": f"{project_dir}/data/train.csv"}, "r1")),
                  step(call("read_file", {"path": f"{project_dir}/hello.py"}, "r2")),
                  text("A done")],
    }, also_in=[str(project_dir.parent)])
    snap = wait_run(client, cid, run_id)
    (first, said), (second, refused) = calls(snap, "Coder", "read_file")
    assert first == "succeeded" and "a,b" in said
    assert second == "failed" and "is a file of the project itself" in refused


@needs_git
def test_from_a_copy_made_whole_the_project_is_not_read(make_client, wait_run, project_dir):
    from tests.test_chat_flow import text
    from tests.test_claim_scenarios import calls, write
    from tests.test_spawn import call, step

    repository(lay_out(project_dir))  # (small enough: copied whole, `.env` and data too)
    snap = turn(make_client, wait_run, project_dir, [
        step(write("a.txt", "A")),
        step(call("read_file", {"path": f"{project_dir}/data/train.csv"}, "r1")), text("A done")])
    ((_made, notice),) = calls(snap, "Coder", "write_file")
    assert "git ignores" not in notice
    ((status, said),) = calls(snap, "Coder", "read_file")
    assert status == "failed" and "is a file of the project itself" in said
