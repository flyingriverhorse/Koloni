"""Coordination (A): agents at work beside each other, each in a copy of its own, do each other
no harm. One way into the project at a time - a Take in waits while a branch merges - and a copy
made meanwhile, or one already made, gets what went in."""

import os
import shutil
import threading
import time
from pathlib import Path

from app import copies, git
from app.agent import AgentRunner, recover_copies
from app.db.models import Agent
from tests.conftest import Gate, scaled
from tests.test_chat_flow import text
from tests.test_claim_scenarios import ORIGIN, calls, setup, two, write
from tests.test_dal_takim import repo, run, runtime, worktrees  # noqa: F401  (fixtures)
from tests.test_parallel import until
from tests.test_spawn import call, step
from tests.test_take_in_scenarios import LINES, LONG, edit, lines, needs_git


def read(path, id="r"):
    return call("read_file", {"path": path}, id)


def waited(ready, seconds=10.0):
    """In a thread of the app's: whether `ready()` came to hold in time."""
    deadline = time.monotonic() + scaled(seconds)
    while not ready():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.01)
    return True


def test_a_copy_made_while_a_take_in_writes_gets_what_was_taken(
    make_client, wait_run, project_dir, monkeypatch
):
    (project_dir / "lines.txt").write_bytes(LINES.encode())
    first, second = Gate(), Gate()
    holding, made = threading.Event(), threading.Event()
    real = copies.make

    def make(project, *args, **kwargs):
        copy = real(project, *args, **kwargs)
        if holding.is_set():
            # The Coder 2's copy holds the project as it was: the Coder's Take in goes in now.
            made.set()
            assert waited(lambda: "TWO-agent" in (project / "lines.txt").read_text())
        return copy

    monkeypatch.setattr(copies, "make", make)
    client, _model, cid, run_id = setup(make_client, project_dir, {
        "Lead": [two(), text("done")],
        "Coder": [step(edit("two", "TWO-agent")), first.step(text("A done"))],
        "Coder 2": [second.step(step(write("b.txt", "b\n"))), step(read("lines.txt")),
                    text("B done")],
    })
    first.wait_partial()  # (the Coder's copy is made, its change in it)
    holding.set()
    second.release()
    assert made.wait(scaled(10))
    first.release()
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    ((status, said),) = calls(snap, "Coder 2", "read_file")
    assert status == "succeeded" and "TWO-agent" in said
    assert sorted(m["status"] for m in snap["merges"]) == ["applied", "applied"]
    assert lines(project_dir)[1] == "TWO-agent" and (project_dir / "b.txt").read_text() == "b\n"


def branch_and_copy(make_client, repo, coder, coder_2):  # noqa: F811
    """A Lead that opens a Coder on a branch `koloni/fix` and a Coder 2 in a copy at once, in a
    repository with `lines.txt` committed, at Full auto: the client, the chat's and run's ids."""
    (repo / "lines.txt").write_bytes(LINES.encode())
    run(repo, "add", "-A")
    run(repo, "commit", "-qm", "lines")
    lead = [step(call("spawn_agent", {"role": "Coder", "task": "fix two", "on_branch": "fix"},
                      "s1"),
                 call("spawn_agent", {"role": "Coder", "task": "write notes"}, "s2")),
            text("done")]
    client, _model, cid, run_id = setup(
        make_client, repo, {"Lead": lead, "Coder": coder, "Coder 2": coder_2})
    return client, cid, run_id


@needs_git
def test_a_take_in_waits_while_a_branch_merges(make_client, wait_run, repo, monkeypatch):  # noqa: F811
    held = Gate()
    merging, looked = threading.Event(), threading.Event()
    order: list[str] = []
    real_merge, real_changes, real_apply = (
        git.merge_branch, AgentRunner._copy_changes, AgentRunner._apply)

    def merge_branch(*args, **kwargs):
        merging.set()
        assert looked.wait(scaled(10))  # (the Coder 2's Take in has looked at its copy)
        sha = real_merge(*args, **kwargs)
        order.append("merged")
        return sha

    async def copy_changes(self, ctx, copy, files):
        fault = await real_changes(self, ctx, copy, files)
        if not copy.branch:
            looked.set()
        return fault

    def apply(self, *args, **kwargs):
        taken = real_apply(self, *args, **kwargs)
        order.append("applied")
        return taken

    monkeypatch.setattr(git, "merge_branch", merge_branch)
    monkeypatch.setattr(AgentRunner, "_copy_changes", copy_changes)
    monkeypatch.setattr(AgentRunner, "_apply", apply)
    client, cid, run_id = branch_and_copy(
        make_client, repo, [step(edit("two", "TWO-branch")), text("A done")],
        [step(write("notes.txt", "b\n")), held.step(text("B done"))])
    assert merging.wait(scaled(LONG))
    held.release()
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert order == ["merged", "applied"]
    assert sorted(m["status"] for m in snap["merges"]) == ["applied", "applied"]
    assert lines(repo)[1] == "TWO-branch" and (repo / "notes.txt").read_text() == "b\n"


