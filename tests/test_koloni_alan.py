"""K-koloni-alan (0.1.10, decisions 8 and 9 of the command-safety plan): `.koloni/`'s free folders
- the agents' scratch `tmp/`, KOLONİ's `worktrees/` and `copies/` - are named with no card of
`.koloni`'s; its settings (rules, allowed commands, recipes, the rest) ask at every level, and so
does what climbs from a free folder into them. After its review: KOLONİ's worktrees and copies are
each another agent's work - free to read from outside them, never to write, delete or run in; the
agent whose tree it is names it by its full path as its own. A branch's worktree is made in the
project's own `.koloni/worktrees/`, which the repository's `.git/info/exclude` is told of; a copy
of a project with no git in its `.koloni/copies/`, and one with git outside it, as before. Neither
is walked, copied, listed or searched as the project's."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app import commands, copies, copy_git, git, project_files, scratch_delete
from app.project_view import ProjectView, standing
from app.workspace import (
    Workspace,
    in_scratch,
    judged_in,
    standing_names,
    stands_over_later_turns,
)
from tests.fakes import Script, ScriptedExecutor
from tests.test_agent_commands import cmd
from tests.test_agent_writes import wait_status, write
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
        "grep -r foo .koloni/worktrees | head",
        "cd .koloni/worktrees/abc/a1/tree; ls",
        "cat .koloni/tmp/a.txt",
        "echo x > .koloni/tmp/a.txt",
    ],
)
def test_a_look_into_koloni_trees_and_the_scratch_has_no_card_of_its_own(line):
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
        # (another agent's tree: no write, delete or run from outside it)
        "echo x > .koloni/worktrees/abc/a1/tree/x.py",
        "cp hello.py .koloni/worktrees/abc/a1/no-hooks/pre-commit",
        "ls | tee .koloni/worktrees/abc/a1/base.json",
        "echo x > .koloni/copies/AGENTS.md",
        "rm .koloni/copies/abc/a1/tree/x.txt",
        "cd .koloni/worktrees/abc/a1/tree; pytest -q",
        "python .koloni/copies/abc/a1/tree/x.py",
    ],
)
def test_the_settings_a_climb_a_git_line_and_a_write_into_a_tree_still_ask(line):
    assert commands.names_koloni(line) or commands.standing_asked(line) == ".koloni"
    assert commands.danger(line) and commands.harms(line)


def test_pytests_basetemp_in_a_tree_is_asked_as_any_but_the_scratchs():
    assert commands.harms("pytest --basetemp=.koloni/worktrees/abcdefabcdef") == commands.BASETEMP
    assert commands.harms("pytest --basetemp=.koloni/copies/abcdefabcdef/m/tree")
    assert not commands.harms("pytest --basetemp=.koloni/tmp/pt")


@pytest.mark.parametrize("area", ["tmp", "worktrees", "copies"])
def test_climbing_out_of_a_free_folder_by_a_change_of_folder_says_so(area):
    said = commands.harms(f"cd .koloni/{area}; echo x > ../rules.md")
    assert said.startswith("Climbs out of .koloni/tmp")


def test_the_scratch_is_no_standing_name_a_tree_is_koloni_s_and_what_is_in_them_is_judged():
    assert standing_names([".koloni", "tmp", "a", "x.py"]) == []
    assert standing_names([".koloni", "worktrees", "a", "tree", "x.py"]) == [".koloni"]
    assert standing_names([".koloni", "tmp", "a", ".claude", "x"]) == [".claude"]
    assert standing_names([".koloni", "shared", "x.md"]) == [".koloni"]
    assert in_scratch(".koloni/copies/a/tree/x.py") and not in_scratch(".koloni/shared/x.md")


def tree_in(root: Path, area: str) -> Path:
    tree = root / ".koloni" / area / "abc" / "a1" / "tree"
    tree.mkdir(parents=True)
    (tree / "x.txt").write_text("x")
    return tree


@pytest.mark.parametrize(
    "line, free",
    [
        ("rm .koloni/tmp/abc/a1/tree/x.txt", True),
        ("rm .koloni/worktrees/abc/a1/tree/x.txt", False),  # (another agent's work)
        ("rm -rf .koloni/copies/abc/a1/tree/x.txt", False),
        ("rm -rf .koloni/worktrees/abc/a1", False),
        ("rm .koloni/copies/abc/a1/base.json", False),
        ("rm .koloni/shared/contracts/api.md", False),
    ],
)
def test_the_one_free_delete_is_the_scratchs(tmp_path, line, free):
    for area in ("tmp", "worktrees", "copies"):
        tree_in(tmp_path, area)
    (tmp_path / ".koloni" / "copies" / "abc" / "a1" / "base.json").write_text("{}")
    assert scratch_delete.scratch_delete_only(line, str(tmp_path)) is free


def own_tree(tmp_path: Path) -> tuple[Path, Path, Path]:
    project, run_root = tmp_path / "proj", tmp_path / "runtime"
    held = copies.in_project(project, run_root, copies.FOLDER)
    assert held is not None
    tree = held / "a1" / copies.TREE
    tree.mkdir(parents=True)
    return project, run_root, tree


def test_an_agent_names_its_own_tree_in_koloni_by_its_full_path_as_its_own(tmp_path):
    """An agent's tree is in the project's `.koloni/`: its own files by their full path, a CLI's
    `cd <its tree>` and Git Bash's `/c/...` included, are its own (`judged_in`); the same lines
    from the project's root are `.koloni`'s."""
    project, run_root, tree = own_tree(tmp_path)
    forms = [str(tree), tree.as_posix()]
    if sys.platform == "win32":
        forms.append(f"/{tree.drive[0].lower()}{tree.as_posix()[2:]}")
    lines = [
        line
        for spelt in forms
        for line in (f"cd {spelt}; pytest -q", f"python {spelt}/x.py", f"echo x > {spelt}/x.py")
    ]
    try:
        judged_in(tree)
        for line in lines:
            assert commands.harms(line) == "", line
            assert commands.copy_reason(line, True, str(project), run_root, tree) == "", line
        climbs = f"cd {tree}; echo x > ../../../../rules.md"
        assert commands.copy_reason(climbs, True, str(project), run_root, tree)
        assert commands.copy_reason(f"cat {project}/hello.py", True, str(project), run_root, tree)
        judged_in(project)  # (the project: no tree of its own)
        assert all(commands.harms(line) for line in lines), lines
    finally:
        judged_in(None)


def test_an_agents_file_tool_writes_its_own_tree_by_its_full_path(tmp_path):
    project, _run_root, tree = own_tree(tmp_path)
    assert stands_over_later_turns(Workspace(tree), str(tree / "x.py")) is None
    assert stands_over_later_turns(Workspace(tree), str(tree / ".claude" / "x")) == ".claude"
    # (from the project's root it is another agent's tree: `.koloni`'s)
    rel = (tree / "x.py").relative_to(project).as_posix()
    assert stands_over_later_turns(Workspace(project), rel) == ".koloni"


def probe(make_client, project_dir, mode, step):
    executor = ScriptedExecutor([Script([""])])
    client, _ = make_client([step, text("done")], executor=executor)
    cid, _run_id = start_in_mode(client, project_dir, mode)
    return client, cid, executor


def test_at_ask_a_look_into_koloni_worktrees_runs_with_no_card(make_client, wait_run, project_dir):
    tree_in(project_dir, "worktrees")
    client, cid, executor = probe(make_client, project_dir, "ask", cmd("ls .koloni/worktrees"))
    snap = wait_run(client, cid, client.get(f"/api/conversations/{cid}").json()["runs"][0]["id"])
    assert [(c["status"], c["danger"]) for c in snap["commands"]] == [("exited", "")]
    assert len(executor.started) == 1


@pytest.mark.parametrize(
    "line",
    [
        "rm .koloni/worktrees/abc/a1/tree/x.txt",
        "rm -rf .koloni/copies/abc/a1/tree/x.txt",
        "pytest --basetemp=.koloni/worktrees/abc",
        "cp hello.py .koloni/worktrees/abc/a1/no-hooks/pre-commit",
        "echo x > .koloni/rules.md",
        "cat .koloni/tmp/../rules.md",
        "echo x > .koloni/allowed.json",
    ],
)
def test_at_full_auto_another_agents_tree_and_the_settings_still_ask(
    make_client, project_dir, line
):
    tree_in(project_dir, "worktrees")
    tree_in(project_dir, "copies")
    (project_dir / ".koloni" / "tmp").mkdir(parents=True)
    client, cid, executor = probe(make_client, project_dir, "full_auto", cmd(line))
    asked = wait_status(client, cid, "waiting_approval")["commands"][0]
    assert asked["status"] == "proposed" and executor.started == []


@pytest.mark.parametrize(
    "path",
    [
        ".koloni/worktrees/abc/a1/no-hooks/pre-commit",
        ".koloni/worktrees/abc/a1/base.json",
        ".koloni/worktrees/abc/a1/tree/x.txt",
    ],
)
def test_at_auto_edit_a_file_tool_write_into_a_tree_is_a_card(make_client, project_dir, path):
    tree_in(project_dir, "worktrees")
    client, cid, _executor = probe(
        make_client, project_dir, "auto_edit", write(path, "#!/bin/sh\n")
    )
    wait_status(client, cid, "waiting_approval")
    assert not (project_dir / path).is_file() or (project_dir / path).read_text() != "#!/bin/sh\n"


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
    assert files_of(second.root) == {"hello.py", ".koloni/.gitignore"}  # (no copy, nor itself)
    assert held in copies.folders(run_root) and copies.place(run_root, "a2") == held / "a2"
    assert copies.named(run_root, str(second.root)) == "a2"
    assert copies.free(run_root, "a1") == "a1-2"
    # (the project's own look sees neither)
    assert sorted(ProjectView(project_dir).paths()) == [".koloni/.gitignore", "hello.py"]
    assert not [path for path in standing(project_dir) if "/copies/" in path]
    copies.clear(run_root)
    assert not os.path.lexists(held / "a1") and not os.path.lexists(held / "a2")


@needs_git
def test_a_git_less_projects_copies_stay_out_of_the_git_it_gets_later(tmp_path, project_dir):
    (project_dir / ".koloni").mkdir()
    (project_dir / ".koloni" / ".gitignore").write_bytes(b"*.log\r\n")  # (the user's bytes)
    copies.make(project_dir, tmp_path / "runtime", "a1")
    ignore = (project_dir / ".koloni" / ".gitignore").read_bytes()
    assert ignore.startswith(b"*.log\r\n") and b"copies/" in ignore and b"worktrees/" in ignore
    subprocess.run(["git", "init", "-q"], cwd=project_dir, check=True)
    added = run(project_dir, "add", "-A", "-n")
    assert ".koloni/copies" not in added and "hello.py" in added


def test_a_project_given_git_later_has_its_next_copy_outside(tmp_path, project_dir):
    run_root = tmp_path / "runtime"
    inside = copies.make(project_dir, run_root, "a1")
    (project_dir / ".git").mkdir()
    outside = copies.make(project_dir, run_root, "a2")
    assert ".koloni" in inside.root.parts and ".koloni" not in outside.root.parts
    assert outside.root == copies.folder(run_root) / "a2" / copies.TREE
    assert files_of(outside.root) == {"hello.py", ".koloni/.gitignore"}


def test_a_copy_made_outside_before_is_still_found_and_kept_or_cleared(tmp_path, project_dir):
    """Upgrade: a copy kept in `runtime/copies` stays found there once the project's copies
    are made in its own .koloni/ (here: the project had git then, and has none now)."""
    run_root = tmp_path / "runtime"
    (project_dir / ".git").mkdir()
    old = copies.make(project_dir, run_root, "old")
    (project_dir / ".git").rmdir()
    new = copies.make(project_dir, run_root, "new")
    assert ".koloni" not in old.root.parts and ".koloni" in new.root.parts
    assert copies.place(run_root, "old") == old.root.parent
    assert copies.load(project_dir, run_root, "old", at=old.root).root == old.root
    copies.clear(run_root, keep=lambda name: name == "old")
    assert old.root.is_dir() and not os.path.lexists(new.root.parent)


def test_a_folder_of_a_copys_name_elsewhere_in_koloni_is_never_taken_for_it(tmp_path):
    """Review: a decoy of a git-less copy's name in `.koloni/worktrees/` stood in for it - read
    after a restart, its files offered at Take in, the real copy left."""
    project, run_root = tmp_path / "plain", tmp_path / "runtime"
    (project / "src").mkdir(parents=True)
    (project / "src" / "main.py").write_text("print('hi')\n")
    real = copies.make(project, run_root, "b1")
    decoy = project / ".koloni" / "worktrees" / real.root.parent.parent.name / "b1"
    (decoy / "tree" / "src").mkdir(parents=True)
    (decoy / "tree" / "src" / "evil.py").write_text("import os\n")
    (decoy / "base.json").write_text(json.dumps({"files": {}}))
    with pytest.raises(ValueError):
        copies.place(run_root, "b1")
    with pytest.raises(ValueError):
        copies.load(project, run_root, "b1", at=real.root)
    with pytest.raises(ValueError):
        copies.remove(run_root, "b1")
    assert real.root.is_dir() and decoy.is_dir()
    # (and with the real one gone, the decoy is not where the record says the copy is)
    copies._remove(real.root.parent)
    with pytest.raises(ValueError):
        copies.kept(project, run_root, "b1", real.root)


def test_a_projects_own_instruction_files_above_keep_no_copy_or_worktree_out_of_it(tmp_path):
    """MARKS: a CLI's instruction files above a place keep copies out of it - but not out of the
    project's own .koloni/, below the project's own AGENTS.md (read twice: known limits)."""
    (tmp_path / "AGENTS.md").write_text("above")
    project = tmp_path / "proj"
    project.mkdir()
    (project / "AGENTS.md").write_text("mine")
    copy = copies.make(project, tmp_path / "runtime", "a1")
    assert ".koloni" in copy.root.parts and (copy.root / "AGENTS.md").read_text() == "mine"
    assert project_files.others_instructions(str(project))["paths"] == []


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
    assert listed == [".gitignore", "rules.md"]
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
    (repo / "AGENTS.md").write_text("mine")  # (above the worktree: no bar to it, MARKS)
    run(repo, "add", "AGENTS.md")
    run(repo, "commit", "-qm", "agents")
    copy = copies.make_branch(repo, runtime, "agent1", "x")
    held = copies.in_project(repo, runtime, copies.WORKTREES)
    assert held is not None and copy.root == held / "agent1" / copies.TREE
    assert (copy.root / "AGENTS.md").read_text() == "mine"
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
def test_a_worktree_whose_note_git_clean_took_is_left_with_its_work_at_the_start(
    repo,  # noqa: F811
    runtime,  # noqa: F811
):
    """Review: the project's `git clean -fdx` takes `base.json` and `no-hooks/` beside a tree
    (`.koloni/` is ignored); the tree itself, with its own `.git`, stays - and so does it at the
    next start, its uncommitted work too, though no record keeps it."""
    copy = copies.make_branch(repo, runtime, "agent1", "x")
    (copy.root / "work.txt").write_text("not committed")
    run(repo, "clean", "-fdxq")
    assert not (copy.root.parent / copies.BASE_FILE).exists() and copy.root.is_dir()
    copies.clear(runtime)
    assert (copy.root / "work.txt").read_text() == "not committed"


@needs_git
def test_a_linked_worktrees_project_tells_its_main_repositorys_exclude(tmp_path, repo):  # noqa: F811
    linked = tmp_path / "linked"
    run(repo, "worktree", "add", "-q", "-b", "side", str(linked))
    copy_git.exclude(linked, copies.EXCLUDED)
    common = Path(repo / ".git" / "info" / "exclude")
    assert set(copies.EXCLUDED) <= set(common.read_text().splitlines())
    assert not (linked / ".git").is_dir()  # (a file: nothing was written beside it)


@needs_git
@pytest.mark.skipif(sys.platform != "win32", reason="a junction")
def test_no_exclude_is_written_where_gits_info_folder_is_a_junction(tmp_path, repo):  # noqa: F811
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    info = repo / ".git" / "info"
    for one in info.iterdir():
        one.unlink()
    info.rmdir()
    copies._link(info, elsewhere)
    with pytest.raises(git.Refused, match="junction"):
        copy_git.exclude(repo, copies.EXCLUDED)
    assert not list(elsewhere.iterdir())


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
