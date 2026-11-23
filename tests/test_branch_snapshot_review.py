"""W-1 after an independent security review: what a branch's snapshot never takes (links,
junctions, staged and secret files), what never leaves with a pull request, where the agents' work
is asked about, and where a snapshot that cannot be made leaves the branch starting from HEAD."""

import asyncio
import os
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import copies, git
from app.agent import (
    BRANCH_OVER_YOURS,
    NOT_IN_BRANCH,
    PR_SNAPSHOT,
    PR_UNPUSHED,
    AgentRunner,
)
from tests import test_dal_takim
from tests.conftest import Gate, scaled
from tests.test_branch_snapshot import has_object, needs_merge_base, porcelain
from tests.test_chat_flow import text
from tests.test_dal_takim import on_branch, pr_run, pushed_main, run
from tests.test_parallel import until
from tests.test_spawn import step
from tests.test_take_in_scenarios import LONG, card, edit, needs_git

pytestmark = needs_git
repo, runtime, github = test_dal_takim.repo, test_dal_takim.runtime, test_dal_takim.github
MOST = (copies.MAX_FILES, copies.MAX_BYTES)
windows_only = pytest.mark.skipif(sys.platform != "win32", reason="a junction is Windows'")
posix_only = pytest.mark.skipif(sys.platform == "win32", reason="a symlink needs a privilege there")


def junction(link, target):
    import _winapi  # (Windows alone)

    _winapi.CreateJunction(str(target), str(link))


def snapshot_of(repo, runtime, most=MOST):
    """The snapshot a new branch starts from, and why there is none."""
    return left_of(repo, runtime, most)[:2]


def left_of(repo, runtime, most=MOST):
    """The snapshot, why there is none, and what of the user's it left out."""
    _branch, _into, _sha, snapshot, why, left = git.add_worktree(
        repo, runtime / "wt", "x", runtime / "no-hooks", most
    )
    return snapshot, why, left


def held(repo, snapshot):
    return run(repo, "ls-tree", "-r", "--name-only", snapshot).split("\n")


def outside(tmp_path):
    there = tmp_path / "outside"
    there.mkdir()
    (there / "secret.txt").write_text("OUTSIDE-SECRET\n")
    return there


# --- 1. a pull request never carries the user's commits not pushed -----------------------------


@needs_merge_base
def test_a_pull_request_after_your_branch_came_in_never_carries_your_unpushed_commits(
    make_client, repo, runtime, github
):
    bare, _log = github
    run(repo, "push", "-q", "origin", "main")
    (repo / "a.txt").write_text("one\ntwo\nUSER-UNCOMMITTED\n")
    copy = copies.make_branch(repo, runtime, "agent1", "x")
    (copy.root / "agent.txt").write_text("agent\n")
    assert git.commit_branch(copy.root, copy.branch, ["agent.txt"], "agent", runtime / "no-hooks")
    (repo / "private.txt").write_text("PRIVATE-UNPUSHED\n")
    run(repo, "add", "private.txt")
    run(repo, "commit", "-qm", "private, not pushed")
    git.merge_in(copy.root, copy.branch, "main", runtime / "no-hooks")  # (D2, or its own merge)
    look = git.branch_look(repo, copy.branch, copy.start, copy.snapshot_sha)
    client, _model = make_client([text("hi")])
    pushed = asyncio.run(client.app.state.runner._sent(copy, look))
    assert run(repo, "diff", "--name-only", f"{pushed}^", pushed).split() == ["agent.txt"]
    held = {
        "source": look["tip"],
        "snapshot": copy.snapshot_sha,  # (as `_pull_request` holds it)
        "under": copies.folders(runtime),
    }
    with pytest.raises(git.Refused, match="push main first"):
        git.push_one(
            repo, pushed, copy.branch, "main", copy.start[1], "m", runtime / "no-hooks", **held
        )
    assert run(bare, "for-each-ref", "refs/heads/koloni/") == ""
    run(repo, "push", "-q", "origin", "main")  # (theirs up by their own hand: then it goes)
    sha = git.push_one(
        repo, pushed, copy.branch, "main", copy.start[1], "m", runtime / "no-hooks", **held
    )
    assert run(bare, "diff", "--name-only", f"{sha}^", sha).split() == ["agent.txt"]
    assert "USER-UNCOMMITTED" not in run(bare, "show", f"{sha}:a.txt")


# --- 2. a link or a junction in the folder is never walked, nor taken ---------------------------


@windows_only
@needs_merge_base
def test_a_junction_in_your_folder_is_never_taken_nor_what_it_leads_to(repo, runtime, tmp_path):
    there = outside(tmp_path)
    junction(repo / "junc", there)
    (repo / "new.txt").write_text("new\n")
    (repo / "newdir").mkdir()
    (repo / "newdir" / "in.txt").write_text("in\n")
    junction(repo / "newdir" / "deep", there)
    snapshot, why, left = left_of(repo, runtime)
    assert snapshot and why is None and left == ["junc", "newdir/deep"]
    taken = held(repo, snapshot)
    assert "new.txt" in taken and "newdir/in.txt" in taken
    assert not [path for path in taken if "junc" in path or "deep" in path]
    assert not has_object(repo, run(repo, "hash-object", str(there / "secret.txt")))


@windows_only
@needs_merge_base
def test_a_junction_back_into_your_folder_is_not_walked(repo, runtime):
    (repo / "a.txt").write_text("changed\n")
    junction(repo / "loop", repo)
    snapshot, why = snapshot_of(repo, runtime)
    assert snapshot and why is None
    assert not [path for path in held(repo, snapshot) if path.startswith("loop")]


@windows_only
@needs_merge_base
def test_a_junction_loop_inside_a_new_folder_leaves_the_branch_from_head_saying_why(repo, runtime):
    (repo / "a.txt").write_text("changed\n")
    (repo / "newdir").mkdir()
    (repo / "newdir" / "in.txt").write_text("in\n")
    junction(repo / "newdir" / "loop", repo)
    snapshot, why = snapshot_of(repo, runtime)
    assert snapshot is None and why and "Filename too long" in why
    assert run(runtime / "wt", "rev-parse", "HEAD") == run(repo, "rev-parse", "HEAD")


@posix_only
@needs_merge_base
def test_a_link_in_your_folder_is_not_taken_staged_or_not(repo, runtime, tmp_path):
    there = outside(tmp_path)
    os.symlink(there / "secret.txt", repo / "link.txt")
    os.symlink(there, repo / "dirlink", target_is_directory=True)
    os.symlink(there / "secret.txt", repo / "staged-link")
    run(repo, "add", "staged-link")
    (repo / "new.txt").write_text("new\n")
    snapshot, why = snapshot_of(repo, runtime)
    assert snapshot and why is None
    assert "new.txt" in held(repo, snapshot)
    entries = run(repo, "ls-tree", "-r", snapshot)
    assert "120000" not in entries and "link" not in entries
    assert not os.path.lexists(runtime / "wt" / "staged-link")


