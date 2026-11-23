"""W-1: a team's branch starts from the user's folder as it is - a snapshot commit made from an
index of KOLONİ's own (the user's index, files, HEAD and branches untouched) - and what comes back
from it is the agents' work alone, measured from that snapshot. Every repository here is made by
the test, in its folder."""

import os
import subprocess
import time

import pytest

from app import copies, git
from app.agent import BRANCH_ON_YOURS, BRANCH_OVER_YOURS, FROM_HEAD, PR_SNAPSHOT, TAKEN_IN_FIRST
from tests import test_dal_takim
from tests.conftest import Gate
from tests.test_backlog_auto import worked
from tests.test_chat_flow import text
from tests.test_claim_scenarios import ORIGIN, calls, write
from tests.test_dal_takim import (
    GO_ON,
    STOP_ON_BRANCH,
    beside,
    on_branch,
    pr_run,
    pushed_main,
    run,
    worktrees,
)
from tests.test_parallel import until
from tests.test_spawn import call, step
from tests.test_take_in_scenarios import (
    CHECK,
    LINES,
    LONG,
    card,
    edit,
    lines,
    needs_git,
)

pytestmark = needs_git
repo, runtime, github = test_dal_takim.repo, test_dal_takim.runtime, test_dal_takim.github


def _known() -> bool:
    found = git.find()
    return found is not None and git.merge_base_known(found)


# (`merge-tree --merge-base` came with git 2.40: an older git starts every branch from HEAD.)
needs_merge_base = pytest.mark.skipif(not _known(), reason="git older than 2.40")


def has_object(repo, sha):
    return (
        subprocess.run(["git", "cat-file", "-e", sha], cwd=repo, capture_output=True).returncode
        == 0
    )


def subject(repo, sha):
    """A commit's subject, as git wrote it (UTF-8, whatever the console's code page)."""
    return (
        subprocess.run(
            ["git", "log", "-1", "--format=%s", sha], cwd=repo, capture_output=True, check=True
        )
        .stdout.decode("utf-8")
        .strip()
    )


def porcelain(repo):
    """`git status --porcelain`'s lines, each as git wrote it (a leading space too)."""
    return subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.splitlines()


def blob_of(repo, path):
    """The id the file would have as git's object - computed, not written."""
    return run(repo, "hash-object", "--", path)


def dirty(repo):
    """The user's folder with work not committed: a tracked file edited, a new file staged, a new
    file not added, an ignored `.env` and a secret-named file git does not ignore."""
    with (repo / ".git" / "info" / "exclude").open("a") as file:
        file.write(".env\n")
    (repo / ".env").write_text("KEY=ignored\n")
    (repo / "a.txt").write_text("one\nTWO-mine\n")
    (repo / "staged.txt").write_text("staged\n")
    run(repo, "add", "staged.txt")
    (repo / "new.txt").write_text("new\n")
    (repo / ".env.local").write_text("TOKEN=not-ignored\n")


@needs_merge_base
def test_a_branch_starts_from_the_folder_as_it_is_and_the_users_git_is_untouched(repo, runtime):
    dirty(repo)
    head, status = run(repo, "rev-parse", "HEAD"), run(repo, "status", "--porcelain")
    index = (repo / ".git" / "index").read_bytes()  # (after the status above: it may refresh it)
    copy = copies.make_branch(repo, runtime, "agent1", "x")
    assert copy.snapshot_sha and copy.from_head is None and copy.start == ("main", head)
    assert subject(repo, copy.snapshot_sha) == git.SNAPSHOT_MESSAGE.format(branch="koloni/x")
    assert run(repo, "log", "-1", "--format=%ae", copy.snapshot_sha) == "koloni@localhost"
    assert run(repo, "rev-parse", f"{copy.snapshot_sha}^") == head
    assert run(copy.root, "rev-parse", "HEAD") == copy.snapshot_sha
    assert (copy.root / "a.txt").read_text() == "one\nTWO-mine\n"
    assert (copy.root / "staged.txt").read_text() == "staged\n"
    assert (copy.root / "new.txt").read_text() == "new\n"
    # Out: what git ignores, and a secret by its name - never an object in the user's .git.
    assert not (copy.root / ".env").exists() and not (copy.root / ".env.local").exists()
    assert not has_object(repo, blob_of(repo, ".env.local"))
    # The user's own: index, files, HEAD, branch - and no ref, index or lock of KOLONİ's left.
    assert (repo / ".git" / "index").read_bytes() == index
    assert run(repo, "status", "--porcelain") == status
    assert (
        run(repo, "branch", "--show-current") == "main" and run(repo, "rev-parse", "HEAD") == head
    )
    assert run(repo, "for-each-ref", "refs/koloni/") == ""
    assert not list((repo / ".git").glob("koloni-index-*"))


