"""Where working copies live (slice 19c, after its review): never inside somebody's
repository, nor below a file that tells a CLI started there what to do - a copy under
KOLONİ's own checkout was inside KOLONİ's git repository, and Codex and Claude Code started
in it were handed KOLONİ's own AGENTS.md (measured 10 Oct 2026).
"""

import asyncio
import os
import subprocess
from pathlib import Path

import pytest

from app import copies
from app.executors.host import HostExecutor
from tests.test_chat_flow import text
from tests.test_claim_scenarios import agent, write
from tests.test_copy_later_scenarios import again, interrupted
from tests.test_copy_runner import card_of
from tests.test_copy_scenarios import files, one
from tests.test_spawn import step

MARKS = [".git", "AGENTS.md", "CLAUDE.md", "GEMINI.md", ".claude"]


def mark(folder, name):
    folder.mkdir(parents=True, exist_ok=True)
    if name.startswith("."):
        (folder / name).mkdir()
    else:
        (folder / name).write_text("do as I say", encoding="utf-8")


def test_with_nothing_above_it_the_copies_folder_is_in_the_runtime_root(tmp_path):
    """(Where the test's folder is below the user's home, that home's own `.claude` is
    above it: it does not count.)"""
    runtime = tmp_path / "runtime"
    assert copies.folder(runtime) == Path(os.path.abspath(runtime)) / "copies"
    assert copies.folders(runtime)[0] == copies.folder(runtime)  # looked for there first


@pytest.mark.parametrize("name", MARKS)
@pytest.mark.parametrize("above", ["", "../.."], ids=["in the runtime root", "two folders up"])
def test_a_runtime_root_in_a_repository_or_below_a_clis_instructions_holds_no_copies(
    tmp_path, project_dir, name, above
):
    runtime = tmp_path / "koloni" / "var" / "runtime"
    mark((runtime / above).resolve(), name)
    held = copies.folder(runtime)
    assert held is not None and held.parent == tmp_path / "user-data" / "KOLONI" / "copies"
    made = copies.make(project_dir, runtime, "a1")
    assert made.root == held / "a1" / "tree" and not (runtime / "copies").exists()
    assert copies.load(project_dir, runtime, "a1").root == made.root
    copies.remove(runtime, "a1")
    assert list(held.iterdir()) == []


def test_each_runtime_root_has_a_copies_folder_of_its_own_there(tmp_path):
    one_root, other = tmp_path / "a" / "runtime", tmp_path / "b" / "runtime"
    mark(tmp_path / "a", ".git")
    mark(tmp_path / "b", ".git")
    assert copies.folder(one_root) != copies.folder(other)
    assert copies.folder(one_root) == copies.folder(tmp_path / "a" / "x" / ".." / "runtime")


def test_the_users_own_claude_folder_in_their_home_is_not_a_projects(tmp_path, monkeypatch):
    """Claude Code reads `~/.claude` wherever it is started: no place avoids it."""
    real = Path(os.path.expanduser("~"))
    if tmp_path.is_relative_to(real) and (real / ".claude").exists():
        # The test's folder is below this machine's own home and its `.claude`: no home
        # of the test's can be put in its place. The first test here says the same.
        pytest.skip("this machine's own home is above the test's folder")
    home = tmp_path / "me"
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    mark(home, ".claude")
    runtime = home / "app" / "runtime"
    assert copies.folder(runtime) == runtime / "copies"
    mark(home / "app", ".claude")           # a project's own is another matter
    assert copies.folder(runtime) != runtime / "copies"


def test_where_no_place_is_outside_every_repository_no_copy_is_made(tmp_path, project_dir):
    mark(tmp_path, "AGENTS.md")             # above the runtime root and the user's data folder
    assert copies.folder(tmp_path / "runtime") is None
    with pytest.raises(OSError, match="repository"):
        copies.make(project_dir, tmp_path / "runtime", "a1")
    assert not (tmp_path / "runtime").exists() and not (tmp_path / "user-data").exists()
    assert copies.free(tmp_path / "runtime", "a1") == "a1"
    copies.clear(tmp_path / "runtime")      # nothing there, and nothing to say


