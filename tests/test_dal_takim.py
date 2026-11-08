"""K-dal-takim: a team's work on a git branch of its own - a worktree on `koloni/<name>` in the
copies folder, KOLONİ's commit of what its agents changed, and the merge into the user's branch
only where git would make it cleanly. Every repository here is made by the test, in its folder."""

import asyncio
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest

from app import copies, git
from app.commands import SHARED_GIT
from app.db.models import Agent, BacklogTask
from app.model_client import ModelUnavailable
from tests.conftest import Gate
from tests.test_backlog import setup
from tests.test_backlog_auto import tasks, worked
from tests.test_chat_flow import text
from tests.test_claim_scenarios import calls, write
from tests.test_git_view import run
from tests.test_parallel import until
from tests.test_session_agent import session_app  # noqa: F401  (a fixture)
from tests.test_spawn import call, role_id, step
from tests.test_take_in_scenarios import (
    CHECK,
    LINES,
    LONG,
    ORIGIN,
    card,
    edit,
    lines,
    needs_git,
    of,
    repository,
    start,
)

pytestmark = needs_git


@pytest.fixture
def repo(project_dir, monkeypatch):
    # (Nothing of the user's own git settings - a signing key, a hook - in these commits.)
    empty = project_dir.parent / "gitconfig"
    empty.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    (project_dir / ".gitignore").write_text(".venv/\n")
    (project_dir / "a.txt").write_text("one\ntwo\n")
    repository(project_dir)
    (project_dir / ".venv").mkdir()
    (project_dir / ".venv" / "marker").write_text("the project's own")
    return project_dir


@pytest.fixture
def runtime(tmp_path):
    return tmp_path / "runtime"


def worktrees(repo):
    return [line for line in run(repo, "worktree", "list", "--porcelain").splitlines()
            if line.startswith("worktree ")]


def tip(repo, copy):
    """The branch's commit, as `branch_look` pins it."""
    return run(repo, "rev-parse", copy.branch)


def gone(repo, runtime, copy):
    copies.remove(runtime, copy.name)
    git.drop_branch(repo, copy.root, copy.branch, runtime / "no-hooks", force=True)  # (a squash)


def test_a_branch_copy_is_merged_and_then_nothing_of_it_is_left_but_the_merge(repo, runtime):
    copy = copies.make_branch(repo, runtime, "agent1", "Login form")
    assert copy.branch == "koloni/login-form"
    assert run(copy.root, "branch", "--show-current") == "koloni/login-form"
    assert copy.root.joinpath(".venv").is_junction() or copy.root.joinpath(".venv").is_symlink()
    assert "a.txt" in copy.names.values() and ".venv/marker" not in copy.names.values()
    (copy.root / "a.txt").write_text("one\nTWO\n")
    (copy.root / "b.txt").write_text("new\n")
    paths = [path for path, _kind, _state in copy.changes()]
    assert sorted(paths) == ["a.txt", "b.txt"]
    assert git.commit_branch(copy.root, copy.branch, paths, "Coder: login form", runtime / "no-hooks")
    assert run(repo, "log", "-1", "--format=%ae", "koloni/login-form") == "koloni@localhost"
    look = git.branch_look(repo, copy.branch)
    assert look.pop("tip") == run(repo, "rev-parse", copy.branch)
    assert look == {"into": "main", "files": {"a.txt": "M", "b.txt": "A"}, "conflicts": [],
                    "dirty": [], "special": [], "drift": None, "half": None}
    sha = git.merge_branch(repo, tip(repo, copy), "Merge koloni/login-form", runtime / "no-hooks",
                           "main", copy.start[1])
    assert run(repo, "rev-parse", "HEAD") == sha
    assert (repo / "b.txt").read_text() == "new\n"
    # (one commit by KOLONİ, on one parent: a squash - not the agents' own steps)
    assert run(repo, "log", "-1", "--format=%P %ae").count(" ") == 1
    assert run(repo, "log", "-1", "--format=%ae") == "koloni@localhost"
    gone(repo, runtime, copy)
    assert not os.path.lexists(copy.root.parent)
    assert (repo / ".venv" / "marker").read_text() == "the project's own"  # (not through a link)
    assert run(repo, "branch", "--list", "koloni/*") == ""
    assert len(worktrees(repo)) == 1


def test_nothing_changed_is_no_commit_and_the_branch_goes_with_its_worktree(repo, runtime):
    copy = copies.make_branch(repo, runtime, "agent1", "x")
    assert not git.commit_branch(copy.root, copy.branch, [], "m", runtime / "no-hooks")
    assert not git.commit_branch(copy.root, copy.branch, ["a.txt"], "m", runtime / "no-hooks")
    gone(repo, runtime, copy)
    assert run(repo, "branch", "--list", "koloni/*") == ""


def test_a_name_taken_gets_a_number_and_a_bad_one_is_refused(repo, runtime):
    run(repo, "branch", "koloni/fix")
    copy = copies.make_branch(repo, runtime, "agent1", "fix")
    assert copy.branch == "koloni/fix-2"
    with pytest.raises(git.Refused, match="short name"):
        copies.make_branch(repo, runtime, "agent2", "---")
    assert not os.path.lexists(copies.place(runtime, "agent2"))


def test_no_branch_where_the_project_is_on_none_or_has_no_git(repo, runtime, tmp_path):
    run(repo, "checkout", "-q", "--detach")
    with pytest.raises(git.Refused, match="detached"):
        copies.make_branch(repo, runtime, "agent1", "x")
    assert not os.path.lexists(copies.place(runtime, "agent1"))
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(git.Refused, match="not the top folder"):
        copies.make_branch(plain, runtime, "agent2", "x")


def test_what_fails_after_the_worktree_leaves_neither_folder_nor_branch(
    repo, runtime, monkeypatch
):
    def too_big(*_args, **_kwargs):
        raise copies.TooBig("too big")

    monkeypatch.setattr(copies, "_scan", too_big)
    with pytest.raises(copies.TooBig):
        copies.make_branch(repo, runtime, "agent1", "x")
    assert not os.path.lexists(copies.place(runtime, "agent1"))
    assert run(repo, "branch", "--list", "koloni/*") == ""
    assert len(worktrees(repo)) == 1


def test_the_users_files_in_the_way_and_a_conflict_are_said_and_nothing_is_merged(
    repo, runtime
):
    copy = copies.make_branch(repo, runtime, "agent1", "x")
    (copy.root / "a.txt").write_text("one\nAGENT\n")
    (copy.root / "c.txt").write_text("agent's\n")
    assert git.commit_branch(copy.root, copy.branch, ["a.txt", "c.txt"], "m", runtime / "no-hooks")
    # Uncommitted, not a file the branch touched: in nobody's way.
    (repo / "notes.txt").write_text("mine\n")
    assert git.branch_look(repo, copy.branch)["dirty"] == []
    # Untracked where the branch makes a file, and an edit of one it changes.
    (repo / "c.txt").write_text("mine\n")
    (repo / "a.txt").write_text("one\nmine\n")
    assert git.branch_look(repo, copy.branch)["dirty"] == ["a.txt", "c.txt"]
    head = run(repo, "rev-parse", "HEAD")
    with pytest.raises(git.Refused, match="c.txt would be written over"):
        git.merge_branch(repo, tip(repo, copy), "m", runtime / "no-hooks", "main")
    assert run(repo, "rev-parse", "HEAD") == head and (repo / "a.txt").read_text() == "one\nmine\n"
    # Staged, though the branch does not touch it: git's merge refuses then too.
    (repo / "c.txt").unlink()
    run(repo, "checkout", "--", "a.txt")
    run(repo, "add", "notes.txt")
    assert git.branch_look(repo, copy.branch)["dirty"] == ["notes.txt"]
    run(repo, "reset", "-q")
    # Committed by the user on the same lines: a conflict, the tree left alone.
    (repo / "a.txt").write_text("one\nUSER\n")
    run(repo, "commit", "-qam", "user")
    look = git.branch_look(repo, copy.branch)
    assert look["conflicts"] == ["a.txt"] and look["dirty"] == []
    assert (repo / "a.txt").read_text() == "one\nUSER\n" and not (repo / ".git" / "MERGE_HEAD").exists()


def test_a_branch_not_koloni_s_is_never_dropped_and_one_with_work_stays_unless_turned_down(
    repo, runtime
):
    with pytest.raises(git.Refused):
        git.drop_branch(repo, Path(runtime / "none"), "main", runtime / "no-hooks", force=True)
    copy = copies.make_branch(repo, runtime, "agent1", "x")
    (copy.root / "a.txt").write_text("changed\n")
    git.commit_branch(copy.root, copy.branch, ["a.txt"], "m", runtime / "no-hooks")
    copies.remove(runtime, copy.name)
    with pytest.raises(git.Refused, match="not fully merged"):
        git.drop_branch(repo, copy.root, copy.branch, runtime / "no-hooks")
    assert run(repo, "branch", "--list", "koloni/x").strip() == "koloni/x"
    git.drop_branch(repo, copy.root, copy.branch, runtime / "no-hooks", force=True)
    assert run(repo, "branch", "--list", "koloni/*") == ""


# --- the Orchestrator puts a line on a branch -------------------------------------------------


def on_branch(make_client, repo, coder, then=(), **conversation):
    """A project in git with `lines.txt` and `check.py` committed, and a Lead that opens one
    Coder on a branch `koloni/fix` (and takes the steps `then`); returns the client, the
    conversation's and the run's ids."""
    (repo / "lines.txt").write_bytes(LINES.encode())
    (repo / "check.py").write_bytes(CHECK.encode())
    run(repo, "add", "-A")
    run(repo, "commit", "-qm", "lines")
    lead = [step(call("spawn_agent", {"role": "Coder", "task": "fix two", "on_branch": "fix"},
                      "s")), *then, text("done")]
    client, _pid, cid, run_id = start(make_client, repo, coder, lead=lead, **conversation)
    return client, cid, run_id


def test_at_full_auto_a_branch_whose_check_passes_is_merged_and_nothing_is_left(
    make_client, wait_run, repo
):
    client, cid, run_id = on_branch(
        make_client, repo, [step(edit("two", "TWO-agent")), text("A done")],
        project={"check_command": "python check.py TWO-agent"})
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    (merge,) = snap["merges"]
    assert merge["status"] == "applied" and merge["check"]["state"] == "passed"
    assert [(f["path"], f["state"]) for f in merge["files"]] == [("lines.txt", "applied")]
    assert merge["branch"]["name"] == "koloni/fix" and merge["branch"]["into"] == "main"
    assert merge["commit"]["state"] == "committed" and merge["commit"]["sha"]
    assert lines(repo)[1] == "TWO-agent"
    assert run(repo, "rev-parse", "HEAD") == merge["commit"]["sha"]
    assert run(repo, "log", "-1", "--format=%ae") == "koloni@localhost"  # (a squash)
    assert " " not in run(repo, "log", "-1", "--format=%P")
    assert run(repo, "branch", "--show-current") == "main"
    assert run(repo, "branch", "--list", "koloni/*") == "" and len(worktrees(repo)) == 1
    assert (repo / ".venv" / "marker").read_text() == "the project's own"


def test_asked_a_merge_waits_for_the_users_files_in_the_way_and_discard_drops_the_branch(
    make_client, wait_run, repo
):
    held = Gate()
    client, cid, run_id = on_branch(
        make_client, repo, [step(edit("two", "TWO-agent")), held.step(text("A done"))],
        permission_mode="ask")
    held.wait_partial()
    (repo / "notes.txt").write_text("mine\n")
    run(repo, "add", "notes.txt")  # (staged: git merges nothing over it)
    held.release()
    merge = card(client, cid)
    assert merge["branch"]["dirty"] == ["notes.txt"] and merge["branch"]["conflicts"] == []
    assert [(f["path"], f["kind"], f["state"]) for f in merge["files"]] == [
        ("lines.txt", "changed", "ready")]
    assert "+TWO-agent" in merge["files"][0]["diff"]
    assert client.post(f"/api/merges/{merge['id']}/approve").status_code == 200
    merge = card(client, cid)  # (still asked: nothing merged over the user's)
    assert lines(repo)[1] == "two" and run(repo, "branch", "--list", "koloni/*").endswith("koloni/fix")
    assert client.post(f"/api/merges/{merge['id']}/reject").status_code == 200
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert [m["status"] for m in snap["merges"]] == ["rejected"]
    assert lines(repo)[1] == "two" and run(repo, "branch", "--list", "koloni/*") == ""
    assert len(worktrees(repo)) == 1 and (repo / "notes.txt").read_text() == "mine\n"


