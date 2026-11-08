"""K-degisenler: the Workspace's Changes tab - what git says is changed in the project, each
file with one letter, and one file's diff against HEAD; null where the project shows no git.
Every repository here is made by the test, in its own folder."""

import os

import pytest

from app import git
from tests.test_git_view import run
from tests.test_take_in_scenarios import needs_git, repository

pytestmark = needs_git


@pytest.fixture
def repo(project_dir, monkeypatch):
    # (Nothing of the user's own git settings - a signing key, a hook - in these commits.)
    empty = project_dir.parent / "gitconfig"
    empty.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    (project_dir / "src").mkdir()
    (project_dir / "src" / "keep.txt").write_text("keep\n")
    (project_dir / "gone.txt").write_text("gone\n")
    (project_dir / "rm.txt").write_text("rm\n")
    (project_dir / "pic.png").write_bytes(b"\x89PNG\x00\x01")
    repository(project_dir)
    return project_dir


def _project(client, folder):
    return client.post("/api/projects", json={"root_path": str(folder)}).json()["id"]


def test_the_changed_files_are_listed_by_path_with_gits_letter(client, repo):
    assert git.changes(repo) == []
    (repo / "hello.py").write_text("print('bye')\n")
    (repo / "added.txt").write_text("added\n")
    run(repo, "add", "added.txt")
    (repo / "gone.txt").unlink()
    (repo / "new.txt").write_text("new\n")
    run(repo, "mv", "src/keep.txt", "src/kept.txt")
    (repo / "pic.png").write_bytes(b"\x89PNG\x00\x02")
    (repo / ".env").write_text("TOKEN=s3cr3t-value\n")  # (a secret: the tree hides it too)
    listed = client.get(f"/api/projects/{_project(client, repo)}/changes").json()
    assert listed == [
        {"path": "added.txt", "status": "A"}, {"path": "gone.txt", "status": "D"},
        {"path": "hello.py", "status": "M"}, {"path": "new.txt", "status": "?"},
        {"path": "pic.png", "status": "M"}, {"path": "src/kept.txt", "status": "R"},
    ]


def test_a_folder_with_no_git_lists_null(client, project_dir):
    assert client.get(f"/api/projects/{_project(client, project_dir)}/changes").json() is None


def test_one_files_diff_against_head_whole_an_untracked_one_all_added(client, repo):
    (repo / "hello.py").write_text("print('bye')\n")
    (repo / "new.txt").write_text("new\n")
    (repo / "gone.txt").unlink()
    run(repo, "rm", "-q", "rm.txt")  # (staged: in neither the index nor the working tree)
    (repo / "pic.png").write_bytes(b"\x89PNG\x00\x02")
    pid = _project(client, repo)
    diff = lambda path: client.get(f"/api/projects/{pid}/changes/diff", params={"path": path})  # noqa: E731
    assert diff("hello.py").json()["diff"].splitlines()[-2:] == ["-print('hi')", "+print('bye')"]
    assert diff("new.txt").json()["diff"].splitlines()[-2:] == ["@@ -0,0 +1 @@", "+new"]
    assert diff("gone.txt").json()["diff"].splitlines()[-1] == "-gone"
    assert diff("rm.txt").json()["diff"].splitlines()[-1] == "-rm"
    # (one not changed: git has no textual difference to show)
    assert diff("src/keep.txt").json() == {"diff": ""}
    assert (diff("pic.png").status_code, diff("pic.png").json()["detail"]) == (
        415, "not text: there is no diff to show")
    assert diff("src").status_code == 404
    assert diff("not-there.txt").status_code == 404


def test_a_path_out_of_the_project_or_a_secret_is_refused_as_the_file_endpoints_do(
    client, repo, tmp_path,
):
    (repo / ".env").write_text("TOKEN=s3cr3t-value\n")
    # (A hard link to a key, added to git: its other name is never read through the diff.)
    key = tmp_path / "id_rsa"
    key.write_text("s3cr3t-key\n")
    os.link(key, repo / "notes.txt")
    run(repo, "add", "notes.txt")
    pid = _project(client, repo)
    for path, status in (("../gitconfig", 400), ("C:/Windows/win.ini", 400), (".env", 404),
                         ("notes.txt", 404)):
        answer = client.get(f"/api/projects/{pid}/changes/diff", params={"path": path})
        assert answer.status_code == status, path
        assert "s3cr3t" not in answer.text
    # No git: there is no diff of a file against HEAD.
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "hello.py").write_text("print('hi')\n")
    assert client.get(f"/api/projects/{_project(client, plain)}/changes/diff",
                      params={"path": "hello.py"}).status_code == 404


