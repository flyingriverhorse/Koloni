"""K-dallar: the project's branch switched from the git map - only while no turn of the project
runs, no Take in or kept copy waits and the working tree holds nothing uncommitted - and a turn
that starts meanwhile waits for it. Every repository here is made by the test, in its folder."""

import os
import threading

import pytest
from sqlalchemy import select

from app import git
from app.db.models import Agent, Merge, Run
from tests.test_chat_flow import text
from tests.test_git_view import run
from tests.test_native_agent import native_app  # noqa: F401  (a fixture)
from tests.test_take_in_scenarios import ORIGIN, needs_git, repository

pytestmark = needs_git


@pytest.fixture
def repo(project_dir, monkeypatch):
    # (Nothing of the user's own git settings - a signing key, a hook - in these commits.)
    empty = project_dir.parent / "gitconfig"
    empty.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    repository(project_dir)
    run(project_dir, "branch", "feature")
    return project_dir


def started(make_client, repo, steps):
    client, _model = make_client(steps)
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(repo)}).json()["id"]
    return client, pid


def switch(client, pid, name, new=False):
    return client.post(f"/api/projects/{pid}/git/switch", json={"name": name, "new": new})


def test_what_is_not_committed_keeps_the_branch_where_it_is_and_is_said(repo):
    assert git.unsaved(repo) is None
    (repo / ".koloni" / "tmp").mkdir(parents=True)
    (repo / ".koloni" / "tmp" / "scratch.txt").write_text("x")  # (the agents' scratch: no change)
    assert git.unsaved(repo) is None
    (repo / "hello.py").write_text("print('bye')\n")
    (repo / "new" / "a.txt").parent.mkdir()
    (repo / "new" / "a.txt").write_text("a")
    (repo / ".env").write_text("TOKEN=x\n")  # (a secret is changed all the same)
    assert git.unsaved(repo) == "3 files changed, not saved in git — commit or set aside first"
    (repo / "MERGE_HEAD").write_text("")  # (in the working tree: no merge)
    (repo / ".git" / "MERGE_HEAD").write_text("0" * 40)
    assert git.unsaved(repo) == "a merge is under way in the repository — finish or abort it first"


def test_git_that_does_not_say_whether_files_changed_lets_no_switch_through(
    make_client, repo, monkeypatch
):
    real = git._said

    def said(project, program, until, *args, **more):
        return None if "status" in args else real(project, program, until, *args, **more)

    monkeypatch.setattr(git, "_said", said)
    assert git.unsaved(repo) == "git did not say in time whether files are changed — try again"
    client, pid = started(make_client, repo, [])
    assert switch(client, pid, "feature").status_code == 409
    assert git.where(repo)["branch"] == "main"


def test_switch_and_a_new_branch_from_here_and_what_is_refused(make_client, repo):
    client, pid = started(make_client, repo, [])
    assert client.get(f"/api/projects/{pid}/git").json()["switch_blocked"] is None
    answer = switch(client, pid, "feature")
    assert answer.status_code == 200, answer.text
    assert answer.json()["branch"] == "feature" and git.where(repo)["branch"] == "feature"
    answer = switch(client, pid, "fix/login", new=True)
    assert answer.status_code == 200 and answer.json()["branch"] == "fix/login"
    for name, new, why in (
        ("-f", True, "not a name git takes"), ("a..b", True, "not a name git takes"),
        ("--orphan=x", False, "not a name git takes"), ("main", True, "already"),
        ("nothing", False, "not a branch of the project"),
    ):
        answer = switch(client, pid, name, new)
        assert answer.status_code == 422 and why in answer.json()["detail"], name
    # A remote's branch is not made into a local one (--no-guess).
    run(repo, "update-ref", "refs/remotes/origin/far", "HEAD")
    assert switch(client, pid, "far").status_code == 422
    assert git.where(repo)["branch"] == "fix/login"
    # From the app's own page only: an agent's request does not move the project.
    del client.headers["Origin"]
    assert switch(client, pid, "main").status_code == 403
    assert git.where(repo)["branch"] == "fix/login"