# --- 3. after a resolve, what the user committed over what they had not is no dead end -----------


@needs_merge_base
def test_after_a_resolve_what_you_committed_over_what_you_had_not_merges(repo, runtime):
    (repo / "b.txt").write_text("bee\n")
    run(repo, "add", "b.txt")
    run(repo, "commit", "-qm", "b")
    (repo / "a.txt").write_text("one\nTWO-USER\n")  # (not committed when the branch begins)
    copy = copies.make_branch(repo, runtime, "agent1", "y")
    (copy.root / "b.txt").write_text("agent-bee\n")
    assert git.commit_branch(copy.root, copy.branch, ["b.txt"], "agent", runtime / "no-hooks")
    (repo / "a.txt").write_text("one\nTWO-USER-MORE\n")  # (committed since, with more in it)
    (repo / "b.txt").write_text("user-bee\n")
    run(repo, "commit", "-qam", "user")
    _before, _sha, left = git.merge_in(copy.root, copy.branch, "main", runtime / "no-hooks")
    assert "b.txt" in left
    (copy.root / "a.txt").write_text("one\nTWO-USER-MORE\n")  # (the agent keeps theirs)
    (copy.root / "b.txt").write_text("resolved-bee\n")
    # (On Linux and macOS this also commits the copy's `.venv` - a symlink KOLONİ made, which the
    # repository's `.venv/` does not ignore: the share leaves it out, `git._kolonis_links`.)
    run(copy.root, "add", "-A")
    run(copy.root, "-c", "core.hooksPath=", "commit", "-qm", "resolved")
    look = git.branch_look(repo, copy.branch, copy.start, copy.snapshot_sha)
    assert porcelain(repo) == []
    assert (look["conflicts"], look["yours"], look["dirty"]) == ([], [], []) and look["share"]
    assert run(repo, "diff", "--name-only", "HEAD", look["share"]).split() == ["b.txt"]
    git.merge_branch(repo, look["share"], "Merge", runtime / "no-hooks", "main")
    assert (repo / "b.txt").read_text() == "resolved-bee\n"
    assert (repo / "a.txt").read_text() == "one\nTWO-USER-MORE\n"


# --- 4. the agents' work over what the user had not committed is asked about -------------------


@needs_merge_base
def test_an_agent_that_dropped_the_snapshot_would_take_back_what_you_committed_so_it_is_asked(
    repo, runtime
):
    (repo / "a.txt").write_text("one\nTWO-USER\n")
    (repo / "u.txt").write_text("user's, not added\n")
    copy = copies.make_branch(repo, runtime, "agent1", "y")
    run(copy.root, "reset", "-q", "--hard", copy.start[1])  # (the agent's own: off the snapshot)
    (copy.root / "agent.txt").write_text("agent\n")
    run(copy.root, "add", "agent.txt")
    run(copy.root, "-c", "core.hooksPath=", "commit", "-qm", "agent")
    run(repo, "add", "-A")
    run(repo, "commit", "-qm", "the user's")
    look = git.branch_look(repo, copy.branch, copy.start, copy.snapshot_sha)
    assert look["over"] == ["a.txt", "u.txt"] and look["dirty"] == []


@needs_merge_base
def test_at_full_auto_a_merge_over_what_you_had_not_committed_waits_for_your_word(
    make_client, wait_run, repo
):
    held_back = Gate()
    client, cid, run_id = on_branch(
        make_client,
        repo,
        [step(edit("two", "TWO-agent", path="a.txt")), held_back.step(text("A done"))],
        wip={"a.txt": "ONE-mine\ntwo\n"},
    )
    held_back.wait_partial()
    run(repo, "commit", "-qam", "mine")  # (committed while the agent works)
    held_back.release()
    merge = card(client, cid)
    assert merge["branch"]["note"] == BRANCH_OVER_YOURS.format(files="a.txt")
    assert merge["branch"]["dirty"] == [] and (repo / "a.txt").read_text() == "ONE-mine\ntwo\n"
    assert client.post(f"/api/merges/{merge['id']}/approve").status_code == 200
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert [m["status"] for m in snap["merges"]] == ["applied"]
    assert (repo / "a.txt").read_text() == "ONE-mine\nTWO-agent\n"


# --- 5. a snapshot that cannot be made leaves the branch from HEAD, and says why ----------------


@needs_merge_base
def test_a_snapshot_git_refuses_leaves_the_branch_from_head_saying_why(repo, runtime):
    run(repo, "config", "core.autocrlf", "true")
    run(repo, "config", "core.safecrlf", "true")
    (repo / "mixed.txt").write_bytes(b"a\r\nb\n")  # (git will not turn its line ends one way)
    head = run(repo, "rev-parse", "HEAD")
    copy = copies.make_branch(repo, runtime, "agent1", "x")
    assert copy.snapshot_sha is None and "LF would be replaced" in copy.from_head
    assert copy.from_head.startswith(git.NOT_TAKEN.split("{")[0])
    assert run(copy.root, "rev-parse", "HEAD") == head and copy.branch == "koloni/x"
    assert not list((repo / ".git").glob("koloni-index-*"))


@windows_only
@needs_merge_base
def test_a_file_another_program_holds_leaves_the_branch_from_head(repo, runtime):
    import ctypes
    from ctypes import wintypes

    (repo / "a.txt").write_text("changed\n")
    (repo / "app.log").write_text("log\n")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.restype = wintypes.HANDLE
    handle = kernel.CreateFileW(str(repo / "app.log"), 0x80000000, 0, None, 3, 0x80, None)
    try:
        copy = copies.make_branch(repo, runtime, "agent1", "x")
    finally:
        kernel.CloseHandle(wintypes.HANDLE(handle))
    assert copy.snapshot_sha is None and copy.from_head and copy.branch == "koloni/x"


@windows_only
@needs_merge_base
def test_a_path_too_long_for_git_leaves_the_branch_from_head(repo, runtime):
    deep = repo / ("L" * 100) / ("M" * 100) / ("N" * 60)
    try:
        deep.mkdir(parents=True)
        (deep / "long.txt").write_text("long\n")
    except OSError:
        pytest.skip("this Windows does not take long paths")
    (repo / "a.txt").write_text("changed\n")
    snapshot, why = snapshot_of(repo, runtime)
    assert snapshot is None and why and "Filename too long" in why


def test_a_large_change_to_a_tracked_file_counts_to_the_caps(repo, runtime):
    (repo / "a.txt").write_text("one\ntwo\n" + "x" * 100)
    snapshot, why = snapshot_of(repo, runtime, (100, 50))
    assert snapshot is None and why == git.TOO_MANY.format(count="1 files, 0 MB")


@needs_merge_base
def test_the_whole_snapshot_has_one_deadline(repo, runtime, monkeypatch):
    (repo / "a.txt").write_text("changed\n")
    real = git._fed

    def slow(*args, **kwargs):  # (a git that takes its time: each call a while)
        threading.Event().wait(0.3)
        return real(*args, **kwargs)

    monkeypatch.setattr(git, "_fed", slow)
    monkeypatch.setattr(git, "SNAPSHOT_SECONDS", 0.5)
    snapshot, why = snapshot_of(repo, runtime)
    assert snapshot is None and "longer than" in why
    assert not list((repo / ".git").glob("koloni-index-*"))