def test_a_clean_folder_starts_from_head_as_before(repo, runtime):
    # (What a snapshot leaves out is no change: ignored, secret-named, dependencies, nested repos,
    # and KOLONİ's own `.koloni/` - its settings, written as a project's setting is saved.)
    with (repo / ".git" / "info" / "exclude").open("a") as file:
        file.write(".env\n")
    (repo / ".env").write_text("KEY=1\n")
    (repo / ".koloni").mkdir()
    (repo / ".koloni" / "settings.json").write_text("{}\n")
    (repo / "id_rsa").write_text("key\n")
    (repo / "node_modules").mkdir()
    (repo / "node_modules" / "m.js").write_text("module\n")
    (repo / "sub").mkdir()
    run(repo / "sub", "init", "-q")
    head = run(repo, "rev-parse", "HEAD")
    copy = copies.make_branch(repo, runtime, "agent1", "x")
    assert copy.snapshot_sha is None and copy.from_head is None
    assert run(copy.root, "rev-parse", "HEAD") == head == copy.start[1]
    assert not list((repo / ".git").glob("koloni-index-*"))


@needs_merge_base
def test_nested_repositories_and_dependencies_stay_out_of_the_snapshot(repo, runtime):
    (repo / "new.txt").write_text("new\n")
    (repo / "sub").mkdir()
    run(repo / "sub", "init", "-q")
    (repo / "sub" / "x.txt").write_text("x\n")
    run(repo / "sub", "add", "x.txt")
    run(repo / "sub", "-c", "user.email=a@b", "-c", "user.name=n", "commit", "-qm", "x")
    (repo / "node_modules").mkdir()
    for at in range(5):  # (more than the cap below: not counted, as not taken)
        (repo / "node_modules" / f"m{at}.js").write_text("module\n")
    tree, no_hooks = runtime / "wt", runtime / "no-hooks"
    branch, _into, _sha, snapshot, why, _left = git.add_worktree(
        repo, tree, "x", no_hooks, (2, 10**9)
    )
    assert snapshot and why is None
    held = run(repo, "ls-tree", "--name-only", snapshot).split()
    assert "new.txt" in held and "sub" not in held and "node_modules" not in held
    run(repo, "worktree", "unlock", str(tree))
    run(repo, "worktree", "remove", "--force", str(tree))
    run(repo, "branch", "-D", branch)


@pytest.mark.parametrize("most", [(2, 10**9), (100, 5)])
def test_over_the_caps_a_branch_starts_from_head_and_says_why_with_nothing_hashed(
    repo, runtime, most
):
    for name in ("n1.txt", "n2.txt", "n3.txt"):
        (repo / name).write_text(f"{name} is new\n")
    head = run(repo, "rev-parse", "HEAD")
    branch, _into, sha, snapshot, why, _left = git.add_worktree(
        repo, runtime / "wt", "x", runtime / "no-hooks", most
    )
    assert snapshot is None and sha == head
    assert why == git.TOO_MANY.format(count="3 files, 0 MB")
    assert run(runtime / "wt", "rev-parse", "HEAD") == head
    assert not has_object(repo, blob_of(repo, "n1.txt"))
    assert branch == "koloni/x" and not list((repo / ".git").glob("koloni-index-*"))


def test_with_an_older_git_a_branch_starts_from_head_and_says_why(repo, runtime, monkeypatch):
    monkeypatch.setattr(git, "merge_base_known", lambda _git: False)
    dirty(repo)
    head = run(repo, "rev-parse", "HEAD")
    copy = copies.make_branch(repo, runtime, "agent1", "x")
    assert copy.snapshot_sha is None and run(copy.root, "rev-parse", "HEAD") == head
    version = run(repo, "--version").removeprefix("git version ").split()[0]
    assert copy.from_head == git.OLD_GIT.format(version=version)
    assert not (copy.root / "new.txt").exists()


def test_the_version_git_gives_is_read_as_its_first_two_numbers():
    assert git._version_of("git version 2.53.0.windows.1") == ("2.53.0.windows.1", (2, 53))
    assert git._version_of("git version 2.39.3 (Apple Git-146)") == ("2.39.3", (2, 39))
    assert git._version_of("not git") == ("not git", (0, 0))