def test_switch_waits_for_work_a_take_in_a_kept_copy_and_a_clean_tree(make_client, wait_run,
                                                                      repo):
    client, pid = started(make_client, repo, [text("done", 1, 1)])
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    run_id = client.post(f"/api/conversations/{cid}/messages", json={"content": "hi"}
                         ).json()["run"]["id"]
    wait_run(client, cid, run_id)
    factory = client.app.state.session_factory

    def refused():
        blocked = client.get(f"/api/projects/{pid}/git").json()["switch_blocked"]
        answer = switch(client, pid, "feature")
        assert answer.status_code == 409 and answer.json()["detail"] == blocked
        return blocked

    with factory() as session:  # (as the record would say it: no model is run)
        session.get_one(Run, run_id).status = "running"
        coder = Agent(run_id=run_id, role_name="Coder", name="Coder", tools=[], depth=1,
                      status="running")
        session.add(coder)
        session.commit()
        coder_id = coder.id
    assert refused() == "Coder is at work — wait for the turn to end"
    with factory() as session:
        session.get_one(Run, run_id).status = "completed"
        session.get_one(Agent, coder_id).status = "completed"
        merge = Merge(run_id=run_id, agent_id=coder_id, files=[])
        session.add(merge)
        session.commit()
        merge_id = merge.id
    assert refused() == "Coder's finished work waits — Take in or Discard it first"
    with factory() as session:
        kept = session.get_one(Merge, merge_id)
        kept.status, kept.kept_in = "interrupted", str(repo)
        session.commit()
    assert refused() == "Coder's work is kept in its copy — Take in or Discard it first"
    with factory() as session:
        session.get_one(Merge, merge_id).status = "discarded"
        session.commit()
    (repo / "hello.py").write_text("print('bye')\n")
    assert refused() == "1 file changed, not saved in git — commit or set aside first"
    run(repo, "checkout", "--", "hello.py")
    assert switch(client, pid, "feature").status_code == 200


def test_a_turn_that_starts_while_the_branch_is_switched_waits_for_it(
    make_client, wait_run, repo, monkeypatch
):
    entered, release, order = threading.Event(), threading.Event(), []
    real_switch, real_where = git.switch, git.where

    def held_switch(*args):
        entered.set()
        assert release.wait(10)
        real_switch(*args)
        order.append("switched")

    def where(project):
        order.append("turn looked")
        return real_where(project)

    monkeypatch.setattr(git, "switch", held_switch)
    monkeypatch.setattr(git, "where", where)
    client, pid = started(make_client, repo, [text("done", 1, 1)])
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    answers = []
    switching = threading.Thread(target=lambda: answers.append(switch(client, pid, "feature")))
    switching.start()
    try:
        assert entered.wait(10)
        run_id = client.post(f"/api/conversations/{cid}/messages", json={"content": "hi"}
                             ).json()["run"]["id"]
        threading.Event().wait(0.5)
        assert "turn looked" not in order  # (it waits: the switch holds the project)
    finally:
        release.set()
        switching.join(10)
    assert answers[0].status_code == 200, answers[0].text
    assert wait_run(client, cid, run_id)["runs"][0]["status"] == "completed"
    assert order[:2] == ["switched", "turn looked"]
    with client.app.state.session_factory() as session:
        assert session.scalars(select(Run.status)).all() == ["completed"]


def test_a_copy_says_the_branch_it_was_made_on(make_client, wait_run, repo):
    # (its Take in card says "made on main, the project is now on ..." once that differs)
    from tests.test_spawn import step
    from tests.test_take_in_scenarios import edit, start

    client, _pid, cid, run_id = start(make_client, repo, [step(edit("two", "TWO")), text("done")])
    wait_run(client, cid, run_id)
    coder = next(a for a in client.get(f"/api/conversations/{cid}").json()["agents"]
                 if a["name"] == "Coder")
    assert coder["copy"] == {"state": "own", "branch": "main"}


