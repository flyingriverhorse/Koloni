"""K-koloni-alan (0.1.10, decisions 8 and 9 of the command-safety plan): `.koloni/`'s free folders
- the agents' scratch `tmp/`, KOLONİ's `worktrees/` and `copies/` - are named and written with no
card of `.koloni`'s, at every level; its settings (rules, allowed commands, recipes, the rest) ask
at every level, and so does what climbs from a free folder into them. A branch's worktree is made
in the project's own `.koloni/worktrees/`, which the repository's `.git/info/exclude` is told of;
a copy of a project with no git in its `.koloni/copies/`, and one with git outside it, as before.
Neither is walked, copied, listed or searched as the project's."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from app import commands, copies, copy_git, project_files, scratch_delete
from app.project_view import ProjectView, standing
from app.workspace import Workspace, in_scratch, standing_names
from tests.fakes import Script, ScriptedExecutor
from tests.test_agent_commands import cmd
from tests.test_agent_writes import wait_status
from tests.test_chat_flow import start_in_mode, text
from tests.test_dal_takim import repo, runtime  # noqa: F401  (fixtures)
from tests.test_git_view import run
from tests.test_project_delete import OWN
from tests.test_take_in_scenarios import needs_git

# --- the command reader ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        "ls .koloni/worktrees",
        "cat .koloni/copies/abc/a1/tree/x.py",
        "echo x > .koloni/worktrees/abc/a1/tree/x.py",
        "cd .koloni/worktrees/abc/a1/tree; pytest -q",
        "cat .koloni/tmp/a.txt",
    ],
)
def test_a_free_folder_of_koloni_is_named_with_no_card_of_its_own(line):
    assert not commands.names_koloni(line) and commands.harms(line) == ""


@pytest.mark.parametrize(
    "line",
    [
        "echo x > .koloni/rules.md",
        "cat .koloni/settings.json",
        "ls .koloni/recipes",
        "cat .koloni/tmp/../rules.md",
        "echo x > .koloni/worktrees/../rules.md",
        "cat .koloni/shared/contracts/api.md",  # (the shared folder: `shared.may`'s)
        "git add -f .koloni/worktrees/abc/a1/tree/x",
    ],
)
def test_the_settings_and_a_climb_or_git_line_from_a_free_folder_still_ask(line):
    assert commands.names_koloni(line)


@pytest.mark.parametrize("area", ["tmp", "worktrees", "copies"])
def test_climbing_out_of_a_free_folder_by_a_change_of_folder_says_so(area):
    said = commands.harms(f"cd .koloni/{area}; echo x > ../rules.md")
    assert said.startswith("Climbs out of .koloni/tmp")


def test_a_free_folders_names_are_no_standing_names_but_what_is_in_them_is_judged():
    assert standing_names([".koloni", "worktrees", "a", "tree", "x.py"]) == []
    assert standing_names([".koloni", "copies", "a", "tree", ".claude", "x"]) == [".claude"]
    assert standing_names([".koloni", "shared", "x.md"]) == [".koloni"]
    assert in_scratch(".koloni/copies/a/tree/x.py") and not in_scratch(".koloni/shared/x.md")


def tree_in(root: Path, area: str) -> Path:
    tree = root / ".koloni" / area / "abc" / "a1" / "tree"
    tree.mkdir(parents=True)
    (tree / "x.txt").write_text("x")
    return tree


@pytest.mark.parametrize("area", ["tmp", "worktrees", "copies"])
def test_a_delete_inside_a_free_folder_is_the_one_free_delete(tmp_path, area):
    tree_in(tmp_path, area)
    assert scratch_delete.scratch_delete_only(f"rm .koloni/{area}/abc/a1/tree/x.txt", str(tmp_path))


@pytest.mark.parametrize(
    "line",
    [
        "rm -rf .koloni/worktrees/abc/a1",  # (a whole worktree: KOLONİ's own)
        "rm .koloni/copies/abc/a1/base.json",  # (what the copy was made from)
        "rm -rf .koloni/worktrees/abc",
        "rm .koloni/shared/contracts/api.md",
    ],
)
def test_what_koloni_keeps_around_a_tree_is_no_free_delete(tmp_path, line):
    tree_in(tmp_path, "worktrees")
    tree_in(tmp_path, "copies")
    (tmp_path / ".koloni" / "copies" / "abc" / "a1" / "base.json").write_text("{}")
    assert not scratch_delete.scratch_delete_only(line, str(tmp_path))


@pytest.mark.skipif(sys.platform != "win32", reason="a junction")
def test_a_recursive_delete_of_a_tree_holding_a_link_into_the_project_is_still_asked(tmp_path):
    tree = tree_in(tmp_path, "copies")
    (tmp_path / "node_modules").mkdir()
    copies._link(tree / "web" / "node_modules", tmp_path / "node_modules")
    (tree / "x").mkdir()
    free = scratch_delete.scratch_delete_only
    assert not free("rm -rf .koloni/copies/abc/a1/tree/web", str(tmp_path))
    assert free("rm -rf .koloni/copies/abc/a1/tree/x", str(tmp_path))
    assert not free("rm -rf .koloni/copies/abc/a1/tree", str(tmp_path))


def test_an_agent_in_its_tree_in_koloni_names_it_by_its_full_path_with_no_card(tmp_path):
    """An agent's tree is in the project's `.koloni/`: a CLI's `cd <its tree>` and its own files
    by their full paths are neither `.koloni` nor the project's folder."""
    project, run_root = tmp_path / "proj", tmp_path / "runtime"
    held = copies.in_project(project, run_root, copies.FOLDER)
    assert held is not None
    tree = held / "a1" / copies.TREE
    tree.mkdir(parents=True)
    for spelt in (str(tree), tree.as_posix()):
        for line in (f"cd {spelt}; pytest -q", f"python {spelt}/x.py", f"cat {spelt}/x.txt"):
            assert commands.harms(line) == "", line
            assert commands.copy_reason(line, True, str(project), run_root, tree) == "", line
    climbs = f"cd {tree}; echo x > ../../../../rules.md"
    assert commands.harms(climbs).startswith("Climbs out")
    assert commands.copy_reason(f"cat {project}/hello.py", True, str(project), run_root, tree)
    # (the scratch by its full path is no enter: KOLONİ's trees alone, as copies names them)
    assert commands.names_koloni(f"cd {project}/.koloni/tmp; echo x > y")
    assert commands.names_koloni(f"cd {project}/.koloni/copies/abc/a1/tree; echo x > y")


