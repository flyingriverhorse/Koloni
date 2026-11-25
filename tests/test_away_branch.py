"""☾ Away, a job on its own branch (0.1.9), its pure parts: which way a job works on the project
(`mode_of`), whether a line pushes (`pushes`), H1 in a job's worktree (`copies.no_push`) and H2's
lines (`moved`). Every repository here is made by the test, in its folder."""

import os
import subprocess
import sys

import pytest

from app import copies, git
from app.away_branch import LFS, SUBMODULE, mode_of, moved, pushes
from tests.conftest import scaled
from tests.test_git_view import run
from tests.test_take_in_scenarios import needs_git, repository

pytestmark = needs_git


@pytest.fixture
def repo(project_dir, monkeypatch):
    # (Nothing of the user's own git settings; a push to a folder on this machine allowed.)
    config = project_dir.parent / "gitconfig"
    config.write_text('[protocol "file"]\n\tallow = always\n')
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    (project_dir / ".gitignore").write_text(".venv/\n")
    (project_dir / "a.txt").write_text("one\n")
    repository(project_dir)
    return project_dir


def with_origin(repo):
    origin = repo.parent / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True, capture_output=True)
    run(repo, "remote", "add", "origin", str(origin))
    run(repo, "push", "-q", "origin", "main")
    return origin


def test_mode_of_no_git_is_a_copy_with_no_reason(project_dir):
    assert mode_of(project_dir) == ("copy", None)


def test_mode_of_a_repository(repo):
    assert mode_of(repo) == ("branch", None)
    with_origin(repo)
    assert mode_of(repo) == ("push", None)


def test_mode_of_a_remote_not_named_origin_is_a_branch_with_no_push(repo):
    origin = repo.parent / "up.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True, capture_output=True)
    run(repo, "remote", "add", "upstream", str(origin))
    assert mode_of(repo) == ("branch", None)


def test_mode_of_a_subfolder(repo):
    (repo / "sub").mkdir()
    assert mode_of(repo / "sub") == ("copy", git.SUBFOLDER)


@pytest.mark.parametrize(
    ("spoil", "want"),
    [
        (lambda repo: run(repo, "checkout", "-q", "--detach"), "HEAD is detached"),
        (lambda repo: (repo / ".git" / "MERGE_HEAD").write_text("x\n"), "merge"),
        (lambda repo: (repo / ".gitmodules").write_text('[submodule "x"]\n'), SUBMODULE),
        (
            lambda repo: run(
                repo,
                "update-index",
                "--add",
                "--cacheinfo",
                f"160000,{run(repo, 'rev-parse', 'HEAD')},vendored",
            ),
            SUBMODULE,
        ),
        (
            lambda repo: (
                (repo / ".gitattributes").write_text("*.bin filter=lfs diff=lfs merge=lfs -text\n"),
                run(repo, "add", ".gitattributes"),
            ),
            LFS,
        ),
    ],
)
def test_mode_of_what_a_worktree_would_not_hold_is_a_copy(repo, spoil, want):
    spoil(repo)
    mode, why = mode_of(repo)
    assert mode == "copy" and want in why


def test_mode_of_no_commit_yet(project_dir, monkeypatch):
    (project_dir.parent / "gitconfig").write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(project_dir.parent / "gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    run(project_dir, "init", "-q", "-b", "main")
    mode, why = mode_of(project_dir)
    assert mode == "copy" and "no commit" in why


@pytest.mark.parametrize(
    "line",
    [
        "git push",
        "git push origin HEAD",
        "git -C . push",
        'bash -c "git push origin x"',
        "cmd /c git push",
        "/usr/lib/git-core/git-push origin HEAD",
        "git status && git push",
    ],
)
def test_pushes(line):
    assert pushes(line)


@pytest.mark.parametrize("line", ["git status", 'git commit -m "push"', "npm run push", "git log"])
def test_not_pushes(line):
    assert not pushes(line)


def test_pushes_reads_16kb_in_a_child_process_in_time():
    # (a bomb try: ~16 KB of nested wrappers and parts, read in a child process with a time limit)
    line = ("bash -c 'cmd /c " * 200 + "git status") + " && git log" * 900
    assert len(line) <= 16 * 1024
    probe = f"from app.away_branch import pushes; print(pushes({line!r}))"
    done = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, timeout=scaled(30)
    )
    assert done.returncode == 0 and done.stdout.strip() in ("True", "False"), done.stderr