def test_asked_the_test_runs_on_the_users_click_and_the_merge_goes_in_on_their_yes(
    make_client, wait_run, repo
):
    client, cid, run_id = on_branch(
        make_client, repo, [step(edit("two", "TWO-agent")), text("A done")],
        project={"check_command": "python check.py TWO-agent"}, permission_mode="ask")
    merge = card(client, cid)
    assert merge["branch"] == {"name": "koloni/fix", "into": "main", "conflicts": [],
                               "dirty": [], "note": None}
    assert merge["check"]["state"] == "not_run" and lines(repo)[1] == "two"
    merge = client.post(f"/api/merges/{merge['id']}/check").json()
    merge = until(client, cid, lambda s: s["merges"][0]["check"]["state"] == "passed",
                  timeout=LONG)["merges"][0]
    assert merge["status"] == "pending" and not merge["check"]["stale"]
    assert "CWD=" in merge["check"]["output"] and "koloni" not in lines(repo)[1]
    assert client.post(f"/api/merges/{merge['id']}/approve").status_code == 200
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert [m["status"] for m in snap["merges"]] == ["applied"]
    assert lines(repo)[1] == "TWO-agent" and run(repo, "branch", "--list", "koloni/*") == ""


def test_on_branch_is_refused_with_why_where_the_project_has_no_git(
    make_client, wait_run, project_dir
):
    lead = [step(call("spawn_agent", {"role": "Coder", "task": "x", "on_branch": "fix"}, "s")),
            text("done")]
    client, _pid, cid, run_id = start(make_client, project_dir, [text("A done")], lead=lead)
    (tool,) = wait_run(client, cid, run_id, timeout=LONG)["tool_calls"]
    assert tool["status"] == "failed" and "not the top folder of a git" in tool["result"]


def test_a_team_that_runs_a_recipe_is_refused_a_branch_before_it_starts_saying_why(
    make_client, wait_run, repo
):
    # B-367 (live): the first recipe team's on_branch passed but no branch was made (its work went
    # to the recipe's copy), and the second was refused "a recipe or a job while the user is away".
    from tests.test_recipe_ends_scenarios import SCRIPTS, rows_of
    from tests.test_recipe_run_scenarios import manual
    lead = step(call("spawn_agent", {"role": "Web app lead", "task": "the page",
                                     "on_branch": "web"}, "l1"))
    client, _model = make_client({"Lead": [lead, text("done")], **SCRIPTS})
    cid, run_id = manual(client, repo, *rows_of(client, False))
    snap = wait_run(client, cid, run_id, timeout=LONG)
    (tool,) = snap["tool_calls"]
    assert tool["status"] == "failed" and "recipe's turn" in tool["result"], tool["result"]
    assert "away" not in tool["result"]
    assert not [a for a in snap["agents"] if a["depth"]]  # (nobody opened beside it either)
    assert run(repo, "branch", "--list", "koloni/*") == ""


WHY = "a two-line fix, the test already exists"


def test_on_branch_with_a_tier_opens_the_agent_and_its_card_says_the_openers_why(
    make_client, wait_run, repo
):
    # The on_branch check once rebound `why` to None: tier + on_branch was always "give why".
    lead = [step(call("spawn_agent", {"role": "Coder", "task": "x", "on_branch": "fix",
                                      "tier": "balanced", "why": WHY}, "s")), text("done")]
    client, _pid, cid, run_id = start(make_client, repo, [text("A done")], lead=lead)
    snap = wait_run(client, cid, run_id, timeout=LONG)
    (tool,) = snap["tool_calls"]
    assert tool["status"] == "succeeded", tool["result"]
    assert snap["agents"][1]["chosen_why"] == WHY  # (no tier models here: `tier` stays None)


@pytest.mark.parametrize("more", [{}, {"folder": "."}])
def test_a_refused_branch_with_a_tier_and_why_is_still_refused(
    make_client, wait_run, repo, project_dir, more
):
    # No git there, or a folder beside on_branch: refused with the branch's own words, not "why".
    where = repo if more else project_dir.parent / "plain"
    where.mkdir(exist_ok=True)
    lead = [step(call("spawn_agent", {"role": "Coder", "task": "x", "on_branch": "fix",
                                      "tier": "balanced", "why": WHY, **more}, "s")), text("done")]
    client, _pid, cid, run_id = start(make_client, where, [text("A done")], lead=lead)
    snap = wait_run(client, cid, run_id, timeout=LONG)
    (tool,) = snap["tool_calls"]
    said = "not both" if more else "not the top folder of a git"
    assert tool["status"] == "failed" and said in tool["result"], tool["result"]
    assert len(snap["agents"]) == 1


def test_nothing_is_committed_onto_another_branch_an_agent_switched_its_worktree_to(
    repo, runtime
):
    run(repo, "branch", "feature")
    copy = copies.make_branch(repo, runtime, "agent1", "x")
    run(copy.root, "switch", "-q", "feature")
    (copy.root / "a.txt").write_text("agent's\n")
    with pytest.raises(git.Refused, match="no longer on koloni/x"):
        git.commit_branch(copy.root, "koloni/x", ["a.txt"], "m", runtime / "no-hooks")
    assert run(repo, "log", "-1", "--format=%s", "feature") == "as it was"


def test_at_full_auto_a_root_lockfile_on_the_branch_waits_for_the_users_word(
    make_client, wait_run, repo
):
    client, cid, run_id = on_branch(
        make_client, repo, [step(write("uv.lock", "x\n")), step(edit("two", "TWO-agent", "e2")),
                            text("A done")])
    merge = card(client, cid)
    head = run(repo, "rev-parse", "HEAD")
    assert "a lockfile at the project root" in of(merge, "uv.lock")["note"]
    assert lines(repo)[1] == "two" and not (repo / "uv.lock").exists()
    assert client.post(f"/api/merges/{merge['id']}/approve").status_code == 200
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert [m["status"] for m in snap["merges"]] == ["applied"]
    assert run(repo, "rev-parse", "HEAD~1") == head and (repo / "uv.lock").exists()


def test_a_file_holding_a_secret_given_this_turn_is_not_committed_and_says_why(repo, runtime):
    from app.agent import SECRET_IN_COPY, _branch_files, _secret_in

    copy = copies.make_branch(repo, runtime, "agent1", "x")
    copy.secrets = lambda: ["s3cr3t-value"]
    (copy.root / "a.txt").write_text("token = s3cr3t-value\n")
    (copy.root / "b.txt").write_text("plain\n")
    assert _secret_in(copy, "a.txt") and not _secret_in(copy, "b.txt")
    git.commit_branch(copy.root, copy.branch, ["b.txt"], "m", runtime / "no-hooks")
    files = _branch_files(copy, git.branch_look(repo, copy.branch), "full_auto",
                          {"a.txt": SECRET_IN_COPY})
    assert files["a.txt"]["state"] == "refused" and files["a.txt"]["note"] == SECRET_IN_COPY
    assert files["b.txt"]["state"] == "ready" and files["b.txt"]["note"] is None


# --- the backlog: a task started while another works goes on a branch ------------------------


def beside(make_client, folder, gate):
    """A backlog task "first" at work (held at its model's first step), and "Second task" started
    beside it, whose Lead opens a Coder that writes b.txt - approved. The client, the project's
    id, the first task's id and the second's conversation."""
    client, _model = make_client({
        "Lead": [gate.step(text("first done")),
                 step(call("spawn_agent", {"role": "Coder", "task": "write b"}, "s")),
                 text("second done")],
        "Coder": [step(write("b.txt", "b\n")), text("b written")]})
    pid, (first,) = setup(client, folder, "first")
    assert client.post(f"/api/projects/{pid}/backlog/next").json()["task_id"] == first
    gate.wait_partial()  # (the first is at work, in the project)
    second = client.post(f"/api/projects/{pid}/backlog", json={"title": "Second task"}).json()
    assert client.post(f"/api/projects/{pid}/backlog/next").json()["task_id"] == second["id"]
    cid = tasks(client, pid)["Second task"]["conversation_id"]
    coder = until(client, cid, lambda s: any(a["status"] == "proposed" for a in s["agents"]),
                  timeout=LONG)["agents"][-1]
    assert client.post(f"/api/agents/{coder['id']}/approve").status_code == 200
    return client, pid, first, cid


def flow(client, task_id):
    with client.app.state.session_factory() as session:
        return session.get_one(BacklogTask, task_id).flow or {}


def second(client, pid):
    """The branch of "Second task": its title's and 4 of its id's (R165)."""
    return "koloni/second-task-" + tasks(client, pid)["Second task"]["id"][:4]


def test_a_backlog_task_started_while_another_works_goes_on_its_own_branch(
    make_client, wait_run, repo, gate
):
    client, pid, first, cid = beside(make_client, repo, gate)
    merge = card(client, cid)  # (at Ask: the merge waits for the user's word)
    assert tasks(client, pid)["Second task"]["waiting"]  # ("waiting for you" on the page)
    assert merge["branch"]["name"] == second(client, pid)
    assert [f["path"] for f in merge["files"]] == ["b.txt"] and not (repo / "b.txt").exists()
    assert client.post(f"/api/merges/{merge['id']}/approve").status_code == 200
    worked(client, wait_run, pid, "Second task")
    assert (repo / "b.txt").read_text() == "b\n"
    assert run(repo, "log", "-1", "--format=%s") == f"Merge {second(client, pid)}: Second task"
    assert run(repo, "branch", "--list", "koloni/*") == "" and len(worktrees(repo)) == 1
    gate.release()
    worked(client, wait_run, pid, "first")
    assert flow(client, first).get("branch") is None  # (alone when it started: in the project)


def test_stopped_while_its_merge_waits_the_turn_ends_and_the_branch_keeps_the_work(
    make_client, wait_run, repo, gate
):
    client, pid, _first, cid = beside(make_client, repo, gate)
    merge = card(client, cid)
    assert client.post(f"/api/runs/{merge['run_id']}/cancel").status_code in (200, 202)
    snap = wait_run(client, cid, merge["run_id"], timeout=LONG)
    assert [m["status"] for m in snap["merges"]] == ["discarded"]
    assert not (repo / "b.txt").exists() and len(worktrees(repo)) == 1
    # (KOLONİ's commit is on it: an unmerged branch is never deleted but on Discard)
    assert run(repo, "branch", "--list", "koloni/*") == second(client, pid)
    gate.release()


def test_where_the_project_has_no_git_the_task_beside_works_as_today(
    make_client, wait_run, project_dir, gate
):
    client, pid, _first, cid = beside(make_client, project_dir, gate)
    merge = card(client, cid)
    assert merge["branch"] is None and not (project_dir / "b.txt").exists()
    assert client.post(f"/api/merges/{merge['id']}/approve").status_code == 200
    worked(client, wait_run, pid, "Second task")
    assert (project_dir / "b.txt").read_text() == "b\n"
    gate.release()


def test_tasks_started_together_each_go_on_a_branch(make_client, repo, gate):
    client, _model = make_client([gate.step(text("a")), gate.step(text("b"))])
    pid, (one, two) = setup(client, repo, "one", "two")
    client.post(f"/api/projects/{pid}/backlog/next")
    assert flow(client, one).get("branch") and flow(client, two).get("branch")
    gate.release()


def test_two_tasks_of_one_title_get_two_branch_names():
    # R165: two backlog tasks of one long title both got `koloni/in-server-py-make-every-json-
    # error-respo`; 4 of each one's id tell them apart, and add_worktree's own cut keeps them.
    title = "In server.py make every JSON error response say what went wrong"
    one, two = git.task_branch(title, "a1b2c3d4"), git.task_branch(title, "e5f6a7b8")
    assert one == "in-server-py-make-every-json-error-a1b2" and two.endswith("-e5f6")
    assert one != two and git.branch_name(one) == one and git.branch_name(two) == two
    assert git.task_branch("!!!", "c0ffee00") == "task-c0ff"


# --- the security review's findings ------------------------------------------------------------


def test_a_file_of_the_users_git_ignores_is_never_merged_over(repo, runtime):
    """Finding 1: the agent un-ignores the user's local.cfg and writes it; or commits `.env`
    with `add -f` itself. Either is in the way, and git's merge is not run."""
    (repo / ".gitignore").write_text(".venv/\n.env\nlocal.cfg\n")
    run(repo, "commit", "-qam", "ignore more")
    (repo / "local.cfg").write_text("the user's\n")
    (repo / ".env").write_text("REAL=1\n")
    copy = copies.make_branch(repo, runtime, "agent1", "x")
    (copy.root / ".gitignore").write_text(".venv/\n.env\n")
    (copy.root / "local.cfg").write_text("agent's\n")
    (copy.root / ".env").write_text("FAKE=1\n")
    git.commit_branch(copy.root, copy.branch, [".gitignore", "local.cfg"], "m",
                      runtime / "no-hooks")
    run(copy.root, "add", "-f", ".env")
    run(copy.root, "commit", "-qm", "the agent's own")
    look = git.branch_look(repo, copy.branch)
    assert look["dirty"] == [".env", "local.cfg"]
    assert (repo / "local.cfg").read_text() == "the user's\n"
    assert (repo / ".env").read_text() == "REAL=1\n"


