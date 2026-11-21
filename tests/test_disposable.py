"""Disposable deletes (coordination §4): a delete KOLONİ can check by itself - a plain line's build
or cache folder, a clean worktree, a merged branch - may go without a card where the user allowed
it in the project. First what a line could delete: anything else on the line, any form not read
here, is no such delete."""

import asyncio
import os
import sys
import time
from types import SimpleNamespace

import pytest

from app import disposable, koloni
from app import git as git_
from app.agent.ctx import Ctx
from app.command_runner import CommandRunner
from app.commands import disposable_targets
from app.db.models import Agent, Command, Conversation, Message, Project, Run, ToolCall
from app.db.session import make_engine, make_session_factory, upgrade_db
from tests.conftest import Gate, scaled
from tests.fakes import Script, ScriptedExecutor
from tests.keyed import OWN
from tests.test_agent_commands import approve, cmd
from tests.test_agy_agent import agy_app  # noqa: F401  (a fixture)
from tests.test_agy_agent import start as start_agy
from tests.test_chat_flow import start_in_mode, text
from tests.test_claim_scenarios import write
from tests.test_codex_app_server_scenarios import ACCEPT, DECLINE, RUN, answers
from tests.test_copilot_agent import copilot_native  # noqa: F401  (a fixture)
from tests.test_copilot_agent import start as start_copilot
from tests.test_copy_scenarios import run
from tests.test_native_agent import native_app  # noqa: F401  (a fixture)
from tests.test_native_agent import start as start_native
from tests.test_spawn import call, step
from tests.test_take_in_scenarios import git, needs_git, repository
from tests.test_trigger_scenarios import run_now, trigger


@pytest.mark.parametrize(("line", "targets"), [
    ("rm -rf build", [("folder", "build", True)]),
    ("Remove-Item -Recurse -Force dist", [("folder", "dist", True)]),
    ("rm -r build dist", [("folder", "build", False), ("folder", "dist", False)]),
    ("rm -R frontend/dist", [("folder", "frontend/dist", False)]),
    ("Remove-Item -LiteralPath .pytest_cache -Recurse", [("folder", ".pytest_cache", False)]),
    ("git worktree remove ../wt/x", [("worktree", "../wt/x", False)]),
    ("git worktree remove /tmp/wt/x", [("worktree", "/tmp/wt/x", False)]),
    ("git branch -d old", [("branch", "old", False)]),
    ("git branch -D a b", [("branch", "a", True), ("branch", "b", True)]),
    ("git branch -d feature/v1.2", [("branch", "feature/v1.2", False)]),
])
def test_a_plain_line_names_what_it_would_delete(line, targets):
    assert disposable_targets(line) == targets