# --- agents and branches: reading needs no switch; a switch under another's work is asked ----


@pytest.mark.parametrize(("command", "switches"), [
    ("git switch feature", True), ("git switch -c x", True), ("git checkout feature", True),
    ("git checkout -b x", True), ("cd sub; git switch x", True), ("git checkout -- a.py", False),
    ("git checkout .", False), ("git checkout", False), ("git switch -h", False),
    ("git checkout other --", True), ("git switch -- other", True), ("git checkout -- .", False),
    ("git log feature", False), ("git show feature:a.py", False), ("git diff main...x", False),
])
def test_what_switches_the_branch(command, switches):
    from app.commands import switches_branch

    assert switches_branch(command) is switches


@pytest.mark.parametrize(("command", "outside"), [
    ("git worktree add ../x", True), ("git worktree add -b f ../x main", True),
    # (Asked on every system: off Windows `C:/x` is a folder named `C:` in the project.)
    ("git worktree add C:/x", True), ("git worktree add ~/x", True),
    ("git worktree add /x", True),
    ("git worktree add a/../../x", True), ("git worktree add -- ../x", True),
    ("git worktree add wt", False), ("git worktree add a/../b", False),
    ("git worktree list", False),
])
def test_a_worktree_opened_outside_the_project_is_harm(command, outside):
    from app.commands import danger, harms

    said = "Opens a git worktree outside the project (git worktree add)."
    assert (danger(command) == said) is outside and (harms(command) == said) is outside


def test_a_path_from_the_root_is_outside_by_python_3_13s_isabs_too(monkeypatch, tmp_path):
    from pathlib import PureWindowsPath

    from app.commands import _outside_here
    from app.git import foreign_folder

    # 3.13+ on Windows: whole only with a drive and a root - `/Users/x` is not, git reads C:\Users\x
    monkeypatch.setattr(os.path, "isabs", lambda p: bool(
        PureWindowsPath(p).drive and PureWindowsPath(p).root))
    assert _outside_here("/Users/x") and _outside_here("\\x")
    assert foreign_folder("/Users/x", tmp_path / "p")
    assert not _outside_here("wt") and not foreign_folder("wt", tmp_path / "p")


def test_an_agents_own_switch_is_asked_at_every_level_only_under_anothers_work(
    make_client, wait_run, repo
):
    from tests.fakes import Script, ScriptedExecutor
    from tests.test_agent_commands import cmd
    from tests.test_agent_writes import wait_status
    from tests.test_chat_flow import start_in_mode
    from tests.test_full_auto_harm import why_asked

    executor = ScriptedExecutor([Script(["Switched\n"])])
    client, _ = make_client([cmd("git switch feature", "k1"), text("alone"),
                             cmd("git switch main", "k2"), text("left it")], executor=executor)
    cid, run_id = start_in_mode(client, repo, "full_auto")
    snap = wait_run(client, cid, run_id)
    # Alone: as before - no card; the turn's end says it.
    assert snap["commands"][0]["status"] == "exited" and len(executor.started) == 1
    assert snap["tool_calls"][0]["why_asked"] is None
    with client.app.state.session_factory() as session:
        lead = session.scalars(select(Agent.id).where(Agent.run_id == run_id)).first()
        session.add(Merge(run_id=run_id, agent_id=lead, files=[]))  # (a Take in waits)
        session.commit()
    run_id = client.post(f"/api/conversations/{cid}/messages", json={"content": "again"}
                         ).json()["run"]["id"]
    snap = wait_status(client, cid, "waiting_approval")
    asked = next(c for c in snap["commands"] if c["status"] == "proposed")
    assert why_asked(snap, asked) == "switches the branch under Lead's work"
    # (R125: on the command's own record too, not on the card alone)
    assert asked["danger"] == "switches the branch under Lead's work"
    assert snap["commands"][0]["danger"] == ""
    client.post(f"/api/commands/{asked['id']}/reject")
    wait_run(client, cid, run_id)
    assert len(executor.started) == 1