def test_a_new_file_where_the_project_has_its_own_is_not_committed(
    make_client, wait_run, repo
):
    """Finding 1b: a new file the project has, which git ignores there, is not taken."""
    (repo / ".gitignore").write_text(".venv/\nlocal.cfg\n")
    (repo / "local.cfg").write_text("the user's\n")
    client, cid, run_id = on_branch(
        make_client, repo, [step(write("local.cfg", "agent's\n")),
                            step(edit("two", "TWO-agent", "e2")), text("A done")],
        project={"check_command": "python check.py TWO-agent"})
    snap = wait_run(client, cid, run_id, timeout=LONG)
    (merge,) = snap["merges"]
    assert merge["status"] == "applied" and of(merge, "local.cfg")["state"] == "refused"
    assert "the project has its own file there" in of(merge, "local.cfg")["note"]
    assert (repo / "local.cfg").read_text() == "the user's\n" and lines(repo)[1] == "TWO-agent"


def test_the_merge_waits_where_the_project_moved_off_what_the_branch_was_made_from(
    repo, runtime
):
    """Finding 3: switched to another branch, or the start reset away: said, for the user."""
    run(repo, "branch", "release")
    (repo / "a.txt").write_text("second\n")
    run(repo, "commit", "-qam", "second")
    copy = copies.make_branch(repo, runtime, "agent1", "x")
    assert copy.start == ("main", run(repo, "rev-parse", "HEAD"))
    assert git.branch_look(repo, copy.branch, copy.start)["drift"] is None
    run(repo, "switch", "-q", "release")
    assert git.branch_look(repo, copy.branch, copy.start)["drift"] == (
        "made from main, the project is on release now")
    run(repo, "switch", "-q", "main")
    run(repo, "commit", "-q", "--amend", "-m", "rewritten")  # (the start is gone from main)
    assert "no longer holds the commit" in git.branch_look(repo, copy.branch, copy.start)["drift"]


def test_no_hook_runs_when_the_branch_goes(repo, runtime):
    """Finding 5."""
    copy = copies.make_branch(repo, runtime, "agent1", "x")
    hook = repo / ".git" / "hooks" / "reference-transaction"
    marker = runtime / "hook-ran"
    hook.write_text(f"#!/bin/sh\necho ran >> '{marker.as_posix()}'\n")
    os.chmod(hook, 0o755)
    copies.remove(runtime, copy.name)
    git.drop_branch(repo, copy.root, copy.branch, runtime / "no-hooks")
    assert not marker.exists() and run(repo, "branch", "--list", "koloni/*") == ""


def test_a_secret_is_found_in_a_file_that_is_not_utf8(repo, runtime):
    """Finding 6."""
    from app.agent import _secret_in

    copy = copies.make_branch(repo, runtime, "agent1", "x")
    copy.secrets = lambda: ["s3cr3t-value"]
    (copy.root / "latin.txt").write_bytes(b"caf\xe9 s3cr3t-value\n")
    (copy.root / "wide.txt").write_bytes("token s3cr3t-value".encode("utf-16-le"))
    assert _secret_in(copy, "latin.txt") and _secret_in(copy, "wide.txt")


@pytest.mark.parametrize("command", [
    "git stash pop", "git stash apply stash@{0}", "git stash drop", "git update-ref refs/heads/main HEAD~1",
    "git symbolic-ref HEAD refs/heads/main", "git branch -f main HEAD", "git branch -D feature",
    "git branch -m main old", "git reflog expire --expire=now --all", "git gc --prune=now",
    "git prune", "git worktree remove ../x", "git config core.hooksPath x", "git remote add o u",
    "git push origin main", "git checkout main", "git switch feature", "git reset --hard main",
    "cd x && git -C . update-ref refs/heads/main HEAD",
])
def test_what_reaches_the_users_shared_git_from_a_worktree_is_asked(command):
    """Finding 2: in a branch's worktree."""
    from app.commands import SHARED_GIT, reaches_shared_git

    assert reaches_shared_git(command) == SHARED_GIT


@pytest.mark.parametrize("command", [
    "git status", "git add -A", "git commit -m x", "git stash show", "git diff --stat",
    "git stash list", "git diff HEAD", "git log", "git branch", "git branch --show-current",
    "git log --oneline -5", "git checkout -- a.txt", "git show HEAD", "git rm -q a", "git mv a b",
    "git restore a.txt", "git show HEAD --stat", "git rev-parse HEAD", "git ls-files",
    "git grep foo", "git blame a", "git merge-base HEAD x", "git cat-file -p HEAD", "git tag",
    "git commit --amend -m y", "cd src && git status", "git --no-pager log", "npm test",
    "python -m pytest",
])
def test_the_worktrees_own_git_is_not_asked(command):
    from app.commands import reaches_shared_git

    assert reaches_shared_git(command) == ""


def test_at_full_auto_a_stash_pop_in_a_branchs_worktree_waits_for_the_user(
    make_client, repo
):
    """Finding 2, agent level: the user's stash is theirs - not taken from the worktree unasked."""
    from tests.test_agent_writes import wait_status
    from tests.test_full_auto_harm import why_asked

    (repo / "a.txt").write_text("one\nmine, stashed\n")
    run(repo, "stash", "-q")
    client, cid, _run_id = on_branch(
        make_client, repo, [step(call("run_command", {"command": "git stash pop"}, "c")),
                            text("A done")])
    snap = wait_status(client, cid, "waiting_approval")
    (asked,) = snap["commands"]
    assert asked["status"] == "proposed"
    assert why_asked(snap, asked) == SHARED_GIT
    assert run(repo, "stash", "list") != ""  # (still the user's)


def test_a_secret_the_agent_committed_itself_is_never_merged_not_even_on_a_click(
    make_client, repo, monkeypatch
):
    """Finding 4."""
    from app.agent import AgentRunner

    monkeypatch.setattr(AgentRunner, "given_spellings", lambda self, run_id: ["s3cr3t-value"])
    client, cid, _run_id = on_branch(make_client, repo, [
        step(write("token.txt", "s3cr3t-value\n")),
        step(call("run_command", {"command": "git add token.txt && git commit -q -m mine"}, "c")),
        text("A done")])
    merge = card(client, cid)
    assert "holds a secret given this turn" in merge["branch"]["note"]
    assert client.post(f"/api/merges/{merge['id']}/approve").status_code == 200
    merge = card(client, cid)  # (still asked: nothing merged)
    assert not (repo / "token.txt").exists()


@pytest.mark.parametrize("how", ["stop", "restart"])
def test_stop_while_a_card_waits_on_a_secret_deletes_the_branch_and_says_so(
    make_client, wait_run, repo, monkeypatch, how
):
    """Fact-check (6 Nov): Stop, or a restart, with the card blocked by a secret left the branch
    - `git branch -d` keeps an unmerged one - though no branch holding such a secret is kept."""
    from app.agent import AgentRunner

    monkeypatch.setattr(AgentRunner, "given_spellings", lambda self, run_id: ["s3cr3t-value"])
    client, cid, run_id = on_branch(make_client, repo, [
        step(write("token.txt", "s3cr3t-value\n")),
        step(call("run_command", {"command": "git add token.txt && git commit -q -m mine"}, "c")),
        text("A done")])
    assert "holds a secret given this turn" in card(client, cid)["branch"]["note"]
    if how == "stop":
        assert client.post(f"/api/runs/{run_id}/cancel").status_code == 202
        snap = wait_run(client, cid, run_id, timeout=LONG)
    else:
        client.__exit__(None, None, None)  # (the app closes: `shutdown`)
        client, _model = make_client({})
        snap = client.get(f"/api/conversations/{cid}").json()
    assert run(repo, "branch", "--list", "koloni/*") == "" and len(worktrees(repo)) == 1
    assert any("its branch koloni/fix was deleted" in m["content"]
               for m in snap["messages"] if m["role"] == "koloni")
    assert not (repo / "token.txt").exists()


def test_stop_while_the_check_of_a_card_blocked_by_a_secret_runs_deletes_the_branch(
    make_client, wait_run, repo, monkeypatch, tmp_path
):
    """Review M1: Stop in any wait of a branch's way in - here the check the user's click
    runs - drops a branch holding a secret given this turn, not only Stop at the card."""
    from app.agent import AgentRunner

    monkeypatch.setattr(AgentRunner, "given_spellings", lambda self, run_id: ["s3cr3t-value"])
    runs = (tmp_path / "runs").as_posix()  # (the first run, before the card, at once)
    client, cid, run_id = on_branch(make_client, repo, [
        step(write("token.txt", "s3cr3t-value\n")),
        step(call("run_command", {"command": "git add token.txt && git commit -q -m mine"}, "c")),
        text("A done")], project={"check_command": (
            f"python -c \"import pathlib,time;p=pathlib.Path('{runs}');"
            "n=p.exists();p.write_text('x');time.sleep(60*n)\"")})
    merge = card(client, cid)
    assert "holds a secret given this turn" in merge["branch"]["note"]
    assert client.post(f"/api/merges/{merge['id']}/check").status_code == 200
    until(client, cid, lambda s: "running" in [c["status"] for c in s["commands"]],
          timeout=LONG)
    assert client.post(f"/api/runs/{run_id}/cancel").status_code == 202
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert run(repo, "branch", "--list", "koloni/*") == "" and len(worktrees(repo)) == 1
    assert any("its branch koloni/fix was deleted" in m["content"]
               for m in snap["messages"] if m["role"] == "koloni")


def test_stop_while_a_card_waits_with_no_secret_keeps_the_branch(make_client, wait_run, repo):
    client, cid, run_id = on_branch(
        make_client, repo, [step(edit("two", "TWO-agent")), text("A done")],
        permission_mode="ask")
    card(client, cid)
    assert client.post(f"/api/runs/{run_id}/cancel").status_code == 202
    wait_run(client, cid, run_id, timeout=LONG)
    assert run(repo, "branch", "--list", "koloni/*").strip() == "koloni/fix"
    assert run(repo, "show", "koloni/fix:lines.txt").split("\n")[1] == "TWO-agent"
    assert lines(repo)[1] == "two"


# --- the re-review's round: a squash, and what else git would write over -------------------------


def committed(copy, *paths, message="agent's own"):
    """What an agent commits itself in its worktree, past KOLONİ's file list."""
    run(copy.root, "add", "-f", "--", *paths)
    run(copy.root, "commit", "-qm", message)


def test_an_ignored_file_where_the_branch_needs_a_folder_is_in_the_way(repo, runtime):
    (repo / ".gitignore").write_text(".venv/\nbuild\ncache/\n")
    run(repo, "commit", "-qam", "ignore")
    (repo / "build").write_text("the user's build file\n")
    (repo / "cache").mkdir()
    (repo / "cache" / "big.bin").write_text("the user's\n")
    copy = copies.make_branch(repo, runtime, "agent1", "x")
    (copy.root / "build").mkdir()
    (copy.root / "build" / "out.txt").write_text("x\n")
    (copy.root / "cache").write_text("a file now\n")
    committed(copy, "build/out.txt", "cache")
    assert git.branch_look(repo, copy.branch)["dirty"] == ["build/out.txt", "cache"]
    with pytest.raises(git.Refused, match="would be written over"):
        git.merge_branch(repo, tip(repo, copy), "m", runtime / "no-hooks", "main")
    assert (repo / "build").read_text() == "the user's build file\n"
    assert (repo / "cache" / "big.bin").read_text() == "the user's\n"


def test_the_merge_is_one_commit_and_the_agents_own_history_stays_out(repo, runtime):
    copy = copies.make_branch(repo, runtime, "agent1", "x")
    (copy.root / "t.txt").write_text("S3CR3T-TOKEN\n")
    committed(copy, "t.txt")
    run(copy.root, "rm", "-q", "t.txt")
    run(copy.root, "commit", "-qm", "taken out")
    (copy.root / "ok.txt").write_text("ok\n")
    git.commit_branch(copy.root, copy.branch, ["ok.txt"], "m", runtime / "no-hooks")
    assert git.holding(repo, tip(repo, copy), ["ok.txt"], [b"S3CR3T-TOKEN"]) == []
    git.merge_branch(repo, tip(repo, copy), "x: done", runtime / "no-hooks", "main", copy.start[1])
    assert (repo / "ok.txt").read_text() == "ok\n" and not (repo / "t.txt").exists()
    assert "S3CR3T" not in run(repo, "log", "-p", "main")
    assert run(repo, "log", "-1", "--format=%ae|%s") == "koloni@localhost|x: done"


def test_a_secret_on_the_branch_is_found_however_it_got_there(repo, runtime):
    copy = copies.make_branch(repo, runtime, "agent1", "x")
    (copy.root / "s.txt").write_text("S3CR3T-TOKEN\n")
    committed(copy, "s.txt")
    run(copy.root, "mv", "s.txt", "notes.md")
    run(copy.root, "commit", "-qm", "renamed")
    (copy.root / "wide.txt").write_bytes("S3CR3T-TOKEN".encode("utf-16-le"))
    committed(copy, "wide.txt")
    files = list(git.branch_look(repo, copy.branch)["files"])
    assert git.holding(repo, tip(repo, copy), files, [b"S3CR3T-TOKEN", "S3CR3T-TOKEN".encode(
        "utf-16-le")]) == ["notes.md", "wide.txt"]