@needs_merge_base
def test_no_hook_runs_while_the_snapshot_is_made(repo, runtime):
    hooks, marker = repo.parent / "hooks", runtime.parent / "hook-ran"
    hooks.mkdir()
    for name in ("post-index-change", "reference-transaction", "post-checkout", "pre-commit"):
        (hooks / name).write_text(
            f"#!/bin/sh\necho {name} >> '{marker.as_posix()}'\n", newline="\n"
        )
        os.chmod(hooks / name, 0o755)
    run(repo, "config", "core.hooksPath", str(hooks))
    (repo / "c.txt").write_text("control\n")
    run(repo, "add", "c.txt")  # (the control: git by itself runs them)
    assert marker.exists()
    run(repo, "rm", "-q", "--cached", "c.txt")
    (repo / "c.txt").unlink()
    dirty(repo)
    marker.unlink(missing_ok=True)  # (`dirty`'s own `git add`)
    copy = copies.make_branch(repo, runtime, "agent1", "x")
    assert copy.snapshot_sha and not marker.exists()


@needs_merge_base
def test_a_split_index_and_an_untracked_cache_of_the_users_stay_as_they_are(repo, runtime):
    run(repo, "config", "core.untrackedCache", "true")
    run(repo, "update-index", "--split-index", "--untracked-cache")
    dirty(repo)
    status = run(repo, "status", "--porcelain")
    before = {one.name: one.read_bytes() for one in (repo / ".git").iterdir() if one.is_file()}
    copy = copies.make_branch(repo, runtime, "agent1", "x")
    assert copy.snapshot_sha and (copy.root / "new.txt").exists()
    after = {one.name: one.read_bytes() for one in (repo / ".git").iterdir() if one.is_file()}
    # (git's own record of the worktree aside, nothing of the git folder's top changed.)
    assert {name: data for name, data in after.items() if name != "ORIG_HEAD"} == {
        name: data for name, data in before.items() if name != "ORIG_HEAD"
    }
    assert run(repo, "status", "--porcelain") == status


def test_an_index_left_over_from_a_snapshot_that_never_ended_goes(repo, runtime):
    stale = repo / ".git" / "koloni-index-0123456789abcdef"
    stale.write_bytes(b"left over")
    (lock := stale.with_name(stale.name + ".lock")).write_bytes(b"")
    old = time.time() - git.STALE_SECONDS - 60
    for one in (stale, lock):
        os.utime(one, (old, old))
    (repo / "new.txt").write_text("new\n")
    copies.make_branch(repo, runtime, "agent1", "x")
    assert not list((repo / ".git").glob("koloni-index-*"))
    assert len(worktrees(repo)) == 2


def test_a_branch_copy_is_made_by_the_one_way_in(make_client, wait_run, repo, monkeypatch):
    held, made, real = [], [], git.add_worktree

    def opened(*args, **kwargs):  # (the client, before its turn starts)
        made.append(make_client(*args, **kwargs))
        return made[-1]

    def add(project, *args, **kwargs):  # (in the copy's thread: no Take in writes meanwhile)
        held.append(made[0][0].app.state.runner._way_in(project).locked())
        return real(project, *args, **kwargs)

    monkeypatch.setattr(git, "add_worktree", add)
    client, cid, run_id = on_branch(opened, repo, [step(edit("two", "TWO-agent")), text("A done")])
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["runs"][0]["status"] == "completed" and held == [True]


# --- what comes back is the agents' work alone, measured from the snapshot (W-1 Task 2) -----------

NINE = "".join(f"{n}\n" for n in range(1, 10))


def numbered(repo):
    """`nine.txt` committed, nine lines: one each side can change apart from the other's."""
    (repo / "nine.txt").write_text(NINE)
    run(repo, "add", "nine.txt")
    run(repo, "commit", "-qm", "nine")


def line(repo, n, words, where="nine.txt"):
    lines = (repo / where).read_text().splitlines(keepends=True)
    lines[n - 1] = f"{words}\n"
    (repo / where).write_text("".join(lines))


def agents(copy, runtime, *paths):
    """What the agent changed, committed on its branch as KOLONİ does."""
    assert git.commit_branch(copy.root, copy.branch, list(paths), "agent", runtime / "no-hooks")
    return git.branch_look(copy.project, copy.branch, copy.start, copy.snapshot_sha)