@pytest.mark.parametrize("line", [
    # (the plan's)
    "rm -rf build && x", "rm -rf ../build", "rm -rf /tmp/build", "rm -rf src", "rm -rf build/*",
    "rm -rf .git/build", "rm -rf node_modules/x/build", "rmdir /s /q build", "cmd /c rd /s build",
    "git worktree remove -f x", "git -C x branch -d y", "git branch -d",
    "git push origin --delete x",
    # A folder: recursive, by a bare deleter, flags it knows, each path one of the names, plainly
    # below where it runs - no dot-part above it, no linked folder, no name Windows reads as
    # another (`node_modules.`), no trailing slash (`build/` is where a link leads).
    "rm -f build", "rm build", "rm -rf", "rm -rf -- build", "rm -rf build/", "rm -rf ./build",
    "rm -rf a//build", "rm -rf Build", "rm -rf build.", "rm -rf NODE_MODULES/build",
    "rm -rf node_modules./build", "rm -rf .venv/build", "rm -rf venv/dist", "rm -rf build src",
    "rm.exe -rf build", "/bin/rm -rf build", "Remove-Item -Rec build", "rm -rfv build",
    "rm -rf --no-preserve-root build", "unlink build", "rmdir build", "rd build",
    # Nothing a shell reads past a plain word: a quote, a backslash, a drive, a comment, a
    # splat, a variable, a tab or another space.
    "rm -rf 'build'", "rm -rf a\\build", "rm -rf C:build", "Remove-Item -Recurse -Path:build",
    "rm -rf build #x", "Remove-Item -Recurse @p", "rm -rf $x/build", "rm\t-rf build",
    "rm -rf\u00a0build", "rm -rf build\u000bx", "rm -rf ~/build", "rm -rf build; ls",
    "rm  -rf build", " rm -rf build", "Remove-Item –Recurse build",
    # A worktree: exactly `git worktree remove <path>`.
    "git worktree remove --force x", "git worktree remove x y", "git worktree remove",
    "git worktree remove ../wt/.x", "git worktree remove .git/worktrees/x",
    "git worktree remove node_modules/x", "git worktree remove C:/wt/x",
    "git worktree remove ..\\wt\\x", "git worktree remove -- x", "git worktree prune",
    "git worktree remove ../wt/x/", "git worktree remove wt./x",
    # A branch: exactly `git branch -d|-D <name>...`, none KOLONİ's own.
    "git branch -d koloni/x", "git branch -D Koloni/x", "git branch -d -f x",
    "git branch --delete x", "git branch -dr x", "git branch -d -r origin/x",
    "git branch -d .x", "git branch -d a/.b", "git branch -d x.", "git branch -d x -D y",
    "git branch x", "git branch -m a b", "GIT branch -d x", "git.exe branch -d x",
    "git branch -d @{-1}", "git branch -d x:y", "git branch -d -- x",
])
def test_anything_else_is_no_disposable_delete(line):
    assert disposable_targets(line) is None


@pytest.mark.parametrize("line", [
    "rm -rf build `\n src", "rm -rf bu\\\nild", "git branch -d old `\n -f",
    "git worktree remove ../wt/x \\\n--force", "rm -rf build`\r\n", "rm -rf build \\\n",
])
def test_a_continued_line_is_no_disposable_delete_however_a_shell_joins_it(line):
    # (sh joins `bu\⏎ild` into `build`, PowerShell runs `ild` as a command of its own: a line
    # that two shells read two ways is never freed by either reading - `commands.joined`)
    assert disposable_targets(line) is None


def test_a_project_asks_as_before_until_the_user_allows_disposable_deletes_on_its_own_page(
        client, project_dir):
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    assert client.get(f"/api/projects/{pid}").json()["disposable_deletes"] is False
    for on in (True, False):
        assert client.patch(f"/api/projects/{pid}", json={"disposable_deletes": on}).status_code == 403
        assert client.patch(f"/api/projects/{pid}", json={"disposable_deletes": on},
                            headers=OWN).json()["disposable_deletes"] is on
    # (the user's own, of this KOLONİ: never from the folder's .koloni/settings.json)
    assert "disposable_deletes" not in koloni.SETTINGS


BUILD = {"what": "build folder build", "allowed": True}


def runner_at(tmp_path, mode, allows=True, calls=9):
    """A command runner over a chat at `mode` in a project that allows disposable deletes or not;
    each card it would show is turned down and counted (`runner.asked`)."""
    db = tmp_path / "r.db"
    upgrade_db(db)
    factory = make_session_factory(make_engine(db))
    with factory() as s:
        s.add(Project(id="p", name="p", root_path=str(tmp_path), disposable_deletes=allows))
        s.flush()
        s.add(Conversation(id="c", project_id="p", permission_mode=mode))
        s.flush()
        s.add(Run(id="r", conversation_id="c", status="running"))
        s.flush()
        s.add(Agent(id="a", run_id="r", role_name="Lead", tools=[]))
        s.flush()
        s.add(Message(id="m", conversation_id="c", run_id="r", role="assistant"))
        s.flush()
        for n in range(calls):
            s.add(ToolCall(id=f"t{n}", run_id="r", agent_id="a", message_id="m", seq=n,
                           provider_call_id=f"k{n}", name="run_command", arguments="{}",
                           status="running"))
        s.commit()
    runner = CommandRunner(factory, SimpleNamespace(emit=lambda *_: None), None, lambda **_: None)
    runner.asked = []

    async def no(run_id, cid, agent_id, command_id, rule):
        runner.asked.append(command_id)
        return "reject"

    runner._wait_for_decision = no
    return runner, factory


