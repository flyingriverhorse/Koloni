"""Working copies (slice 19b), the pure part: made, compared, refreshed - and deleted
without ever touching what a link in them leads to. The links are real ones: directory
junctions on Windows, symlinks elsewhere."""

import os
import shutil
import stat
from pathlib import Path

import pytest

from app import copies
from app.workspace import Workspace, WorkspaceError


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    (root / "hello.py").write_bytes(b"print('hi')\n")
    (root / "src" / "app.py").write_bytes(b"x = 1\n")
    (root / "node_modules" / "pkg").mkdir(parents=True)
    (root / "node_modules" / "pkg" / "index.js").write_text("dep", encoding="utf-8")
    return root


@pytest.fixture
def runtime(tmp_path: Path) -> Path:
    return tmp_path / "runtime"


def test_the_scratch_under_koloni_tmp_is_neither_copied_nor_offered(project, runtime):
    # K-koloni-klasor: what an agent puts in .koloni/tmp/ stays where it is; .koloni's own goes.
    for rel in (".koloni/tmp/profile/Cookies", ".koloni/settings.json"):
        (project / rel).parent.mkdir(parents=True, exist_ok=True)
        (project / rel).write_text("{}", encoding="utf-8")
    copy = copies.make(project, runtime, "a1")
    assert (copy.root / ".koloni/settings.json").exists() and not (copy.root / ".koloni/tmp").exists()
    (copy.root / ".koloni/tmp").mkdir()
    (copy.root / ".koloni/tmp/run.log").write_text("made\n", encoding="utf-8")
    (copy.root / ".koloni/rules.md").write_text("be brief\n", encoding="utf-8")
    assert copy.changes() == [(".koloni/rules.md", "new", "ready")]


def tree(top: Path) -> dict[str, bytes]:
    """Every file under a folder with what it holds, links followed."""
    return {
        path.relative_to(top).as_posix(): path.read_bytes()
        for path in sorted(top.rglob("*")) if path.is_file()
    }


# --- deleting: what a link leads to is never touched --------------------------------------


def test_removing_a_copy_leaves_what_its_links_lead_to(project, runtime):
    (project / "web" / ".venv" / "lib").mkdir(parents=True)
    (project / "web" / ".venv" / "lib" / "site.py").write_text("venv", encoding="utf-8")
    before = tree(project)
    copy = copies.make(project, runtime, "a1")
    assert (copy.root / "node_modules").is_junction() or (copy.root / "node_modules").is_symlink()
    assert sorted(copy.links) == ["node_modules", "web/.venv"]
    # seen through the links: the project's own
    assert (copy.root / "web" / ".venv" / "lib" / "site.py").read_text(encoding="utf-8") == "venv"
    copies.remove(runtime, "a1")
    assert not copy.root.exists()
    assert tree(project) == before


def test_a_removal_that_fails_half_way_has_taken_the_links_out_first(
    project, runtime, monkeypatch
):
    before = tree(project)
    copy = copies.make(project, runtime, "a1")
    real = copies._unlink_file

    def refuse(path):
        raise PermissionError(13, "in use", str(path))

    monkeypatch.setattr(copies, "_unlink_file", refuse)
    with pytest.raises(OSError):
        copies.remove(runtime, "a1")
    # what is left of the copy leads nowhere, and the project has lost nothing
    assert copy.root.is_dir() and not (copy.root / "node_modules").exists()
    assert tree(project) == before
    monkeypatch.setattr(copies, "_unlink_file", real)
    copies.clear(runtime)       # the next start deletes what was left
    assert not copy.root.exists() and tree(project) == before


@pytest.mark.skipif(os.name != "nt", reason="only Windows keeps an open file from being deleted")
def test_a_file_held_open_stops_the_removal_and_nothing_of_the_project_is_lost(
    project, runtime
):
    before = tree(project)
    copy = copies.make(project, runtime, "a1")
    with (copy.root / "src" / "app.py").open("rb"):
        with pytest.raises(OSError):
            copies.remove(runtime, "a1")
        assert not (copy.root / "node_modules").exists()
        assert tree(project) == before
    copies.remove(runtime, "a1")
    assert not copy.root.exists() and tree(project) == before