def test_a_stop_while_a_branch_is_made_holds_the_way_in_until_its_thread_is_over(
    tmp_path, monkeypatch
):
    go, started = threading.Event(), threading.Event()
    made = SimpleNamespace(branch="koloni/x")
    dropped, removed = [], []

    def make():
        started.set()
        go.wait(scaled(10))
        return made

    fake = SimpleNamespace(
        _merging_in={},
        _on_branch={"o": "x"},
        _ctxs={"o": SimpleNamespace(model=None)},
        settings=SimpleNamespace(runtime_root=tmp_path / "rt"),
        _copy_part=lambda owner: None,
        _make_copy=lambda *args: make,
        _drop_branch=lambda copy, force=False: dropped.append((copy, force)),
    )
    fake._way_in = lambda project: AgentRunner._way_in(fake, project)
    fake._unmade = lambda *args: AgentRunner._unmade(fake, *args)
    monkeypatch.setattr(copies, "remove", lambda root, name: removed.append(name))

    async def scene():
        task = asyncio.ensure_future(
            AgentRunner._made_copy(fake, SimpleNamespace(folder=str(tmp_path)), "o", "o", None)
        )
        while not started.is_set():
            await asyncio.sleep(0.01)
        way = fake._way_in(tmp_path)
        for _stop in range(2):  # (Stop, and Stop again)
            task.cancel()
            await asyncio.sleep(0.05)
        assert way.locked() and not task.done()  # (git still writes: the way in stays held)
        go.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not way.locked() and removed == ["o"] and dropped == [(made, True)]

    asyncio.run(scene())


# --- 6, 7. what is staged, and secrets by Google's names, stay out ---------------------------------


@needs_merge_base
def test_what_a_snapshot_leaves_out_stays_out_where_you_staged_it_too(repo, runtime):
    (repo / "build").mkdir()
    (repo / "build" / "keep.txt").write_text("committed\n")
    run(repo, "add", "-f", "build/keep.txt")
    run(repo, "commit", "-qm", "a build file kept in git")
    (repo / "build" / "keep.txt").write_text("changed, staged\n")
    staged = {
        ".env": "API_KEY=STAGED-SECRET\n",
        "id_rsa": "KEY\n",
        "node_modules/x/i.js": "x\n",
        "build/out.txt": "out\n",
        ".koloni/settings.json": "{}\n",
    }
    for path, words in staged.items():
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_text(words)
    run(repo, "add", "-f", "build/keep.txt", *staged)
    (repo / "a.txt").write_text("changed\n")
    status = porcelain(repo)
    snapshot, why = snapshot_of(repo, runtime)
    assert snapshot and why is None
    taken = held(repo, snapshot)
    assert "a.txt" in taken and not set(staged) & set(taken)
    assert run(repo, "show", f"{snapshot}:build/keep.txt") == "committed"  # (HEAD's, back)
    assert not (runtime / "wt" / ".env").exists() and porcelain(repo) == status


@needs_merge_base
def test_secrets_by_their_names_stay_out_and_code_named_like_one_is_taken(repo, runtime):
    code = ("credentials.py", "api_keys.ts")
    for name in code:
        (repo / name).write_text("committed\n")
    run(repo, "add", *code)
    run(repo, "commit", "-qm", "code named like a secret")
    for name in code:
        (repo / name).write_text("edited\n")  # (an edit not committed: in the snapshot)
    (repo / "src").mkdir()
    for name in (*code, ".env.example"):
        (repo / "src" / name).write_text("new\n")
    for name in ("credentials.json", "token.json", ".env"):  # (Google's OAuth files; a .env)
        (repo / name).write_text("SECRET\n")
    snapshot, why, left = left_of(repo, runtime)
    taken = held(repo, snapshot)
    assert {"src/credentials.py", "src/api_keys.ts", "src/.env.example"} <= set(taken)
    assert [run(repo, "show", f"{snapshot}:{name}") for name in code] == ["edited", "edited"]
    assert not {"credentials.json", "token.json", ".env"} & set(taken)
    assert left == [".env", "credentials.json", "token.json"] and why is None
    assert not has_object(repo, run(repo, "hash-object", "token.json"))


@needs_merge_base
def test_the_card_says_what_of_yours_is_not_in_the_branch(make_client, wait_run, repo):
    client, cid, run_id = on_branch(
        make_client,
        repo,
        [step(edit("two", "TWO-agent")), text("A done")],
        wip={"notes.txt": "mine\n", ".env": "KEY=1\n", "token.json": "{}\n"},
    )
    snap = wait_run(client, cid, run_id, timeout=LONG)
    (merge,) = snap["merges"]
    assert merge["branch"]["not_taken"] == NOT_IN_BRANCH.format(count=2, files=".env, token.json")
    assert merge["status"] == "applied" and merge["branch"]["note"] is None


@needs_merge_base
def test_a_staged_submodule_entry_stays_out(repo, runtime):
    head = run(repo, "rev-parse", "HEAD")
    run(repo, "update-index", "--add", "--cacheinfo", f"160000,{head},sub")
    (repo / "a.txt").write_text("changed\n")
    snapshot, why = snapshot_of(repo, runtime)
    assert snapshot and why is None
    assert "sub" not in held(repo, snapshot) and "160000" not in run(repo, "ls-tree", snapshot)


def test_a_snapshot_whose_index_cannot_be_copied_leaves_the_branch_from_head(
    repo, runtime, monkeypatch
):
    def fails(*_args, **_kwargs):
        raise OSError("the index is held")

    (repo / "a.txt").write_text("changed\n")
    monkeypatch.setattr(git.shutil, "copy2", fails)
    snapshot, why = snapshot_of(repo, runtime)
    assert snapshot is None and "the index is held" in why
    assert run(runtime / "wt", "rev-parse", "HEAD") == run(repo, "rev-parse", "HEAD")


@needs_merge_base
def test_a_clash_over_what_you_committed_since_is_a_conflict_not_yours(repo, runtime):
    (repo / "nine.txt").write_text("".join(f"{n}\n" for n in range(1, 10)))
    run(repo, "add", "nine.txt")
    run(repo, "commit", "-qm", "nine")
    lines = (repo / "nine.txt").read_text().splitlines(keepends=True)
    (repo / "nine.txt").write_text("".join([*lines[:4], "5-mine\n", *lines[5:]]))
    copy = copies.make_branch(repo, runtime, "agent1", "x")  # (5-mine not committed then)
    (copy.root / "nine.txt").write_text("".join([*lines[:4], "5-agent\n", *lines[5:]]))
    assert git.commit_branch(copy.root, copy.branch, ["nine.txt"], "agent", runtime / "no-hooks")
    (repo / "nine.txt").write_text("".join([*lines[:4], "5-mine-other\n", *lines[5:]]))
    run(repo, "commit", "-qam", "mine, otherwise")  # (nothing left to commit: theirs is in)
    look = git.branch_look(repo, copy.branch, copy.start, copy.snapshot_sha)
    assert (look["conflicts"], look["yours"], look["dirty"]) == (["nine.txt"], [], [])