@needs_merge_base
def test_the_card_and_the_merge_carry_the_agents_work_alone(repo, runtime):
    numbered(repo)
    dirty(repo)  # (a.txt edited, staged.txt staged, new.txt new: none of it the agent's)
    copy = copies.make_branch(repo, runtime, "agent1", "x")
    line(copy.root, 9, "9-agent")
    (copy.root / "b.txt").write_text("agent's\n")
    look = agents(copy, runtime, "nine.txt", "b.txt")
    assert look["files"] == {"b.txt": "A", "nine.txt": "M"}
    assert (look["conflicts"], look["dirty"], look["yours"]) == ([], ["staged.txt"], [])
    assert run(repo, "rev-parse", f"{look['share']}^") == run(repo, "rev-parse", "HEAD")
    assert run(repo, "diff", "--name-only", "HEAD", look["share"]).split() == ["b.txt", "nine.txt"]
    diffs = git.branch_diffs(repo, copy.branch, ["nine.txt"], at=copy.snapshot_sha)
    assert "+9-agent" in diffs["nine.txt"] and "mine" not in diffs["nine.txt"]
    run(repo, "reset", "-q", "staged.txt")  # (staged, git merges nothing: the user unstages it)
    look = git.branch_look(repo, copy.branch, copy.start, copy.snapshot_sha)
    assert look["dirty"] == []
    sha = git.merge_branch(
        repo, look["share"], "Merge koloni/x", runtime / "no-hooks", "main", copy.start[1]
    )
    assert run(repo, "show", "--name-only", "--format=", sha).split() == ["b.txt", "nine.txt"]
    assert (repo / "nine.txt").read_text() == NINE.replace("9\n", "9-agent\n")
    assert (repo / "a.txt").read_text() == "one\nTWO-mine\n"  # (the user's, still uncommitted)
    assert porcelain(repo) == [" M a.txt", "?? .env.local", "?? new.txt", "?? staged.txt"]


@needs_merge_base
def test_the_users_uncommitted_lines_in_the_way_wait_until_they_commit_them(repo, runtime):
    numbered(repo)
    line(repo, 1, "1-mine")  # (not committed: the snapshot holds it)
    copy = copies.make_branch(repo, runtime, "agent1", "x")
    line(copy.root, 9, "9-agent")
    look = agents(copy, runtime, "nine.txt")
    assert look["share"] and look["dirty"] == ["nine.txt"] and look["yours"] == []
    # (The work alone, onto HEAD: the user's line is not in it.)
    assert run(repo, "show", f"{look['share']}:nine.txt").splitlines()[0] == "1"
    run(repo, "commit", "-qam", "mine")
    look = git.branch_look(repo, copy.branch, copy.start, copy.snapshot_sha)
    assert (look["dirty"], look["conflicts"]) == ([], [])
    git.merge_branch(
        repo, look["share"], "Merge koloni/x", runtime / "no-hooks", "main", copy.start[1]
    )
    assert (repo / "nine.txt").read_text().splitlines() == [
        "1-mine",
        *NINE.splitlines()[1:8],
        "9-agent",
    ]


@needs_merge_base
@pytest.mark.parametrize("theirs", ["new.txt", "nine.txt"])
def test_the_agents_change_over_the_users_uncommitted_work_is_theirs_to_commit_first(
    repo, runtime, theirs
):
    numbered(repo)
    (repo / "new.txt").write_text("the user's own\n")  # (new, not added)
    line(repo, 5, "5-mine")  # (and a line not committed)
    copy = copies.make_branch(repo, runtime, "agent1", "x")
    if theirs == "new.txt":
        (copy.root / "new.txt").write_text("the agent's\n")
    else:
        line(copy.root, 5, "5-agent")
    look = agents(copy, runtime, theirs)
    assert look["share"] is None and look["yours"] == [theirs]
    assert theirs in look["dirty"] and look["conflicts"] == []  # (no agent resolves it)
    share, clash = git.agents_share(repo, copy.snapshot_sha, look["tip"], copy.start[1])
    assert share is None and clash == [theirs]  # (nor does a pull request send it)


@needs_merge_base
def test_a_pull_requests_share_sits_on_where_the_branch_was_made_and_holds_the_agents_alone(
    repo, runtime
):
    numbered(repo)
    dirty(repo)
    copy = copies.make_branch(repo, runtime, "agent1", "x")
    line(copy.root, 9, "9-agent")
    tip = git.branch_look(repo, copy.branch, copy.start, copy.snapshot_sha)["tip"]
    agents(copy, runtime, "nine.txt")
    run(repo, "commit", "-qam", "the user's own since")  # (HEAD moves: the share does not)
    tip = git.branch_look(repo, copy.branch, copy.start, copy.snapshot_sha)["tip"]
    share, clash = git.agents_share(repo, copy.snapshot_sha, tip, copy.start[1])
    assert clash == [] and run(repo, "rev-parse", f"{share}^") == copy.start[1]
    assert run(repo, "diff", "--name-only", copy.start[1], share).split() == ["nine.txt"]