def test_the_merge_looks_again_right_before_it_writes(repo, runtime):
    run(repo, "branch", "release")
    copy = copies.make_branch(repo, runtime, "agent1", "x")
    (copy.root / ".env").write_text("FAKE\n")
    committed(copy, ".env")
    assert git.branch_look(repo, copy.branch, copy.start)["dirty"] == []
    (repo / ".env").write_text("REAL, made since the look\n")
    with pytest.raises(git.Refused, match=r"\.env would be written over"):
        git.merge_branch(repo, tip(repo, copy), "m", runtime / "no-hooks", "main", copy.start[1])
    (repo / ".env").unlink()
    run(repo, "switch", "-q", "release")
    with pytest.raises(git.Refused, match="on release now, not main"):
        git.merge_branch(repo, tip(repo, copy), "m", runtime / "no-hooks", "main")
    run(repo, "switch", "-q", "main")
    run(repo, "commit", "-q", "--allow-empty", "-m", "more")
    run(repo, "reset", "-q", "--hard", "HEAD~1")
    (repo / "a.txt").write_text("other\n")
    run(repo, "commit", "-q", "--amend", "-am", "rewritten")
    with pytest.raises(git.Refused, match="no longer holds the commit"):
        git.merge_branch(repo, tip(repo, copy), "m", runtime / "no-hooks", "main", copy.start[1])
    assert not (repo / ".env").exists()


def test_a_link_a_submodule_or_gits_own_files_on_the_branch_are_said_and_a_link_comes_as_a_file(
    repo, runtime
):
    copy = copies.make_branch(repo, runtime, "agent1", "x")
    blob = subprocess.run(["git", "hash-object", "-w", "--stdin"], cwd=copy.root, input="../../out",
                          capture_output=True, text=True).stdout.strip()
    run(copy.root, "update-index", "--add", "--cacheinfo", f"120000,{blob},lnk")
    run(copy.root, "commit", "-qm", "a link")
    (copy.root / ".gitignore").write_text(".venv/\n!.env\n")
    committed(copy, ".gitignore")
    assert git.branch_look(repo, copy.branch)["special"] == [".gitignore", "lnk"]
    run(repo, "config", "core.symlinks", "true")
    git.merge_branch(repo, tip(repo, copy), "m", runtime / "no-hooks", "main")  # (the user's click)
    assert not (repo / "lnk").is_symlink() and (repo / "lnk").read_text() == "../../out"


def test_at_full_auto_a_branch_that_changes_gitignore_waits_for_the_user(
    make_client, repo
):
    client, cid, _run_id = on_branch(make_client, repo, [
        step(write(".gitignore", ".venv/\n!.env\n")), text("A done")])
    merge = card(client, cid)
    assert "changes how git reads the project" in merge["branch"]["note"]
    assert (repo / ".gitignore").read_text() == ".venv/\n"


@pytest.mark.parametrize("command", [
    "GIT_DIR=../x git update-ref refs/heads/main HEAD", "env git stash pop", "command git stash pop",
    "cmd /c git stash pop", 'bash -c "git stash drop"', 'powershell -Command "git stash drop"',
    "git -c alias.x=stash x pop", "git fetch . +HEAD:refs/heads/feature",
    "git fetch --update-head-ok . HEAD", "git fetch -u origin", "git notes add -m x",
    "git send-pack ../x main", "git fast-import", "git maintenance run", "git repack -ad",
])
def test_through_a_wrapper_a_fetch_into_a_ref_or_an_alias_the_shared_git_is_still_asked(command):
    from app.commands import reaches_shared_git

    assert reaches_shared_git(command) == SHARED_GIT


def test_what_an_agent_committed_and_took_back_is_not_what_is_merged(
    make_client, wait_run, repo
):
    """The branch's tip is the worktree as the agents left it: a file an agent committed itself,
    then put back, comes in as it is now - its secret neither merged nor in the history."""
    client, cid, run_id = on_branch(make_client, repo, [
        step(edit("two", "token=S3CR3T-TOKEN")),
        step(call("run_command", {"command": "git commit -q -a -m mine"}, "c")),
        step(edit("token=S3CR3T-TOKEN", "two", "e2")), step(write("b.txt", "b", "w2")),
        text("A done")])
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert [m["status"] for m in snap["merges"]] == ["applied"]
    assert lines(repo)[1] == "two" and (repo / "b.txt").exists()
    assert "S3CR3T" not in run(repo, "log", "-p", "main")
    assert run(repo, "branch", "--list", "koloni/*") == ""  # (a squash's branch goes all the same)


# --- the third review's round: an allow-list, and the squash held to what was looked at -------


@pytest.mark.parametrize("command", [
    # what the reviewer's probes ran (r3/cmds.py, cmds2.py): each asked
    "git -c core.hooksPath=x commit -m y", "git -c core.fsmonitor=evil.sh status",
    "git -C ../.. stash pop", "git -C ../.. checkout -- .",
    r"git --work-tree=C:\Users\x\proj checkout .", r"git --work-tree C:\Users\x\proj checkout .",
    "git restore --source=main -- ../../proj", "git worktree add C:/x y", "git clean -fdx",
    r"& 'C:\Program Files\Git\cmd\git.exe' stash pop", r"C:\PROGRA~1\Git\cmd\git.exe stash pop",
    "git stash apply", "git stash -q pop", "git stash --quiet drop", "git stash store abc",
    "git stash create", "git stash branch x", "git stash push --all",
    "git -c Alias.x=stash x pop", "git --config-env=alias.x=FOO x pop",
    "git --config-env alias.x=FOO x drop", "git --git-dir=../../.git log",
    "git checkout -B main", "git switch -C main", "git checkout -b koloni/x main",
    "git branch -M main", "git branch new", "git tag v1", "git tag -d v1",
    "git update-index --assume-unchanged a", "git read-tree main", "git commit-tree x",
    "git hash-object -w x", "git rebase --update-refs main", "git pull", "git pull . main:main",
    "git pull --no-rebase . +main:feature", "git fetch origin main:main", "git am",
    "git apply --index x.patch", "git cherry-pick main", "git merge main", "git gc --prune=now",
    "git submodule foreach git stash pop", "git bisect start", "git --exec-path=. stash",
    "git --namespace=x branch -D main", 'pwsh -c "git stash pop"',
    "powershell -Command git stash pop", "Start-Process git -ArgumentList 'stash','pop'",
    "iex 'git stash pop'", "git `stash pop", "g`it stash pop", "git sta''sh pop",
    "(git) stash pop", "$g='git'; & $g stash pop", "set GIT_DIR=../../.git && git log",
    "git checkout main", "git checkout -", "git checkout @{-1}", "git switch -",
    "git checkout HEAD~1", "git reset --hard HEAD@{1}", "git reset --soft main",
    "$env:FOO='stash'; git --config-env=alias.x=FOO x drop",
    "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=alias.x GIT_CONFIG_VALUE_0=stash git x drop",
    "$env:GIT_CONFIG_COUNT=1; $env:GIT_CONFIG_KEY_0='alias.x'; git x drop",
    "export GIT_CONFIG_PARAMETERS=\"'alias.x=stash'\"; git x drop",
    "git -C ../../ml-deneme stash -u", "git --work-tree=../../ml-deneme stash",
    "git grep -O'sh -c x' foo", "git myalias",
])
def test_in_a_worktree_git_beyond_the_agents_own_work_is_asked(command):
    from app.commands import reaches_shared_git

    assert reaches_shared_git(command) == SHARED_GIT


def test_gits_own_files_are_found_in_any_case_and_lfs_too(repo, runtime):
    copy = copies.make_branch(repo, runtime, "agent1", "x")
    (copy.root / "sub").mkdir()
    (copy.root / "sub" / ".GitIgnore").write_text("*.txt\n")
    (copy.root / ".GITATTRIBUTES").write_text("* -text\n")
    (copy.root / ".lfsconfig").write_text("[lfs]\n")
    committed(copy, "sub/.GitIgnore", ".GITATTRIBUTES", ".lfsconfig")
    assert git.branch_look(repo, copy.branch)["special"] == [
        ".GITATTRIBUTES", ".lfsconfig", "sub/.GitIgnore"]


def test_a_half_done_squash_in_the_tree_is_said_and_undone_by_the_user(repo, runtime):
    copy = copies.make_branch(repo, runtime, "agent1", "x")
    (copy.root / "a.txt").write_text("one\nAGENT\n")
    committed(copy, "a.txt")
    look = git.branch_look(repo, copy.branch, copy.start)
    (repo / "a.txt").write_text("one\nUSER\n")  # (a conflict made after the look)
    run(repo, "commit", "-qam", "user")
    with pytest.raises(git.Refused, match="git reset --merge` undoes it"):
        git.merge_branch(repo, look["tip"], "m", runtime / "no-hooks", "main")
    assert "a half-done squash" in git.branch_look(repo, copy.branch)["half"]
    run(repo, "reset", "--merge")
    assert git.branch_look(repo, copy.branch)["half"] is None


def test_what_is_merged_is_the_commit_that_was_looked_at(repo, runtime):
    copy = copies.make_branch(repo, runtime, "agent1", "x")
    (copy.root / "b.txt").write_text("looked at\n")
    committed(copy, "b.txt")
    look = git.branch_look(repo, copy.branch, copy.start)
    (copy.root / "c.txt").write_text("made since\n")
    committed(copy, "c.txt")
    git.merge_branch(repo, look["tip"], "m", runtime / "no-hooks", "main", copy.start[1])
    assert (repo / "b.txt").exists() and not (repo / "c.txt").exists()


def test_a_file_that_cannot_be_read_counts_as_holding_a_secret(repo, runtime):
    copy = copies.make_branch(repo, runtime, "agent1", "x")
    (copy.root / "b.txt").write_text("plain\n")
    committed(copy, "b.txt")
    at = tip(repo, copy)
    assert git.holding(repo, at, ["b.txt"], [b"S3CR3T"]) == []
    assert git.holding(repo, at, ["gone.txt"], [b"S3CR3T"]) == ["gone.txt"]


def test_a_secret_given_this_turn_goes_into_no_commit_message(make_client, wait_run, repo,
                                                              monkeypatch):
    from app.agent import AgentRunner

    monkeypatch.setattr(AgentRunner, "given_spellings", lambda self, run_id: ["two"])
    client, cid, run_id = on_branch(
        make_client, repo, [step(edit("two", "TWO-agent")), text("A done")],
        project={"check_command": "python check.py TWO-agent"})
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert [m["status"] for m in snap["merges"]] == ["applied"]
    assert run(repo, "log", "-1", "--format=%s") == "Merge koloni/fix: fix ***"


# --- the final review: each option exactly as listed ---------------------------------------------


R4_ASKED = [
    # stuck values, bundled short options, unique prefixes of long ones (r4/c1..c7)
    "git checkout -Bdevelop koloni/x", "git switch -Cdevelop koloni/x",
    "git checkout --force-c=develop koloni/x", "git switch --force-cr=develop koloni/x",
    "git checkout -bnew koloni/x", "git switch --ignore-other-worktrees koloni/other",
    "git checkout --det koloni/x", "git checkout koloni/x~1", "git commit --fixup HEAD",
    "git checkout -- ../../a.txt", "git checkout C:/proj/user/a.txt",
    "git restore --worktree --source HEAD -- ../../a.txt", "git add ../../a.txt",
    "git add C:/Users/x/a.txt", "git rm --cached ../../a.txt", "git mv a.txt ../../b.txt",
    "git stash push", "git stash", "git stash push -u", "git stash push --include-untracked",
    "git stash push -m x", "git stash push --al", "git stash --al", "git stash push -ua",
    "git stash push --a",
    "git log --output=C:/Users/Murat/.gitconfig", "git log -1 --format=x --output=../x",
    "git diff --output=C:/x", "git show --output=../x", "git log -o x",
    "git log --output ../../../proj/a.txt -1", "git log -1 --format=%H --output=../p",
    "git cat-file --filters HEAD:a.txt", "git cat-file --textconv HEAD:a.txt",
    "git grep --open-files-in-pager=notepad x", "git grep --open-files-in=notepad x",
    "git grep --open x", "git grep -Onotepad x", 'git grep "--open=rm -rf ~; true" one',
    'git grep --op="rm -rf ~;" one', 'git grep -O"rm -rf ~;" one',
    "git diff --ext-diff", "git diff --textconv", "git log -p --ext-diff",
    "git blame --contents ../../a.txt a.txt", "git describe --dirty",
    "git stash show -p --ext-diff", "git commit -F ../../secret.txt", "git show --ext-diff HEAD",
    "git log --no-pager", "git --paginate log", "git -p log", "git --exec-path",
    "git rev-parse --git-common-dir", "git restore -s main a.txt",
    "git restore --source=HEAD@{1} a.txt", "git restore --sourc=main a.txt",
    "git restore --sour main a.txt", "git checkout main -- a.txt", "git checkout main .",
    "git commit --template=../../x", "git tag -l --contains HEAD", "git branch --edit-description",
    "git branch --no-color -lv", "git tag -n9 -l", "git stash list -p --ext-diff",
    "git log --exec=x", "git diff --no-index ../../a C:/x",
    "git checkout --ignore-other-worktrees -Bmain koloni/x",
    "git switch --ignore-other-worktrees -Cmain koloni/x",
    "git checkout --ignore-other-worktrees koloni/x -Bmain", "git switch -qCdevelop koloni/other",
    "git switch koloni/other",
]