def test_a_disposable_delete_goes_without_its_levels_card_only_where_the_project_allows_it(
        tmp_path):
    runner, factory = runner_at(tmp_path, "auto_edit")

    def asked(call, line="rm -rf build", **given):
        ran, command_id = asyncio.run(runner.ask_for("r", "c", "a", call, line, cwd=".", **given))
        with factory() as s:
            return ran, command_id in runner.asked, s.get_one(Command, command_id).disposable

    unasked = {"what": "build folder build", "unasked": True}
    assert asked("t0", disposable=BUILD) == (True, False, unasked)
    # (what asks at every level still asks: a secret, a reason of the caller's)
    assert asked("t1", "rm -rf build .env", disposable=BUILD)[1]
    assert asked("t2", always=True, disposable=BUILD)[1:] == (True, {**unasked, "unasked": False})
    # (one not found allowed asks, and keeps what was disposable of it for its card)
    assert asked("t3", disposable={**BUILD, "allowed": False}) == (
        False, True, {**unasked, "unasked": False})
    assert asked("t4") == (False, True, None)
    # (a turn nobody watches runs it by its trigger's leave, not as disposable)
    assert asked("t5", ask=False, disposable=BUILD) == (True, False, {**unasked, "unasked": False})
    # Read again as it is decided: at Ask, or with the project's switch off, the card stays.
    with factory() as s:
        s.get_one(Conversation, "c").permission_mode = "ask"
        s.commit()
    assert asked("t6", disposable=BUILD)[1]
    with factory() as s:
        s.get_one(Conversation, "c").permission_mode = "auto_edit"
        s.get_one(Project, "p").disposable_deletes = False
        s.commit()
    assert asked("t7", disposable=BUILD) == (False, True, {**unasked, "unasked": False})
    # (at Full auto too, where nothing of the level asks: its caller made no ask of its own)
    with factory() as s:
        s.get_one(Conversation, "c").permission_mode = "full_auto"
        s.commit()
    assert asked("t8", disposable=BUILD) == (False, True, {**unasked, "unasked": False})


def proposed(client, cid, line):
    """The card of `line`, once it waits."""
    deadline = time.monotonic() + scaled(5)
    while time.monotonic() < deadline:
        snap = client.get(f"/api/conversations/{cid}").json()
        if found := [c for c in snap["commands"]
                     if (c["command"], c["status"]) == (line, "proposed")]:
            return found[0]
        time.sleep(0.02)
    raise AssertionError(f"{line} never waited: {snap['commands']}")


# --- what of it is disposable: checked against its folder and the project's git (3.4) --------

def junction(link, target):
    """`link` a junction to `target` (Windows), else a symbolic link."""
    if sys.platform == "win32":
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
    else:
        os.symlink(target, link)


