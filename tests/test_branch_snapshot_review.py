"""W-1 after an independent security review: what a branch's snapshot never takes (links,
junctions, staged and secret files), what never leaves with a pull request, where the agents' work
is asked about, and where a snapshot that cannot be made leaves the branch starting from HEAD."""

import asyncio
import os
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest

from app import copies, git
from app.agent import BRANCH_OVER_YOURS, NOT_IN_BRANCH, AgentRunner
from tests import test_dal_takim
from tests.conftest import Gate, scaled
from tests.test_branch_snapshot import has_object, needs_merge_base, porcelain
from tests.test_chat_flow import text
from tests.test_dal_takim import on_branch, run
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
        repo, runtime / "wt", "x", runtime / "no-hooks", most)
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
    with pytest.raises(git.Refused, match="push main first"):
        git.push_one(repo, pushed, copy.branch, "main", copy.start[1], "m", runtime / "no-hooks")
    assert run(bare, "for-each-ref", "refs/heads/koloni/") == ""
    run(repo, "push", "-q", "origin", "main")  # (theirs up by their own hand: then it goes)
    sha = git.push_one(repo, pushed, copy.branch, "main", copy.start[1], "m", runtime / "no-hooks")
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
def test_a_junction_loop_inside_a_new_folder_leaves_the_branch_from_head_saying_why(
    repo, runtime
):
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
    client, cid, run_id = on_branch(make_client, repo, [
        step(edit("two", "TWO-agent", path="a.txt")), held_back.step(text("A done"))],
        wip={"a.txt": "ONE-mine\ntwo\n"})
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
        _merging_in={}, _on_branch={"o": "x"}, _ctxs={"o": SimpleNamespace(model=None)},
        settings=SimpleNamespace(runtime_root=tmp_path / "rt"), _copy_part=lambda owner: None,
        _make_copy=lambda *args: make,
        _drop_branch=lambda copy, force=False: dropped.append((copy, force)))
    fake._way_in = lambda project: AgentRunner._way_in(fake, project)
    fake._unmade = lambda *args: AgentRunner._unmade(fake, *args)
    monkeypatch.setattr(copies, "remove", lambda root, name: removed.append(name))

    async def scene():
        task = asyncio.ensure_future(AgentRunner._made_copy(
            fake, SimpleNamespace(folder=str(tmp_path)), "o", "o", None))
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
    staged = {".env": "API_KEY=STAGED-SECRET\n", "id_rsa": "KEY\n", "node_modules/x/i.js": "x\n",
              "build/out.txt": "out\n", ".koloni/settings.json": "{}\n"}
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
    client, cid, run_id = on_branch(make_client, repo, [
        step(edit("two", "TWO-agent")), text("A done")],
        wip={"notes.txt": "mine\n", ".env": "KEY=1\n", "token.json": "{}\n"})
    snap = wait_run(client, cid, run_id, timeout=LONG)
    (merge,) = snap["merges"]
    assert merge["branch"]["not_taken"] == NOT_IN_BRANCH.format(
        count=2, files=".env, token.json")
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


def origin_case(repo, runtime, dirty=True):
    """A project whose main is on a bare origin, a branch from it (a snapshot of an uncommitted
    edit where `dirty`), and the agent's commit on it: the copy and the origin."""
    origin = runtime.parent / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True, capture_output=True)
    run(repo, "remote", "add", "origin", str(origin))
    run(repo, "push", "-q", "origin", "main")
    if dirty:
        (repo / "a.txt").write_text("one\ntwo\nUSER-UNCOMMITTED\n")
    copy = copies.make_branch(repo, runtime, "agent1", "x")
    (copy.root / "agent.txt").write_text("agent\n")
    assert git.commit_branch(copy.root, copy.branch, ["agent.txt"], "agent", runtime / "no-hooks")
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
    return git.push_one(repo, sent, copy.branch, "main", copy.start[1], "m", runtime / "no-hooks",
                        source=tip)


def agent_merges(copy, ref="main"):
    run(copy.root, "-c", "core.hooksPath=", "merge", "-q", "--no-edit", ref)  # (its own, allowed)


def rebased(repo):
    """The user's unpushed commit made anew (another time: another commit)."""
    subprocess.run(["git", "rebase", "-q", "--autostash", "--force-rebase", "origin/main"],
                   cwd=repo, check=True, capture_output=True,
                   env={**os.environ, "GIT_COMMITTER_DATE": "2001-01-01T00:00:00"})
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
    with pytest.raises(git.Refused, match="not on origin"):
        push_pr(repo, runtime, copy)
    assert run(origin, "for-each-ref", "refs/heads/koloni/") == ""


@needs_merge_base
@pytest.mark.parametrize("merged", [False, True])
def test_a_pull_request_of_the_agents_work_and_what_is_on_origin_goes(repo, runtime, merged):
    copy, origin = origin_case(repo, runtime)
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