@needs_merge_base
def test_a_conflict_with_what_the_user_committed_since_is_a_conflict_and_a_resolve_goes_in(
    repo, runtime
):
    numbered(repo)
    dirty(repo)
    copy = copies.make_branch(repo, runtime, "agent1", "x")
    line(copy.root, 5, "5-agent")
    agents(copy, runtime, "nine.txt")
    line(repo, 5, "5-user")
    (repo / "theirs.txt").write_text("the user's, committed since\n")
    run(repo, "add", "theirs.txt")
    run(repo, "commit", "-qm", "user", "nine.txt", "theirs.txt")
    look = git.branch_look(repo, copy.branch, copy.start, copy.snapshot_sha)
    assert (look["share"], look["conflicts"], look["yours"]) == (None, ["nine.txt"], [])
    # D2: the user's branch merged into the branch, the clash put together there.
    before, _sha, left = git.merge_in(copy.root, copy.branch, "main", runtime / "no-hooks")
    assert left == ["nine.txt"]
    (copy.root / "nine.txt").write_text(NINE.replace("5\n", "5-both\n"))  # (no marks left)
    run(copy.root, "add", "nine.txt")
    run(copy.root, "-c", "core.hooksPath=", "commit", "-qm", "resolved")
    (repo / "theirs.txt").write_text("the user's, edited again\n")  # (not committed)
    look = git.branch_look(repo, copy.branch, copy.start, copy.snapshot_sha)
    assert (look["conflicts"], look["yours"]) == ([], []) and look["share"]
    # What came in from the user's branch is not the agent's: not on the card, not in the way.
    assert (look["files"], look["dirty"]) == ({"nine.txt": "M"}, ["staged.txt"])
    diffs = git.branch_diffs(repo, copy.branch, ["nine.txt"], at=look["since"])["nine.txt"]
    assert "-5-user" in diffs and "+5-both" in diffs
    assert run(repo, "diff", "--name-only", "HEAD", look["share"]).split() == ["nine.txt"]
    assert run(repo, "show", f"{look['share']}:nine.txt").splitlines()[4] == "5-both"
    assert before != run(copy.root, "rev-parse", "HEAD")


@needs_merge_base
def test_a_share_git_cannot_make_is_refused(repo, runtime):
    (repo / "new.txt").write_text("new\n")
    copy = copies.make_branch(repo, runtime, "agent1", "x")
    with pytest.raises(git.Refused):
        git.agents_share(repo, copy.snapshot_sha, "0" * 40)


# --- the runner merges, shows and pushes the agents' work alone (W-1 Task 3, (A).3, answer 3) ----

MINE = {"notes.txt": "the user's own\n", "a.txt": "one\ntwo-mine\n"}
# The user's line not committed, which the agent's edit of "two" changes too.
ON_YOURS = {"a.txt": "one\ntwo-mine\n"}


def said_yes(client, cid):
    """A branch that began from uncommitted work: its pull request waits for the user's click
    (`PR_SNAPSHOT`), at Full auto too - given here."""
    merge = until(
        client,
        cid,
        lambda s: s["merges"] and (s["merges"][0].get("branch") or {}).get("note") == PR_SNAPSHOT,
        timeout=LONG,
    )["merges"][0]
    assert client.post(f"/api/merges/{merge['id']}/approve", json={"shown": {}}).status_code == 200


def landed(repo):
    """The files the project's last commit changed."""
    return run(repo, "show", "--name-only", "--format=", "HEAD").split()


@needs_merge_base
def test_an_agent_on_a_branch_sees_your_uncommitted_work_and_the_merge_brings_its_work_alone(
    make_client, wait_run, repo
):
    client, cid, run_id = on_branch(
        make_client,
        repo,
        [
            step(call("read_file", {"path": "notes.txt"}, "r")),
            step(edit("two", "TWO-agent")),
            text("A done"),
        ],
        wip=MINE,
    )
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    (read,) = calls(snap, "Coder", "read_file")
    assert read[0] == "succeeded" and "the user's own" in read[1]
    (merge,) = snap["merges"]
    assert merge["status"] == "applied" and [f["path"] for f in merge["files"]] == ["lines.txt"]
    assert landed(repo) == ["lines.txt"] and lines(repo)[1] == "TWO-agent"
    assert porcelain(repo) == [" M a.txt", "?? notes.txt"]  # (theirs, as they left it)
    assert run(repo, "branch", "--list", "koloni/*") == "" and len(worktrees(repo)) == 1


