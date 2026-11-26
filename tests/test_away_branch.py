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


def test_h2_sees_every_ref_the_stash_list_and_gits_own_files(repo):
    # (the fix round's probe: replace, notes, a namespace of anyone's, an older stash dropped,
    # info/exclude - none of them seen before)
    from app.away_branch import refs

    (repo / "a.txt").write_text("two\n")
    run(repo, "stash", "-q")
    (repo / "a.txt").write_text("three\n")
    run(repo, "stash", "-q")
    before = refs(repo)
    head = run(repo, "rev-parse", "HEAD")
    other = run(repo, "commit-tree", "HEAD^{tree}", "-m", "other")
    run(repo, "replace", head, other)
    run(repo, "notes", "add", "-m", "n", head)
    run(repo, "update-ref", "refs/anyone/x", other)
    run(repo, "stash", "drop", "-q", "stash@{1}")
    (repo / ".git" / "info" / "exclude").write_text("*.secret\n")
    found = moved(before, refs(repo), "koloni/x")
    assert set(found) == {
        "Changed outside its branch: other refs (replace objects, notes, ...)",
        "Changed outside its branch: the stash list",
        "Changed outside its branch: git's own files (info/attributes, info/exclude, info/grafts, "
        "alternates)",
    }


def test_the_config_digest_reads_every_scope_a_worktrees_config_too(repo, tmp_path):
    from app.away_branch import config_digest

    run(repo, "config", "extensions.worktreeConfig", "true")
    before = config_digest(repo)
    (repo / ".git" / "config.worktree").write_text('[remote "origin"]\n\tpushurl = /elsewhere\n')
    assert before is not None and config_digest(repo) != before
    later = config_digest(repo)
    (repo.parent / "gitconfig").write_text('[url "/elsewhere"]\n\tpushInsteadOf = /x\n')
    assert config_digest(repo) != later  # (the user's global one)


def test_git_reads_no_replace_object_for_koloni(repo):
    head = run(repo, "rev-parse", "HEAD")
    run(repo, "replace", head, run(repo, "commit-tree", "HEAD^{tree}", "-m", "other"))
    code, out, _said = git._in(repo, git.find(), "log", "-1", "--format=%s", "HEAD")
    assert code == 0 and out.decode().strip() == "as it was"


# --- a team's pull request (push_one): origin's branches as origin says, never as refs here ----------


def _branch_on(repo, runtime):
    """KOLONİ's branch made from the project's main as it is, with an agent's commit on it."""
    copy = copies.make_branch(repo, runtime, "agent1", "pr")
    (copy.root / "agent.txt").write_text("agent\n")
    assert git.commit_branch(copy.root, copy.branch, ["agent.txt"], "agent", runtime / "no-hooks")
    return copy


def _push_pr(repo, runtime, copy):
    return git.push_one(
        repo,
        run(repo, "rev-parse", copy.branch),
        copy.branch,
        "main",
        copy.start[1],
        "m",
        runtime / "no-hooks",
        under=copies.folders(runtime),
    )


def test_a_symbolic_remote_tracking_ref_never_sends_your_unpushed_commit(repo, tmp_path):
    # (H-A: refs/remotes/origin/main -> refs/heads/main once "proved" your commit pushed)
    origin, runtime = with_origin(repo), tmp_path / "runtime"
    (repo / "u.txt").write_text("yours, not pushed\n")
    run(repo, "add", "u.txt")
    run(repo, "commit", "-qm", "U")
    users = run(repo, "rev-parse", "HEAD")
    run(repo, "symbolic-ref", "refs/remotes/origin/main", "refs/heads/main")
    copy = _branch_on(repo, runtime)
    with pytest.raises(git.Refused, match="push main first"):
        _push_pr(repo, runtime, copy)
    assert subprocess.run(["git", "cat-file", "-e", users], cwd=origin).returncode != 0
    assert git.unpushed_count(repo, copies.folders(runtime)) == (1, 0)  # (yours: noted)


def test_a_branch_deleted_on_origin_and_not_pruned_stops_no_pull_request(repo, tmp_path):
    # (M-A: a stale remote-tracking ref is no ref of origin's - it is not read, nor refused)
    origin, runtime = with_origin(repo), tmp_path / "runtime"
    run(repo, "push", "-q", "origin", "main:refs/heads/old-feature")
    run(repo, "fetch", "-q", "origin")
    run(origin, "update-ref", "-d", "refs/heads/old-feature")
    copy = _branch_on(repo, runtime)
    sha = _push_pr(repo, runtime, copy)
    assert run(origin, "rev-parse", f"refs/heads/{copy.branch}") == sha
    assert git.unpushed_count(repo, copies.folders(runtime)) == (0, 0)


def test_an_address_git_rewrites_pushes_nothing(repo, tmp_path):
    # (H-B: ls-remote takes insteadOf, push takes pushInsteadOf - two repositories)
    origin, runtime = with_origin(repo), tmp_path / "runtime"
    url = run(repo, "config", "remote.origin.url")
    run(repo, "config", f"url.{url}.pushInsteadOf", url)
    copy = _branch_on(repo, runtime)
    with pytest.raises(git.Refused, match="git's config rewrites the address"):
        _push_pr(repo, runtime, copy)
    assert run(origin, "branch", "--list", copy.branch) == ""


def test_an_empty_rewrite_rule_rewrites_every_address_and_pushes_nothing(repo, tmp_path):
    # (L-1: `url.<x>.pushInsteadOf=` - an empty prefix - is a rule like any)
    origin, runtime = with_origin(repo), tmp_path / "runtime"
    copy = _branch_on(repo, runtime)
    run(repo, "config", "url.elsewhere:.pushInsteadOf", "")
    with pytest.raises(git.Refused, match="git's config rewrites the address"):
        _push_pr(repo, runtime, copy)
    assert run(origin, "branch", "--list", copy.branch) == ""


def test_a_graft_never_makes_your_commit_look_pushed(repo, tmp_path):
    # (L-2: info/grafts once made U an ancestor of origin's main - KOLONİ's git reads none)
    origin, runtime = with_origin(repo), tmp_path / "runtime"
    pushed = run(repo, "rev-parse", "HEAD")
    (repo / "u.txt").write_text("yours, not pushed\n")
    run(repo, "add", "u.txt")
    run(repo, "commit", "-qm", "U")
    users = run(repo, "rev-parse", "HEAD")
    (repo / ".git" / "info" / "grafts").write_text(f"{pushed} {users}\n")
    copy = _branch_on(repo, runtime)
    with pytest.raises(git.Refused, match="push main first"):
        _push_pr(repo, runtime, copy)
    assert subprocess.run(["git", "cat-file", "-e", users], cwd=origin).returncode != 0


def test_moved_counts_a_kolonis_branch_of_another_day():
    # (L-3: only the night's own jobs' branches are left out)
    before = {"refs/heads/koloni/old-1a2b": "1111111", "refs/heads/koloni/x": "2222222"}
    after = {"refs/heads/koloni/old-1a2b": "3333333", "refs/heads/koloni/x": "4444444"}
    assert moved(before, after, {"koloni/x"}) == [
        "Changed outside its branch: koloni/old-1a2b 1111111 → 3333333"
    ]