def unlinked(link):
    if sys.platform == "win32":
        link.rmdir()
    else:
        link.unlink()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A project with git: build/, dist/ and .next/ ignored, a commit on main; a branch `old`
    at that commit (merged) and `ahead` one past it; a build folder with a file in it."""
    empty = tmp_path / "gitconfig"
    empty.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    project = tmp_path / "proj"
    project.mkdir()
    (project / ".gitignore").write_text("build/\ndist/\n.next/\n*.db\n")
    (project / "a.txt").write_text("a\n")
    repository(project)
    git(project, "branch", "old")
    git(project, "branch", "ahead")
    git(project, "switch", "-q", "ahead")
    (project / "b.txt").write_text("b\n")
    git(project, "add", "b.txt")
    git(project, "commit", "-q", "-m", "b")
    git(project, "switch", "-q", "main")
    (project / "build").mkdir()
    (project / "build" / "out.txt").write_text("made\n")
    return project


def judged(project, line, cwd=".", root=None, in_copy=False, copies_at=(), keep=None):
    return disposable.what(line, project, root or project, cwd, in_copy=in_copy,
                           copies_at=list(copies_at), keep=keep)


@needs_git
def test_a_build_folder_is_disposable_where_git_ignores_it_holds_nothing_tracked_and_no_link(
        repo, tmp_path, monkeypatch):
    assert judged(repo, "rm -rf build") == "build folder build"
    (repo / "web" / "dist").mkdir(parents=True)
    assert judged(repo, "rm -r dist", cwd="web") == "build folder dist"
    assert judged(repo, "rm -rf web/dist") == "build folder web/dist"
    assert judged(repo, "rm -rf build web/dist") == "build folder build; build folder web/dist"
    # Not: nothing there; not ignored; a file git tracks in it; a link in it, or itself a link.
    assert judged(repo, "rm -rf .next") is None
    (repo / "target").mkdir()
    (repo / "target" / "x").write_text("x")
    assert judged(repo, "rm -rf target") is None
    (repo / "dist").mkdir()
    (repo / "dist" / "keep.txt").write_text("kept\n")
    git(repo, "add", "-f", "dist/keep.txt")
    assert judged(repo, "rm -rf dist") is None
    # (git 2.53 calls no folder ignored that holds a file it tracks; one that did is no wall)
    with monkeypatch.context() as patched:
        patched.setattr(git_, "ignored", lambda project, paths, above=False: set(paths))
        assert judged(repo, "rm -rf dist") is None
        assert judged(repo, "rm -rf build") == "build folder build"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    junction(repo / "build" / "in", elsewhere)
    assert judged(repo, "rm -rf build") is None
    unlinked(repo / "build" / "in")
    assert judged(repo, "rm -rf build") == "build folder build"
    (repo / "web" / "dist").rmdir()
    junction(repo / "web" / "dist", elsewhere)
    assert judged(repo, "rm -rf web/dist") is None
    # (a folder of the path a link: what is deleted is not where it is spelt)
    unlinked(repo / "web" / "dist")
    (repo / "web" / "dist").mkdir()
    junction(repo / "lib", repo / "web")
    assert judged(repo, "rm -rf web/dist") == "build folder web/dist"
    assert judged(repo, "rm -rf lib/dist") is None
    # (and only a line the parser reads)
    assert judged(repo, "rm -rf build && ls") is None


@needs_git
def test_in_a_copy_a_build_folder_is_judged_by_the_projects_git_and_nothing_else_is_disposable(
        repo, tmp_path):
    copy = tmp_path / "copies" / "a" / "tree"
    (copy / "build").mkdir(parents=True)
    (copy / "src").mkdir()
    assert judged(repo, "rm -rf build", root=copy, in_copy=True) == "build folder build"
    assert judged(repo, "rm -rf src", root=copy, in_copy=True) is None
    assert judged(repo, "git branch -d old", root=copy, in_copy=True) is None
    assert judged(repo, "rm -rf build", root=copy, cwd=None, in_copy=True) is None


@needs_git
def test_a_clean_worktree_of_the_users_is_disposable_and_none_of_koloni_s_locked_or_holding_more(
        repo, tmp_path):
    git(repo, "worktree", "add", "-q", "-b", "feat", str(tmp_path / "wt" / "x"))
    assert judged(repo, "git worktree remove ../wt/x") == "worktree ../wt/x"
    git(repo, "worktree", "lock", str(tmp_path / "wt" / "x"))
    assert judged(repo, "git worktree remove ../wt/x") is None
    git(repo, "worktree", "unlock", str(tmp_path / "wt" / "x"))
    (tmp_path / "wt" / "x" / ".env").write_text("KEY=1\n")
    assert judged(repo, "git worktree remove ../wt/x") is None
    (tmp_path / "wt" / "x" / ".env").unlink()
    junction(tmp_path / "wt" / "x" / "in", tmp_path / "wt")
    assert judged(repo, "git worktree remove ../wt/x") is None
    unlinked(tmp_path / "wt" / "x" / "in")
    assert judged(repo, "git worktree remove ../wt/x") == "worktree ../wt/x"
    # (git deletes what it ignores with the worktree: a build folder may go, nothing else)
    (tmp_path / "wt" / "x" / "build").mkdir()
    (tmp_path / "wt" / "x" / "build" / "out.txt").write_text("made\n")
    assert judged(repo, "git worktree remove ../wt/x") == "worktree ../wt/x"
    (tmp_path / "wt" / "x" / "local.db").write_text("the user's own\n")
    assert judged(repo, "git worktree remove ../wt/x") is None
    (tmp_path / "wt" / "x" / "local.db").unlink()
    # (the main one - from a project that is a worktree itself too -, a folder git does not
    # list, one under KOLONİ's copies)
    assert judged(repo, "git worktree remove ../proj") is None
    assert judged(tmp_path / "wt" / "x", "git worktree remove ../../proj") is None
    (tmp_path / "wt" / "y").mkdir()
    assert judged(repo, "git worktree remove ../wt/y") is None
    held = tmp_path / "copies"
    git(repo, "worktree", "add", "-q", "-b", "held", str(held / "b" / "tree"))
    assert judged(repo, "git worktree remove ../copies/b/tree", copies_at=[held]) is None
    assert judged(repo, "git worktree remove ../copies/b/tree") == "worktree ../copies/b/tree"


@needs_git
def test_a_merged_local_branch_no_one_stands_on_is_disposable(repo, tmp_path):
    assert git_.default_branch(repo) == "main"
    assert judged(repo, "git branch -d old") == "branch old"
    assert judged(repo, "git branch -D old") == "branch old"
    assert git_.ahead(repo, "main", "ahead") == 1
    assert judged(repo, "git branch -D ahead") is None  # (commits only it holds)
    assert judged(repo, "git branch -d ahead") == "branch ahead"  # (git's own -d refuses it)
    assert judged(repo, "git branch -D old ahead") is None
    # Not: the current one, the default one, the turn's own, one a worktree stands on, one
    # that is not there, one spelt in another case, KOLONİ's own.
    git(repo, "switch", "-q", "old")
    assert judged(repo, "git branch -d old") is None
    git(repo, "switch", "-q", "main")
    assert judged(repo, "git branch -d old", keep="old") is None
    git(repo, "branch", "free")
    git(repo, "worktree", "add", "-q", str(tmp_path / "wt" / "f"), "free")
    assert judged(repo, "git branch -d free") is None
    assert judged(repo, "git branch -d nope") is None
    assert judged(repo, "git branch -d Old") is None
    git(repo, "branch", "koloni/x")
    assert judged(repo, "git branch -d koloni/x") is None
    # The default as the remote says it; main and master never.
    git(repo, "switch", "-q", "old")
    assert judged(repo, "git branch -d main") is None
    git(repo, "branch", "develop")
    git(repo, "update-ref", "refs/remotes/origin/develop", "HEAD")
    git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/develop")
    assert git_.default_branch(repo) == "develop"
    assert judged(repo, "git branch -d develop") is None
    assert judged(repo, "git branch -d main") is None


@needs_git
def test_what_git_tracks_under_a_folder(repo):
    assert git_.tracked_under(repo, "build") is False
    (repo / "src").mkdir()
    (repo / "src" / "x.py").write_text("x\n")
    git(repo, "add", "src/x.py")
    assert git_.tracked_under(repo, "src") is True
    assert git_.tracked_under(repo, "sr") is False


# --- the agent runner hands it in: where the user allowed it, at Auto-edit and Full auto (3.5) -

@pytest.fixture
def at_git(project_dir, monkeypatch):
    """The project as a git repository: build/ ignored (and there), a branch `old` merged, and
    KOLONİ's koloni/x."""
    empty = project_dir.parent / "gitconfig"
    empty.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    (project_dir / ".gitignore").write_text("build/\n")
    repository(project_dir)
    git(project_dir, "branch", "old")
    git(project_dir, "branch", "koloni/x")
    (project_dir / "build").mkdir()
    return project_dir