@needs_merge_base
def test_the_agent_changed_your_uncommitted_file_so_nothing_is_merged_until_you_commit_it(
    make_client, wait_run, repo
):
    # (a.txt: `on_branch` writes lines.txt anew as the turn starts.)
    client, cid, run_id = on_branch(
        make_client,
        repo,
        [step(edit("two", "TWO-agent", path="a.txt")), text("A done")],
        wip=ON_YOURS,
    )
    merge = card(client, cid)  # (at Full auto too: the user's word)
    assert merge["branch"]["dirty"] == ["a.txt"] and merge["branch"]["conflicts"] == []
    assert merge["branch"]["note"] == BRANCH_ON_YOURS.format(files="a.txt")
    assert "resolve" not in merge["branch"]  # (no agent puts the user's lines together)
    head = run(repo, "rev-parse", "HEAD")
    assert client.post(f"/api/merges/{merge['id']}/approve").status_code == 200
    merge = card(client, cid)
    assert run(repo, "rev-parse", "HEAD") == head
    assert (repo / "a.txt").read_text() == ON_YOURS["a.txt"]
    run(repo, "commit", "-qam", "mine")
    assert client.post(f"/api/merges/{merge['id']}/approve").status_code == 200
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert [m["status"] for m in snap["merges"]] == ["applied"]
    assert (repo / "a.txt").read_text() == "one\nTWO-agent-mine\n" and landed(repo) == ["a.txt"]


@needs_merge_base
def test_a_pull_request_never_carries_your_uncommitted_files(make_client, wait_run, repo, github):
    bare, _log = github
    client, cid, run_id = pr_run(make_client, repo, lambda: pushed_main(repo), wip=MINE)
    said_yes(client, cid)  # (a branch from uncommitted work: asked, at Full auto too)
    snap = wait_run(client, cid, run_id, timeout=LONG)
    (merge,) = snap["merges"]
    assert merge["commit"]["state"] == "pull_request", merge["branch"]
    pushed = run(bare, "rev-parse", "refs/heads/koloni/fix")
    assert run(bare, "log", "-1", "--format=%P", pushed) == run(repo, "rev-parse", "HEAD")
    assert run(bare, "diff", "--name-only", f"{pushed}^", pushed).split() == ["lines.txt"]
    assert run(bare, "show", f"{pushed}:a.txt") == "one\ntwo"  # (main's, not the user's edit)
    assert porcelain(repo) == [" M a.txt", "?? notes.txt"]


@needs_merge_base
def test_a_pull_request_over_your_uncommitted_lines_pushes_nothing(
    make_client, wait_run, repo, github
):
    bare, _log = github
    held = Gate()
    client, cid, _run_id = on_branch(
        make_client,
        repo,
        [step(edit("two", "TWO-agent", path="a.txt")), held.step(text("A done"))],
        wip=ON_YOURS,
        project={"finish_way": "pull_request"},
    )
    held.wait_partial()
    pushed_main(repo)
    held.release()
    said_yes(client, cid)
    merge = until(
        client,
        cid,
        lambda s: (
            "no pull request" in (((s["merges"] or [{}])[0].get("branch") or {}).get("note") or "")
        ),
        timeout=LONG,
    )["merges"][0]
    assert BRANCH_ON_YOURS.format(files="a.txt") in merge["branch"]["note"]
    assert run(bare, "for-each-ref", "refs/heads/koloni/") == ""


@needs_merge_base
def test_an_agent_gone_on_with_on_its_branch_is_measured_from_the_snapshot_it_began_from(
    make_client, wait_run, repo
):
    client, cid, run_id = on_branch(
        make_client,
        repo,
        [*STOP_ON_BRANCH, step(edit("TWO-agent", "TWO-again", "e2")), text("done")],
        then=[GO_ON],
        wip=MINE,
    )
    snap = wait_run(client, cid, run_id, timeout=LONG)
    (merge,) = snap["merges"]
    assert merge["status"] == "applied" and [f["path"] for f in merge["files"]] == ["lines.txt"]
    assert landed(repo) == ["lines.txt"] and lines(repo)[1] == "TWO-again"
    assert porcelain(repo) == [" M a.txt", "?? notes.txt"]


@needs_merge_base
def test_a_branch_whose_agent_changed_nothing_goes_with_its_snapshot(make_client, wait_run, repo):
    # (It wrote the user's own file as it was: nothing of its own - the branch holds the snapshot
    # alone, which git counts as not merged.)
    client, cid, run_id = on_branch(
        make_client, repo, [step(write("notes.txt", MINE["notes.txt"])), text("A done")], wip=MINE
    )
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["runs"][0]["status"] == "completed" and snap["merges"] == []
    assert run(repo, "branch", "--list", "koloni/*") == "" and len(worktrees(repo)) == 1
    assert porcelain(repo) == [" M a.txt", "?? notes.txt"]


