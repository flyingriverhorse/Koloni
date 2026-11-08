"""K-tetik-degismedi: the key a clock trigger is skipped by is read as slice 70's look at git
is (`git.state`) - read only, in one look's time, running no program of the repository's: no
filter (an "=" in its name, or a submodule's, neither), no fetch of a partial clone. Every
repository here is made by the test, in its own folder."""

import subprocess

import pytest

from app import git
from tests.test_git_view import commit, marker, run, touched
from tests.test_take_in_scenarios import needs_git, repository

pytestmark = needs_git


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A repository with one commit, as tests/test_git_view.py makes one: none of the user's
    own git settings in it."""
    empty = tmp_path / "gitconfig"
    empty.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    folder = tmp_path / "repo"
    folder.mkdir()
    (folder / "a.txt").write_text("a\n")
    repository(folder)
    return folder


def test_state_runs_no_filter_of_the_repository(repo, tmp_path):
    mark, line = marker(tmp_path, "filter")
    (repo / ".gitattributes").write_text("* filter=x\n")
    run(repo, "config", "filter.x.clean", line)
    run(repo, "config", "filter.x.required", "true")
    touched(repo / "a.txt")
    run(repo, "status", "--porcelain")  # (git's own status runs it)
    assert mark.exists()
    mark.unlink()
    touched(repo / "a.txt")
    assert git.state(repo) is not None
    assert not mark.exists()


def test_state_runs_no_filter_whose_name_holds_an_equals_sign(repo, tmp_path):
    mark, line = marker(tmp_path, "equals")
    commit(repo, "b.txt")
    included = tmp_path / "included.cfg"
    run(repo, "config", "-f", str(included), "filter.a=b.clean", line)
    run(repo, "config", "include.path", included.as_posix())
    (repo / ".git" / "info").mkdir(exist_ok=True)
    (repo / ".git" / "info" / "attributes").write_text("b.txt filter=a=b\n")
    touched(repo / "b.txt")
    run(repo, "status", "--porcelain")
    assert mark.exists()
    mark.unlink()
    touched(repo / "b.txt")
    assert git.state(repo) is not None
    assert not mark.exists()


def test_state_runs_no_filter_inside_a_submodule_and_counts_its_commit(repo, tmp_path):
    mark, line = marker(tmp_path, "sub")
    sub = repo / "sub"
    sub.mkdir()
    (sub / "s.txt").write_text("s\n")
    run(sub, "init", "-q")
    run(sub, "add", "s.txt")
    run(sub, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "s")
    # (Its own .git folder in it, not absorbed: git's status goes into it.)
    run(repo, "add", "sub")
    run(repo, "commit", "-q", "-m", "sub")
    (sub / ".gitattributes").write_text("* filter=y\n")
    run(sub, "config", "filter.y.clean", line)
    touched(sub / "s.txt")
    run(repo, "status", "--porcelain")
    assert mark.exists()
    mark.unlink()
    touched(sub / "s.txt")
    before = git.state(repo)
    assert before is not None and not mark.exists()
    # Its commit moving is a change; an edit inside it, not committed there, is not (a limit).
    (sub / "s.txt").write_text("edited\n")
    assert git.state(repo) == before
    run(sub, "add", "s.txt")
    run(sub, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "s2")
    mark.unlink(missing_ok=True)  # (that commit's own add ran it)
    assert git.state(repo) != before
    assert not mark.exists()


@pytest.mark.parametrize("missing", ["ref", "tree"])
def test_state_fetches_nothing_for_a_partial_clone(repo, tmp_path, missing):
    mark, line = marker(tmp_path, "fetch", passes=False)
    for key, value in (("core.repositoryformatversion", "1"),
                       ("extensions.partialClone", "origin"), ("remote.origin.promisor", "true"),
                       ("remote.origin.url", (tmp_path / "origin").as_uri()),
                       ("remote.origin.uploadpack", line)):
        run(repo, "config", key, value)
    if missing == "ref":  # a branch whose commit is not here
        (repo / ".git" / "refs" / "heads" / "ghost").write_text("1234567890" * 4 + "\n")
        own = ["for-each-ref", "--sort=-committerdate", "refs/heads/"]
    else:  # HEAD's tree is not here
        tree = run(repo, "rev-parse", "HEAD^{tree}")
        loose = repo / ".git" / "objects" / tree[:2] / tree[2:]
        loose.chmod(0o644)  # (git keeps its objects read only)
        loose.unlink()
        own = ["status", "--porcelain"]
    subprocess.run(["git", *own], cwd=repo, capture_output=True, timeout=30)
    assert mark.exists()  # (git's own command fetches it, and runs the upload-pack named)
    mark.unlink()
    git.state(repo)
    assert not mark.exists()


def test_a_repository_with_no_commit_has_a_state_and_one_with_no_git_has_none(tmp_path, repo):
    empty = tmp_path / "empty"
    empty.mkdir()
    run(empty, "init", "-q")
    assert git.state(empty) is not None
    plain = tmp_path / "plain"
    plain.mkdir()
    assert git.state(plain) is None