def test_a_branch_is_read_without_switching_to_it_and_no_secret_of_it_is_shown(client, repo):
    # K-dallar: Look in the git map - the Workspace on another branch, read from git only.
    run(repo, "switch", "-q", "-c", "feature")
    (repo / "src" / "keep.txt").write_text("keep\nmore\n")
    (repo / "added.txt").write_text("added\n")
    (repo / ".env").write_text("TOKEN=s3cr3t-value\n")
    run(repo, "add", "-A")
    run(repo, "commit", "-q", "-m", "feature")
    run(repo, "switch", "-q", "main")
    base, ref = f"/api/projects/{_project(client, repo)}", "refs/heads/feature"

    def get(what, **params):
        return client.get(f"{base}/{what}", params={"ref": ref, **params})

    assert [(one["name"], one["kind"]) for one in get("files").json()] == [
        ("src", "dir"), ("added.txt", "file"), ("gone.txt", "file"), ("hello.py", "file"),
        ("pic.png", "file"), ("rm.txt", "file")]
    assert get("files", path="src").json()[0]["name"] == "keep.txt"
    assert get("file", path="src/keep.txt").json()["text"] == "keep\nmore\n"
    assert get("file", path="pic.png").json()["binary"] is True
    assert get("changes").json() == [
        {"path": "added.txt", "status": "A"}, {"path": "src/keep.txt", "status": "M"}]
    assert "+more" in get("changes/diff", path="src/keep.txt").json()["diff"]
    for what in ("file", "changes/diff"):
        answer = get(what, path=".env")
        assert answer.status_code == 404 and "s3cr3t" not in answer.text
    assert get("file", path="../gitconfig").status_code == 400
    assert get("file", path="nothing.txt").status_code == 404
    # Only a branch git lists, by its full name: never a word handed to git as it is.
    for wrong in ("feature", "--output=x", "HEAD", "refs/heads/feature:src"):
        assert client.get(f"{base}/file", params={"ref": wrong, "path": "added.txt"}
                          ).status_code == 404, wrong
    # Nothing was checked out, nothing written.
    assert git.where(repo)["branch"] == "main" and not (repo / "added.txt").exists()
    assert git.changes(repo) == []


def test_a_folder_named_to_a_diff_brings_none_of_its_files_a_secret_least(client, repo):
    # (git takes the path for a pathspec: a folder - gone from disk too - is no one file)
    (repo / "cfg").mkdir()
    (repo / "cfg" / "id_rsa").write_text("s3cr3t-key\n")
    (repo / "src" / ".env").write_text("SECRET=s3cr3t\n")
    run(repo, "add", "-f", "cfg", "src/.env")
    run(repo, "commit", "-q", "-m", "secrets")
    run(repo, "switch", "-q", "-c", "other")
    (repo / "cfg" / "id_rsa").write_text("s3cr3t-key2\n")
    (repo / "src" / ".env").write_text("SECRET=s3cr3t2\n")
    (repo / "src" / "keep.txt").write_text("other\n")
    blob = run(repo, "hash-object", "-w", "--stdin")  # (a link, as git keeps one: no disk link)
    run(repo, "update-index", "--add", "--cacheinfo", f"120000,{blob},src/link")
    run(repo, "commit", "-q", "-am", "other")
    run(repo, "switch", "-q", "main")
    base = f"/api/projects/{_project(client, repo)}"
    ref = {"ref": "refs/heads/other"}
    assert client.get(f"{base}/changes", params=ref).json() == [
        {"path": "src/keep.txt", "status": "M"}]
    for path in ("src", "cfg", "src/link", ""):
        answer = client.get(f"{base}/changes/diff", params={**ref, "path": path})
        assert answer.status_code in (400, 404) and "s3cr3t" not in answer.text, path
    # The project's own: a tracked folder deleted from disk.
    for gone in ("src/.env", "src/keep.txt", "cfg/id_rsa"):
        (repo / gone).unlink()
    (repo / "src").rmdir()
    (repo / "cfg").rmdir()
    for path in ("src", "cfg"):
        answer = client.get(f"{base}/changes/diff", params={"path": path})
        assert answer.status_code == 404 and "s3cr3t" not in answer.text, path
    assert "-keep" in client.get(f"{base}/changes/diff", params={"path": "src/keep.txt"}
                                 ).json()["diff"]


def test_what_a_cli_left_in_koloni_is_no_change_listed_but_kolonis_own_files_are(repo):
    # R125: a Chrome profile in .koloni/browser-smoke/ filled the tab; the rules are the user's.
    (repo / ".koloni" / "browser-smoke" / "Default").mkdir(parents=True)
    (repo / ".koloni" / "browser-smoke" / "Default" / "Cookies").write_text("x")
    (repo / ".koloni" / "rules.md").write_text("Answer briefly.\n")
    (repo / ".koloni" / "recipes").mkdir()
    (repo / ".koloni" / "recipes" / "fix.json").write_text("{}")
    assert [one["path"] for one in git.changes(repo)] == [
        ".koloni/recipes/fix.json", ".koloni/rules.md"]


def test_kolonis_own_files_are_listed_whatever_their_case(repo):
    # (review: on Windows `.koloni/Rules.md` is the rules file)
    (repo / ".koloni").mkdir()
    (repo / ".koloni" / "Rules.md").write_text("Answer briefly.\n")
    assert [one["path"] for one in git.changes(repo)] == [".koloni/Rules.md"]