def allowing(client, project_dir, allows):
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    assert client.patch(f"/api/projects/{pid}", json={"disposable_deletes": allows},
                        headers=OWN).status_code == 200
    return pid


@needs_git
@pytest.mark.parametrize("mode", ["full_auto", "auto_edit"])
def test_where_the_user_allowed_it_a_merged_branch_and_a_build_folder_go_without_a_card(
        make_client, wait_run, at_git, mode):
    executor = ScriptedExecutor([Script([""]), Script([""])])
    client, _ = make_client([cmd("git branch -D old", "k1"), cmd("rm -rf build", "k2"),
                             text("done")], executor=executor)
    allowing(client, at_git, True)
    cid, run_id = start_in_mode(client, at_git, mode)
    snap = wait_run(client, cid, run_id)
    assert [(c["command"], c["status"], c["disposable"]) for c in snap["commands"]] == [
        ("git branch -D old", "exited", {"what": "branch old", "unasked": True}),
        ("rm -rf build", "exited", {"what": "build folder build", "unasked": True})]


@needs_git
def test_at_ask_a_disposable_delete_still_asks(make_client, wait_run, at_git):
    client, _ = make_client([cmd("git branch -D old"), text("done")],
                            executor=ScriptedExecutor([]))
    allowing(client, at_git, True)
    cid, run_id = start_in_mode(client, at_git, "ask")
    card = proposed(client, cid, "git branch -D old")
    assert card["disposable"] == {"what": "branch old", "unasked": False}
    assert client.post(f"/api/commands/{card['id']}/reject").status_code == 200
    wait_run(client, cid, run_id)


