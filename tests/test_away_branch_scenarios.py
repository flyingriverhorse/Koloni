"""☾ Away, a job on its own branch (0.1.9): where the project is a git repository, a job works on
`koloni/<task>` in a worktree and commits there; its own `git push` is refused, a script's is cut
(H1); its end commits what is left, keeps the worktree for Take in and puts the branch on record
for the morning - what moved outside it said (H2). Nothing goes into the project by itself, at Full
auto too; a second try and the going-on turn after the user's decisions go on on the same branch.
Every repository here is made by the test, in its folder."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import select

from app import git, parked
from app.agent import AgentRunner
from app.agent.story_branch_mixin import BRANCH_SECRET_GONE
from app.away_branch import AWAY_BRANCH_JOB, NOT_ON_BRANCH_NOW, PUSH_REFUSED
from app.db.away_models import Parked
from app.db.models import Agent, AwayRun, Merge
from app.model_client import ModelUnavailable
from tests.conftest import Gate
from tests.test_agent_writes import edit, write
from tests.test_away_park import call_result, chat, commands_in, run
from tests.test_away_scenarios import ended, evening, go_away, night
from tests.test_away_waiting import decide, waiting
from tests.test_backlog_auto import until
from tests.test_chat_flow import text
from tests.test_git_view import run as git_run
from tests.test_run_checks_scenarios import asked
from tests.test_take_in_scenarios import needs_git, repository

pytestmark = needs_git

ONE = {"jobs": [{"title": "one"}], "kept_out": []}
# The project's test command: one test, passing - what makes the job's checks green.
PASSES = "print('===== 1 passed in 0.01s =====')\n"


@pytest.fixture
def repo(project_dir, monkeypatch):
    # (Nothing of the user's own git settings; a push to a folder on this machine allowed.)
    config = project_dir.parent / "gitconfig"
    config.write_text('[protocol "file"]\n\tallow = always\n')
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    (project_dir / "check.py").write_text(PASSES)
    repository(project_dir)
    return project_dir


def origin_of(repo, url=None):
    """A bare origin beside the project, main pushed to it - or only `url` named as origin."""
    if url is not None:
        git_run(repo, "remote", "add", "origin", url)
        return None
    origin = repo.parent / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True, capture_output=True)
    git_run(repo, "remote", "add", "origin", str(origin))
    git_run(repo, "push", "-q", "origin", "main")
    return origin


def never(*_args, **_kwargs):
    raise AssertionError("a job's work never goes into the project by itself")


def branch_night(make_client, wait_run, repo, steps, mode="full_auto", **project):
    """An evening in `repo` whose one job plays `steps`, the night over: (client, model, pid, the
    night, the job)."""
    # (the Orchestrator writes itself: one agent's steps to script)
    project = {"check_command": f"{sys.executable} check.py", "lead_work": "itself", **project}
    client, model, pid, cid, run_id = evening(
        make_client, repo, steps, mode=mode, plan=ONE, **project
    )
    wait_run(client, cid, run_id)
    assert go_away(client, cid).status_code == 200
    done = ended(client, pid)
    return client, model, pid, done, done["jobs"][0]


def name_of(job):
    return git.BRANCH_PREFIX + git.task_branch("one", job["task_id"])


def lead_record(client, cid):
    """The job's newest Orchestrator's record of its copy."""
    with client.app.state.session_factory() as session:
        found = [
            agent.copy
            for agent in session.scalars(select(Agent).where(Agent.depth == 0))
            if agent.copy and "away" in agent.copy and agent.run_id in runs_of(client, cid)
        ]
    return found[-1]


def runs_of(client, cid):
    return {one["id"] for one in chat(client, cid)["runs"]}


def test_a_job_in_a_repository_works_on_its_branch(make_client, wait_run, repo, monkeypatch):
    origin = origin_of(repo)
    main = git_run(repo, "rev-parse", "main")
    monkeypatch.setattr(AgentRunner, "_merge_branch", never)
    client, _model, _pid, _done, job = branch_night(
        make_client,
        wait_run,
        repo,
        [
            edit(),
            run("git add hello.py", "c1"),
            run("git commit -m agent", "c2"),
            run("git push origin HEAD", "c3"),
            asked(),
            write("new.txt", "left\n", "w2"),
            text("one done"),
        ],
    )
    name, cid = name_of(job), job["conversation_id"]
    first = next(m["content"] for m in chat(client, cid)["messages"] if m["role"] == "user")
    assert first.endswith(AWAY_BRANCH_JOB.format(branch=name))
    # its own git ran there unasked; its push refused, no card, nothing on origin
    assert call_result(client, cid, "c3") == f"error: {PUSH_REFUSED}"
    assert [(c["command"], c["status"]) for c in commands_in(client, cid)][:2] == [
        ("git add hello.py", "exited"),
        ("git commit -m agent", "exited"),
    ]
    assert git_run(origin, "branch", "--list", "koloni/*") == ""
    # run_checks names its branch
    (answer,) = [c["result"] for c in chat(client, cid)["tool_calls"] if c["name"] == "run_checks"]
    assert answer.startswith("CHECKS: green") and f" on {name}; nothing uncommitted." in answer
    # the end: KOLONİ committed what was left, on the branch; the worktree kept for Take in
    log = git_run(repo, "log", "--format=%s|%b", f"main..{name}")
    assert log.splitlines()[-1] == "agent|" and "Koloni-Agent:" in log.splitlines()[0]
    assert job["state"] == "done" and job["mode"] == "push" and len(job["kept"]) == 1
    branch = job["branch"]
    assert (branch["name"], branch["commits"], branch["files"], branch["checks"]) == (
        name,
        2,
        2,
        "green",
    )
    assert branch["tip"] == git_run(repo, "rev-parse", name) and branch["moved"] == []
    record = lead_record(client, cid)
    assert record["on_branch"] == name and record["away"]["refs"]["refs/heads/main"] == main
    # nothing in the project: its branch and its files as they were
    assert git_run(repo, "rev-parse", "main") == main
    assert (repo / "hello.py").read_bytes() == b"print('hi')\n" and not (repo / "new.txt").exists()
    # the push waits for the user's Run under Waiting for you
    (row,) = waiting(client, job_night(client, job))
    assert row["kind"] == "push" and row["what"].startswith(f"Push {name} to origin (")
    assert "one commit by KOLONİ, 2 files · checks ✓ at " + branch["tip"][:7] in row["what"]


def job_night(client, job):
    with client.app.state.session_factory() as session:
        return session.scalar(select(Parked.away_run_id).where(Parked.task_id == job["task_id"]))


def test_a_repository_with_no_origin_has_a_branch_and_no_push(make_client, wait_run, repo):
    client, _model, _pid, done, job = branch_night(
        make_client, wait_run, repo, [edit(), text("one done")]
    )
    assert job["mode"] == "branch" and job["branch"]["commits"] == 1
    assert waiting(client, done["id"]) == []
    # N11: KOLONİ's commit names the Orchestrator as the screen does, not its role "Lead"
    assert git_run(repo, "log", "-1", "--format=%s", name_of(job)) == "Orchestrator: one"
    assert job["branch"]["gone"] is False


@pytest.mark.parametrize("word", ["approve", "reject"])
@pytest.mark.parametrize("retried", [False, True])
def test_a_take_in_or_discard_says_the_branch_is_gone(make_client, wait_run, repo, word, retried):
    # N12: the morning's row still said "On branch … 1 commits … merge it with git, or Take in"
    # after its Take in had deleted the branch. (A second try's Orchestrator holds the record.)
    again = [ModelUnavailable("model server unreachable"), write("b.txt", "b\n")] if retried else []
    client, _model, pid, _done, job = branch_night(
        make_client, wait_run, repo, [edit(), *again, text("one done")]
    )
    (kept,) = job["kept"]
    assert client.post(f"/api/merges/{kept}/{word}").status_code == 200
    assert git_run(repo, "branch", "--list", name_of(job)) == ""
    (job,) = night(client, pid)["jobs"]
    assert job["kept"] == [] and job["branch"]["gone"] is True
    files = ["b.txt", "hello.py"] if retried else ["hello.py"]
    # (and a discarded job is not one that changed nothing)
    assert (job["taken"], job["discarded"]) == ((files, []) if word == "approve" else ([], files))


def test_detached_at_job_start_works_in_a_copy_and_says_why(
    make_client, wait_run, repo, monkeypatch
):
    from app import away_branch

    real, seen = away_branch.mode_of, []

    def at_go_away_on_a_branch(root):
        seen.append(root)
        return ("branch", None) if len(seen) == 1 else real(root)

    monkeypatch.setattr(away_branch, "mode_of", at_go_away_on_a_branch)
    git_run(repo, "checkout", "-q", "--detach")
    client, model, _pid, _done, job = branch_night(
        make_client, wait_run, repo, [edit(), text("one done")]
    )
    assert job["mode"] == "copy" and "HEAD is detached" in job["mode_why"]
    assert job["branch"] is None and job["kept"]
    said = NOT_ON_BRANCH_NOW.format(why=job["mode_why"])
    assert any(said in str(m.get("content")) for m in model.calls[-1])


def test_a_secret_given_in_the_job_drops_its_branch(make_client, wait_run, repo, monkeypatch):
    secret = "s3cr3t-given-in-the-turn-0123456789"
    monkeypatch.setattr(AgentRunner, "given_spellings", lambda _self, _run_id=None: [secret])
    client, _model, _pid, _done, job = branch_night(
        make_client,
        wait_run,
        repo,
        [
            write("key.txt", f"{secret}\n"),
            run("git add key.txt", "c1"),
            run("git commit -m key", "c2"),
            text("one done"),
        ],
    )
    name = name_of(job)
    lines = [m["content"] for m in chat(client, job["conversation_id"])["messages"]]
    assert BRANCH_SECRET_GONE.format(name="Orchestrator", branch=name, earlier="") in lines or any(
        f"its branch {name} was deleted" in line for line in lines
    )
    assert git_run(repo, "branch", "--list", name) == ""


def test_a_worktree_on_another_branch_is_kept_as_a_plain_copy(make_client, wait_run, repo):
    gate = Gate()
    client, _model, pid, cid, run_id = evening(
        make_client,
        repo,
        [edit(), gate.step(text("one done"))],
        plan=ONE,
        check_command=f"{sys.executable} check.py",
        lead_work="itself",
    )
    wait_run(client, cid, run_id)
    go_away(client, cid)
    gate.wait_partial()
    with client.app.state.session_factory() as session:
        tree = next(
            agent.copy["tree"]
            for agent in session.scalars(select(Agent))
            if (agent.copy or {}).get("on_branch")
        )
    git_run(tree, "switch", "-q", "-c", "elsewhere")  # (a script of the job's, say)
    gate.release()
    job = ended(client, pid)["jobs"][0]
    assert job["branch"] is None and job["kept"]
    said = [m["content"] for m in chat(client, job["conversation_id"])["messages"]]
    assert any("not on its branch: its worktree is no longer on" in one for one in said)


def test_a_script_that_moves_main_is_said_in_the_morning(make_client, wait_run, repo):
    gate = Gate()
    client, _model, pid, cid, run_id = evening(
        make_client,
        repo,
        [edit(), gate.step(text("one done"))],
        plan=ONE,
        check_command=f"{sys.executable} check.py",
        lead_work="itself",
    )
    wait_run(client, cid, run_id)
    go_away(client, cid)
    gate.wait_partial()
    before = git_run(repo, "rev-parse", "main")
    after = git_run(repo, "commit-tree", "HEAD^{tree}", "-p", "HEAD", "-m", "a script's")
    git_run(repo, "update-ref", "refs/heads/main", after)
    gate.release()
    job = ended(client, pid)["jobs"][0]
    assert job["branch"]["moved"] == [
        f"Changed outside its branch: main {before[:7]} → {after[:7]}"
    ]


def test_a_retry_goes_on_on_the_same_branch_in_the_same_worktree(make_client, wait_run, repo):
    client, _model, _pid, _done, job = branch_night(
        make_client,
        wait_run,
        repo,
        [edit(), ModelUnavailable("model server unreachable"), write("b.txt", "b\n"), text("done")],
    )
    name = name_of(job)
    runs = chat(client, job["conversation_id"])["runs"]
    assert [one["status"] for one in runs] == ["failed", "completed"]
    assert job["state"] == "done" and len(job["kept"]) == 1  # (the first try's withdrawn)
    files = git_run(repo, "diff", "--name-only", f"main...{name}").split()
    assert sorted(files) == ["b.txt", "hello.py"]
    assert len(git_run(repo, "worktree", "list").splitlines()) == 2


def test_the_report_never_shows_origins_password(make_client, wait_run, repo):
    origin_of(repo, url="https://u:tok3n@example.invalid/x.git")
    client, _model, _pid, done, job = branch_night(
        make_client, wait_run, repo, [edit(), text("one done")]
    )
    assert job["branch"]["origin"] == "https://***@example.invalid/x.git"
    shown = json.dumps([done, waiting(client, done["id"]), client.get("/api/board").json()])
    assert "tok3n" not in shown and "https://***@example.invalid/x.git" in shown
    # (L-B: nor on any record - an agent's copy, the card's jobs - which the page may read)
    with client.app.state.session_factory() as session:
        kept = [agent.copy for agent in session.scalars(select(Agent))]
        kept += [night.jobs for night in session.scalars(select(AwayRun))]
    assert "tok3n" not in json.dumps(kept, default=str)


# --- park and continue on a branch (§10): its lines run in the worktree; it goes on there ------

# A git line of the job's own work but for its `-c`: asked at every level, so parked at Full auto.
MORNING = "git -c core.quotepath=false commit --allow-empty -m morning"


def test_a_parked_line_runs_in_its_worktree_and_the_job_goes_on_on_its_branch(
    make_client, wait_run, repo, monkeypatch
):
    origin_of(repo)
    main = git_run(repo, "rev-parse", "main")
    monkeypatch.setattr(AgentRunner, "_merge_branch", never)
    client, _model, _pid, done, job = branch_night(
        make_client,
        wait_run,
        repo,
        [
            edit(),
            run(MORNING, "c1"),
            text("one done"),
            # (the going-on turn)
            write("later.txt", "later\n"),
            text("went on"),
        ],
    )
    name, cid = name_of(job), job["conversation_id"]
    assert (job["state"], job["why"]) == ("waits", "1 parked")
    line, push = waiting(client, done["id"])
    assert (line["kind"], line["closed"], line["place"]) == ("command", None, "copy")
    assert (push["kind"], push["closed"]) == ("push", parked.LAST)
    night_tip = git_run(repo, "rev-parse", name)
    assert decide(client, done["id"], line["id"], "run").status_code == 200
    until(lambda: len(chat(client, cid)["runs"]) == 2)
    until(lambda: chat(client, cid)["runs"][1]["status"] == "completed")
    # the morning's line ran in the worktree: its commit is on the branch
    log = git_run(repo, "log", "--format=%s", f"{night_tip}..{name}").splitlines()
    assert "morning" in log and len(log) == 2  # (and KOLONİ's of the going-on turn's work)
    assert git_run(repo, "show", f"{name}:later.txt") == "later"
    assert git_run(repo, "rev-parse", "main") == main and not (repo / "later.txt").exists()
    # the push row made again with the new tip, open now
    (push,) = [one for one in waiting(client, done["id"]) if one["kind"] == "push"]
    assert push["closed"] is None and git_run(repo, "rev-parse", name)[:7] in push["what"]
    with client.app.state.session_factory() as session:
        (row,) = session.scalars(select(Parked).where(Parked.kind == "push")).all()
        assert row.data["tip"] == git_run(repo, "rev-parse", name)
        (kept,) = [
            one
            for one in session.scalars(select(Merge).where(Merge.kept_in.is_not(None)))
            if one.status == "interrupted"
        ]
        assert kept.kept_in == row.data["tree"]


def test_a_parked_line_is_closed_once_the_worktree_changed_after_it(make_client, wait_run, repo):
    client, _model, _pid, done, _job = branch_night(
        make_client,
        wait_run,
        repo,
        [run(MORNING, "c1"), edit(), text("one done")],
    )
    (line,) = [one for one in waiting(client, done["id"]) if one["kind"] == "command"]
    assert line["closed"] == parked.WROTE_SINCE
    assert decide(client, done["id"], line["id"], "run").status_code == 409


# A script of the project's that pushes, as a test or a build step might (H1).
PUSHES = (
    "import subprocess\n"
    "done = subprocess.run(['git', 'push', 'origin', 'HEAD:refs/heads/x'], capture_output=True,"
    " text=True)\n"
    "print('push exit', done.returncode, done.stderr[-300:])\n"
)


def test_a_jobs_script_push_fails_by_h1_through_run_command(make_client, wait_run, repo):
    (repo / "push.py").write_text(PUSHES)
    git_run(repo, "add", "push.py")
    git_run(repo, "commit", "-qm", "a script that pushes")
    origin = origin_of(repo)
    client, _model, _pid, _done, job = branch_night(
        make_client, wait_run, repo, [run(f"{sys.executable} push.py", "c1"), text("one done")]
    )
    (ran,) = commands_in(client, job["conversation_id"])
    assert ran["status"] == "exited" and "push exit 0" not in ran["output"], ran["output"]
    assert "koloni-no-push" in ran["output"]
    assert git_run(origin, "branch", "--list", "x") == ""


def test_a_morning_line_in_a_jobs_worktree_pushes_nothing_after_a_restart_too(
    make_client, wait_run, repo
):
    from app import copies

    # (git's config is the shared repository's: parked at every level, so at Full auto too)
    line = "git config --get url.koloni-no-push://.pushinsteadof"
    client, _model, _pid, done, _job = branch_night(
        make_client, wait_run, repo, [run(line, "c1"), text("one done"), text("went on")]
    )
    (row,) = waiting(client, done["id"])
    copies._NO_PUSH.clear()  # (a restart: this process's trees forgotten)
    assert decide(client, done["id"], row["id"], "run").status_code == 200
    ran = until(lambda: (one := waiting(client, done["id"])[0])["result"] and one)
    assert ran["result"].startswith("exit code 0"), ran["result"]  # (set: the line found H1's)


# --- L6, L10: a Fix it turn on a job's kept worktree, back from Away ---------------------------

FAILS = "print('===== 1 failed in 0.01s ====='); raise SystemExit(1)\n"


def test_fix_it_on_a_jobs_kept_branch_never_merges_and_pushes_nothing_after_a_restart(
    make_client, wait_run, repo, monkeypatch
):
    from app import copies

    (repo / "check.py").write_text(FAILS)
    git_run(repo, "add", "check.py")
    git_run(repo, "commit", "-qm", "a failing check")
    main = git_run(repo, "rev-parse", "main")
    merged = []

    def merge_branch(*_args, **_kwargs):
        merged.append(True)
        never()

    monkeypatch.setattr(AgentRunner, "_merge_branch", merge_branch)
    client, _model, _pid, _done, job = branch_night(
        make_client,
        wait_run,
        repo,
        [edit(), text("one done"), *(text(f"done {n}") for n in range(12))],
        fix_rounds=1,
    )
    cid = job["conversation_id"]
    snap = chat(client, cid)
    rows = [one for m in snap["messages"] if m["role"] == "checked" for one in m["checked"] or []]
    (held,) = [one for one in rows if one.get("kind") == "not_taken"]
    tree = lead_record(client, cid)["tree"]
    copies._NO_PUSH.clear()  # (a restart: this process's trees forgotten)
    went = client.post(
        f"/api/runs/{snap['runs'][0]['id']}/held/fix",
        json={"merge_id": held["merge_id"], "reply": "fix it"},
    )
    assert went.status_code == 202, went.text
    second = went.json()["run_id"]
    until(
        lambda: (
            next(r for r in chat(client, cid)["runs"] if r["id"] == second)["status"]
            in ("completed", "failed", "cancelled")
        )
    )
    # (a plain copy there, never merged by itself; whatever runs there pushes nothing - H1)
    assert copies._tree_key(Path(tree)) in copies._NO_PUSH
    assert merged == [] and git_run(repo, "rev-parse", "main") == main


# --- L7: after some of its work was taken in, a branch job's git line never runs in the project ---


@pytest.mark.parametrize("line", [MORNING, 'cmd /c "git stash"'])
def test_a_branch_jobs_git_line_never_runs_in_the_project_after_a_take_in(
    make_client, wait_run, repo, line
):
    # (L-A: any line of the job's worktree - a git in a wrapper too, which no reading finds)
    client, _model, _pid, done, job = branch_night(
        make_client, wait_run, repo, [edit(), run(line, "c1"), text("one done")]
    )
    (line,) = [one for one in waiting(client, done["id"]) if one["kind"] == "command"]
    assert line["closed"] is None and line["place"] == "copy"
    with client.app.state.session_factory() as session:  # (some of it taken in: hello.py)
        merge = session.get_one(Merge, job["kept"][0])
        merge.files = [{**one, "state": "applied"} for one in merge.files]
        session.commit()
    (line,) = [one for one in waiting(client, done["id"]) if one["kind"] == "command"]
    assert (line["place"], line["closed"]) == ("project", parked.BRANCH_GIT)
    assert decide(client, done["id"], line["id"], "run").status_code == 409