@pytest.mark.parametrize("command", R4_ASKED)
def test_an_option_not_written_exactly_as_listed_is_asked(command):
    from app.commands import reaches_shared_git

    assert reaches_shared_git(command, "koloni/x") == SHARED_GIT


@pytest.mark.parametrize("command", [
    "git status", "git status --porcelain", "git add -A", 'git commit -m "x"', "git diff --stat",
    "git log --oneline -5", "git log -n 3 --format=%H", "git show HEAD --stat", "git grep -n foo",
    "git grep -n -e foo -- src", "git rev-parse --show-toplevel", "git switch koloni/x",
    "git checkout -q koloni/x", "git checkout -- a.txt", "git commit --amend --no-edit",
    "git stash list", "git branch --show-current", "git ls-files --others --exclude-standard",
    "git blame -L 1,5 -- a.txt", "git cat-file -p HEAD:a.txt",
])
def test_ordinary_work_on_its_own_branch_runs_unasked(command):
    from app.commands import reaches_shared_git

    assert reaches_shared_git(command, "koloni/x") == ""


@pytest.mark.parametrize(("command", "asked"), [
    ('git commit -am "x"', False), ("git commit -qam x", False), ("git commit -aqm x", False),
    ("git commit -qm x", False), ("git commit -aq", False),
    ("git commit -amend", True), ("git commit -ma x", True), ("git commit -aC x", True),
    ("git commit -aam x", True), ("git add -Aq", True), ("git status -sb", True),
])
def test_commit_alone_takes_a_bundle_of_a_q_and_a_last_m(command, asked):
    from app.commands import reaches_shared_git

    assert bool(reaches_shared_git(command, "koloni/x")) is asked


# --- D2: an agent resolves the conflicts; Keep this branch; a pull request -----------------


def clash(repo, runtime):
    """A branch copy whose lines.txt clashes with what the user committed on main since."""
    (repo / "lines.txt").write_bytes(LINES.encode())
    run(repo, "add", "-A")
    run(repo, "commit", "-qm", "lines")
    copy = copies.make_branch(repo, runtime, "agent1", "fix")
    (copy.root / "lines.txt").write_bytes(LINES.replace("two", "TWO-agent").encode())
    assert git.commit_branch(copy.root, copy.branch, ["lines.txt"], "m", runtime / "no-hooks")
    (repo / "lines.txt").write_bytes(LINES.replace("two", "TWO-user").encode())
    run(repo, "commit", "-qam", "user")
    return copy


def test_the_users_branch_is_merged_into_the_worktree_and_a_resolution_with_marks_is_undone(
    repo, runtime
):
    copy = clash(repo, runtime)
    head = run(repo, "rev-parse", "HEAD")
    before, sha, left = git.merge_in(copy.root, copy.branch, "main", runtime / "no-hooks")
    assert left == ["lines.txt"] and sha == head and before == tip(repo, copy)
    assert "<<<<<<< " in (copy.root / "lines.txt").read_text()
    # The user's tree and branch are not touched, and nothing is under way there.
    assert run(repo, "rev-parse", "HEAD") == head and not (repo / ".git" / "MERGE_HEAD").exists()
    assert git.branch_look(repo, copy.branch)["half"] is None
    assert git.resolved(copy.root, copy.branch, before, sha, left) == "the merge was not committed"
    # An agent that adds the file with its marks and commits: not put together, undone.
    run(copy.root, "commit", "-qam", "as it is")
    assert "still holds git's conflict marks" in git.resolved(copy.root, copy.branch, before,
                                                             sha, left)
    git.undo_merge_in(copy.root, copy.branch, before, runtime / "no-hooks")
    assert tip(repo, copy) == before and "TWO-agent" in (copy.root / "lines.txt").read_text()
    # Put together: the branch holds the user's commit, and merges cleanly.
    git.merge_in(copy.root, copy.branch, "main", runtime / "no-hooks")
    (copy.root / "lines.txt").write_bytes(LINES.replace("two", "TWO-both").encode())
    run(copy.root, "commit", "-qam", "resolved")
    assert git.resolved(copy.root, copy.branch, before, sha, left) is None
    look = git.branch_look(repo, copy.branch)
    assert look["conflicts"] == [] and look["files"] == {"lines.txt": "M"}
    git.merge_branch(repo, tip(repo, copy), "m", runtime / "no-hooks", "main")
    assert lines(repo)[1] == "TWO-both"


def clashing(make_client, repo, resolve, **conversation):
    """A Coder on `koloni/fix` changes line two while the user commits their own line two; then,
    told to resolve, it takes the `resolve` steps."""
    held = Gate()
    client, cid, run_id = on_branch(
        make_client, repo,
        [step(edit("two", "TWO-agent")), held.step(text("A done")), *resolve], **conversation)
    held.wait_partial()
    (repo / "lines.txt").write_bytes(LINES.replace("two", "TWO-user").encode())
    (repo / "theirs.txt").write_bytes(b"the user's new file")  # (no file of the line's)
    run(repo, "add", "-A")
    run(repo, "commit", "-qm", "user")
    held.release()
    return client, cid, run_id


RESOLVED = LINES.replace("two", "TWO-both")
RESOLVING = [step(call("read_file", {"path": "lines.txt"}, "r")), step(write("lines.txt", RESOLVED)),
             text("put together")]


def test_asked_an_agent_resolves_the_conflicts_on_the_card_and_the_merge_takes_its_resolution(
    make_client, wait_run, repo
):
    client, cid, run_id = clashing(
        make_client, repo, RESOLVING,
        permission_mode="ask")
    merge = card(client, cid)
    assert merge["branch"]["conflicts"] == ["lines.txt"] and merge["branch"]["resolve"]
    assert client.post(f"/api/merges/{merge['id']}/resolve").status_code == 200
    merge = until(client, cid, lambda s: s["merges"][0]["branch"]["conflicts"] == []
                  and s["merges"][0]["status"] == "pending", timeout=LONG)["merges"][0]
    assert merge["branch"]["note"] is None and "resolve" not in merge["branch"]
    assert [(f["path"], f["state"]) for f in merge["files"]] == [("lines.txt", "ready")]
    assert lines(repo)[1] == "TWO-user"  # (nothing merged before the user's yes)
    assert client.post(f"/api/merges/{merge['id']}/approve").status_code == 200
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert [m["status"] for m in snap["merges"]] == ["applied"]
    assert lines(repo)[1] == "TWO-both" and run(repo, "branch", "--list", "koloni/*") == ""
    assert " " not in run(repo, "log", "-1", "--format=%P")  # (still one commit: a squash)


def test_a_resolution_that_leaves_the_marks_is_undone_and_the_card_stays(
    make_client, wait_run, repo
):
    client, cid, run_id = clashing(make_client, repo, [text("I could not")],
                                   permission_mode="ask")
    merge = card(client, cid)
    sha = run(repo, "rev-parse", "koloni/fix")
    assert client.post(f"/api/merges/{merge['id']}/resolve").status_code == 200
    merge = until(client, cid, lambda s: (s["merges"][0]["branch"]["note"] or "").startswith(
        "Coder"), timeout=LONG)["merges"][0]
    assert "could not put the conflicts together" in merge["branch"]["note"]
    assert merge["status"] == "pending" and merge["branch"]["conflicts"] == ["lines.txt"]
    assert run(repo, "rev-parse", "koloni/fix") == sha  # (back where it was)
    assert client.post(f"/api/merges/{merge['id']}/reject").status_code == 200
    wait_run(client, cid, run_id, timeout=LONG)
    assert lines(repo)[1] == "TWO-user"


def test_at_full_auto_an_agent_resolves_the_conflicts_by_itself_and_the_user_sees_it_first(
    make_client, wait_run, repo
):
    client, cid, run_id = clashing(
        make_client, repo, RESOLVING,
        project={"check_command": "python check.py TWO"})
    # (A resolution may drop lines of the user's own commit: a card, even where the check passed.)
    merge = until(client, cid, lambda s: [m["status"] for m in s["merges"]] == ["pending"]
                  and s["merges"][0]["branch"]["conflicts"] == [], timeout=LONG)["merges"][0]
    assert merge["check"]["state"] == "passed" and lines(repo)[1] == "TWO-user"
    assert client.post(f"/api/merges/{merge['id']}/approve", json={"shown": {}}).status_code == 200
    snap = wait_run(client, cid, run_id, timeout=LONG)
    (merge,) = snap["merges"]
    assert merge["status"] == "applied" and merge["check"]["state"] == "passed"
    assert lines(repo)[1] == "TWO-both" and run(repo, "branch", "--list", "koloni/*") == ""


def test_a_clash_with_no_marked_lines_is_not_an_agents_and_the_users_deletion_stands(
    make_client, wait_run, repo
):
    held = Gate()
    client, cid, run_id = on_branch(
        make_client, repo, [step(edit("two", "TWO-agent")), held.step(text("A done")),
                            *RESOLVING], permission_mode="ask")
    held.wait_partial()
    run(repo, "rm", "-q", "lines.txt")
    run(repo, "commit", "-qm", "user deletes it")
    held.release()
    merge = card(client, cid)
    assert merge["branch"]["conflicts"] == ["lines.txt"] and merge["branch"]["resolve"]
    sha = run(repo, "rev-parse", "koloni/fix")
    assert client.post(f"/api/merges/{merge['id']}/resolve").status_code == 200
    merge = until(client, cid, lambda s: "no text lines" in (
        s["merges"][0]["branch"]["note"] or ""), timeout=LONG)["merges"][0]
    assert merge["status"] == "pending" and run(repo, "rev-parse", "koloni/fix") == sha
    assert client.post(f"/api/merges/{merge['id']}/reject").status_code == 200
    wait_run(client, cid, run_id, timeout=LONG)
    assert not (repo / "lines.txt").exists()


def test_resolve_is_refused_where_nothing_clashes(make_client, wait_run, repo):
    client, cid, run_id = on_branch(
        make_client, repo, [step(edit("two", "TWO-agent")), text("A done")],
        permission_mode="ask")
    merge = card(client, cid)
    assert "resolve" not in merge["branch"]
    assert client.post(f"/api/merges/{merge['id']}/resolve").status_code == 409
    assert client.post(f"/api/merges/{merge['id']}/reject").status_code == 200
    wait_run(client, cid, run_id, timeout=LONG)


def test_a_branch_kept_after_its_merge_stays(make_client, wait_run, repo):
    client, cid, run_id = on_branch(
        make_client, repo, [step(edit("two", "TWO-agent")), text("A done")],
        permission_mode="ask")
    merge = card(client, cid)
    assert client.post(f"/api/merges/{merge['id']}/approve",
                       json={"keep_branch": True, "shown": {}}).status_code == 200
    snap = wait_run(client, cid, run_id, timeout=LONG)
    (merge,) = snap["merges"]
    assert merge["status"] == "applied" and lines(repo)[1] == "TWO-agent"
    assert merge["commit"]["notes"] == ["The branch koloni/fix is kept, as you asked"]
    assert run(repo, "branch", "--list", "koloni/*").strip() == "koloni/fix"
    assert len(worktrees(repo)) == 1


def test_a_branch_is_not_kept_where_its_agents_commits_hold_a_secret(
    make_client, wait_run, repo, monkeypatch
):
    # (Its agents' own commits holding a secret given this turn: `git.held_since`, below.)
    monkeypatch.setattr(git, "held_since", lambda *_args: True)
    client, cid, run_id = on_branch(
        make_client, repo, [step(edit("two", "TWO-agent")), text("A done")],
        permission_mode="ask")
    merge = card(client, cid)
    assert client.post(f"/api/merges/{merge['id']}/approve",
                       json={"keep_branch": True, "shown": {}}).status_code == 200
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert "was not kept" in snap["merges"][0]["commit"]["notes"][0]
    assert run(repo, "branch", "--list", "koloni/*") == ""