def test_a_link_made_in_the_copy_afterwards_is_not_followed_either(project, runtime, tmp_path):
    """A command may leave a link of its own in the copy, at any depth."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "keep.txt").write_text("keep", encoding="utf-8")
    copy = copies.make(project, runtime, "a1")
    copies._link(copy.root / "src" / "deep" / "out", elsewhere)
    copies._link(copy.root / "to-project", project)
    copies.remove(runtime, "a1")
    assert not copy.root.exists()
    assert (elsewhere / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert (project / "hello.py").is_file()


def test_a_link_met_while_the_files_are_deleted_is_removed_as_a_link(project, runtime, tmp_path):
    """Should one appear after the links were taken out, deleting does not go into it."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "keep.txt").write_text("keep", encoding="utf-8")
    copy = copies.make(project, runtime, "a1")
    copies._link(copy.root / "late", elsewhere)
    copies._delete(copy.root)
    assert not copy.root.exists()
    assert (elsewhere / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_a_copy_that_is_itself_a_link_is_removed_as_one(project, runtime):
    copies.folder(runtime).mkdir(parents=True)
    copies._link(copies.folder(runtime) / "a1", project)
    before = tree(project)
    copies.remove(runtime, "a1")
    assert not (copies.folder(runtime) / "a1").exists()
    assert tree(project) == before


@pytest.mark.parametrize("name", ["", ".", "..", "../proj", "a/b", pytest.param("a\\b", marks=(
    pytest.mark.skipif(os.name != "nt", reason="a backslash is a folder's mark on Windows only"))),
    "C:proj"])
def test_nothing_but_a_folder_directly_in_the_copies_folder_is_deleted(project, runtime, name):
    copies.folder(runtime).mkdir(parents=True)
    before = tree(project)
    with pytest.raises(ValueError):
        copies.remove(runtime, name)
    with pytest.raises(ValueError):
        copies.make(project, runtime, name)
    assert tree(project) == before


def test_nothing_is_deleted_through_a_copies_folder_that_is_a_link(project, runtime):
    runtime.mkdir()
    copies._link(copies.folder(runtime), project)
    before = tree(project)
    with pytest.raises(ValueError):
        copies.remove(runtime, "src")
    copies.clear(runtime)
    assert tree(project) == before


def test_at_the_start_every_copy_left_over_is_deleted(project, runtime):
    before = tree(project)
    one, two = copies.make(project, runtime, "a1"), copies.make(project, runtime, "a2")
    copies.clear(runtime)
    assert not one.root.exists() and not two.root.exists()
    assert tree(project) == before
    copies.clear(runtime / "never-made")       # nothing there: nothing to do


# --- making -------------------------------------------------------------------------------


def test_a_copy_has_the_projects_files_but_not_git_nor_the_caches(project, runtime):
    for skipped in (".git", "__pycache__", "src/__pycache__", ".pytest_cache", "dist", "build"):
        (project / skipped).mkdir(parents=True)
        (project / skipped / "x").write_text("x", encoding="utf-8")
    copy = copies.make(project, runtime, "a1")
    assert copy.root == runtime.resolve() / "copies" / "a1" / "tree"
    assert sorted(copy.names.values()) == ["hello.py", "src/app.py"]
    assert (copy.root / "src" / "app.py").read_bytes() == b"x = 1\n"
    assert not (copy.root / ".git").exists() and not (copy.root / "dist").exists()
    assert copy.changes() == []


def test_a_project_over_the_limit_is_not_copied_at_all(project, runtime, monkeypatch):
    monkeypatch.setattr(copies, "MAX_FILES", 1)
    with pytest.raises(copies.TooBig):
        copies.make(project, runtime, "a1")
    monkeypatch.setattr(copies, "MAX_FILES", 2)
    monkeypatch.setattr(copies, "MAX_BYTES", 5)
    with pytest.raises(copies.TooBig):
        copies.make(project, runtime, "a1")
    assert not (copies.folder(runtime) / "a1").exists()
    # what is linked is not counted: it is not copied
    monkeypatch.setattr(copies, "MAX_BYTES", 500)
    assert copies.make(project, runtime, "a1").root.is_dir()


def test_a_copy_that_could_not_be_made_leaves_nothing_behind_whatever_went_wrong(
    project, runtime, monkeypatch
):
    before = tree(project)

    def refuse(link, target):
        raise ValueError("not a folder that can be linked")

    monkeypatch.setattr(copies, "_link", refuse)
    with pytest.raises(ValueError):
        copies.make(project, runtime, "a1")
    assert not (copies.folder(runtime) / "a1").exists() and tree(project) == before


def test_a_project_that_holds_the_runtime_root_does_not_copy_its_copies(project):
    runtime = project / "runtime"
    first = copies.make(project, runtime, "a1")
    second = copies.make(project, runtime, "a2")
    assert not (second.root / "runtime" / "copies").exists()
    assert sorted(first.names.values()) == sorted(second.names.values())


def test_a_link_of_the_projects_own_that_is_not_a_dependency_folder_is_left_out(
    project, runtime, tmp_path
):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "secret.txt").write_text("s", encoding="utf-8")
    copies._link(project / "out", elsewhere)
    copy = copies.make(project, runtime, "a1")
    assert not (copy.root / "out").exists() and "out" not in copy.links