def probe(make_client, project_dir, mode, line):
    executor = ScriptedExecutor([Script([""])])
    client, _ = make_client([cmd(line), text("done")], executor=executor)
    cid, _run_id = start_in_mode(client, project_dir, mode)
    return client, cid, executor


def test_at_ask_a_look_into_koloni_worktrees_runs_with_no_card(make_client, wait_run, project_dir):
    tree_in(project_dir, "worktrees")
    client, cid, executor = probe(make_client, project_dir, "ask", "ls .koloni/worktrees")
    snap = wait_run(client, cid, client.get(f"/api/conversations/{cid}").json()["runs"][0]["id"])
    assert [(c["status"], c["danger"]) for c in snap["commands"]] == [("exited", "")]
    assert len(executor.started) == 1


@pytest.mark.parametrize("area", ["worktrees", "copies"])
def test_at_full_auto_a_delete_inside_a_tree_runs_unasked(make_client, wait_run, project_dir, area):
    tree_in(project_dir, area)
    line = f"rm .koloni/{area}/abc/a1/tree/x.txt"
    client, cid, executor = probe(make_client, project_dir, "full_auto", line)
    snap = wait_run(client, cid, client.get(f"/api/conversations/{cid}").json()["runs"][0]["id"])
    assert [c["status"] for c in snap["commands"]] == ["exited"] and len(executor.started) == 1


@pytest.mark.parametrize(
    "line",
    [
        "echo x > .koloni/rules.md",
        "cat .koloni/tmp/../rules.md",
        "echo x > .koloni/allowed.json",
    ],
)
def test_at_full_auto_the_settings_still_ask(make_client, project_dir, line):
    (project_dir / ".koloni" / "tmp").mkdir(parents=True)
    client, cid, executor = probe(make_client, project_dir, "full_auto", line)
    asked = wait_status(client, cid, "waiting_approval")["commands"][0]
    assert asked["status"] == "proposed" and ".koloni" in asked["danger"]
    assert executor.started == []


# --- where copies and worktrees are made -----------------------------------------------------


def files_of(folder: Path) -> set[str]:
    return {path.relative_to(folder).as_posix() for path in folder.rglob("*") if path.is_file()}


def test_a_project_with_no_git_has_its_copies_in_its_own_koloni_and_no_copy_holds_another(
    tmp_path, project_dir
):
    run_root = tmp_path / "runtime"
    first = copies.make(project_dir, run_root, "a1")
    held = copies.in_project(project_dir, run_root, copies.FOLDER)
    assert held is not None and first.root == held / "a1" / copies.TREE
    assert held.parent == project_dir.resolve() / ".koloni" / "copies"
    second = copies.make(project_dir, run_root, "a2")
    assert files_of(second.root) == {"hello.py"}  # (not the first copy, nor itself)
    assert held in copies.folders(run_root) and copies.place(run_root, "a2") == held / "a2"
    assert copies.named(run_root, str(second.root)) == "a2"
    assert copies.free(run_root, "a1") == "a1-2"
    # (the project's own look sees neither)
    assert ProjectView(project_dir).paths() == ["hello.py"]
    assert not [path for path in standing(project_dir) if path.startswith(".koloni/")]
    copies.clear(run_root)
    assert not os.path.lexists(held / "a1") and not os.path.lexists(held / "a2")