def test_a_secret_in_any_of_the_agents_own_commits_is_found(repo, runtime):
    copy = copies.make_branch(repo, runtime, "agent1", "x")
    start = copy.start[1]
    (copy.root / "key.txt").write_bytes(b"token zz-secret")
    committed(copy, "key.txt")
    run(copy.root, "rm", "-q", "key.txt")
    run(copy.root, "commit", "-qm", "taken out")
    assert git.held_since(repo, start, tip(repo, copy), [b"zz-secret"])
    assert not git.held_since(repo, start, tip(repo, copy), [b"other"])
    assert not git.held_since(repo, start, tip(repo, copy), [])
    committed_message = copies.make_branch(repo, runtime, "agent2", "y")
    run(committed_message.root, "commit", "-q", "--allow-empty", "-m", "the key is zz-secret")
    assert git.held_since(repo, start, tip(repo, committed_message), [b"zz-secret"])


FAKE_GH = """import json, os, sys
args = sys.argv[1:]
log = os.environ["FAKE_GH_LOG"]
with open(log, "a", encoding="utf-8") as f:
    f.write(json.dumps(args) + "\\n")
if args[:2] == ["auth", "status"]:
    sys.exit(0 if os.environ.get("FAKE_GH_IN") == "1" else 1)
if args[:2] == ["repo", "view"]:
    print("owner/repo")
    sys.exit(0)
if args[:2] == ["pr", "create"]:
    once = os.environ.get("FAKE_GH_FAIL_ONCE")
    if once and os.path.exists(once):
        os.remove(once)
        print("GraphQL: something went wrong", file=sys.stderr)
        sys.exit(1)
    body = next(a for a in args if a.startswith("--body-file=")).split("=", 1)[1]
    with open(log + ".body", "w", encoding="utf-8") as f:
        f.write(open(body, encoding="utf-8").read())
    print("https://github.com/owner/repo/pull/7")
    sys.exit(0)
sys.exit(2)
"""


@pytest.fixture
def github(repo, tmp_path, monkeypatch):
    """The project's origin is GitHub's owner/repo to gh (faked: never the network), and it
    pushes to a bare repository here. Returns the bare repository and gh's log."""
    import sys

    fake = tmp_path / "fake_gh.py"
    fake.write_text(FAKE_GH)
    log = tmp_path / "gh.log"
    monkeypatch.setattr(git, "gh", lambda: [sys.executable, str(fake)])
    monkeypatch.setenv("FAKE_GH_LOG", str(log))
    monkeypatch.setenv("FAKE_GH_IN", "1")
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    run(repo, "remote", "add", "origin", "https://github.com/owner/repo.git")
    run(repo, "config", "remote.origin.pushurl", str(bare))
    return bare, log


def gh_calls(log):
    import json

    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def pushed_main(repo):
    """The user pushes their branch: origin holds where a pull request's branch starts."""
    run(repo, "push", "-q", "origin", "main")


def test_the_first_finished_branch_on_github_asks_which_way_and_a_pull_request_is_pushed(
    make_client, wait_run, repo, github
):
    bare, log = github
    client, cid, run_id = on_branch(
        make_client, repo, [step(edit("two", "TWO-agent")), text("A done")])
    merge = card(client, cid)  # (at Full auto too: the way is the user's to choose)
    assert merge["branch"]["ask_way"] and "pr_off" not in merge["branch"]
    pushed_main(repo)
    main = run(repo, "rev-parse", "HEAD")
    assert client.post(f"/api/merges/{merge['id']}/approve",
                       json={"way": "pull_request", "shown": {}}).status_code == 200
    snap = wait_run(client, cid, run_id, timeout=LONG)
    (merge,) = snap["merges"]
    assert merge["commit"]["state"] == "pull_request"
    assert merge["commit"]["url"] == "https://github.com/owner/repo/pull/7"
    assert merge["commit"]["pushed"] == "origin/koloni/fix"
    # (B-205: KOLONİ's line under the answer says where it went - not "in the project".)
    assert [m["content"] for m in snap["messages"] if m["role"] == "landed"] == [
        "Sent as a pull request: https://github.com/owner/repo/pull/7."]
    # Nothing merged here; the branch went up as ONE commit by KOLONİ on main's commit.
    assert run(repo, "rev-parse", "HEAD") == main and lines(repo)[1] == "two"
    pushed = run(bare, "rev-parse", "refs/heads/koloni/fix")
    assert pushed == merge["commit"]["sha"]
    assert run(bare, "log", "-1", "--format=%P %ae", pushed) == f"{main} koloni@localhost"
    assert "TWO-agent" in run(bare, "show", f"{pushed}:lines.txt")
    (create,) = [one for one in gh_calls(log) if one[:2] == ["pr", "create"]]
    assert "--head=koloni/fix" in create and "--base=main" in create
    assert "--title=fix two" in create and "--repo=owner/repo" in create
    body = log.with_name("gh.log.body").read_text(encoding="utf-8")
    assert "`lines.txt` (M)" in body and "A done" in body
    assert run(repo, "branch", "--list", "koloni/*") == "" and len(worktrees(repo)) == 1
    project = client.get("/api/projects").json()[0]
    assert project["finish_way"] == "pull_request"


def pr_run(make_client, repo, meanwhile, **conversation):
    """A Coder on `koloni/fix` in a project whose finished work goes as a pull request; the user
    does `meanwhile` while it works."""
    held = Gate()
    client, cid, run_id = on_branch(
        make_client, repo, [step(edit("two", "TWO-agent")), held.step(text("A done"))],
        project={"finish_way": "pull_request", "check_command": "python check.py TWO-agent"},
        **conversation)
    held.wait_partial()
    meanwhile()
    held.release()
    return client, cid, run_id


def test_with_pull_requests_set_full_auto_opens_one_unasked_and_never_merges(
    make_client, wait_run, repo, github
):
    bare, log = github
    client, cid, run_id = pr_run(make_client, repo, lambda: pushed_main(repo))
    snap = wait_run(client, cid, run_id, timeout=LONG)
    (merge,) = snap["merges"]
    assert merge["commit"]["state"] == "pull_request" and merge["check"]["state"] == "passed"
    assert lines(repo)[1] == "two" and run(bare, "rev-parse", "refs/heads/koloni/fix")
    assert [m["content"] for m in snap["messages"] if m["role"] == "landed"] == [
        "Sent as a pull request: https://github.com/owner/repo/pull/7."]  # (B-205)


def test_the_users_own_commits_not_on_origin_never_go_up_with_a_pull_request(
    make_client, wait_run, repo, github
):
    bare, log = github
    client, cid, run_id = pr_run(make_client, repo, lambda: None)  # (main not pushed)
    merge = until(client, cid, lambda s: "push main first" in (
        (s["merges"] or [{}])[0].get("branch") or {}).get("note", "") or "", timeout=LONG)[
        "merges"][0]
    assert run(bare, "for-each-ref") == ""
    pushed_main(repo)
    assert client.post(f"/api/merges/{merge['id']}/approve", json={"shown": {}}).status_code == 200
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["merges"][0]["commit"]["state"] == "pull_request"


def test_a_config_changed_during_the_turn_holds_the_push_for_a_click(
    make_client, wait_run, repo, github
):
    bare, log = github

    def meanwhile():
        pushed_main(repo)
        run(repo, "config", "core.sshCommand", "ssh -o SendEnv=X")

    client, cid, run_id = pr_run(make_client, repo, meanwhile)
    merge = card(client, cid)
    assert ".git/config changed during this turn" in merge["branch"]["note"]
    assert run(bare, "branch", "--list", "koloni/*") == ""
    assert client.post(f"/api/merges/{merge['id']}/approve", json={"shown": {}}).status_code == 200
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["merges"][0]["commit"]["state"] == "pull_request"


def test_a_pull_request_that_failed_after_its_push_is_opened_again_without_a_second_push(
    make_client, wait_run, repo, github, tmp_path, monkeypatch
):
    bare, log = github
    once = tmp_path / "fail-once"
    once.write_text("x")
    monkeypatch.setenv("FAKE_GH_FAIL_ONCE", str(once))
    client, cid, run_id = pr_run(make_client, repo, lambda: pushed_main(repo))
    merge = card(client, cid)
    assert "was pushed to origin, but gh pr create failed" in merge["branch"]["note"]
    sha = run(bare, "rev-parse", "refs/heads/koloni/fix")
    assert client.post(f"/api/merges/{merge['id']}/approve", json={"shown": {}}).status_code == 200
    snap = wait_run(client, cid, run_id, timeout=LONG)
    (merge,) = snap["merges"]
    assert merge["commit"]["state"] == "pull_request" and merge["commit"]["sha"] == sha
    assert len([one for one in gh_calls(log) if one[:2] == ["pr", "create"]]) == 2


def test_a_push_carries_no_tag_nor_unpushed_commit_and_runs_gits_own_receive_pack(
    repo, runtime, tmp_path
):
    import sys

    bare = tmp_path / "o.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    run(repo, "remote", "add", "origin", str(bare))
    pushed_main(repo)
    run(repo, "tag", "-a", "v-private", "-m", "private")
    run(repo, "config", "push.followTags", "true")
    marker, script = tmp_path / "RAN", tmp_path / "rp.py"
    script.write_text(f"open({str(marker)!r}, 'w').write('x')\nraise SystemExit(1)\n")
    run(repo, "config", "remote.origin.receivepack",
        f'"{Path(sys.executable).as_posix()}" "{script.as_posix()}"')
    copy = copies.make_branch(repo, runtime, "agent1", "x")
    (copy.root / "b.txt").write_text("agent\n")
    git.commit_branch(copy.root, copy.branch, ["b.txt"], "m", runtime / "no-hooks")
    sha = git.push_one(repo, tip(repo, copy), copy.branch, "main", copy.start[1], "m",
                       runtime / "no-hooks")
    assert not marker.exists() and run(bare, "tag") == ""
    assert run(bare, "rev-parse", "refs/heads/koloni/x") == sha
    # A commit of the user's not on origin yet: nothing goes up.
    (repo / "local-secret.txt").write_text("mine\n")
    run(repo, "add", "local-secret.txt")
    run(repo, "commit", "-qm", "local only")
    other = copies.make_branch(repo, runtime, "agent2", "y")
    (other.root / "c.txt").write_text("agent\n")
    git.commit_branch(other.root, other.branch, ["c.txt"], "m", runtime / "no-hooks")
    with pytest.raises(git.Refused, match="push main first"):
        git.push_one(repo, tip(repo, other), other.branch, "main", other.start[1], "m",
                     runtime / "no-hooks")
    assert run(bare, "branch", "--list", "koloni/y") == ""


def test_no_pull_request_where_origin_is_not_the_repository_gh_names(repo, github):
    assert git.pr_ready(repo) == ("owner/repo", None)
    run(repo, "remote", "set-url", "origin", "git@github.com:someone/thing.git")
    assert git.pr_ready(repo) == (
        None, "origin is not owner/repo, the repository gh opens pull requests on")
    run(repo, "remote", "set-url", "origin", "git@github.com:Owner/Repo")
    assert git.pr_ready(repo)[0] == "owner/repo"


def test_a_way_said_on_a_card_that_did_not_ask_it_pushes_nothing(
    make_client, wait_run, repo, github
):
    bare, log = github
    client, cid, run_id = on_branch(
        make_client, repo, [step(edit("two", "TWO-agent")), text("A done")],
        project={"finish_way": "merge"}, permission_mode="ask")
    merge = card(client, cid)
    assert "ask_way" not in merge["branch"] and "way" not in merge["branch"]
    assert client.post(f"/api/merges/{merge['id']}/approve",
                       json={"way": "pull_request", "shown": {}}).status_code == 200
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["merges"][0]["commit"]["state"] == "committed" and lines(repo)[1] == "TWO-agent"
    assert run(bare, "for-each-ref") == "" and gh_calls(log) == []


def test_a_pull_request_cannot_be_chosen_where_gh_is_logged_out_and_says_why(
    make_client, repo, github, monkeypatch
):
    monkeypatch.setenv("FAKE_GH_IN", "0")
    client, _model = make_client({})
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(repo)}).json()["id"]
    assert client.get(f"/api/projects/{pid}/pull-request").json() == {
        "why_not": "gh is not logged in: run gh auth login"}
    answer = client.patch(f"/api/projects/{pid}", json={"finish_way": "pull_request"})
    assert answer.status_code == 422 and "not logged in" in answer.json()["detail"]
    assert client.patch(f"/api/projects/{pid}", json={"finish_way": "merge"}).status_code == 200
    monkeypatch.setenv("FAKE_GH_IN", "1")
    assert client.get(f"/api/projects/{pid}/pull-request").json() == {"why_not": None}
    assert client.patch(f"/api/projects/{pid}",
                        json={"finish_way": "pull_request"}).json()["finish_way"] == "pull_request"