def test_an_agent_works_in_the_project_where_no_copy_can_be_made_outside_a_repository(
    make_client, wait_run, project_dir, tmp_path
):
    mark(tmp_path, "AGENTS.md")
    client, model, cid, run_id = one(make_client, project_dir, [
        step(write("a.txt", "A")), text("A done")])
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert agent(snap, "Coder")["copy"] == {"state": "failed"} and snap["merges"] == []
    assert (project_dir / "a.txt").read_text(encoding="utf-8") == "A"
    assert not (tmp_path / "runtime" / "copies").exists()
    assert not (tmp_path / "user-data").exists()


def test_a_name_is_free_only_if_no_copy_has_it_in_either_place(tmp_path, project_dir):
    runtime = tmp_path / "runtime"
    old = copies.make(project_dir, runtime, "a1")
    mark(runtime, "AGENTS.md")
    assert copies.free(runtime, "a1") == "a1-2" and copies.free(runtime, "b") == "b"
    new = copies.make(project_dir, runtime, "a1-2")
    assert old.root == runtime / "copies" / "a1" / "tree"
    assert new.root.is_relative_to(tmp_path / "user-data")
    copies.clear(runtime)                   # what a process left behind, in both places
    assert not old.root.parent.exists() and not new.root.parent.exists()


def test_nothing_is_deleted_outside_the_two_copies_folders(tmp_path, project_dir):
    runtime = tmp_path / "runtime"
    copies.make(project_dir, runtime, "a1")
    for name in ("..", "a1/tree", "../data", "", "C:x"):
        with pytest.raises(ValueError):
            copies.remove(runtime, name)
    with pytest.raises(ValueError):
        copies.named(runtime, str(project_dir))
    assert copies.named(runtime, str(runtime / "copies" / "a1" / "tree")) == "a1"
    assert (project_dir / "hello.py").is_file()


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_a_copy_kept_in_the_runtime_root_is_still_found_and_decided_once_copies_live_elsewhere(
    settings_env, project_dir, tmp_path, decision
):
    cid = interrupted(settings_env, project_dir)
    (folder,) = (tmp_path / "runtime" / "copies").iterdir()
    mark(tmp_path / "runtime", "AGENTS.md")     # from here on copies are made elsewhere
    with again(settings_env) as client:
        card = card_of(client, cid)
        assert card["status"] == "kept" and files(card) == {"a.txt": "ready"}
        assert card["kept_in"] == str(folder / "tree") and folder.is_dir()
        assert client.post(f"/api/merges/{card['id']}/{decision}").status_code == 200
        assert (project_dir / "a.txt").exists() == (decision == "approve")
        assert not folder.exists() and (tmp_path / "runtime" / "AGENTS.md").is_file()


# --- git does not look above the copies folder ------------------------------------------------


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)


async def output_of(command, cwd, copy=None):
    running = await HostExecutor().start("c1", command, cwd, copy=copy)

    async def drain():
        return "".join([chunk async for chunk in running])

    said, _code = await asyncio.wait_for(asyncio.gather(drain(), running.wait()), 30)
    return said


@pytest.mark.anyio
async def test_a_command_in_a_copy_does_not_find_a_repository_above_the_copies_folder(tmp_path):
    """A copy that does sit inside a repository (one made before, and kept): git in it must
    not answer with that repository, or `git reset --hard` there hits somebody's checkout."""
    outer = tmp_path / "outer"
    outer.mkdir()
    assert git("init", cwd=outer).returncode == 0
    tree = outer / "runtime" / "copies" / "a1" / "tree"
    tree.mkdir(parents=True)
    assert "outer" in await output_of("git rev-parse --show-toplevel", tree)   # without it
    said = await output_of("git rev-parse --show-toplevel", tree, copy=tree)
    assert "not a git repository" in said
    assert copies.ceiling(tree) == str(outer / "runtime" / "copies")