@needs_merge_base
def test_a_task_beside_another_leaves_the_firsts_work_in_progress_alone(
    make_client, wait_run, repo, gate
):
    (repo / "first.txt").write_text("the first task's, not done\n")  # (in the project: its own)
    client, pid, _first, cid = beside(make_client, repo, gate)
    merge = card(client, cid)
    assert [f["path"] for f in merge["files"]] == ["b.txt"] and merge["branch"]["dirty"] == []
    assert client.post(f"/api/merges/{merge['id']}/approve").status_code == 200
    worked(client, wait_run, pid, "Second task")
    assert landed(repo) == ["b.txt"] and porcelain(repo) == ["?? first.txt"]
    gate.release()


@needs_merge_base
@pytest.mark.parametrize("offered", [True, False])
def test_a_branch_in_the_way_of_an_uncommitted_take_in_names_it_and_merges_after_its_commit(
    make_client, wait_run, repo, offered
):
    (repo / "lines.txt").write_bytes(LINES.encode())
    (repo / "check.py").write_bytes(CHECK.encode())
    run(repo, "add", "-A")
    run(repo, "commit", "-qm", "lines")
    client, _model = make_client(
        {
            "Lead": [
                step(call("spawn_agent", {"role": "Coder", "task": "seven"}, "s1")),
                step(
                    call("spawn_agent", {"role": "Coder", "task": "two", "on_branch": "fix"}, "s2")
                ),
                text("done"),
            ],
            "Coder": [step(edit("seven", "SEVEN-a", "e1")), text("A done")],
            "Coder 2": [step(edit("two", "TWO-b", "e2")), text("B done")],
        }
    )
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(repo)}).json()["id"]
    # (Where the project offers a commit of what was taken in, the card says to make it there.)
    assert client.patch(f"/api/projects/{pid}", json={"git_commit": offered}).status_code == 200
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    assert (
        client.patch(
            f"/api/conversations/{cid}",
            json={"permission_mode": "full_auto", "spawn_approval": "never"},
        ).status_code
        == 200
    )
    run_id = client.post(f"/api/conversations/{cid}/messages", json={"content": "go"}).json()[
        "run"
    ]["id"]
    snap = until(
        client,
        cid,
        lambda s: [m["status"] for m in s["merges"]] == ["applied", "pending"],
        timeout=LONG,
    )
    taken, merge = snap["merges"]
    name = next(a["name"] for a in snap["agents"] if a["id"] == taken["agent_id"])
    # (Its work changes what the snapshot held of the Take in, not committed: said, and asked.)
    assert merge["branch"]["dirty"] == ["lines.txt"]
    assert merge["branch"]["note"] == BRANCH_OVER_YOURS.format(files="lines.txt")
    assert merge["branch"]["taken_in"] == TAKEN_IN_FIRST.format(
        files="lines.txt", name=name, how="commit it on its card" if offered else "commit it"
    )
    run(repo, "commit", "-qam", "the Take in")
    assert client.post(f"/api/merges/{merge['id']}/approve").status_code == 200
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert [m["status"] for m in snap["merges"]] == ["applied", "applied"]
    assert lines(repo)[1] == "TWO-b" and lines(repo)[6] == "SEVEN-a"


def test_a_branch_from_your_last_commit_says_so_on_its_card(
    make_client, wait_run, repo, monkeypatch
):
    monkeypatch.setattr(git, "merge_base_known", lambda _git: False)
    client, cid, run_id = on_branch(
        make_client, repo, [step(edit("two", "TWO-agent")), text("A done")], wip=MINE
    )
    snap = wait_run(client, cid, run_id, timeout=LONG)
    (merge,) = snap["merges"]
    version = run(repo, "--version").removeprefix("git version ").split()[0]
    assert merge["branch"]["started"] == FROM_HEAD.format(
        branch="koloni/fix", why=git.OLD_GIT.format(version=version)
    )
    assert merge["status"] == "applied" and merge["branch"]["note"] is None
    assert porcelain(repo) == [" M a.txt", "?? notes.txt"]


# --- a branch copy's file merges line by line from what it was made of (W-1 Task 4) -------------


def crlf(text):
    return text.replace("\n", "\r\n").encode()