def test_a_dependency_folder_that_is_itself_a_link_out_of_the_project_is_left_out(
    project, runtime, tmp_path
):
    """Linked into the copy it would be read there: the project's own file tools refuse it."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "secret.txt").write_text("s", encoding="utf-8")
    copies._link(project / "web" / ".venv", elsewhere)
    with pytest.raises(WorkspaceError):
        Workspace(project).resolve("web/.venv/secret.txt")
    copy = copies.make(project, runtime, "a1")
    assert sorted(copy.links) == ["node_modules"]
    assert not (copy.root / "web" / ".venv").exists()
    with pytest.raises(WorkspaceError):
        copy.workspace().read_text("web/.venv/secret.txt")


def test_a_name_that_a_folder_still_has_is_not_given_to_another_copy(project, runtime):
    assert copies.free(runtime, "a1") == "a1"
    copies.make(project, runtime, "a1")
    assert copies.free(runtime, "a1") == "a1-2"
    copies.make(project, runtime, "a1-2")
    assert copies.free(runtime, "a1") == "a1-3"


# --- comparing: what it was, what the project holds, what the copy holds --------------------


def test_what_a_copy_changed_is_new_changed_or_deleted(project, runtime):
    copy = copies.make(project, runtime, "a1")
    (copy.root / "new.txt").write_text("n", encoding="utf-8")
    (copy.root / "hello.py").write_text("print('yo')\n", encoding="utf-8")
    (copy.root / "src" / "app.py").unlink()
    (copy.root / "__pycache__").mkdir()
    (copy.root / "__pycache__" / "x.pyc").write_bytes(b"\x00")
    (copy.root / "node_modules" / "pkg" / "added.js").write_text("shared", encoding="utf-8")
    assert copy.changes() == [
        ("hello.py", "changed", "ready"), ("new.txt", "new", "ready"),
        ("src/app.py", "deleted", "ready"),
    ]


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_a_new_file_git_ignores_is_not_offered_and_one_the_project_has_is(project, runtime, tmp_path):
    # B-189 (live): a generated data/clean.csv in .gitignore was taken in, and two teams' clashed.
    from tests.test_take_in_scenarios import repository

    (project / ".gitignore").write_text("data/\n*.log\n.vscode/\n", encoding="utf-8")
    (project / ".vscode").mkdir()
    (project / ".vscode" / "settings.json").write_text("{}", encoding="utf-8")
    repository(project)
    copy = copies.make(project, runtime, "a1")
    (copy.root / "data").mkdir()
    for name in ("data/clean.csv", "run.log", ".vscode/settings.json", "src/new.py"):
        (copy.root / name).write_text("made\n", encoding="utf-8")
    # (The coordinator's: only a new one is left out - an ignored file the project has, changed,
    # goes through Take in as before, with its cards.)
    assert copy.changes() == [(".vscode/settings.json", "changed", "ready"),
                              ("data/clean.csv", "new", "left_out"), ("run.log", "new", "left_out"),
                              ("src/new.py", "new", "ready")]
    assert copy.state("run.log") == ("new", "left_out") and copy.ignored("data/clean.csv")
    assert not copy.ignored(".vscode/settings.json") and not copy.ignored("src/new.py")
    # Asked once a file: a look again runs no git for it.
    import app.git

    asked = []
    real = app.git.ignored
    app.git.ignored = lambda root, paths: asked.append(paths) or real(root, paths)
    try:
        copy.changes()
        (copy.root / "more.log").write_text("x", encoding="utf-8")
        assert ("more.log", "new", "left_out") in copy.changes()
    finally:
        app.git.ignored = real
    assert asked == [["more.log"]]
    # No git there: nothing is left out.
    plain = tmp_path / "plain"
    plain.mkdir()
    other = copies.make(plain, runtime, "a2")
    (other.root / "run.log").write_text("x", encoding="utf-8")
    assert other.changes() == [("run.log", "new", "ready")]


def test_a_file_the_project_changed_meanwhile_is_a_conflict(project, runtime):
    copy = copies.make(project, runtime, "a1")
    for name in ("hello.py", "new.txt", "same.txt"):
        (copy.root / name).write_text("from the copy", encoding="utf-8")
    (copy.root / "src" / "app.py").unlink()
    (project / "hello.py").write_text("the user's own", encoding="utf-8")
    (project / "new.txt").write_text("made here too", encoding="utf-8")
    (project / "same.txt").write_text("from the copy", encoding="utf-8")
    (project / "src" / "app.py").write_text("x = 2\n", encoding="utf-8")
    assert copy.changes() == [
        ("hello.py", "changed", "conflict"), ("new.txt", "new", "conflict"),
        ("same.txt", "new", "ready"),          # both hold the same: nothing is lost
        ("src/app.py", "deleted", "conflict"),
    ]
    # and a file the copy did not change is not its business, whatever the project did
    (project / "other.txt").write_text("o", encoding="utf-8")
    assert copy.state("other.txt") is None


@pytest.mark.skipif(os.name != "nt", reason="names differ by case only where the disk has none")
def test_a_name_written_in_another_case_is_the_same_file(project, runtime):
    copy = copies.make(project, runtime, "a1")
    (copy.root / "hello.py").rename(copy.root / "HELLO.py")
    assert copy.changes() == []
    (copy.root / "HELLO.py").write_text("changed", encoding="utf-8")
    assert copy.changes() == [("HELLO.py", "changed", "ready")]


def test_put_makes_the_projects_file_what_the_copys_is(project, runtime):
    copy = copies.make(project, runtime, "a1")
    (copy.root / "img" / "a.bin").parent.mkdir()
    (copy.root / "img" / "a.bin").write_bytes(b"\xff\x00")
    (copy.root / "hello.py").unlink()
    copy.put("img/a.bin")
    copy.put("hello.py")
    assert (project / "img" / "a.bin").read_bytes() == b"\xff\x00"
    assert not (project / "hello.py").exists()


# --- refreshing ---------------------------------------------------------------------------


def test_a_file_taken_into_the_project_is_refreshed_where_the_copy_left_it_alone(
    project, runtime
):
    copy = copies.make(project, runtime, "a1")
    (copy.root / "src" / "app.py").write_text("mine", encoding="utf-8")
    (project / "hello.py").write_text("print('new')\n", encoding="utf-8")
    (project / "src" / "app.py").write_text("theirs", encoding="utf-8")
    (project / "added.txt").write_text("added", encoding="utf-8")
    assert copy.refresh("hello.py") and copy.refresh("added.txt")
    assert not copy.refresh("src/app.py")                       # its own change stays
    assert (copy.root / "hello.py").read_text(encoding="utf-8") == "print('new')\n"
    assert (copy.root / "added.txt").read_text(encoding="utf-8") == "added"
    assert (copy.root / "src" / "app.py").read_text(encoding="utf-8") == "mine"
    # what was refreshed is what the copy was made from: only its own change is one
    assert copy.changes() == [("src/app.py", "changed", "conflict")]
    (project / "hello.py").unlink()
    assert copy.refresh("hello.py") and not (copy.root / "hello.py").exists()
    assert copy.changes() == [("src/app.py", "changed", "conflict")]
    assert not copy.refresh("node_modules/pkg/index.js")


# --- file access confined to the copy -------------------------------------------------------


def test_a_copys_links_are_read_through_and_nothing_else_leaves_it(project, runtime, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "secret.txt").write_text("s", encoding="utf-8")
    copy = copies.make(project, runtime, "a1")
    ws = copy.workspace()
    assert ws.read_text("node_modules/pkg/index.js") == "dep"
    inside = ws.resolve("node_modules/pkg/index.js")
    assert not ws.is_own(inside) and ws.rel(inside) == "node_modules/pkg/index.js"
    assert ws.is_own(ws.resolve("hello.py")) and ws.rel(ws.resolve("src/app.py")) == "src/app.py"
    assert ws.search("dep", "node_modules/pkg")[0] == [("node_modules/pkg/index.js", 1, "dep")]
    # a link a command made is no way out, and neither is the project itself
    copies._link(copy.root / "out", elsewhere)
    for path in ("out/secret.txt", "../../../proj/hello.py", str(project / "hello.py")):
        with pytest.raises(WorkspaceError):
            ws.resolve(path)
    # nor is a link in the project's own dependency folder that leads out of it
    copies._link(project / "node_modules" / "leak", elsewhere)
    with pytest.raises(WorkspaceError):
        ws.resolve("node_modules/leak/secret.txt")
    # a folder without links is as closed as ever
    with pytest.raises(WorkspaceError):
        Workspace(copy.root).resolve("node_modules/pkg/index.js")


# --- nothing leaves the project, or the copy, through a link ---------------------------------


def swap(folder: Path, target: Path) -> None:
    """Put a link to another folder where a folder was."""
    if folder.exists():
        shutil.rmtree(folder)
    copies._link(folder, target)


@pytest.fixture
def elsewhere(tmp_path: Path) -> Path:
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep", encoding="utf-8")
    return outside


def test_a_file_behind_a_link_of_the_projects_is_refused_and_never_written(
    project, runtime, elsewhere
):
    copies._link(project / "ext", elsewhere)
    copy = copies.make(project, runtime, "a1")
    (copy.root / "ext").mkdir()
    (copy.root / "ext" / "a.bin").write_bytes(b"\xff\x00")
    (copy.root / "ext" / "keep.txt").write_text("not kept", encoding="utf-8")
    assert copy.changes() == [("ext/a.bin", "new", "refused"), ("ext/keep.txt", "new", "refused")]
    for path in ("ext/a.bin", "ext/keep.txt"):
        with pytest.raises(OSError):
            copy.put(path)
    assert tree(elsewhere) == {"keep.txt": b"keep"}


def test_a_file_the_copy_deleted_is_not_deleted_through_a_link_of_the_projects(
    project, runtime, elsewhere
):
    copy = copies.make(project, runtime, "a1")
    (elsewhere / "app.py").write_bytes(b"x = 1\n")
    swap(project / "src", elsewhere)            # the project's folder became a link meanwhile
    (copy.root / "src" / "app.py").unlink()
    assert copy.changes() == [("src/app.py", "deleted", "refused")]
    with pytest.raises(OSError):
        copy.put("src/app.py")
    assert (elsewhere / "app.py").read_bytes() == b"x = 1\n"


def test_what_is_behind_a_link_a_command_made_in_the_copy_is_not_taken_nor_refreshed(
    project, runtime, elsewhere
):
    copy = copies.make(project, runtime, "a1")
    (elsewhere / "app.py").write_bytes(b"from outside\n")
    swap(copy.root / "src", elsewhere)
    # not the copy's file any more: neither a change to take nor a deletion
    assert copy.changes() == [("src/app.py", "changed", "refused")]
    with pytest.raises(OSError):
        copy.put("src/app.py")
    assert (project / "src" / "app.py").read_bytes() == b"x = 1\n"
    # and what another agent put into the project is not written through it
    (project / "src" / "x.py").write_text("new", encoding="utf-8")
    assert not copy.refresh("src/x.py")
    assert tree(elsewhere) == {"app.py": b"from outside\n", "keep.txt": b"keep"}


def test_what_is_left_out_of_a_copy_is_not_refreshed_into_it(project, runtime):
    copy = copies.make(project, runtime, "a1")
    for path in (".git/config", "build/out.js", "src/__PYCACHE__/x.pyc", "web/Node_Modules/x.js"):
        (project / path).parent.mkdir(parents=True, exist_ok=True)
        (project / path).write_text("x", encoding="utf-8")
        assert not copy.refresh(path)
        assert not (copy.root / path).exists()


def test_deleting_what_became_a_link_removes_the_link_only(project, runtime, elsewhere):
    copy = copies.make(project, runtime, "a1")
    swap(copy.root / "src", elsewhere)
    copies._delete(copy.root / "src")
    assert not (copy.root / "src").exists()
    assert tree(elsewhere) == {"keep.txt": b"keep"}


def test_a_folder_that_becomes_a_link_while_the_copy_is_deleted_is_not_gone_into(
    project, runtime, elsewhere, monkeypatch
):
    """A command still alive may put a link where a folder was, after the links were
    removed: each entry is looked at when it is reached."""
    copy = copies.make(project, runtime, "a1")
    for name in ("one", "two"):
        (copy.root / name).mkdir()
        (copy.root / name / "f.txt").write_text("f", encoding="utf-8")
    real, swapped = copies._unlink_file, []

    def unlink(path):
        if not swapped:
            other = copy.root / ("two" if path.parent.name == "one" else "one")
            swap(other, elsewhere)
            swapped.append(other)
        real(path)

    monkeypatch.setattr(copies, "_unlink_file", unlink)
    copies.remove(runtime, "a1")
    assert swapped and not copy.root.exists()
    assert tree(elsewhere) == {"keep.txt": b"keep"}


def test_a_copy_that_is_kept_at_the_start_loses_its_links_and_nothing_else(project, runtime):
    before = tree(project)
    kept, gone = copies.make(project, runtime, "a1"), copies.make(project, runtime, "a2")
    (kept.root / "mine.txt").write_text("work", encoding="utf-8")
    copies.clear(runtime, keep=lambda name: name == "a1")
    assert not gone.root.exists()
    assert sorted(tree(kept.root)) == ["hello.py", "mine.txt", "src/app.py"]
    assert not (kept.root / "node_modules").exists() and tree(project) == before


def test_what_a_copy_was_made_from_is_kept_beside_its_tree_and_read_again(project, runtime):
    copy = copies.make(project, runtime, "a1")
    base = copy.root.parent / copies.BASE_FILE
    assert base.is_file()
    assert not (copy.root / copies.BASE_FILE).exists()      # not where the agent works
    (copy.root / "hello.py").write_text("print('yo')\n", encoding="utf-8")
    (copy.root / "new.txt").write_text("n", encoding="utf-8")
    copies.unlink(runtime, "a1")
    again = copies.load(project, runtime, "a1")
    assert (again.base, again.names, again.links) == (copy.base, copy.names, {})
    assert again.changes() == [("hello.py", "changed", "ready"), ("new.txt", "new", "ready")]
    # what was taken since is what it was made from, once that is written down
    copy.taken("new.txt")
    copy.save()
    assert copies.load(project, runtime, "a1").changes() == [("hello.py", "changed", "ready")]
    # where the files go is the caller's to say: nothing in the folder names a place
    assert copies.load(runtime, runtime, "a1").project == runtime.resolve()


@pytest.mark.parametrize("held", ["{", "[]", '{"files": {"a.txt": 1}}', '{"files": []}'])
def test_a_copy_whose_base_cannot_be_read_is_not_given_one(project, runtime, held):
    copy = copies.make(project, runtime, "a1")
    (copy.root.parent / copies.BASE_FILE).write_text(held, encoding="utf-8")
    with pytest.raises(ValueError):
        copies.load(project, runtime, "a1")
    copies.forget(runtime, "a1")
    with pytest.raises(OSError):
        copies.load(project, runtime, "a1")
    assert copy.root.is_dir()


def test_changes_are_found_against_what_the_copy_was_made_from_as_handed_in(project, runtime):
    """The scan runs in a thread while another copy's taking in may refresh this one."""
    copy = copies.make(project, runtime, "a1")
    base, names = dict(copy.base), dict(copy.names)
    (project / "hello.py").write_text("print('new')\n", encoding="utf-8")
    assert copy.refresh("hello.py")
    assert copy.changes() == []
    assert copy.changes(base, names) == [("hello.py", "changed", "ready")]