@needs_git
def test_allow_such_deletes_on_its_card_turns_the_switch_on_and_runs_it_and_koloni_s_branch_asks(
        make_client, wait_run, at_git):
    executor = ScriptedExecutor([Script([""]), Script([""])])
    client, _ = make_client([cmd("git branch -D old", "k1"), cmd("git branch -D koloni/x", "k2"),
                             text("done")], executor=executor)
    pid = allowing(client, at_git, False)
    cid, run_id = start_in_mode(client, at_git, "full_auto")
    card = proposed(client, cid, "git branch -D old")
    assert card["disposable"] == {"what": "branch old", "unasked": False}
    sent = f"/api/commands/{card['id']}/approve"
    assert client.post("/api/commands/none/approve", json={"disposable": True}).status_code == 404
    assert client.post(sent, json={"disposable": True, "remember": True}).status_code == 422
    assert client.post(sent, json={"disposable": True}, headers={"Origin": None}).status_code == 403
    assert client.post(sent, json={"disposable": True}).json()["status"] in (
        "approved", "running", "exited")
    assert client.get(f"/api/projects/{pid}").json()["disposable_deletes"] is True
    # KOLONİ's own branch is never disposable: asked though the switch is on, and its card
    # takes no such word.
    plain = proposed(client, cid, "git branch -D koloni/x")
    assert plain["disposable"] is None and plain["danger"]
    assert client.post(f"/api/commands/{plain['id']}/approve",
                       json={"disposable": True}).status_code == 422
    assert approve(client, plain["id"]).status_code == 200
    wait_run(client, cid, run_id)
    assert [line for line, _ in executor.started] == ["git branch -D old", "git branch -D koloni/x"]


