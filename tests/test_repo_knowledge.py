"""K-bilgi-repo: a public repository as a knowledge ("repo: https://github.com/<owner>/<name>"). On
Learn it is cloned into a folder outside the project, with git hardened and its tree counted
before it is written out; its code is scanned with no model (lookup answers where a name is
defined and who calls it) and kept in the knowledge's folder as text - each file `<path>.md`, line
for line - and its guide written from its docs, then from its most central code files: at most
`max_code_files` new ones a learning, each Learn going on after the last. Nothing runnable of it is
in the project, and no working copy, look, git status, search, map or trigger goes into what is
kept; removing the knowledge deletes it.

No test reaches the network: the clone is stood in for, or made by git from a local folder with
the https-only rule lifted in the test alone."""

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from app import copies, git, knowledge, knows, project_files, project_view, schemas, triggers
from app.agent import _kept_framed
from app.workspace import Workspace, stray_in_koloni
from tests.test_chat_teams_scenarios import OWN
from tests.test_experts_scenarios import asker
from tests.test_knowledge_page import _pid

URL = "https://github.com/acme/payments"
FOLDER = Path(".koloni", "knowledge", "payments")
KEPT = FOLDER / "code"
FILES = {
    "README.md": "# Payments\nTake a payment with `pay()`.",
    "docs/guide.md": "## Refunds\n`refund()` gives it back.",
    "main.py": "from core import pay\n\n\ndef run():\n    return pay(1)\n",
    "core.py": "from util import cents\n\n\ndef pay(amount):\n    return cents(amount)\n",
    "util.py": "def cents(amount):\n    return amount * 100\n",
    "tests/test_core.py": "from core import pay\n\n\ndef test_pay():\n    assert pay(1)\n",
    "web/pay.test.ts": "test('pays', () => {})\n",
    "vendor/lib.py": "def hidden():\n    pass\n",
    ".claude/hooks/run.py": "import os\n",
}


def kept(**more):
    return knowledge.checked({"topic": "Payments", "sources": [f"repo: {URL}"], "max_pages": 50,
                              "max_usd": 0.5, "learn_with": None, **more})


def fake_clone(monkeypatch, files=FILES):
    """`_cloned` stood in for: the tree written where the clone goes; each folder it went to."""
    made: list[Path] = []

    def cloned(into, url, until, most=None):
        made.append(into)
        for rel, body in files.items():
            (into / rel).parent.mkdir(parents=True, exist_ok=True)
            (into / rel).write_text(body, encoding="utf-8")

    monkeypatch.setattr(knowledge, "_cloned", cloned)
    return made


def learn(root, known, extend=True, said="## What it offers\n- pay() takes a payment",
          tree=None):
    ask, asked = asker(said)

    async def run():
        knowledge.begin(str(root), known)
        try:
            return await knowledge.learn(str(root), known, ask, None, "Fake · fake-model",
                                         extend=extend, tree=tree)
        finally:
            knowledge.end(str(root), known)

    return asyncio.run(run()), asked