# --- a kept copy with nothing to say what it was made from: against the project alone ------


def kept_without_a_base(project, runtime):
    copy = copies.make(project, runtime, "a1")
    copies.unlink(runtime, "a1")
    copies.forget(runtime, "a1")
    return copy


def test_without_what_it_was_made_from_a_kept_copy_is_compared_with_the_project_alone(
    project, runtime
):
    copy = kept_without_a_base(project, runtime)
    (copy.root / "hello.py").write_text("print('yo')\n", encoding="utf-8")   # differs
    (copy.root / "new.txt").write_text("n", encoding="utf-8")                # the project lacks it
    (copy.root / "src" / "app.py").unlink()            # deleted there - or never copied
    (copy.root / "dist").mkdir()
    (copy.root / "dist" / "out.js").write_text("built", encoding="utf-8")    # left out of a copy
    (copy.root / "node_modules" / "pkg").mkdir(parents=True)
    (copy.root / "node_modules" / "pkg" / "evil.js").write_text("x", encoding="utf-8")
    # a file that differs is the agent's change only where one is on record: without one
    # it may as well be the user's later work, and is not offered
    assert copies.kept(project, runtime, "a1", copy.root).changes() == [
        ("hello.py", "changed", "left_out"), ("new.txt", "new", "conflict")]
    kept = copies.kept(project, runtime, "a1", copy.root, ["Hello.py" if os.name == "nt"
                                                           else "hello.py"])
    assert kept.two_way and kept.root == copy.root
    # nothing vouches for a file: never ready; the same file is not listed; nothing is deleted
    assert kept.changes() == [("hello.py", "changed", "conflict"), ("new.txt", "new", "conflict")]
    assert kept.state("src/app.py") is None
    kept.put("new.txt")
    kept.taken("new.txt")
    kept.save()                                         # no base is made up for it afterwards
    assert not (copy.root.parent / copies.BASE_FILE).exists()
    assert copies.kept(project, runtime, "a1", copy.root, ["hello.py"]).changes() == [
        ("hello.py", "changed", "conflict")]
    assert (project / "src" / "app.py").is_file()