# --- 1 (again): what the branch took in from the user's unpushed commits never goes up ------------


def origin_case(repo, runtime, dirty=True, agent=True):
    """A project whose main is on a bare origin, a branch from it (a snapshot of an uncommitted
    edit where `dirty`), and - `agent` - the agent's commit on it: the copy and the origin."""
    origin = runtime.parent / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True, capture_output=True)
    run(repo, "remote", "add", "origin", str(origin))
    run(repo, "push", "-q", "origin", "main")
    if dirty:
        (repo / "a.txt").write_text("one\ntwo\nUSER-UNCOMMITTED\n")
    copy = copies.make_branch(repo, runtime, "agent1", "x")
    if agent:
        (copy.root / "agent.txt").write_text("agent\n")
        assert git.commit_branch(
            copy.root, copy.branch, ["agent.txt"], "agent", runtime / "no-hooks"
        )
    return copy, origin


def private(repo, name="private.txt"):
    (repo / name).write_text("PRIVATE, NOT PUSHED\n")
    run(repo, "add", name)
    run(repo, "commit", "-qm", f"{name}, not pushed")


def push_pr(repo, runtime, copy):
    """What `_pull_request` pushes, as it pushes it: the share (onto where the branch left main)
    or the tip, held to the branch's real tip."""
    tip = run(repo, "rev-parse", copy.branch)
    sent = tip
    if copy.snapshot_sha:
        onto = git.merge_base(repo, "refs/heads/main", tip)
        sent = git.agents_share(repo, copy.snapshot_sha, tip, onto, copy.branch)[0]
    return git.push_one(
        repo,
        sent,
        copy.branch,
        "main",
        copy.start[1],
        "m",
        runtime / "no-hooks",
        source=tip,
        snapshot=copy.snapshot_sha,
        under=copies.folders(runtime),
    )


def agent_merges(copy, ref="main"):
    run(copy.root, "-c", "core.hooksPath=", "merge", "-q", "--no-edit", ref)  # (its own, allowed)


def rebased(repo):
    """The user's unpushed commit made anew (another time: another commit)."""
    subprocess.run(
        ["git", "rebase", "-q", "--autostash", "--force-rebase", "origin/main"],
        cwd=repo,
        check=True,
        capture_output=True,
        env={**os.environ, "GIT_COMMITTER_DATE": "2001-01-01T00:00:00"},
    )
    assert run(repo, "log", "-1", "--format=%cd", "--date=format:%Y") == "2001"


AFTER = {
    "kept": lambda repo: None,
    "amended": lambda repo: run(repo, "commit", "-q", "--amend", "-m", "amended"),
    "rebased": lambda repo: rebased(repo),
    "reset": lambda repo: run(repo, "reset", "-q", "--keep", "origin/main"),
}


@needs_merge_base
@pytest.mark.parametrize("dirty", [True, False])
@pytest.mark.parametrize("after", list(AFTER))
def test_a_pull_request_never_sends_unpushed_commits_the_branch_took_in(
    repo, runtime, dirty, after
):
    copy, origin = origin_case(repo, runtime, dirty)
    private(repo)
    agent_merges(copy)  # (or D2's merge_in: the user's branch into the branch)
    AFTER[after](repo)  # (and the user rewrites, or drops, what was not pushed)
    with pytest.raises(git.Refused, match="not on origin"):
        push_pr(repo, runtime, copy)
    assert run(origin, "for-each-ref", "refs/heads/koloni/") == ""


@needs_merge_base
def test_a_pull_request_never_sends_what_was_not_pushed_of_main_after_what_was(repo, runtime):
    copy, origin = origin_case(repo, runtime)
    private(repo, "u1.txt")
    run(repo, "push", "-q", "origin", "main")
    private(repo, "u2.txt")
    git.merge_in(copy.root, copy.branch, "main", runtime / "no-hooks")
    with pytest.raises(git.Refused, match="not on origin"):
        push_pr(repo, runtime, copy)
    assert run(origin, "for-each-ref", "refs/heads/koloni/") == ""


@needs_merge_base
def test_a_pull_request_never_sends_another_local_branch_the_agent_merged(repo, runtime):
    copy, origin = origin_case(repo, runtime)
    run(repo, "switch", "-q", "-c", "feat")
    private(repo, "feat.txt")
    run(repo, "switch", "-q", "main")
    agent_merges(copy, "feat")
    with pytest.raises(git.Refused, match="commits of yours not on origin"):  # (feat holds it)
        push_pr(repo, runtime, copy)
    assert run(origin, "for-each-ref", "refs/heads/koloni/") == ""


def own_commit(copy, name="agent2.txt"):
    """A commit of the agent's own in its worktree, its git as KOLONİ gives it (`copies.git_env`)."""
    (copy.root / name).write_text("the agent's\n")
    for args in (["add", name], ["commit", "-qm", name]):
        subprocess.run(
            ["git", *args],
            cwd=copy.root,
            check=True,
            capture_output=True,
            env={**os.environ, **copies.git_env(copy.root, os.environ)},
        )


# Ways a commit made elsewhere comes onto a branch without a merge commit of its own.
WAYS_IN = {
    "fast-forward": lambda copy, made: run(copy.root, "merge", "-q", "--ff-only", "main"),
    "rebase": lambda copy, made: run(copy.root, "-c", "core.hooksPath=", "rebase", "-q", "main"),
    "cherry-pick": lambda copy, made: run(copy.root, "-c", "core.hooksPath=", "cherry-pick", made),
}


@needs_merge_base
@pytest.mark.parametrize("after", ["kept", "amended"])
@pytest.mark.parametrize("way", list(WAYS_IN))
def test_a_commit_of_yours_that_came_in_by_no_merge_never_goes_up(repo, runtime, way, after):
    # (A clean folder: no snapshot. A fast-forward wants no commit of the agent's before it.)
    copy, origin = origin_case(repo, runtime, dirty=False, agent=way != "fast-forward")
    private(repo)
    WAYS_IN[way](copy, run(repo, "rev-parse", "HEAD"))
    own_commit(copy)
    AFTER[after](repo)  # (amended: main no longer holds it, the branch still does)
    # (Amended: main's reflog holds theirs, named alone - a rebased commit of the agent's beside it
    # is not. A pick is a new commit no ref of theirs holds: not called theirs.)
    said = (
        "KOLONİ cannot attribute"
        if way == "cherry-pick"
        else {"kept": "push main first", "amended": "commits of yours not on origin"}[after]
    )
    with pytest.raises(git.Refused, match=said) as refused:
        push_pr(repo, runtime, copy)
    assert "," not in str(refused.value).partition("(")[2].partition(")")[0]  # (one named)
    assert run(origin, "for-each-ref", "refs/heads/koloni/") == ""