def test_a_clis_own_switch_under_anothers_work_is_a_card_too(native_app, wait_run, repo):  # noqa: F811
    from tests.test_agent_commands import approve
    from tests.test_agent_writes import wait_status
    from tests.test_codex_app_server_scenarios import ACCEPT, RUN, answers
    from tests.test_full_auto_harm import why_asked
    from tests.test_native_agent import start as start_native

    client, provider, _ = native_app([{"run": "git switch feature", "output": "ok\n"},
                                      {"say": "switched"}])
    pid = client.post("/api/projects", json={"root_path": str(repo)}).json()["id"]
    other = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    with client.app.state.session_factory() as session:  # (a Take in waits in another chat)
        done = Run(conversation_id=other, status="completed")
        session.add(done)
        session.flush()
        coder = Agent(run_id=done.id, role_name="Coder", name="Coder", tools=[], status="completed")
        session.add(coder)
        session.flush()
        session.add(Merge(run_id=done.id, agent_id=coder.id, files=[]))
        session.commit()
    cid, run_id = start_native(client, repo, provider, "full_auto")
    snap = wait_status(client, cid, "waiting_approval")
    (asked,) = snap["commands"]
    assert (asked["status"], asked["origin"]) == ("proposed", "cli")
    assert why_asked(snap, asked) == "switches the branch under Coder's work"
    assert approve(client, asked["id"]).status_code == 200
    wait_run(client, cid, run_id)
    assert answers(native_app) == [(RUN, ACCEPT)]


# --- the security review's round ----------------------------------------------------------


def test_git_that_does_not_answer_at_all_keeps_the_branch_where_it_is(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert git.unsaved(plain) == "git did not say in time whether files are changed — try again"


def test_a_switch_writes_no_ignored_file_of_the_users_over(make_client, repo):
    (repo / ".gitignore").write_text(".env\n")
    run(repo, "add", ".gitignore")
    run(repo, "commit", "-q", "-m", "ignore")
    run(repo, "switch", "-q", "-c", "other")
    (repo / ".env").write_text("SECRET=theirs\n")
    run(repo, "add", "-f", ".env")
    run(repo, "commit", "-q", "-m", "env")
    run(repo, "switch", "-q", "main")
    (repo / ".env").write_text("MINE=keep\n")  # (the user's own, git leaves it out)
    client, pid = started(make_client, repo, [])
    answer = switch(client, pid, "other")
    assert answer.status_code == 422
    assert answer.json()["detail"] == (".env would be written over by other's own: a file of "
                                       "yours git leaves out - move it aside first")
    assert (repo / ".env").read_text() == "MINE=keep\n" and git.where(repo)["branch"] == "main"


def test_a_switch_runs_no_hook_of_the_repositorys(make_client, repo):
    import os

    ran = repo.parent / "hook-ran"
    hooks = repo / ".githooks"
    hooks.mkdir()
    (hooks / "post-checkout").write_text(f"#!/bin/sh\necho ran > '{ran.as_posix()}'\n",
                                         newline="\n")
    os.chmod(hooks / "post-checkout", 0o755)
    run(repo, "add", ".githooks")
    run(repo, "commit", "-q", "-m", "hooks")
    run(repo, "config", "core.hooksPath", ".githooks")  # (a folder an agent could write)
    run(repo, "branch", "hooked")
    run(repo, "switch", "-q", "hooked")  # (git by itself runs it here)
    assert ran.exists()
    run(repo, "switch", "-q", "main")
    ran.unlink()
    client, pid = started(make_client, repo, [])
    assert switch(client, pid, "hooked").status_code == 200
    assert switch(client, pid, "fresh", new=True).status_code == 200
    assert not ran.exists() and git.where(repo)["branch"] == "fresh"