def upstream(tmp_path, files: dict[str, bytes]) -> Path:
    """A local repository of these files, one commit."""
    source = tmp_path / "upstream"
    source.mkdir()
    for rel, body in files.items():
        (source / rel).parent.mkdir(parents=True, exist_ok=True)
        (source / rel).write_bytes(body)
    me = ["-c", "user.name=T", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
    for args in (["init", "-q"], ["add", "."], [*me, "commit", "-q", "-m", "one"]):
        subprocess.run(["git", *args], cwd=source, check=True, capture_output=True)
    return source


@pytest.fixture
def local(monkeypatch):
    """git clones from a local folder: the https-only rule lifted here alone."""
    real = git.run

    def lifted(argv, *rest, **env):
        return real([one.replace("protocol.allow=never", "protocol.allow=always") for one in argv],
                    *rest, **env)

    monkeypatch.setattr(git, "run", lifted)

    def at(source: Path):
        monkeypatch.setattr(knowledge, "_remote", lambda url: str(source))

    return at


# --- its address ---------------------------------------------------------------------------------


def test_a_repository_is_a_github_address_made_plain():
    for given in (URL, f"{URL}.git", f"{URL}/", f"{URL}/tree/main/docs",
                  "https://GitHub.com/acme/payments"):
        assert kept(sources=[f"repo: {given}"])["sources"] == [f"repo: {URL}"]
    assert kept(sources=[f"REPO:{URL}"])["sources"] == [f"repo: {URL}"]


@pytest.mark.parametrize("given", [
    "http://github.com/acme/payments",  # (not https)
    "git@github.com:acme/payments.git",  # (ssh)
    "ssh://git@github.com/acme/payments",
    "file:///C:/repos/payments",
    "https://127.0.0.1/acme/payments",  # (no public host - and no host named)
    "https://localhost/acme/payments",
    "https://gitlab.com/acme/payments",
    "https://github.com.evil.test/acme/payments",
    "https://user:token@github.com/acme/payments",
    "https://github.com:8443/acme/payments",
    "https://github.com/acme",
    "https://github.com/../payments",
])
def test_an_address_that_is_not_a_public_github_repository_is_refused(given):
    with pytest.raises(ValueError, match="github.com/<owner>/<name>"):
        kept(sources=[f"repo: {given}"])


def test_a_repository_is_a_knowledge_of_its_own_and_learning_it_goes_to_the_web():
    with pytest.raises(ValueError, match="no other source"):
        kept(sources=[f"repo: {URL}", "docs"])
    assert knowledge.reads_web(kept()) and knowledge.web_tools(kept()) == {"http_request"}
    # (A github.com address given as a site is read as a site, as before.)
    assert not knowledge.is_repo(kept(sources=[URL]))


# --- the clone -----------------------------------------------------------------------------------


def test_every_git_command_runs_hardened_and_the_tree_is_counted_before_it_is_written(
        monkeypatch, tmp_path):
    calls = []

    seconds_given = []

    def run(argv, cwd, seconds, stdin=None, /, **env):
        calls.append((argv, cwd, env))
        seconds_given.append(seconds)
        return 0, b"", b""

    def fed_to(argv, cwd, seconds, take, /, **env):
        calls.append((argv, cwd, env))
        seconds_given.append(seconds)
        assert take(b"100644 blob abc 12\tREADME.md\0") is True
        return 0

    monkeypatch.setattr(git, "run", run)
    monkeypatch.setattr(git, "fed_to", fed_to)
    into = tmp_path / "repo"
    knowledge._cloned(into, URL, time.monotonic() + 100)
    # The three share what is left of the learning's reading time.
    assert len(seconds_given) == 3 and all(0 < one <= 100 for one in seconds_given)
    (clone, clone_at, _env), (listing, listing_at, _e), (reset, reset_at, _v) = calls
    assert clone[clone.index("--") + 1:] == [f"{URL}.git", str(into)]
    for flag in ("--no-checkout", "--depth", "--single-branch", "--no-tags",
                 "--no-recurse-submodules", "--template="):
        assert flag in clone
    assert not [one for one in clone if one.startswith("--filter")]  # (blobs whole: nothing lazy)
    assert listing[-5:] == ["ls-tree", "-r", "-l", "-z", "HEAD"] and listing_at == into
    assert reset[-4:] == ["reset", "-q", "--hard", "HEAD"] and reset_at == into
    # Each with every setting: no hook, https alone, no link, no credential, no watcher...
    for argv, _cwd, env in calls:
        for flag in knowledge.CLONE_SETTINGS:
            assert flag in argv
        assert [one for one in argv if one.startswith("core.hooksPath=")] == [
            f"core.hooksPath={clone_at}"]
        # ...and no setting of the machine's or the user's, no LFS, no lazy fetch, no prompt.
        assert env == knowledge.CLONE_ENV and env["GIT_CONFIG_GLOBAL"] == os.devnull
    assert not Path(clone_at).exists()  # (an empty folder for hooks, outside every project)


def test_a_clone_that_fails_keeps_nothing(monkeypatch, project_dir):
    monkeypatch.setattr(git, "run", lambda argv, *a, **k: (128, b"", b"fatal: repository not found\n"))
    with pytest.raises(knowledge.LearnError, match="is it public.*repository not found"):
        learn(project_dir, kept())
    assert not (project_dir / KEPT).exists()
    assert knowledge.failed(str(project_dir), kept()) is not None


def test_the_real_git_clones_with_these_flags(local, tmp_path):
    local(upstream(tmp_path, {"README.md": b"# Upstream", "app.py": b"def main():\n    pass\n"}))
    into = tmp_path / "repo"
    knowledge._cloned(into, URL, time.monotonic() + 120)
    assert sorted(one.name for one in into.iterdir()) == [".git", "README.md", "app.py"]


@pytest.mark.parametrize("bomb", ["bytes", "files"])
def test_a_tree_over_its_caps_is_refused_before_a_file_is_written(local, monkeypatch, tmp_path,
                                                                  bomb):
    """One blob at many paths: small to download, big written out; or many small files."""
    if bomb == "bytes":
        files = {f"same/{n}.bin": b"x" * 4096 for n in range(40)}  # (one blob, 160 KB written)
        monkeypatch.setattr(knowledge, "MAX_CLONE_BYTES", 64 * 1024)
    else:
        files = {f"many/{n}.txt": b"" for n in range(40)}
        monkeypatch.setattr(knowledge, "MAX_CLONE_FILES", 10)
    local(upstream(tmp_path, files))
    into = tmp_path / "repo"
    with pytest.raises(knowledge.LearnError, match="its files are not written out"):
        knowledge._cloned(into, URL, time.monotonic() + 120)
    assert sorted(one.name for one in into.iterdir()) == [".git"]


def test_no_time_no_room_or_a_path_too_long_clones_nothing(monkeypatch, tmp_path):
    with pytest.raises(knowledge.LearnError, match="took more than"):
        knowledge._cloned(tmp_path / "repo", URL, time.monotonic() - 1)
    monkeypatch.setattr(git, "run", lambda *a, **k: (0, b"", b""))
    monkeypatch.setattr(git, "fed_to", lambda argv, cwd, s, take, **k: None if not take(
        b"x" * (knowledge.MAX_PATH_BYTES + 1)) else 0)
    with pytest.raises(knowledge.LearnError, match="path over 64 KB"):
        knowledge._cloned(tmp_path / "repo", URL, time.monotonic() + 60)
    monkeypatch.setattr(knowledge.shutil, "disk_usage", lambda at: type("U", (), {"free": 10})())
    with pytest.raises(knowledge.LearnError, match="GB is free"):
        knowledge._cloned(tmp_path / "repo", URL, time.monotonic() + 60)


def test_a_listing_cut_short_ends_git(tmp_path):
    """`git.fed_to` stops a command once what it writes is enough."""
    source = upstream(tmp_path, {f"{n}.txt": b"" for n in range(300)})
    seen = []
    ended = git.fed_to([git.find() or "git", "ls-tree", "-r", "-z", "HEAD"], source, 30,
                       lambda chunk: seen.append(chunk) or False)
    assert ended is None and len(seen) == 1


@pytest.mark.skipif(sys.platform != "win32", reason="a junction is Windows' own")
def test_removing_it_deletes_what_it_kept_and_never_goes_through_a_junction(project_dir, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("mine", encoding="utf-8")
    (project_dir / KEPT / "files" / "src").mkdir(parents=True)
    (project_dir / KEPT / "files" / "src" / "a.py.md").write_text("x", encoding="utf-8")
    (project_dir / FOLDER / "pages").mkdir()
    (project_dir / FOLDER / "pages" / "0001.md").write_text("x", encoding="utf-8")
    (project_dir / FOLDER / "guide.md").write_text("# guide", encoding="utf-8")
    subprocess.run(["cmd", "/c", "mklink", "/J", str(project_dir / KEPT / "linked"), str(outside)],
                   check=True, capture_output=True)
    knowledge.forget(str(project_dir), kept())
    assert not (project_dir / KEPT).exists() and not (project_dir / FOLDER / "pages").exists()
    assert (project_dir / FOLDER / "guide.md").is_file() and (outside / "keep.txt").is_file()
    # Its folder itself a junction: not followed, nothing behind it deleted.
    subprocess.run(["cmd", "/c", "mklink", "/J", str(project_dir / KEPT), str(outside)], check=True,
                   capture_output=True)
    (project_dir / FOLDER / "pages").mkdir()
    knowledge.forget(str(project_dir), kept())
    # (Its pages go all the same: each is deleted on its own.)
    assert (outside / "keep.txt").is_file() and not (project_dir / FOLDER / "pages").exists()


# --- what it is learned from ---------------------------------------------------------------------


def test_learning_keeps_its_code_as_text_and_writes_the_docs_guide_then_the_codes(
        monkeypatch, project_dir):
    made = fake_clone(monkeypatch)
    record, asked = learn(project_dir, kept())
    read = [one["source"] for one in record["pages"] if one["read"]]
    # Its Markdown first, then its code files - where a program starts, then the most imported;
    # no test and no vendored code.
    assert read == ["README.md", "docs/guide.md", "main.py", "core.py", "util.py"]
    assert [one.get("code", False) for one in record["pages"]] == [False, False, True, True, True]
    code = record["code"]
    assert code["ranked"] == 3 and code["in_guide"] == read[2:] and code["stopped"] is None
    assert code["scanned"] == 7 and code["symbols"] >= 4  # (the free scan reads the tests too)
    assert record["guide_from"] == 2  # (its docs' pages: the card's own line)
    # As the page reads it (a record not of its shape would show no card's state).
    learned = schemas.Learned.model_validate(record).code
    assert learned is not None and learned.in_guide == read[2:]
    # Two requests: the docs' guide, then the code's - asked how the code works, of its files.
    assert [one[0]["content"][:60] for one in asked] == [
        knowledge.GUIDE_ASKED.format(topic="Payments")[:60],
        knowledge.CODE_ASKED.format(topic="Payments")[:60]]
    assert "Take a payment" in asked[0][1]["content"] and "def pay" not in asked[0][1]["content"]
    assert "def pay(amount)" in asked[1][1]["content"]
    guide = knowledge.guide(str(project_dir), kept()) or ""
    assert guide.index("## What it offers") < guide.index(knowledge.CODE_GUIDE)
    # The clone was outside the project, and is gone.
    assert len(made) == 1 and not made[0].is_relative_to(project_dir) and not made[0].exists()
    # Its code is kept as text, line for line - nothing a test runner or a build takes for code -
    # but under a hidden folder (.claude/) or one a CLI agent loads by itself.
    files = project_dir / KEPT / "files"
    assert (files / "core.py.md").read_text(encoding="utf-8") == FILES["core.py"]
    assert (files / "web" / "pay.test.ts.md").is_file() and not (files / ".claude").exists()
    everything = [one.relative_to(project_dir / FOLDER).as_posix()
                  for one in (project_dir / FOLDER).rglob("*") if one.is_file()]
    assert all(one.endswith((".md", ".json", ".gitignore")) for one in everything), everything
    assert "code/graph.json" in everything
    # The scan answers where a name is defined and who calls it, by the file kept to read.
    told = knows.looked_up(str(project_dir), [kept()], "who calls pay?")
    assert f"{(KEPT / 'files').as_posix()}/core.py.md:4" in told and "main.py:5" in told
    # Its expert is told where its code is kept, and to answer from its guide first.
    brief = knowledge.brief(str(project_dir), kept())
    assert f"{(KEPT / 'files').as_posix()}/<path>.md" in brief and "How the code works" in brief
    # What it keeps is out of the project's git.
    ignored = (project_dir / FOLDER / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "pages/" in ignored and "code/" in ignored


def test_each_learn_goes_on_with_the_next_code_files_and_then_asks_nothing(monkeypatch,
                                                                           project_dir):
    """The code-file cap holds where no price does (a CLI): 2 of 5 ranked files a learning."""
    files = {"README.md": "# Five",
             **{f"m{n}.py": f"def f{n}():\n    return {n}\n" for n in range(1, 6)}}
    made = fake_clone(monkeypatch, files)
    known = kept(max_code_files=2)
    learned = []
    price = type("Price", (), {"input": 1.0, "output": 1.0})()
    for _ in range(3):
        record, asked = learn(project_dir, known)
        learned.append(record["code"]["in_guide"])
        assert asked  # (a model was asked each time)
        # Code files left: the next Learn may spend its whole money limit on them.
        assert knowledge.estimate(known, record, price) == (
            known["max_usd"] if len(learned[-1]) < 5 else pytest.approx(
                knowledge._call(knowledge.MAX_GUIDE_INPUT, price)))
    assert learned == [["m1.py", "m2.py"], ["m1.py", "m2.py", "m3.py", "m4.py"],
                       [f"m{n}.py" for n in range(1, 6)]]
    assert record["code"]["stopped"] is None
    # A fourth: nothing new to read, nothing changed - no model is asked; the guide stands.
    guide = knowledge.guide(str(project_dir), known)
    fourth, asked = learn(project_dir, known)
    assert asked == [] and fourth["changed"] == 0 and len(made) == 4
    assert fourth["code"]["in_guide"] == learned[-1]
    code = schemas.Learned.model_validate(fourth).code
    assert code is not None and code.in_guide == learned[-1]
    assert knowledge.guide(str(project_dir), known) == guide


def test_the_cap_and_the_page_cap_say_what_stopped_the_code(monkeypatch, project_dir):
    fake_clone(monkeypatch)
    record, _asked = learn(project_dir, kept(max_code_files=1))
    assert len(record["code"]["in_guide"]) == 1
    assert record["code"]["stopped"] == "the code-file cap (1)"
    record, _asked = learn(project_dir, kept(max_pages=3))
    assert record["code"]["stopped"] == "the page cap (3)"
    # 0: no guide to its code - its docs' and the scan only.
    record, asked = learn(project_dir, kept(max_code_files=0))
    assert record["code"]["ranked"] == 0 and record["code"]["in_guide"] == [] and len(asked) == 1
    assert knowledge.CODE_GUIDE not in (knowledge.guide(str(project_dir), kept()) or "")


def test_on_a_price_the_money_limit_leaves_code_for_the_next_learn(monkeypatch, project_dir):
    big = {"README.md": "# Big",
           **{f"m{n}.py": f"# {n}\n" + "x = 1\n" * 12_000 for n in range(1, 4)}}
    fake_clone(monkeypatch, big)
    price = type("Price", (), {"input": 10.0, "output": 1.0})()
    ask, _asked = asker("## What it offers\n- it adds")
    known = kept(max_usd=0.12)  # (its docs' request, and no section of 60 000 characters more)

    async def run():
        knowledge.begin(str(project_dir), known)
        try:
            return await knowledge.learn(str(project_dir), known, ask, price, "Fake · priced")
        finally:
            knowledge.end(str(project_dir), known)

    record = asyncio.run(run())
    code = record["code"]
    assert code["stopped"] == "the money limit" and code["in_guide"] == []
    assert len(code["left"]) == 3 and record["left"] > 0


def test_a_learning_stopped_or_failing_after_the_clone_keeps_nothing(monkeypatch, project_dir,
                                                                     tmp_path):
    clone = tmp_path / "clone"
    clone.mkdir()
    (clone / "a.py").write_text("def a():\n    pass\n", encoding="utf-8")
    tries = {"left": 10, "until": float("inf"), "stopped": True}
    with pytest.raises(knowledge.LearnError, match="stopped"):
        knowledge._read_repo(str(project_dir), kept(), str(clone), 10, {}, tries)
    assert not (project_dir / KEPT).exists()
    fake_clone(monkeypatch)

    def held(*args):
        raise PermissionError("a file is held open")

    # A learning that keeps its code, then one that fails as the new is put in its place: the
    # last stays, whole, and nothing half-written is left beside it.
    learn(project_dir, kept())
    files = project_dir / KEPT / "files"
    before = sorted(one.relative_to(files).as_posix() for one in files.rglob("*"))
    monkeypatch.setattr(knowledge, "_swapped", held)
    with pytest.raises(knowledge.LearnError, match="could not be read or kept"):
        learn(project_dir, kept())
    assert sorted(one.relative_to(files).as_posix() for one in files.rglob("*")) == before
    assert sorted(one.name for one in (project_dir / KEPT).iterdir()) == ["files", "graph.json"]
    # Stopped while it keeps: nothing more is written.
    with pytest.raises(knowledge.LearnError, match="stopped"):
        knowledge._keep(str(project_dir), kept(), str(clone), ["a.py"], {"stopped": True})
    assert sorted(one.name for one in (project_dir / KEPT).iterdir()) == ["files", "graph.json"]


def test_a_file_that_cannot_be_kept_is_left_out_and_said(monkeypatch, project_dir):
    """A name both a file's and a folder's once kept (x.py and x.py.md/): one is left out."""
    fake_clone(monkeypatch, {"README.md": "# Two", "x.py": "def x():\n    pass\n",
                             "x.py.md/y.py": "def y():\n    pass\n"})
    record, _asked = learn(project_dir, kept())
    unkept = [one for one in record["pages"]
              if (one["why"] or "").startswith("it could not be kept")]
    assert len(unkept) == 1 and unkept[0]["source"] in ("x.py", "x.py.md/y.py")


# --- what it keeps is no part of the project -----------------------------------------------------


def _with_kept_code(project_dir) -> Path:
    files = project_dir / KEPT / "files"
    for rel in ("a.py.md", ".github/workflows/ci.yml.md", "deep/b.py.md", "sub/CLAUDE.md"):
        (files / rel).parent.mkdir(parents=True, exist_ok=True)
        (files / rel).write_text("needle = 1\n", encoding="utf-8")
    (project_dir / KEPT / "graph.json").write_text("{}", encoding="utf-8")
    pages = project_dir / FOLDER / "pages"
    pages.mkdir(parents=True)
    (pages / "0001.md").write_text("needle in a page\n", encoding="utf-8")
    return files


def test_no_copy_look_search_trigger_or_git_status_goes_into_its_kept_code(project_dir):
    files = _with_kept_code(project_dir)
    at = KEPT.as_posix()
    copied, links, _size = copies._scan(project_dir)
    assert ".koloni/knowledge/payments/pages/0001.md" in copied
    assert not [one for one in copied if one.startswith(at)] and links == [at]
    view = project_view.ProjectView(project_dir)
    assert not [one for one in view.paths() if one.startswith(at)]
    assert not [one for one in project_view.standing(project_dir) if one.startswith(at)]
    assert not [one for one in triggers.listing(project_dir, "**/*.md") if one.startswith(at)]
    assert not project_files.others_instructions(str(project_dir))["paths"]
    ws = Workspace(project_dir)
    found, *_rest = ws.search("needle")
    assert [one[0] for one in found] == [".koloni/knowledge/payments/pages/0001.md"]
    # Searched in its own folder - as its expert does - it is found.
    inside, *_rest = ws.search("needle", f"{at}/files")
    assert len(inside) == 4
    # git status: left out by its path, whatever its .gitignore says.
    subprocess.run(["git", "init", "-q"], cwd=project_dir, check=True, capture_output=True)
    listed = [one["path"] for one in git.changes(project_dir) or []]
    assert "hello.py" in listed and not [one for one in listed if one.startswith(at)]
    assert stray_in_koloni(f"{at}/files/a.py.md") and not stray_in_koloni(f"{FOLDER.as_posix()}/guide.md")
    assert files.is_dir()


def test_the_page_adds_it_removes_what_it_kept_and_will_not_copy_it(client, project_dir, tmp_path):
    pid = _pid(client, project_dir)
    added = client.post(f"/api/projects/{pid}/knowledge", headers=OWN, json={
        "topic": "Payments", "sources": [f"repo: {URL}/tree/main"]})
    assert added.status_code == 201, added.text
    body = added.json()
    assert body["knowledge"]["sources"] == [f"repo: {URL}"]
    assert body["knowledge"]["max_code_files"] == 100
    other = tmp_path / "other"
    other.mkdir()
    to = _pid(client, other)
    _with_kept_code(project_dir)
    (project_dir / FOLDER / "guide.md").write_text("# guide", encoding="utf-8")
    copied = client.post(f"/api/knowledge/{body['id']}/copy", headers=OWN,
                         json={"project_id": pid, "to_project_id": to})
    assert copied.status_code == 422 and "own project" in copied.text
    gone = client.delete(f"/api/knowledge/{body['id']}", params={"project_id": pid}, headers=OWN)
    assert gone.status_code == 204
    assert not (project_dir / KEPT).exists() and not (project_dir / FOLDER / "pages").exists()
    assert (project_dir / FOLDER / "guide.md").is_file()


def test_a_repository_is_not_changed_while_it_learns_and_made_a_site_loses_its_code(client,
                                                                                    project_dir):
    pid = _pid(client, project_dir)
    body = client.post(f"/api/projects/{pid}/knowledge", headers=OWN, json={
        "topic": "Payments", "sources": [f"repo: {URL}"]}).json()
    _with_kept_code(project_dir)
    put = {"topic": "Payments", "sources": [f"repo: {URL}"], "max_code_files": 5}
    knowledge.begin(str(project_dir), kept())
    try:
        busy = client.put(f"/api/knowledge/{body['id']}", params={"project_id": pid},
                          headers=OWN, json=put)
        assert busy.status_code == 409 and "learning" in busy.text
    finally:
        knowledge.end(str(project_dir), kept())
    kept_still = client.put(f"/api/knowledge/{body['id']}", params={"project_id": pid},
                            headers=OWN, json=put)
    assert kept_still.status_code == 200 and (project_dir / KEPT).is_dir()
    assert kept_still.json()["knowledge"]["max_code_files"] == 5
    changed = client.put(f"/api/knowledge/{body['id']}", params={"project_id": pid}, headers=OWN,
                         json={"topic": "Payments", "sources": ["https://docs.test/pay"]})
    assert changed.status_code == 200, changed.text
    assert not (project_dir / KEPT).exists()


def test_a_working_copy_reads_its_kept_code_framed_through_a_link(project_dir, tmp_path):
    _with_kept_code(project_dir)
    copy = copies.make(project_dir, tmp_path / "runtime", "a1")
    at = f"{KEPT.as_posix()}/files/a.py.md"
    assert KEPT.as_posix() in copy.links
    assert (copy.root / at).read_text(encoding="utf-8") == "needle = 1\n"
    # What read_file returns of it is framed as data - its output, the file as it is.
    for ws in (Workspace(project_dir), Workspace(copy.root, copy.links)):
        said = _kept_framed(ws, "read_file", {"path": at}, "1: needle = 1")
        assert said.startswith("[") and "1: needle = 1" in said and said != "1: needle = 1"
    assert _kept_framed(Workspace(project_dir), "read_file", {"path": "hello.py"}, "x") == "x"
    assert "another project's code" in knowledge.brief(str(project_dir), kept())