@needs_git
def test_a_copy_gets_what_a_branchs_merge_brought(make_client, wait_run, repo):  # noqa: F811
    first, second = Gate(), Gate()
    client, cid, run_id = branch_and_copy(
        make_client, repo, [step(edit("two", "TWO-branch")), first.step(text("A done"))],
        [step(write("notes.txt", "b\n")), second.step(step(read("lines.txt"))),
         text("B done")])
    first.wait_partial()
    second.wait_partial()  # (the Coder 2's copy is made: it wrote its notes there)
    first.release()
    until(client, cid, lambda s: [m["status"] for m in s["merges"]] == ["applied"],
          timeout=LONG)
    second.release()
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    ((status, said),) = calls(snap, "Coder 2", "read_file")
    assert status == "succeeded" and "TWO-branch" in said
    # (its own notes go in by themselves: nothing of the merge is the Coder 2's to take in)
    assert sorted(m["status"] for m in snap["merges"]) == ["applied", "applied"]
    assert (repo / "notes.txt").read_text() == "b\n" and lines(repo)[1] == "TWO-branch"


# --- KOLONİ's worktrees are locked while their agents work ----------------------------------


def key(path):
    return os.path.normcase(os.path.realpath(path))


def listed(repo):  # noqa: F811
    """git's worktrees of the repository, by their folder's key."""
    return {key(one["path"]): one for one in git.where(repo)["worktrees"]}


@needs_git
def test_a_branchs_worktree_is_locked_while_its_agent_works(repo, runtime):  # noqa: F811
    copy = copies.make_branch(repo, runtime, "agent1", "x")
    held = Path(run(copy.root, "rev-parse", "--absolute-git-dir")) / "locked"
    assert held.read_text(encoding="utf-8").strip() == git.LOCK_REASON
    assert listed(repo)[key(copy.root)]["locked"] is True
    copies.remove(runtime, copy.name)
    run(repo, "worktree", "prune")  # (the user's own git upkeep: a locked record stays)
    assert key(copy.root) in listed(repo)
    git.drop_branch(repo, copy.root, copy.branch, runtime / "no-hooks", force=True)
    assert len(worktrees(repo)) == 1 and run(repo, "branch", "--list", "koloni/*") == ""


@needs_git
def test_at_start_only_kolonis_own_stale_worktree_records_go(repo, runtime, tmp_path):  # noqa: F811
    stale = copies.make_branch(repo, runtime, "agent1", "x")
    kept = copies.make_branch(repo, runtime, "agent2", "y")
    mine = tmp_path / "users-own"
    run(repo, "worktree", "add", "-q", "-b", "mine", str(mine))
    shutil.rmtree(mine)  # (the user's own, its folder gone: theirs to prune)
    copies.remove(runtime, stale.name)
    gone = git.forget_worktrees(repo, copies.folders(runtime), runtime / "no-hooks")
    assert [key(one) for one in gone] == [key(stale.root)]
    left = listed(repo)
    assert key(stale.root) not in left and key(mine) in left
    assert left[key(kept.root)]["locked"] is True
    assert run(repo, "branch", "--list", "koloni/x").strip() == "koloni/x"  # (its work stays)


@needs_git
def test_a_branch_whose_locked_worktree_lost_its_folder_opens_again(repo, runtime):  # noqa: F811
    copy = copies.make_branch(repo, runtime, "agent1", "x")
    copies.remove(runtime, copy.name)  # (deleted by hand: git's record stays, locked)
    again = copies.make_branch(repo, runtime, "agent1-2", copy.branch, start=copy.start)
    assert again.branch == copy.branch and again.root.is_dir()
    assert key(again.root) in listed(repo) and key(copy.root) not in listed(repo)


@needs_git
def test_at_start_koloni_forgets_its_worktree_that_a_crash_left(make_client, wait_run, repo):  # noqa: F811
    client, _model = make_client([text("hi")])
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(repo)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    run_id = client.post(f"/api/conversations/{cid}/messages", json={"content": "go"}).json()[
        "run"]["id"]
    (lead,) = wait_run(client, cid, run_id)["agents"]
    root = client.app.state.settings.runtime_root
    copy = copies.make_branch(repo, root, lead["id"], "x")  # (its agent at work: a crash)
    with client.app.state.session_factory() as session:
        session.get_one(Agent, lead["id"]).copy = {"state": "own", "tree": str(copy.root),
                                                   "on_branch": copy.branch}
        session.commit()
    copies.remove(root, copy.name)  # (its folder gone, git's record of it left)
    recover_copies(client.app.state.session_factory, root)  # (as at the next start)
    assert len(worktrees(repo)) == 1
    assert run(repo, "branch", "--list", "koloni/x").strip() == "koloni/x"