@needs_git
@pytest.mark.parametrize("dependencies", [False, True])
def test_in_a_copy_a_build_folder_goes_without_a_card_but_not_one_holding_a_link(
        make_client, wait_run, at_git, tmp_path, dependencies):
    if dependencies:  # (linked into the copy: there any other recursive delete is asked)
        (at_git / "node_modules" / "pkg").mkdir(parents=True)
        (at_git / "node_modules" / "pkg" / "index.js").write_text("dep")
    made, linked = Gate(), Gate()
    client, _ = make_client({
        "Lead": [step(call("spawn_agent", {"role": "Coder", "task": "do it"}, "s")),
                 text("done")],
        "Coder": [step(write("a.txt", "A")), made.step(step(run("rm -rf build", "c1"))),
                  linked.step(step(run("rm -rf build", "c2"))), text("A done")],
    }, executor=ScriptedExecutor([Script([""])]))
    pid = allowing(client, at_git, True)
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    assert client.patch(f"/api/conversations/{cid}", json={
        "permission_mode": "full_auto", "spawn_approval": "never"}, headers=OWN).status_code == 200
    run_id = client.post(f"/api/conversations/{cid}/messages",
                         json={"content": "go"}).json()["run"]["id"]
    try:
        made.wait_partial()
        (copy,) = client.app.state.runner._copies.values()
        (copy.root / "build").mkdir()
        made.release()
        linked.wait_partial()
        (tmp_path / "elsewhere").mkdir()
        junction(copy.root / "build" / "in", tmp_path / "elsewhere")
    finally:
        made.release()
        linked.release()
    card = proposed(client, cid, "rm -rf build")
    assert card["disposable"] is None and card["danger"]
    assert client.post(f"/api/commands/{card['id']}/reject").status_code == 200
    first = wait_run(client, cid, run_id)["commands"][0]
    assert (first["status"], first["disposable"]) == (
        "exited", {"what": "build folder build", "unasked": True})


@needs_git
def test_a_turn_nobody_watches_gets_no_disposable_delete_unasked(make_client, wait_run, at_git):
    executor = ScriptedExecutor([])
    client, _ = make_client([cmd("git branch -D old"), text("done")], executor=executor)
    pid = allowing(client, at_git, True)
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    assert client.patch(f"/api/conversations/{cid}", json={"permission_mode": "full_auto"},
                        headers=OWN).status_code == 200
    client.headers["Origin"] = OWN["Origin"]  # (a trigger is the user's, from their page)
    run_id = run_now(client, trigger(client, pid, cid)["id"])
    snap = wait_run(client, cid, run_id)
    assert snap["commands"] == [] and executor.started == []
    (refused,) = [t for t in snap["tool_calls"] if t["name"] == "run_command"]
    assert refused["status"] == "denied", refused


@needs_git
@pytest.mark.parametrize("allows", [True, False])
def test_a_clis_own_disposable_delete_where_its_folder_is_known(
        native_app, wait_run, at_git, allows):  # noqa: F811
    client, provider, _ = native_app([{"run": "git branch -D old", "output": ""}, {"say": "ok"}])
    allowing(client, at_git, allows)
    cid, run_id = start_native(client, at_git, provider, "full_auto")
    if not allows:
        assert proposed(client, cid, "git branch -D old")["disposable"] == {
            "what": "branch old", "unasked": False}
        assert client.post(f"/api/commands/{proposed(client, cid, 'git branch -D old')['id']}"
                           "/reject").status_code == 200
    (ran,) = wait_run(client, cid, run_id)["commands"]
    assert (ran["origin"], ran["disposable"]) == ("cli", {"what": "branch old", "unasked": allows})
    assert answers(native_app) == [(RUN, ACCEPT if allows else DECLINE)]


@needs_git
@pytest.mark.parametrize("parameters", [
    {"CommandLine": "rm -rf build", "Cwd": "."},  # (agy's Cwd: its model's word)
    {"CommandLine": "rm -rf build"},  # (no folder: where its shell stands is not known)
])
def test_a_clis_delete_where_its_folder_is_its_models_word_or_not_known_is_never_disposable(
        agy_app, wait_run, at_git, parameters):  # noqa: F811
    client, cli, _ = agy_app([{"tool": "run_command", "asks": True, "parameters": parameters,
                               "output": ""}, {"say": "left it"}], mode="native")
    allowing(client, at_git, True)
    cid, run_id = start_agy(client, at_git, cli, "full_auto")
    card = proposed(client, cid, "rm -rf build")
    assert card["disposable"] is None
    assert client.post(f"/api/commands/{card['id']}/reject").status_code == 200
    wait_run(client, cid, run_id, 30)