@needs_merge_base
@pytest.mark.parametrize("dirty", [True, False])
def test_the_agents_own_commits_go_up_where_the_repository_keeps_no_reflog(repo, runtime, dirty):
    run(repo, "config", "core.logAllRefUpdates", "false")  # (the user's: KOLONİ's git keeps one)
    copy, origin = origin_case(repo, runtime, dirty)
    own_commit(copy)
    sha = push_pr(repo, runtime, copy)
    assert run(origin, "diff", "--name-only", f"{sha}^", sha).split() == ["agent.txt", "agent2.txt"]


@needs_merge_base
@pytest.mark.parametrize("dirty", [True, False])
@pytest.mark.parametrize("merged", [False, True])
def test_a_pull_request_of_the_agents_work_and_what_is_on_origin_goes(repo, runtime, merged, dirty):
    copy, origin = origin_case(repo, runtime, dirty)
    if merged:  # (main moved on origin, and the branch took it in)
        private(repo, "pushed.txt")
        run(repo, "push", "-q", "origin", "main")
        agent_merges(copy)
    sha = push_pr(repo, runtime, copy)
    assert run(origin, "diff", "--name-only", f"{sha}^", sha).split() == ["agent.txt"]


def test_a_folder_whose_only_change_is_left_out_starts_from_head_and_names_it(repo, runtime):
    (repo / ".env").write_text("KEY=1\n")  # (not ignored here: its only change, a secret)
    snapshot, why, left = left_of(repo, runtime)
    assert (snapshot, why, left) == (None, None, [".env"])


# --- KOLONİ's own links in a branch's worktree are never the agents' work -------------------------


@needs_merge_base
def test_the_dependency_links_kolonis_worktree_holds_never_go_into_the_share(repo, runtime):
    # (On Linux and macOS a copy's .venv / node_modules are symlinks KOLONİ put there, and `.venv/`
    # in a .gitignore names a folder alone: an agent's own `git add -A` commits them. Written here
    # as git's entries, so that Windows - where they are junctions, folders to git - tries it too.)
    (repo / "a.txt").write_text("one\ntwo-mine\n")  # (a snapshot)
    copy = copies.make_branch(repo, runtime, "agent1", "x")
    target = (
        subprocess.run(
            ["git", "hash-object", "-w", "--stdin"],
            cwd=copy.root,
            check=True,
            capture_output=True,
            input=str(repo / ".venv").encode(),
        )
        .stdout.decode()
        .strip()
    )
    for path in (".venv", "frontend/node_modules"):
        run(copy.root, "update-index", "--add", "--cacheinfo", f"120000,{target},{path}")
    (copy.root / "agent.txt").write_text("agent\n")
    run(copy.root, "add", "agent.txt")
    run(copy.root, "-c", "core.hooksPath=", "commit", "-qm", "the agent's, links and all")
    look = git.branch_look(repo, copy.branch, copy.start, copy.snapshot_sha)
    assert look["files"] == {"agent.txt": "A"} and look["dirty"] == [] and look["share"]
    assert run(repo, "diff", "--name-only", "HEAD", look["share"]).split() == ["agent.txt"]
    assert "120000" not in run(repo, "ls-tree", "-r", look["share"])


# --- what an agent copies of the user's unpushed work never goes up unasked ---------------------


def agent_git(copy, *args):
    """git as the agent runs it in its worktree (`copies.git_env`): what Full auto runs unasked."""
    done = subprocess.run(
        ["git", *args],
        cwd=copy.root,
        capture_output=True,
        text=True,
        env={**os.environ, **copies.git_env(copy.root, os.environ)},
    )
    assert done.returncode == 0, done.stderr


def a1_amended(copy, made):  # (a fast-forward, then the agent's own amend of what came)
    agent_git(copy, "merge", "-q", "--ff-only", "main")
    (copy.root / "agent.txt").write_text("agent\n")
    agent_git(copy, "add", "agent.txt")
    agent_git(copy, "commit", "-q", "--amend", "--no-edit")


def a2_soft(copy, made):  # (a fast-forward, taken back softly and committed again as its own)
    agent_git(copy, "merge", "-q", "--ff-only", "main")
    agent_git(copy, "reset", "-q", "--soft", "HEAD~1")
    agent_git(copy, "commit", "-q", "-C", "ORIG_HEAD")


def a3_squash(copy, made):
    agent_git(copy, "merge", "-q", "--squash", "main")
    agent_git(copy, "commit", "-qm", "the agent's, squashed")


def a4_picked(copy, made):
    agent_git(copy, "cherry-pick", "-n", made)
    agent_git(copy, "commit", "-qm", "the agent's, picked")


COPIED = {"a1": a1_amended, "a2": a2_soft, "a3": a3_squash, "a4": a4_picked}


@needs_merge_base
@pytest.mark.parametrize("after", ["kept", "amended"])
@pytest.mark.parametrize("way", list(COPIED))
def test_your_unpushed_work_copied_into_the_agents_own_commit_never_goes_up(
    repo, runtime, way, after
):
    copy, origin = origin_case(repo, runtime, dirty=False, agent=False)
    private(repo)
    COPIED[way](copy, run(repo, "rev-parse", "HEAD"))
    AFTER[after](repo)  # (amended: only main's reflog holds it now)
    # (Kept, an a2 made the user's very commit again - same tree, parent, author, second: what
    # "push main first" refuses already. Amended away, only the files say whose it is.)
    said = "private.txt.*not pushed yet" if after == "amended" else "not (pushed|on origin) yet"
    with pytest.raises(git.Refused, match=said):
        push_pr(repo, runtime, copy)
    assert run(origin, "for-each-ref", "refs/heads/koloni/") == ""


@needs_merge_base
def test_how_many_commits_and_stashes_of_yours_are_not_on_origin(repo, runtime):
    copy, _origin = origin_case(repo, runtime)
    under = copies.folders(runtime)
    assert git.unpushed_count(repo, under) == (0, 0)  # (KOLONİ's branch is not the user's)
    private(repo)
    private(repo, "private2.txt")
    assert git.unpushed_count(repo, under) == (2, 0)
    run(repo, "stash", "-q")  # (its work and its index: one stash, not two commits)
    (repo / "new.txt").write_text("new\n")
    run(repo, "stash", "-q", "-u")  # (and its untracked files: one more, not three commits)
    assert git.unpushed_count(repo, under) == (2, 2)


# --- a second worktree of the user's own: what its HEAD holds is theirs too ----------------------