def test_a_project_given_git_later_has_its_next_copy_outside(tmp_path, project_dir):
    run_root = tmp_path / "runtime"
    inside = copies.make(project_dir, run_root, "a1")
    (project_dir / ".git").mkdir()
    outside = copies.make(project_dir, run_root, "a2")
    assert ".koloni" in inside.root.parts and ".koloni" not in outside.root.parts
    assert outside.root == copies.folder(run_root) / "a2" / copies.TREE
    assert files_of(outside.root) == {"hello.py"}


def test_a_project_below_a_repository_has_its_copies_outside(tmp_path):
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    project = tmp_path / "repo" / "proj"
    project.mkdir()
    (project / "a.txt").write_text("a")
    copy = copies.make(project, tmp_path / "runtime", "a1")
    assert ".koloni" not in copy.root.parts


@pytest.mark.skipif(sys.platform != "win32", reason="a junction")
def test_a_koloni_folder_that_is_a_link_holds_no_copy(tmp_path, project_dir):
    (tmp_path / "elsewhere").mkdir()
    copies._link(project_dir / ".koloni", tmp_path / "elsewhere")
    copy = copies.make(project_dir, tmp_path / "runtime", "a1")
    assert ".koloni" not in copy.root.parts and not list((tmp_path / "elsewhere").iterdir())


def test_two_runtimes_on_one_folder_never_clear_each_others_copies(tmp_path, project_dir):
    mine, theirs = tmp_path / "runtime", tmp_path / "other-runtime"
    kept = copies.make(project_dir, theirs, "a1")
    copies.make(project_dir, mine, "b1")
    copies.clear(mine)
    assert kept.root.is_dir() and not os.path.lexists(copies.place(mine, "b1"))


def test_the_files_window_and_the_agents_search_pass_by_koloni_trees(tmp_path, project_dir):
    copies.make(project_dir, tmp_path / "runtime", "a1")
    (project_dir / ".koloni" / "rules.md").write_text("mine")
    listed = [one["name"] for one in project_files.listing(str(project_dir), ".koloni")]
    assert listed == ["rules.md"]
    matches = Workspace(project_dir).search("print")[0]
    assert [path for path, _line, _text in matches] == ["hello.py"]
    # (a secret an agent made in its copy alone is still found for a whole-folder search)
    (copies.place(tmp_path / "runtime", "a1") / copies.TREE / ".env").write_text("K=1")
    assert commands.secret_files(project_dir)


@needs_git
def test_a_branchs_worktree_is_in_the_projects_koloni_and_git_status_stays_clean(
    repo,  # noqa: F811
    runtime,  # noqa: F811
):
    gitignore = (repo / ".gitignore").read_bytes()
    copy = copies.make_branch(repo, runtime, "agent1", "x")
    held = copies.in_project(repo, runtime, copies.WORKTREES)
    assert held is not None and copy.root == held / "agent1" / copies.TREE
    assert run(repo, "status", "--porcelain") == ""
    exclude = (repo / ".git" / "info" / "exclude").read_text().splitlines()
    assert [line for line in exclude if line in copies.EXCLUDED] == list(copies.EXCLUDED)
    # A second worktree adds no line again; the user's .gitignore is not touched.
    second = copies.make_branch(repo, runtime, "agent2", "y")
    assert (repo / ".git" / "info" / "exclude").read_text().splitlines() == exclude
    assert (repo / ".gitignore").read_bytes() == gitignore
    # It runs: git there answers with its own branch, as an agent's command started there does.
    env = {**os.environ, **copies.git_env(copy.root, os.environ)}
    done = subprocess.run(
        ["git", "branch", "--show-current"], cwd=copy.root, env=env, capture_output=True, text=True
    )
    assert done.stdout.strip() == copy.branch
    assert second.root not in copy.root.parents and ProjectView(repo).paths()
    assert not [path for path in ProjectView(repo).paths() if path.startswith(".koloni/")]


@needs_git
def test_a_linked_worktrees_project_tells_its_main_repositorys_exclude(tmp_path, repo):  # noqa: F811
    linked = tmp_path / "linked"
    run(repo, "worktree", "add", "-q", "-b", "side", str(linked))
    copy_git.exclude(linked, copies.EXCLUDED)
    common = Path(repo / ".git" / "info" / "exclude")
    assert set(copies.EXCLUDED) <= set(common.read_text().splitlines())
    assert not (linked / ".git").is_dir()  # (a file: nothing was written beside it)


def test_a_project_deleted_takes_koloni_copies_with_it(make_client, wait_run, project_dir):
    client, _model = make_client([text("a", 1, 1)])
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    run_root = client.app.state.settings.runtime_root
    copy = copies.make(project_dir, run_root, "leftover")
    (project_dir / ".koloni" / "rules.md").write_text("mine")
    assert client.delete(f"/api/projects/{pid}", headers=OWN).status_code == 204
    assert not os.path.lexists(copy.root.parent)
    assert not (project_dir / ".koloni" / "copies").exists()
    assert (project_dir / ".koloni" / "rules.md").read_text() == "mine"
    assert (project_dir / "hello.py").is_file()
