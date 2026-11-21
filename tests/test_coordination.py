"""Coordination (A): agents at work beside each other, each in a copy of its own, do each other
no harm. One way into the project at a time - a Take in waits while a branch merges - and a copy
made meanwhile, or one already made, gets what went in."""

import threading
import time

from app import copies, git
from app.agent import AgentRunner
from tests.conftest import Gate, scaled
from tests.test_chat_flow import text
from tests.test_claim_scenarios import calls, setup, two, write
from tests.test_dal_takim import repo, run  # noqa: F401  (`repo`: a fixture)
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