def test_a_copy_that_says_what_it_was_made_from_is_compared_by_that(project, runtime):
    copy = copies.make(project, runtime, "a1")
    (copy.root / "src" / "app.py").unlink()
    kept = copies.kept(project, runtime, "a1")
    assert not kept.two_way and kept.changes() == [("src/app.py", "deleted", "ready")]


def test_a_copy_from_before_there_was_a_tree_is_its_folder_itself(project, runtime):
    """Slice 19b laid a copy's files out directly in its folder - also for a project that
    has a folder called tree."""
    (project / "tree").mkdir()
    (project / "tree" / "oak.txt").write_text("oak", encoding="utf-8")
    old = copies.folder(runtime) / "a1"
    shutil.copytree(project, old, ignore=shutil.ignore_patterns("node_modules"))
    (old / "tree" / "oak.txt").write_text("OAK", encoding="utf-8")
    kept = copies.kept(project, runtime, "a1", old, ["tree/oak.txt"])
    assert kept.two_way and kept.root == old
    assert kept.changes() == [("tree/oak.txt", "changed", "conflict")]
    kept.save()
    assert not (copies.folder(runtime) / copies.BASE_FILE).exists()


def test_a_kept_copy_whose_tree_is_a_link_is_not_compared_at_all(project, runtime, tmp_path):
    copy = kept_without_a_base(project, runtime)
    victim = tmp_path / "victim"
    victim.mkdir()
    shutil.rmtree(copy.root)
    copies._link(copy.root, victim)
    with pytest.raises((OSError, ValueError)):
        copies.kept(project, runtime, "a1", copy.root)