def test_a_secret_amended_away_is_still_found_in_the_branchs_reflog(repo, runtime):
    copy = copies.make_branch(repo, runtime, "agent1", "x")
    start = copy.start[1]
    (copy.root / "key.txt").write_bytes(b"token zz-secret")
    committed(copy, "key.txt")
    run(copy.root, "rm", "-q", "key.txt")
    (copy.root / "ok.txt").write_bytes(b"fine")
    run(copy.root, "add", "ok.txt")
    run(copy.root, "commit", "-q", "--amend", "-m", "clean")
    assert not git.held_since(repo, start, tip(repo, copy), [b"zz-secret"])
    assert git.held_since(repo, start, tip(repo, copy), [b"zz-secret"], copy.branch)


def test_no_merge_in_over_a_change_the_line_left_uncommitted(repo, runtime):
    copy = clash(repo, runtime)
    (copy.root / "a.txt").write_bytes(b"held back\n")
    with pytest.raises(git.Refused, match="not committed"):
        git.merge_in(copy.root, copy.branch, "main", runtime / "no-hooks")
    assert (copy.root / "a.txt").read_bytes() == b"held back\n"
    assert not (copy.root / "lines.txt").read_bytes().count(b"<<<<<<<")


def test_no_push_of_a_branch_made_from_a_local_branch_the_user_left(repo, runtime, tmp_path):
    bare = tmp_path / "o.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    run(repo, "remote", "add", "origin", str(bare))
    pushed_main(repo)
    run(repo, "switch", "-q", "-c", "feature")
    (repo / "feat-secret.txt").write_text("mine\n")
    run(repo, "add", "feat-secret.txt")
    run(repo, "commit", "-qm", "feature only")
    copy = copies.make_branch(repo, runtime, "agent1", "x")
    (copy.root / "b.txt").write_text("agent\n")
    git.commit_branch(copy.root, copy.branch, ["b.txt"], "m", runtime / "no-hooks")
    run(repo, "switch", "-q", "main")
    with pytest.raises(git.Refused, match="push main first"):
        git.push_one(repo, tip(repo, copy), copy.branch, "main", copy.start[1], "m",
                     runtime / "no-hooks")
    assert run(bare, "branch", "--list", "koloni/*") == ""


@pytest.mark.parametrize(("url", "names"), [
    ("https://github.com/owner/repo.git", True), ("git@github.com:Owner/Repo", True),
    ("ssh://git@github.com/owner/repo", True), ("https://user@github.com/owner/repo/", True),
    ("https://evilgithub.com/owner/repo.git", False),
    ("https://x.example/github.com/owner/repo", False),
    ("git@github.com:owner/repo2", False), ("https://github.com/owner/repo.git.evil", False),
])
def test_origin_names_the_repository_only_with_github_com_as_its_host(url, names):
    assert git._names(url, "owner/repo") is names


def test_a_config_changed_between_the_look_and_the_push_pushes_nothing(
    make_client, wait_run, repo, github, monkeypatch
):
    bare, log = github
    looked = git.holding

    def holding(*args):  # (inside the merge lock: after git's config was read, before the push)
        run(repo, "config", "koloni.meanwhile", "1")
        return looked(*args)

    monkeypatch.setattr(git, "holding", holding)
    client, cid, run_id = pr_run(make_client, repo, lambda: pushed_main(repo))
    merge = card(client, cid)
    assert "changed just now" in merge["branch"]["note"]
    assert run(bare, "branch", "--list", "koloni/*") == ""
    assert client.post(f"/api/merges/{merge['id']}/reject").status_code == 200
    wait_run(client, cid, run_id, timeout=LONG)


# --- an agent that stopped on a branch goes on there ------------------------------------------


def stopped_on(repo, runtime):
    """A branch copy whose agent changed a.txt and stopped: KOLONİ's commit is on the branch, the
    worktree is gone and the branch stays (`branch -d` refuses unmerged work)."""
    copy = copies.make_branch(repo, runtime, "agent1", "x")
    (copy.root / "a.txt").write_text("one\nTWO\n")
    git.commit_branch(copy.root, copy.branch, ["a.txt"], "Coder: half", runtime / "no-hooks")
    copies.remove(runtime, copy.name)
    with pytest.raises(git.Refused):
        git.drop_branch(repo, copy.root, copy.branch, runtime / "no-hooks")
    return copy


def test_a_branch_opened_again_holds_its_earlier_commit_and_new_work_goes_on_top(repo, runtime):
    first = stopped_on(repo, runtime)
    copy = copies.make_branch(repo, runtime, "agent1", "koloni/x", start=first.start)
    assert copy.branch == "koloni/x" and run(copy.root, "branch", "--show-current") == "koloni/x"
    assert (copy.root / "a.txt").read_text() == "one\nTWO\n"
    assert copy.start == first.start  # (where it left main: what a merge is held to)
    assert copy.changes() == []
    (copy.root / "b.txt").write_text("new\n")
    assert git.commit_branch(copy.root, copy.branch, ["b.txt"], "Coder: rest", runtime / "no-hooks")
    look = git.branch_look(repo, copy.branch, copy.start)
    assert look["files"] == {"a.txt": "M", "b.txt": "A"} and look["drift"] is None
    git.merge_branch(repo, look["tip"], "Merge koloni/x", runtime / "no-hooks", "main",
                     copy.start[1])
    assert (repo / "a.txt").read_text() == "one\nTWO\n" and (repo / "b.txt").read_text() == "new\n"
    gone(repo, runtime, copy)
    assert run(repo, "branch", "--list", "koloni/*") == "" and len(worktrees(repo)) == 1


def test_a_branch_gone_or_checked_out_elsewhere_is_refused_and_its_work_stays(
    repo, runtime, tmp_path
):
    first = stopped_on(repo, runtime)
    run(repo, "worktree", "add", str(tmp_path / "elsewhere"), "koloni/x")
    with pytest.raises(git.Refused, match="could not be opened again"):
        copies.make_branch(repo, runtime, "agent1", "koloni/x", start=first.start)
    assert run(repo, "branch", "--list", "koloni/x").strip().endswith("koloni/x")
    assert not os.path.lexists(copies.place(runtime, "agent1"))  # (nothing left behind)
    run(repo, "worktree", "remove", "--force", str(tmp_path / "elsewhere"))
    run(repo, "branch", "-D", "koloni/x")
    with pytest.raises(git.Refused, match="no branch koloni/x any more"):
        copies.make_branch(repo, runtime, "agent1", "koloni/x", start=first.start)
    assert len(worktrees(repo)) == 1
    with pytest.raises(git.Refused, match="not on record"):  # (a record made before starts were)
        copies.make_branch(repo, runtime, "agent1", "koloni/x")


def test_a_branch_opened_again_after_the_project_moved_off_its_start_says_so(repo, runtime):
    """The merge is held to where the branch was first made from, not where it meets the
    project now: switched to a branch without main's commit, the merge would bring that in."""
    (repo / "main_only.txt").write_text("main's\n")
    run(repo, "add", "main_only.txt")
    run(repo, "commit", "-qm", "main only")
    run(repo, "branch", "feature", "HEAD~1")
    first = stopped_on(repo, runtime)
    run(repo, "switch", "-q", "feature")
    copy = copies.make_branch(repo, runtime, "agent1", "koloni/x", start=first.start)
    assert copy.start == first.start and first.start[0] == "main"
    look = git.branch_look(repo, copy.branch, copy.start)
    assert look["files"] == {"a.txt": "M", "main_only.txt": "A"}
    assert look["drift"] == "made from main, the project is on feature now"
    copies.remove(runtime, copy.name)
    git.drop_branch(repo, copy.root, copy.branch, runtime / "no-hooks", keep=True)
    run(repo, "switch", "-q", "main")
    run(repo, "reset", "-q", "--hard", "HEAD~1")  # (its start gone from main)
    copy = copies.make_branch(repo, runtime, "agent1", "koloni/x", start=first.start)
    assert "no longer holds the commit" in git.branch_look(repo, copy.branch, copy.start)["drift"]
    with pytest.raises(git.Refused, match="no longer holds the commit"):
        git.merge_branch(repo, tip(repo, copy), "m", runtime / "no-hooks", "main", copy.start[1])


def test_another_branch_of_the_same_name_since_is_not_opened_again(repo, runtime):
    first = stopped_on(repo, runtime)
    stopped = tip(repo, first)
    run(repo, "branch", "-D", "koloni/x")  # (the user's, by hand)
    other = copies.make_branch(repo, runtime, "agent2", "x")  # (a later agent's: the name is free)
    (other.root / "b.txt").write_text("C's\n")
    git.commit_branch(other.root, other.branch, ["b.txt"], "C: its own", runtime / "no-hooks")
    copies.remove(runtime, other.name)
    git.drop_branch(repo, other.root, other.branch, runtime / "no-hooks", keep=True)
    assert other.branch == "koloni/x"
    with pytest.raises(git.Refused, match="not the one it stopped on"):
        copies.make_branch(repo, runtime, "agent1", "koloni/x", start=first.start, tip=stopped)
    assert tip(repo, other) != stopped and len(worktrees(repo)) == 1
    copy = copies.make_branch(repo, runtime, "agent1", "koloni/x", start=other.start,
                              tip=tip(repo, other))
    assert copy.branch == "koloni/x"


def test_a_branch_whose_worktree_folder_was_deleted_by_hand_is_opened_again(
    repo, runtime, tmp_path
):
    first = stopped_on(repo, runtime)
    run(repo, "worktree", "add", str(tmp_path / "elsewhere"), "koloni/x")
    shutil.rmtree(tmp_path / "elsewhere")  # (git's record of it stays)
    copy = copies.make_branch(repo, runtime, "agent1", "koloni/x", start=first.start)
    assert (copy.root / "a.txt").read_text() == "one\nTWO\n" and len(worktrees(repo)) == 2


# (Its model fails: it stops unfinished, with no card for more steps that waits for an answer.)
STOP_ON_BRANCH = [step(edit("two", "TWO-agent")), ModelUnavailable("model server unreachable")]
GO_ON = step(call("message_agent", {"to": "Coder", "message": "go on"}, "m"))


def test_told_to_go_on_an_agent_that_stopped_on_a_branch_goes_on_on_that_branch(
    make_client, wait_run, repo
):
    client, cid, run_id = on_branch(make_client, repo, [
        *STOP_ON_BRANCH, step(edit("TWO-agent", "TWO-again", "e2")), text("done")], then=[GO_ON])
    snap = wait_run(client, cid, run_id, timeout=LONG)
    ((_status, stopped),) = calls(snap, "Lead", "spawn_agent")
    assert "committed on branch koloni/fix" in stopped
    # (Its earlier edit is there: in a copy of the project, "TWO-agent" would not be found.)
    assert calls(snap, "Coder", "edit_file")[-1][0] == "succeeded"
    (merge,) = snap["merges"]
    assert merge["status"] == "applied" and merge["branch"]["name"] == "koloni/fix"
    assert lines(repo)[1] == "TWO-again"
    assert run(repo, "branch", "--list", "koloni/*") == "" and len(worktrees(repo)) == 1


def test_gone_on_with_in_a_later_turn_an_agent_that_stopped_on_a_branch_goes_on_on_it(
    make_client, wait_run, repo
):
    client, cid, first = on_branch(make_client, repo, [
        *STOP_ON_BRANCH, step(edit("TWO-agent", "TWO-again", "e2")), text("done")],
        then=[text("stopped"), GO_ON])
    wait_run(client, cid, first, timeout=LONG)
    assert run(repo, "branch", "--list", "koloni/*").strip() == "koloni/fix"
    second = client.post(f"/api/conversations/{cid}/messages",
                         json={"content": "go on"}).json()["run"]["id"]
    snap = wait_run(client, cid, second, timeout=LONG)
    (merge,) = snap["merges"]
    assert merge["status"] == "applied" and merge["branch"]["name"] == "koloni/fix"
    assert lines(repo)[1] == "TWO-again"


def test_stop_everything_mid_work_keeps_the_branch_with_its_work_and_a_later_go_on_opens_it(
    make_client, wait_run, repo, gate
):
    """B-405 (live): Stop everything while a Coder works on its branch deleted the branch and
    its file - its worktree's work was never committed, and `branch -d` takes a branch with
    nothing on it. Now it is committed and kept, as where the agent stops by itself."""
    client, cid, first = on_branch(make_client, repo, [
        step(edit("two", "TWO-agent")), gate.step(text("never")),
        step(edit("TWO-agent", "TWO-again", "e2")), text("done")], then=[GO_ON])
    gate.wait_partial()  # (its edit made, in its worktree; the next step held)
    assert client.post("/api/hold").json()["held"] is True
    snap = wait_run(client, cid, first, timeout=LONG)
    assert snap["runs"][0]["status"] in ("cancelled", "interrupted")
    assert run(repo, "branch", "--list", "koloni/*").strip() == "koloni/fix"
    assert run(repo, "show", "koloni/fix:lines.txt").split("\n")[1] == "TWO-agent"
    assert len(worktrees(repo)) == 1 and lines(repo)[1] == "two"
    assert any("committed on branch koloni/fix" in m["content"]
               for m in snap["messages"] if m["role"] == "koloni")
    gate.release()
    second = client.post(f"/api/conversations/{cid}/messages",
                         json={"content": "go on"}).json()["run"]["id"]
    snap = wait_run(client, cid, second, timeout=LONG)
    assert calls(snap, "Coder", "edit_file")[-1][0] == "succeeded"  # (on its branch: found)
    (merge,) = snap["merges"]
    assert merge["status"] == "applied" and merge["branch"]["name"] == "koloni/fix"
    assert lines(repo)[1] == "TWO-again"
    assert run(repo, "branch", "--list", "koloni/*") == "" and len(worktrees(repo)) == 1