@needs_merge_base
def test_a_commit_on_your_other_worktrees_detached_head_is_yours(repo, runtime, tmp_path):
    copy, origin = origin_case(repo, runtime, dirty=False, agent=True)
    for twin in ("a", "b"):  # (two folders of one name: git's ids for them are not their names)
        run(repo, "worktree", "add", "-q", "--detach", str(tmp_path / twin / "users-wt"))
    assert (repo / ".git" / "worktrees" / "users-wt1").is_dir()
    mine = tmp_path / "b" / "users-wt"
    private(mine)  # (on no branch, not on origin)
    a4_picked(copy, run(mine, "rev-parse", "HEAD"))  # (the agent's pick of it, as its own)
    assert git.unpushed_count(repo, copies.folders(runtime)) == (1, 0)
    with pytest.raises(git.Refused, match="private.txt in it is your work not pushed yet"):
        push_pr(repo, runtime, copy)
    assert run(origin, "for-each-ref", "refs/heads/koloni/") == ""


def test_a_project_that_is_a_linked_worktree_counts_the_main_ones_detached_commit(
    repo, runtime, tmp_path
):
    linked, under = tmp_path / "linked", copies.folders(runtime)
    run(repo, "worktree", "add", "-q", "-b", "side", str(linked))
    commits, _stashes = git.unpushed_count(linked, under)  # (no origin: all of theirs)
    run(repo, "checkout", "-q", "--detach")
    private(repo)  # (on the main worktree's HEAD alone)
    assert git.unpushed_count(linked, under) == (commits + 1, 0)


@needs_merge_base
def test_a_commit_on_a_detached_head_in_kolonis_own_worktree_is_not_yours(repo, runtime):
    copy, origin = origin_case(repo, runtime, dirty=False, agent=True)
    other = copies.make_branch(repo, runtime, "agent2", "y")
    agent_git(other, "checkout", "-q", "--detach")  # (KOLONİ's by its folder, on no branch of its)
    own_commit(other, "other.txt")
    assert git.unpushed_count(repo, copies.folders(runtime)) == (0, 0)
    sha = push_pr(repo, runtime, copy)
    assert run(origin, "diff", "--name-only", f"{sha}^", sha).split() == ["agent.txt"]


@needs_merge_base
def test_with_your_reflogs_expired_the_agents_own_commit_is_held_and_not_called_yours(
    repo, runtime
):
    copy, origin = origin_case(repo, runtime, dirty=False, agent=True)
    own_commit(copy)
    run(repo, "reflog", "expire", "--expire=now", "--all")  # (the user's housekeeping, or gc's)
    with pytest.raises(git.Refused, match="not on origin that KOLONİ cannot attribute") as said:
        push_pr(repo, runtime, copy)
    assert "of yours" not in str(said.value)
    assert run(origin, "for-each-ref", "refs/heads/koloni/") == ""


@needs_merge_base
def test_with_commits_of_yours_not_on_github_full_auto_asks_before_a_pull_request(
    make_client, wait_run, repo, github
):
    bare, _log = github

    def meanwhile():  # (theirs up, then one more not pushed - nothing of it on the branch)
        pushed_main(repo)
        private(repo, "mine.txt")

    client, cid, run_id = pr_run(make_client, repo, meanwhile)
    merge = until(
        client,
        cid,
        lambda s: (((s["merges"] or [{}])[0].get("branch") or {}).get("note") or "").startswith(
            "you have"
        ),
        timeout=LONG,
    )["merges"][0]
    assert merge["branch"]["note"] == PR_UNPUSHED.format(commits="1 commit")
    assert merge["status"] == "pending" and run(bare, "for-each-ref", "refs/heads/koloni/") == ""
    assert client.post(f"/api/merges/{merge['id']}/approve", json={"shown": {}}).status_code == 200
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["merges"][0]["commit"]["state"] == "pull_request"
    pushed = run(bare, "rev-parse", "refs/heads/koloni/fix")
    assert run(bare, "diff", "--name-only", f"{pushed}^", pushed).split() == ["lines.txt"]


# --- through the real pull-request path: what of the user's an agent copies, at Full auto ---------


def worktree_of(repo):
    """The folder of the branch's worktree (`koloni/fix`), as git lists it."""
    listed = run(repo, "worktree", "list", "--porcelain").split("\n\n")
    return Path(
        next(
            block.split("\n")[0][len("worktree ") :]
            for block in listed
            if "refs/heads/koloni/fix" in block
        )
    )


def copied_in(repo, source, target="private.txt"):
    """The agent's own unasked `git show <source> > <target>`, add and commit, in its worktree."""
    root = worktree_of(repo)
    done = subprocess.run(
        ["git", "show", source],
        cwd=root,
        capture_output=True,
        check=True,
        env={**os.environ, **copies.git_env(root, os.environ)},
    )
    (root / target).parent.mkdir(parents=True, exist_ok=True)
    (root / target).write_bytes(done.stdout)
    own = copy_like(root)
    own("add", target)
    own("commit", "-qm", "the agent's")


def copy_like(root):
    def own(*args):
        subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            check=True,
            env={**os.environ, **copies.git_env(root, os.environ)},
        )

    return own


def pr_card(client, cid):
    """The pull request's card, once it waits with a note."""
    return until(
        client,
        cid,
        lambda s: (
            s["merges"]
            and s["merges"][0]["status"] == "pending"
            and ((s["merges"][0].get("branch") or {}).get("note"))
        ),
        timeout=LONG,
    )["merges"][0]


def stashed(repo):
    pushed_main(repo)
    (repo / "private.txt").write_text("STASHED, NEVER COMMITTED\n")
    run(repo, "stash", "-q", "-u")
    copied_in(repo, "stash@{0}^3:private.txt")


def detached(repo):
    pushed_main(repo)
    run(repo, "checkout", "-q", "--detach")
    private(repo)
    made = run(repo, "rev-parse", "HEAD")
    run(repo, "checkout", "-q", "main")
    copied_in(repo, f"{made}:private.txt")


def other_worktree(repo):  # (a second worktree of the user's own, its HEAD on no branch)
    pushed_main(repo)
    mine = repo.parent / "users-wt"
    run(repo, "worktree", "add", "-q", "--detach", str(mine))
    private(mine)
    copied_in(repo, f"{run(mine, 'rev-parse', 'HEAD')}:private.txt")


@needs_merge_base
@pytest.mark.parametrize(
    ("how", "yours"),
    [
        (stashed, "a stash"),
        (detached, "1 commit"),
        (other_worktree, "1 commit (in your worktree {wt})"),
    ],  # (k-okuyucu-3: which one)
    ids=["stash", "detached", "other-worktree"],
)
def test_a_stash_or_a_detached_commit_copied_onto_the_branch_is_asked_and_never_sent(
    make_client, wait_run, repo, github, how, yours
):
    bare, _log = github
    client, cid, _run_id = pr_run(make_client, repo, lambda: how(repo))
    merge = pr_card(client, cid)  # (Full auto: asked, the user has work not on GitHub)
    said = PR_UNPUSHED.format(commits=yours).split("{wt}")  # (the folder as git keeps it)
    note = merge["branch"]["note"]
    assert (
        note.startswith(said[0])
        and note.endswith(said[-1])
        and (len(said) == 1 or "users-wt" in note)
    ), note
    assert merge["status"] == "pending"
    assert client.post(f"/api/merges/{merge['id']}/approve", json={"shown": {}}).status_code == 200
    merge = until(
        client,
        cid,
        lambda s: "not pushed yet" in ((s["merges"][0].get("branch") or {}).get("note") or ""),
        timeout=LONG,
    )["merges"][0]
    assert "private.txt in it is your work not pushed yet" in merge["branch"]["note"]
    assert run(bare, "for-each-ref", "refs/heads/koloni/") == ""