def _push(tree, env, ref):
    return subprocess.run(
        ["git", "push", "origin", f"HEAD:refs/heads/{ref}"],
        cwd=tree,
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        timeout=scaled(60),
    )


def test_h1_cuts_a_scripts_push_not_its_fetch(repo, tmp_path):
    origin = with_origin(repo)
    runtime = tmp_path / "runtime"
    copy = copies.make_branch(repo, runtime, "agent1", "job")
    # control: a worktree's git as any copy's - its push goes up
    assert _push(copy.root, copies.git_env(copy.root, os.environ), "x").returncode == 0
    copies.no_push(copy.root)
    env = copies.git_env(copy.root, os.environ)
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    pushed = _push(copy.root, env, "y")
    assert pushed.returncode != 0 and "koloni-no-push" in pushed.stderr
    assert run(origin, "branch", "--list", "y") == ""
    fetched = subprocess.run(
        ["git", "fetch", "-q", "origin"],
        cwd=copy.root,
        env={**os.environ, **env},
        capture_output=True,
        timeout=scaled(60),
    )
    assert fetched.returncode == 0
    # (by the tree as it really is: its path as another spelling of it has it)
    assert copies.git_env(copy.root / ".", os.environ).get("GIT_TERMINAL_PROMPT") == "0"


def test_h1_with_an_explicit_pushurl_and_a_longer_users_push_instead_of(repo, tmp_path):
    # MEASURED (git 2.53, 25 Nov), pinned: H1 is no wall - a remote with its own pushurl, and a
    # pushInsteadOf of the user's longer than H1's, push all the same (`copies.git_env`'s note).
    origin = with_origin(repo)
    copy = copies.make_branch(repo, tmp_path / "runtime", "agent1", "job")
    copies.no_push(copy.root)
    env = copies.git_env(copy.root, os.environ)
    url = run(repo, "config", "remote.origin.url")
    run(repo, "config", "remote.origin.pushurl", url)
    assert _push(copy.root, env, "p").returncode == 0
    run(repo, "config", "--unset", "remote.origin.pushurl")
    run(repo, "config", f"url.{url}.pushInsteadOf", url)
    assert _push(copy.root, env, "q").returncode == 0
    assert {"p", "q"} <= set(run(origin, "branch", "--format=%(refname:short)").split())


def test_moved():
    main = {"refs/heads/main": "1a2b3c4d", "HEAD": "refs/heads/main", "tags": "t", "remotes": "r"}
    assert moved(main, {**main, "refs/heads/main": "3c4d5e6f"}, "koloni/x") == [
        "Changed outside its branch: main 1a2b3c4 → 3c4d5e6"
    ]
    assert moved(main, {**main, "refs/heads/koloni/x": "abc"}, "koloni/x") == []
    assert moved(main, {**main, "tags": "t2"}, "koloni/x") == ["Changed outside its branch: tags"]
    assert moved(main, {**main, "remotes": "r2"}, "koloni/x") == [
        "Changed outside its branch: remote-tracking branches"
    ]
    assert moved(main, {**main, "HEAD": "refs/heads/other"}, "koloni/x") == [
        "Changed outside its branch: HEAD main → other"
    ]
    many = {f"refs/heads/b{n:02}": "abcdef0" for n in range(15)}
    found = moved(main, {**main, **many}, "koloni/x")
    assert len(found) == 11 and found[-1] == "and 5 more"
    assert found[0] == "Changed outside its branch: b00 none → abcdef0"