def test_a_second_stop_while_the_branch_work_is_saved_does_not_lose_it(
    make_client, wait_run, repo, gate, monkeypatch
):
    """B-405 review: Stop has no guard - pressed again (or Stop everything after it) while the
    work is being committed, the turn's end must not delete the worktree under the commit."""
    committing, real = threading.Event(), git.commit_branch

    def slow(*args, **kwargs):
        committing.set()
        time.sleep(0.5)  # (the second Stop comes now)
        return real(*args, **kwargs)

    monkeypatch.setattr(git, "commit_branch", slow)
    client, cid, first = on_branch(make_client, repo, [
        step(edit("two", "TWO-agent")), gate.step(text("never"))])
    gate.wait_partial()
    assert client.post(f"/api/runs/{first}/cancel").status_code == 202
    assert committing.wait(LONG)
    assert client.post(f"/api/runs/{first}/cancel").status_code in (202, 409)
    wait_run(client, cid, first, timeout=LONG)
    deadline = time.monotonic() + LONG  # (the turn is on record as over before its copies go)
    while len(worktrees(repo)) > 1 and time.monotonic() < deadline:
        time.sleep(0.05)
    assert len(worktrees(repo)) == 1
    assert run(repo, "show", "koloni/fix:lines.txt").split("\n")[1] == "TWO-agent"
    gate.release()


def test_a_lead_that_breaks_stops_a_sub_agent_nobody_waited_for_before_its_copies_go(
    session_app, wait_run, repo, monkeypatch  # noqa: F811
):
    """B-405 (last review): the Lead's turn ending in an internal error deleted the copies
    first, and only then stopped the sub-agent a failed CLI opener had left at work - its copy
    went from under it. Now as on the way that did not break (`_saved`): stopped, then ended,
    and only then its copy goes."""
    from app.agent import AgentRunner
    from tests.test_session_agent import _local
    from tests.test_session_agent import start as session_start

    work, lead = Gate(), Gate()
    client, provider, _ = session_app(
        [{"call": "spawn_agent", "args": {"role": "Debugger", "task": "fix two"}},
         {"exit": 3, "stderr": "boom"}],
        default_steps={"Lead": [step(call("spawn_agent", {"role": "Coder", "task": "make it"},
                                          "s")), lead.step(text("done"))],
                       "Debugger": [step(edit("two", "TWO-agent", path="a.txt")),
                                    work.step(text("never"))]})
    client.patch(f"/api/roles/{role_id(client, 'Coder')}", json={"provider_id": provider["id"]})
    client.patch(f"/api/roles/{role_id(client, 'Debugger')}",
                 json={"provider_id": _local(client)["id"]})
    real, real_drop = AgentRunner._attempt, AgentRunner._drop_copy
    # Once it broke: whether a sub-agent of the turn left at work was still at work as a copy
    # went (its tasks taken as it broke: `_saved` takes them off the turn's list).
    left, dropped = [], []

    def drop(self, agent_id, *args, **kwargs):
        if left:
            dropped.append(any(not task.done() for task in left))
        return real_drop(self, agent_id, *args, **kwargs)

    async def breaks(self, ctx):
        turn = asyncio.ensure_future(real(self, ctx))
        while not (work._partial_seen.is_set() and lead._partial_seen.is_set()):
            await asyncio.sleep(0.01)
        turn.cancel()  # (the Coder failed: its Debugger works on, waited for by nobody)
        await asyncio.gather(turn, return_exceptions=True)
        left.extend(one[3] for one in self._later_work.get(run_id, ()))
        assert left  # (its Debugger)
        raise RuntimeError("broke")

    monkeypatch.setattr(AgentRunner, "_attempt", breaks)
    monkeypatch.setattr(AgentRunner, "_drop_copy", drop)
    cid, run_id = session_start(client, repo, None)
    snap = wait_run(client, cid, run_id, timeout=LONG)
    work.release()
    lead.release()
    assert snap["runs"][0]["error"] == "internal error: RuntimeError('broke')"
    assert dropped and not any(dropped)


def keeping(make_client, models):
    """`make_client` that keeps its model in `models`: what each agent was sent."""
    def make(*args, **kwargs):
        client, model = make_client(*args, **kwargs)
        models.append(model)
        return client, model
    return make


def told(model, role="Coder"):
    """What of NOT_ON_BRANCH_AGAIN the agent was sent, in each step's messages."""
    return [[m["content"] for m in sent if "You are not going on on your branch" in str(
        m.get("content"))] for sent in model.calls_of[role]]


def test_gone_on_with_after_the_project_switched_branch_the_merge_waits_for_the_user(
    make_client, wait_run, repo
):
    """Opened again, the branch is held to where it was first made from (main): on feature now,
    its merge would bring main's commits in - the user's word, at Full auto too."""
    client, cid, first = on_branch(make_client, repo, [
        *STOP_ON_BRANCH, step(edit("TWO-agent", "TWO-again", "e2")), text("done")],
        then=[text("stopped"), GO_ON])
    wait_run(client, cid, first, timeout=LONG)
    run(repo, "switch", "-qc", "feature")
    second = client.post(f"/api/conversations/{cid}/messages",
                         json={"content": "go on"}).json()["run"]["id"]
    merge = card(client, cid)
    assert merge["branch"]["name"] == "koloni/fix" and merge["branch"]["into"] == "feature"
    assert merge["branch"]["note"] == "made from main, the project is on feature now"
    assert lines(repo)[1] == "two"
    assert client.post(f"/api/merges/{merge['id']}/reject").status_code == 200
    wait_run(client, cid, second, timeout=LONG)


def test_gone_on_with_where_its_branch_is_gone_the_agent_is_told_before_its_first_step(
    make_client, wait_run, repo
):
    models: list = []
    client, cid, first = on_branch(keeping(make_client, models), repo, [
        *STOP_ON_BRANCH, step(edit("two", "TWO-fresh", "e2")), text("done")],
        then=[text("stopped"), GO_ON])
    wait_run(client, cid, first, timeout=LONG)
    run(repo, "branch", "-D", "koloni/fix")
    second = client.post(f"/api/conversations/{cid}/messages",
                         json={"content": "go on"}).json()["run"]["id"]
    snap = wait_run(client, cid, second, timeout=LONG)
    assert snap["merges"][-1]["status"] == "applied" and lines(repo)[1] == "TWO-fresh"
    words = ("You are not going on on your branch: there is no branch koloni/fix any more: merged "
             "or deleted. You work in a new copy of the project as it is now: read each file "
             "again before you change it.")
    assert told(models[0])[-2:] == [[words]] * 2
    # (Where it stopped, before the go-on - not moved to the end at each step.)
    said = [str(m.get("content")) for m in models[0].calls_of["Coder"][-1]]
    assert said[said.index(words) + 1].endswith("go on")


def test_a_go_on_turned_down_on_its_card_leaves_no_branch_waiting_for_it(
    make_client, wait_run, repo
):
    client, cid, first = on_branch(make_client, repo, [*STOP_ON_BRANCH],
                                   then=[text("stopped"), GO_ON])
    wait_run(client, cid, first, timeout=LONG)
    assert client.patch(f"/api/conversations/{cid}",
                        json={"spawn_approval": "always"}).status_code == 200
    second = client.post(f"/api/conversations/{cid}/messages",
                         json={"content": "go on"}).json()["run"]["id"]
    snap = until(client, cid, lambda s: any(a["status"] == "proposed" for a in s["agents"]),
                 timeout=LONG)
    (child,) = [a for a in snap["agents"] if a["status"] == "proposed"]
    runner = client.app.state.runner
    assert runner._on_branch[child["id"]] == "koloni/fix"
    assert client.post(f"/api/agents/{child['id']}/reject").status_code == 200
    wait_run(client, cid, second, timeout=LONG)
    assert child["id"] not in runner._on_branch and child["id"] not in runner._left_on


def test_told_to_go_on_after_its_branch_was_merged_an_agent_gets_a_copy_and_says_why(
    make_client, wait_run, repo
):
    models: list = []
    client, cid, run_id = on_branch(keeping(make_client, models), repo, [
        step(edit("two", "TWO-agent")), text("A done"),
        step(edit("TWO-agent", "TWO-again", "e2")), text("again")], then=[GO_ON])
    snap = wait_run(client, cid, run_id, timeout=LONG)
    ((_status, said),) = calls(snap, "Lead", "message_agent")
    assert "not on a branch: its branch koloni/fix was merged, or sent as a pull request, already" in said
    assert [m["status"] for m in snap["merges"]] == ["applied", "applied"]
    assert lines(repo)[1] == "TWO-again"
    assert told(models[0])[-2:] == [[
        "You are not going on on your branch: its branch koloni/fix was merged, or sent as a pull "
        "request, already. You work in a new copy of the project as it is now: read each file "
        "again before you change it."]] * 2


def test_told_to_go_on_where_its_branch_is_checked_out_elsewhere_an_agent_gets_a_copy(
    make_client, wait_run, repo, tmp_path
):
    held = Gate()
    models: list = []
    client, cid, run_id = on_branch(keeping(make_client, models), repo, [
        *STOP_ON_BRANCH, step(edit("two", "TWO-fresh", "e2")), text("done"),
        step(edit("TWO-fresh", "TWO-third", "e3")), text("third")],
        then=[held.step(GO_ON), text("first"), GO_ON])
    held.wait_partial()
    run(repo, "worktree", "add", str(tmp_path / "elsewhere"), "koloni/fix")
    held.release()
    snap = wait_run(client, cid, run_id, timeout=LONG)
    ((_status, said),) = calls(snap, "Lead", "message_agent")
    assert "its branch koloni/fix could not be opened again" in said
    assert lines(repo)[1] == "TWO-fresh"
    # (The branch keeps its work: KOLONİ never deletes a branch it could not open.)
    assert run(repo, "show", "koloni/fix:lines.txt").splitlines()[1] == "TWO-agent"
    assert "its branch koloni/fix could not be opened again" in told(models[0])[-2][0]
    # (On record apart from `on_branch`, which the git map reads as the team on it.)
    coder = next(a for a in snap["agents"] if a["role_name"] == "Coder")
    assert "on_branch" not in coder["copy"]
    with client.app.state.session_factory() as session:
        record = session.get_one(Agent, coder["id"]).copy
    assert record["left_on"] == "koloni/fix" and record["start"][0] == "main" and record["tip"]
    # Its work went in from that copy: a later go-on, the branch free again, does not open the old
    # half-done branch over it - the agent is told, and goes on from the project.
    run(repo, "worktree", "remove", "--force", str(tmp_path / "elsewhere"))
    second = client.post(f"/api/conversations/{cid}/messages",
                         json={"content": "go on"}).json()["run"]["id"]
    snap = wait_run(client, cid, second, timeout=LONG)
    assert [m["status"] for m in snap["merges"]] == ["applied", "applied"]
    assert lines(repo)[1] == "TWO-third"
    assert told(models[0])[-1][-1] == (
        "You are not going on on your branch: its work went in from a copy since, not from its "
        "branch koloni/fix. You work in a new copy of the project as it is now: read each file "
        "again before you change it.")


def test_a_branch_opened_again_and_dropped_for_a_secret_says_its_earlier_work_went_too(
    make_client, wait_run, repo, monkeypatch
):
    from app.agent import AgentRunner

    given: list[str] = []
    monkeypatch.setattr(AgentRunner, "given_spellings", lambda self, run_id: given)
    client, cid, first = on_branch(make_client, repo, [
        *STOP_ON_BRANCH, ModelUnavailable("model server unreachable")],
        then=[text("stopped"), GO_ON])
    wait_run(client, cid, first, timeout=LONG)
    given.append("TWO-agent")  # (given in the next turn: on the branch from the one before)
    second = client.post(f"/api/conversations/{cid}/messages",
                         json={"content": "go on"}).json()["run"]["id"]
    snap = wait_run(client, cid, second, timeout=LONG)
    (said,) = [t["result"] for t in snap["tool_calls"] if t["name"] == "message_agent"]
    assert "its branch koloni/fix was deleted, with the work of its earlier turns on it:" in said
    assert run(repo, "branch", "--list", "koloni/*") == "" and lines(repo)[1] == "two"