@needs_merge_base
def test_a_branch_copys_file_merges_line_by_line_from_what_it_was_made_of(repo, runtime):
    from app.agent.merge import _kept_files

    run(repo, "config", "core.autocrlf", "true")  # (checked out with CRLF line ends, kept LF)
    (repo / "nine.txt").write_bytes(crlf(NINE))
    run(repo, "add", "nine.txt")
    run(repo, "commit", "-qm", "nine")
    mine = NINE.replace("1\n", "1-mine\n", 1)
    (repo / "nine.txt").write_bytes(crlf(mine))  # (not committed: the snapshot holds it)
    copy = copies.make_branch(repo, runtime, "agent1", "x")
    assert copy.started_from("nine.txt") == crlf(mine) == (copy.root / "nine.txt").read_bytes()
    (copy.root / "nine.txt").write_bytes(crlf(mine.replace("9\n", "9-agent\n")))
    (repo / "nine.txt").write_bytes(crlf(mine.replace("5\n", "5-user\n")))
    files = _kept_files(copy, False)
    assert files["nine.txt"]["state"] == "merged", files["nine.txt"].get("note")
    # Believed no further than its digest: a file the copy did not start from is not.
    copy.base[copies._key("nine.txt")] = "0" * 64
    assert copy.started_from("nine.txt") is None


# --- a kept branch copy after a restart (W-1 Task 5) ---------------------------------------------


@needs_merge_base
@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_after_a_restart_a_kept_branch_copy_merges_line_by_line_and_its_branch_goes_with_it(
    make_client, wait_run, repo, decision
):
    from app.agent import recover_copies
    from app.db.models import Agent

    numbered(repo)
    (repo / "notes.txt").write_text("the user's own\n")  # (not committed: the snapshot holds it)
    client, _model = make_client([text("hi")])
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(repo)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    run_id = client.post(f"/api/conversations/{cid}/messages", json={"content": "go"}).json()[
        "run"
    ]["id"]
    (lead,) = wait_run(client, cid, run_id)["agents"]
    root = client.app.state.settings.runtime_root
    copy = copies.make_branch(repo, root, lead["id"], "x")  # (its agent at work: a crash)
    assert copy.snapshot_sha
    with client.app.state.session_factory() as session:
        session.get_one(Agent, lead["id"]).copy = {
            "state": "own",
            "tree": str(copy.root),
            "on_branch": copy.branch,
            "start": list(copy.start),
            "snapshot": copy.snapshot_sha,
        }
        session.commit()
    line(copy.root, 9, "9-agent")  # (its work, not committed when the app stopped)
    line(repo, 5, "5-user")  # (the user's, meanwhile)
    recover_copies(client.app.state.session_factory, root)  # (as at the next start)
    (merge,) = client.get(f"/api/conversations/{cid}").json()["merges"]
    assert [(f["path"], f["state"]) for f in merge["files"]] == [("nine.txt", "merged")]
    assert client.post(f"/api/merges/{merge['id']}/{decision}").status_code == 200
    took = decision == "approve"
    assert (repo / "nine.txt").read_text().splitlines()[4::4] == [
        "5-user",
        "9-agent" if took else "9",
    ]
    assert run(repo, "branch", "--list", "koloni/*") == "" and len(worktrees(repo)) == 1
    assert not os.path.lexists(copy.root)
    assert "?? notes.txt" in porcelain(repo)


@needs_merge_base
def test_a_kept_copys_branch_is_believed_only_where_its_agents_record_names_its_tree(
    make_client, wait_run, repo, tmp_path
):
    from app.agent.merge import _as_branch, _kept_branch
    from app.db.models import Agent

    client, _model = make_client([text("hi")])
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(repo)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    run_id = client.post(f"/api/conversations/{cid}/messages", json={"content": "go"}).json()[
        "run"
    ]["id"]
    (lead,) = wait_run(client, cid, run_id)["agents"]
    held = tmp_path / "copies" / "agent1"
    said = {
        "state": "own",
        "tree": str(held / copies.TREE),
        "on_branch": "koloni/x",
        "start": ["main", "a" * 40],
        "snapshot": "b" * 40,
    }
    with client.app.state.session_factory() as session:
        for record, found in (
            (said, ("koloni/x", ("main", "a" * 40), "b" * 40)),
            ({**said, "tree": str(tmp_path / "other")}, None),
            ({**said, "on_branch": "main"}, None),
            ({**said, "start": "main"}, None),
        ):
            session.get_one(Agent, lead["id"]).copy = record
            got = _kept_branch(session, lead["id"], held)
            assert (got and (got["branch"], got["start"], got["snapshot"])) == found or (
                got is None and found is None
            )
        loaded = copies.Copy(repo, held / copies.TREE, {}, {}, {})
        _as_branch(loaded, _kept_branch(session, lead["id"], held))
        assert loaded.branch is None  # (the last record named no start it could be held to)