@needs_git
def test_only_a_watched_turn_of_its_own_at_auto_edit_or_full_auto_gets_it_unasked(
        make_client, at_git):
    client, _ = make_client([])
    runner = client.app.state.runner
    pid = allowing(client, at_git, True)
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]

    def allowed(mode="full_auto"):
        assert client.patch(f"/api/conversations/{cid}", json={"permission_mode": mode},
                            headers=OWN).status_code == 200
        ctx = Ctx(run_id="r", cid=cid, root=str(at_git), agent_id="a", role="Lead", tools=(),
                  depth=0)
        found = asyncio.run(runner._disposable(ctx, "git branch -D old", at_git, ".", False))
        assert found["what"] == "branch old"
        return found["allowed"]

    assert allowed() is True and allowed("auto_edit") is True
    assert allowed("ask") is False
    # Not a turn nobody watches, a side of a comparison, a job while the user is away, a To-do
    # task's turn.
    for place in (runner._unwatched, runner._sides, runner._away_jobs):
        place["r"] = "a"
        assert allowed() is False
        del place["r"]
    runner._backlog_turns.add("r")
    assert allowed() is False
    runner._backlog_turns.discard("r")
    assert client.patch(f"/api/projects/{pid}", json={"disposable_deletes": False},
                        headers=OWN).status_code == 200
    assert allowed() is False


@needs_git
def test_a_look_that_fails_is_no_disposable_delete_and_its_card_as_before(
        make_client, wait_run, at_git, monkeypatch):
    def broken(*_args, **_kwargs):
        raise ValueError("a path on another drive")

    monkeypatch.setattr(disposable, "what", broken)
    client, _ = make_client([cmd("git branch -D old"), text("done")],
                            executor=ScriptedExecutor([]))
    allowing(client, at_git, True)
    cid, run_id = start_in_mode(client, at_git, "full_auto")
    card = proposed(client, cid, "git branch -D old")
    assert card["disposable"] is None
    assert client.post(f"/api/commands/{card['id']}/reject").status_code == 200
    assert wait_run(client, cid, run_id)["runs"][0]["status"] == "completed"


@needs_git
def test_a_delete_whose_folder_changed_while_the_turn_waited_is_asked(
        make_client, wait_run, at_git, tmp_path):
    client, _ = make_client([cmd("rm -rf build"), text("done")], executor=ScriptedExecutor([]))
    runner = client.app.state.runner
    looked = runner._keeps_answered
    (tmp_path / "elsewhere").mkdir()

    async def meanwhile(ctx, own=False):
        # (a card of the turn waited for: another agent's link in the folder meanwhile)
        junction(at_git / "build" / "in", tmp_path / "elsewhere")
        await looked(ctx, own)

    runner._keeps_answered = meanwhile
    allowing(client, at_git, True)
    cid, run_id = start_in_mode(client, at_git, "full_auto")
    card = proposed(client, cid, "rm -rf build")
    assert card["disposable"] is None and card["danger"]
    snap = client.get(f"/api/conversations/{cid}").json()
    assert snap["tool_calls"][0]["why_asked"] == disposable.CHANGED
    assert client.post(f"/api/commands/{card['id']}/reject").status_code == 200
    wait_run(client, cid, run_id)


@needs_git
def test_copilots_delete_from_a_new_shell_is_never_disposable(
        copilot_native, wait_run, at_git):  # noqa: F811
    # (as a delete in the scratch: 1.0.67 has no sandbox, and a link a script makes after the
    # look is followed by the delete - `commands.scratch_delete_only`)
    client, provider = copilot_native([{"shell": "git branch -D old"}, {"say": "ok"}],
                                      version="1.0.105")
    allowing(client, at_git, True)
    cid, run_id = start_copilot(client, at_git, provider)
    card = proposed(client, cid, "git branch -D old")
    assert (card["cwd"], card["disposable"]) == (".", None)
    assert client.post(f"/api/commands/{card['id']}/reject").status_code == 200
    wait_run(client, cid, run_id)