@needs_merge_base
@pytest.mark.parametrize("changed", [False, True])
def test_your_uncommitted_work_copied_under_another_name_is_asked_and_an_exact_copy_never_sent(
    make_client, wait_run, repo, github, changed
):
    bare, _log = github
    draft = "MY UNCOMMITTED DRAFT\n"

    def copied():  # (the snapshot put draft.txt in the worktree; the agent copies it away)
        pushed_main(repo)
        root = worktree_of(repo)
        (root / "docs").mkdir()
        (root / "docs" / "draft.txt").write_bytes(
            (root / "draft.txt").read_bytes() + (b"and the agent's own line\n" if changed else b"")
        )  # (byte for byte, or not)
        own = copy_like(root)
        own("add", "docs/draft.txt")
        own("commit", "-qm", "the agent's")

    client, cid, run_id = pr_run(make_client, repo, copied, wip={"draft.txt": draft})
    merge = pr_card(client, cid)
    assert merge["branch"]["note"] == PR_SNAPSHOT and merge["status"] == "pending"
    assert client.post(f"/api/merges/{merge['id']}/approve", json={"shown": {}}).status_code == 200
    if changed:  # (not the user's bytes: theirs to judge, and they said yes)
        snap = wait_run(client, cid, run_id, timeout=LONG)
        assert snap["merges"][0]["commit"]["state"] == "pull_request"
        return
    merge = until(
        client,
        cid,
        lambda s: "not pushed yet" in ((s["merges"][0].get("branch") or {}).get("note") or ""),
        timeout=LONG,
    )["merges"][0]
    assert "docs/draft.txt in it is your work not pushed yet" in merge["branch"]["note"]
    assert run(bare, "for-each-ref", "refs/heads/koloni/") == ""


@needs_merge_base
def test_at_ask_the_pull_requests_card_says_you_have_commits_not_on_github(
    make_client, wait_run, repo, github
):
    def meanwhile():
        pushed_main(repo)
        private(repo, "mine.txt")

    client, cid, _run_id = pr_run(make_client, repo, meanwhile, permission_mode="ask")
    merge = pr_card(client, cid)
    assert merge["branch"]["note"] == PR_UNPUSHED.format(commits="1 commit")


# --- k-okuyucu-3: whose a worktree's commits are (the k-pr-wt review's non-blocking items) --------


def users_wt(repo, tmp_path, name="users-wt"):
    """A second worktree of the user's, on no branch, with a commit of theirs not on origin."""
    mine = tmp_path / name
    run(repo, "worktree", "add", "-q", "--detach", str(mine))
    private(mine)
    return mine


@needs_merge_base
@pytest.mark.parametrize("where", ["other-wt", "other-wt-left", "project", "project-left"])
def test_your_look_at_the_agents_branch_does_not_make_its_commits_yours(
    repo, runtime, tmp_path, where
):
    """(a) The user checks the agent's work out (detached: git refuses a second checkout of the
    branch) - its commits on their HEAD, or its reflog, are still the agent's."""
    copy, origin = origin_case(repo, runtime, dirty=False, agent=True)
    look = tmp_path / "look"
    if where.startswith("other-wt"):
        run(repo, "worktree", "add", "-q", "--detach", str(look), copy.branch)
    else:
        run(repo, "checkout", "-q", "--detach", copy.branch)
    if where.endswith("left"):
        run(look if where.startswith("other-wt") else repo, "checkout", "-q", "--detach", "main")
    assert git.unpushed_count(repo, copies.folders(runtime), copy.branch) == (0, 0)
    sha = push_pr(repo, runtime, copy)
    assert run(origin, "diff", "--name-only", f"{sha}^", sha).split() == ["agent.txt"]


@needs_merge_base
def test_a_commit_of_yours_the_agent_made_again_on_its_branch_stays_yours(repo, runtime, tmp_path):
    """(a) What the user's own reflog says they made stays theirs, though the branch's says it was
    made there too (a fast-forward taken back softly and committed again: the very commit, made in
    the same second)."""
    copy, origin = origin_case(repo, runtime, dirty=False, agent=False)
    made = run(users_wt(repo, tmp_path), "rev-parse", "HEAD")
    agent_git(copy, "merge", "-q", "--ff-only", made)
    agent_git(copy, "reset", "-q", "--soft", "HEAD~1")
    agent_git(copy, "commit", "-q", "-C", "ORIG_HEAD")
    with pytest.raises(git.Refused, match="not on origin|not pushed yet"):
        push_pr(repo, runtime, copy)
    assert run(origin, "for-each-ref", "refs/heads/koloni/") == ""


@needs_merge_base
@pytest.mark.parametrize("same", [False, True])
def test_another_kolonis_worktree_on_its_own_branch_is_not_yours(repo, runtime, tmp_path, same):
    """(b) Another KOLONİ runtime's worktree, outside this one's copies folders, on a branch of
    KOLONİ's: its commits are not the user's - not when its agent wrote the very file ours did."""
    copy, origin = origin_case(repo, runtime, dirty=False, agent=True)
    second = tmp_path / "runtime2"
    other = copies.make_branch(repo, second, "agentZ", "z")
    if same:
        (other.root / "agent.txt").write_text("agent\n")
        assert git.commit_branch(other.root, other.branch, ["agent.txt"], "a", second / "no-hooks")
    else:
        own_commit(other, "z.txt")
    assert git.unpushed_count(repo, copies.folders(runtime)) == (0, 0)
    sha = push_pr(repo, runtime, copy)
    assert run(origin, "diff", "--name-only", f"{sha}^", sha).split() == ["agent.txt"]


@needs_merge_base
def test_a_commit_on_your_worktree_whose_branch_was_deleted_is_still_yours(repo, runtime, tmp_path):
    """(c) Its HEAD names a branch no more (git calls it dangling and gives no reflog of it): the
    reflog file is read all the same."""
    copy, origin = origin_case(repo, runtime, dirty=False, agent=True)
    mine = tmp_path / "side-wt"
    run(repo, "worktree", "add", "-q", "-b", "side", str(mine))
    private(mine)
    made = run(mine, "rev-parse", "HEAD")
    run(repo, "update-ref", "-d", "refs/heads/side")
    a4_picked(copy, made)
    assert git.unpushed_count(repo, copies.folders(runtime)) == (1, 0)
    with pytest.raises(git.Refused, match="private.txt in it is your work not pushed yet"):
        push_pr(repo, runtime, copy)
    assert run(origin, "for-each-ref", "refs/heads/koloni/") == ""