def test_a_folder_that_lost_its_tree_is_not_taken_for_a_copy_of_the_older_layout(
    project, runtime
):
    """What is left in it is KOLONİ's own note of what the copy was made from - not a
    file of the copy's, to be offered to the project."""
    copy = copies.make(project, runtime, "a1")
    copies.unlink(runtime, "a1")
    shutil.rmtree(copy.root)
    for on_record in (copy.root, copy.root.parent):     # whichever the records say it is
        with pytest.raises((OSError, ValueError)):
            copies.kept(project, runtime, "a1", on_record)


def test_how_a_kept_copy_is_laid_out_is_what_the_records_say_or_it_is_not_compared(
    project, runtime
):
    copy = kept_without_a_base(project, runtime)
    for no_record in (None, copy.root / "src", project, copy.root.parent.parent):
        with pytest.raises((OSError, ValueError)):
            copies.kept(project, runtime, "a1", no_record)
    # a file beside the tree does not make it a copy of the layout before trees
    (copy.root.parent / "notes.txt").write_text("left by a command", encoding="utf-8")
    assert copies.kept(project, runtime, "a1", copy.root).root == copy.root


def test_a_path_that_leaves_the_project_through_a_link_is_refused_two_way_too(
    project, runtime, tmp_path
):
    copy = kept_without_a_base(project, runtime)
    outside = tmp_path / "outside"
    outside.mkdir()
    copies._link(project / "ext", outside)
    (copy.root / "ext").mkdir()
    (copy.root / "ext" / "a.txt").write_text("x", encoding="utf-8")
    # (what the project holds there is not looked at: the path is refused, whatever it is)
    kept = copies.kept(project, runtime, "a1", copy.root)
    assert kept.changes() == [("ext/a.txt", "changed", "refused")]


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")
def test_a_runnable_file_stays_runnable_in_a_copy_and_when_taken_back(project, runtime, tmp_path):
    def mode(path):
        return stat.S_IMODE(path.stat().st_mode)

    old = os.umask(0o022)
    try:
        (project / "gradlew").write_bytes(b"#!/bin/sh\n")
        (project / "gradlew").chmod(0o755)
        (project / "private.sh").write_bytes(b"#!/bin/sh\n")
        (project / "private.sh").chmod(0o600)
        copy = copies.make(project, runtime, "a1")
        assert mode(copy.root / "gradlew") == 0o755 and not mode(copy.root / "hello.py") & 0o111
        # (only the run bits go, as git carries them: the target keeps its own read and write)
        (copy.root / "tool").write_bytes(bytes([127, 69, 76, 70, 0]))
        (copy.root / "tool").chmod(0o750)
        (copy.root / "private.sh").chmod(0o755)
        copy.put("tool")
        copy.put("private.sh")
    finally:
        os.umask(old)
    assert mode(project / "tool") == 0o754 and mode(project / "private.sh") == 0o711
    # never through a link
    (tmp_path / "elsewhere").write_bytes(b"x")
    (tmp_path / "elsewhere").chmod(0o644)
    (tmp_path / "link").symlink_to(tmp_path / "elsewhere")
    copies.keep_mode(project / "gradlew", tmp_path / "link")
    assert mode(tmp_path / "elsewhere") == 0o644