@needs_merge_base
def test_the_worktree_that_holds_your_unpushed_commit_is_named_and_a_gone_one_too(
    repo, runtime, tmp_path
):
    """(d) What the pull request's card says (`PR_HELD_IN`): by its folder - one deleted by hand
    is git's until `git worktree prune`. A commit a branch of theirs holds too is not on it."""
    import shutil

    from app.agent import PR_HELD_GONE, PR_HELD_IN

    origin_case(repo, runtime, dirty=False, agent=True)
    under = copies.folders(runtime)
    assert git.unpushed_places(repo, under) == []
    mine = users_wt(repo, tmp_path)
    run(repo, "worktree", "add", "-q", "--detach", str(tmp_path / "clean-wt"))  # (nothing of its)
    ((there, kept),) = git.unpushed_places(repo, under)
    assert os.path.samefile(there, mine) and kept
    assert PR_HELD_IN.format(folder=there) == f"in your worktree {there}"
    run(repo, "branch", "keep", run(mine, "rev-parse", "HEAD"))  # (a branch of theirs holds it)
    assert git.unpushed_places(repo, under) == []
    run(repo, "branch", "-D", "keep")
    shutil.rmtree(mine)  # (deleted by hand, never pruned)
    ((there, kept),) = git.unpushed_places(repo, under)
    assert there.name == "users-wt" and not kept
    assert "git worktree prune" in PR_HELD_GONE.format(folder=there)


# The lines that defeated the pull request's protection, each in the user's worktree `users-wt`:
# the k-pr-wt review's, the k-okuyucu-3 review's (another writer, `>|`) and CL-311's (another
# worktree's link and HEAD - the user's commit left unreferenced).
SHARED_LINES = {
    "gitdir": 'echo "$(pwd -W)/x" > "$(dirname "$(git rev-parse --git-dir)")/users-wt/gitdir"',
    "sed-i": 'sed -i "s#.*#$(pwd -W)/x#" "$(dirname "$(git rev-parse --git-dir)")/users-wt/gitdir"',
    "perl-pi": (
        'perl -pi -e "s#.*#$(pwd -W)/x#" "$(dirname "$(git rev-parse --git-dir)")/users-wt/gitdir"'
    ),
    "ps-iofile-copy": (
        '[IO.File]::Copy("$PWD/g.txt", (Join-Path (Split-Path (git rev-parse '
        "--git-dir)) 'users-wt/gitdir'), $true)"
    ),
    "clobber-ref": (
        'git rev-parse HEAD >| "$(dirname "$(dirname "$(git rev-parse --git-dir)")")'
        '/refs/remotes/origin/x"'
    ),
    "cl311-gitdir": 'echo "$(dirname "$PWD")/zz/x" > "$(git rev-parse --git-dir)/../users-wt/gitdir"',
    "cl311-head": (
        'git rev-parse HEAD > "$(git rev-parse --git-dir)/../users-wt/HEAD" && : > '
        '"$(git rev-parse --git-dir)/../users-wt/logs/HEAD"'
    ),
}


@needs_merge_base
@pytest.mark.parametrize("how", list(SHARED_LINES))
def test_at_full_auto_a_write_into_your_shared_git_by_a_built_path_waits_and_the_card_stays(
    make_client, wait_run, repo, github, how
):
    """K-okuyucu-3 (the reviews' probes): the agent's one unasked line would point the user's other
    worktree into its own folder, rewrite its HEAD, or forge a ref of origin's - KOLONİ would take
    that worktree for its own, and its unpushed commit would go out with the pull request, no card.
    Asked at Full auto: with the shared git's path built (BUILT_TARGET), or computed by a writer
    the reader does not list (`git rev-parse --git-dir`: SHARED_GIT)."""
    from app.commands import BUILT_TARGET, SHARED_GIT
    from tests.test_agent_writes import wait_status
    from tests.test_full_auto_harm import why_asked
    from tests.test_spawn import call

    bare, _log = github
    held = Gate()
    client, cid, _run_id = on_branch(
        make_client,
        repo,
        [
            step(edit("two", "TWO-agent")),
            held.step(step(call("run_command", {"command": SHARED_LINES[how]}, "c"))),
            text("A done"),
        ],
        project={"finish_way": "pull_request", "check_command": "python check.py TWO-agent"},
    )
    held.wait_partial()
    pushed_main(repo)
    users_wt(repo, repo.parent)
    admin = repo / ".git" / "worktrees" / "users-wt"
    before = [(admin / name).read_bytes() for name in ("gitdir", "HEAD", "logs/HEAD")]
    held.release()
    snap = wait_status(client, cid, "waiting_approval")
    (asked,) = snap["commands"]
    assert why_asked(snap, asked) in (BUILT_TARGET, SHARED_GIT)  # (Full auto: asked)
    assert client.post(f"/api/commands/{asked['id']}/reject").status_code == 200
    merge = pr_card(client, cid)
    note = merge["branch"]["note"]
    assert note.startswith("you have 1 commit (in your worktree ") and "users-wt)" in note, note
    assert merge["status"] == "pending"
    assert [(admin / name).read_bytes() for name in ("gitdir", "HEAD", "logs/HEAD")] == before
    assert run(bare, "for-each-ref", "refs/heads/koloni/") == ""


@needs_merge_base
def test_your_worktree_later_on_a_branch_of_kolonis_still_holds_your_commit(
    repo, runtime, tmp_path
):
    """K-okuyucu-3 review (B2): the user's second worktree made a commit on no branch, then went onto
    an earlier agent's `koloni/` branch to try that work: its reflog still holds the commit - only
    what that branch's own reflog says was made on it is the agents'."""
    copy, origin = origin_case(repo, runtime, dirty=False, agent=True)
    mine = users_wt(repo, tmp_path)
    made = run(mine, "rev-parse", "HEAD")
    run(repo, "branch", "koloni/old", "main")
    run(mine, "switch", "-q", "koloni/old")
    a4_picked(copy, made)
    assert git.unpushed_count(repo, copies.folders(runtime), copy.branch) == (1, 0)
    with pytest.raises(git.Refused, match="private.txt in it is your work not pushed yet"):
        push_pr(repo, runtime, copy)
    assert run(origin, "for-each-ref", "refs/heads/koloni/") == ""


@needs_merge_base
def test_an_agents_commit_a_branch_of_yours_holds_too_stays_yours(repo, runtime):
    """K-okuyucu-3 review (N7): what the branch's reflog says was made on it is never taken out of
    your work where a branch, tag or other remote of yours holds it too."""
    copy, origin = origin_case(repo, runtime, dirty=False, agent=True)
    run(repo, "branch", "keep", copy.branch)  # (the user's own branch on the agent's commit)
    assert git.unpushed_count(repo, copies.folders(runtime), copy.branch) == (1, 0)
    with pytest.raises(git.Refused, match="agent.txt in it is your work not pushed yet"):
        push_pr(repo, runtime, copy)
    assert run(origin, "for-each-ref", "refs/heads/koloni/") == ""
