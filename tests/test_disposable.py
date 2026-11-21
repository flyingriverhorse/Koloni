"""Disposable deletes (coordination §4): a delete KOLONİ can check by itself - a plain line's build
or cache folder, a clean worktree, a merged branch - may go without a card where the user allowed
it in the project. First what a line could delete: anything else on the line, any form not read
here, is no such delete."""

import asyncio
import time
from types import SimpleNamespace

import pytest

from app import koloni
from app.command_runner import CommandRunner
from app.commands import disposable_targets
from app.db.models import Agent, Command, Conversation, Message, Project, Run, ToolCall
from app.db.session import make_engine, make_session_factory, upgrade_db
from tests.conftest import scaled
from tests.fakes import Script, ScriptedExecutor
from tests.keyed import OWN
from tests.test_agent_commands import approve, cmd
from tests.test_chat_flow import start_in_mode, text


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


def given(client, disposable):
    """`rm -rf build` handed to the agent runner's commands with `disposable`, as the agent
    runner would; any other line as it is. One it found free goes without the harm ask of a
    watched turn (`always`), which it then does not make."""
    commands = client.app.state.runner.commands
    run = commands.run

    async def handed(run_id, cid, agent_id, ws, call_id, args, **kwargs):
        if args.get("command") == "rm -rf build":
            kwargs["disposable"] = disposable
            kwargs["always"] = kwargs["always"] and not disposable["allowed"]
        return await run(run_id, cid, agent_id, ws, call_id, args, **kwargs)

    commands.run = handed


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


def test_allow_such_deletes_on_a_disposable_deletes_card_turns_the_project_switch_on_and_runs_it(
        make_client, wait_run, project_dir):
    executor = ScriptedExecutor([Script([""]), Script([""])])
    client, _ = make_client([cmd("rm -rf build", "k1"), cmd("pytest -q", "k2"), text("done")],
                            executor=executor)
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    given(client, {**BUILD, "allowed": False})
    cid, run_id = start_in_mode(client, project_dir, "ask")
    card = proposed(client, cid, "rm -rf build")
    assert card["disposable"] == {"what": "build folder build", "unasked": False}
    sent = f"/api/commands/{card['id']}/approve"
    assert client.post("/api/commands/none/approve", json={"disposable": True}).status_code == 404
    assert client.post(sent, json={"disposable": True, "remember": True}).status_code == 422
    assert client.post(sent, json={"disposable": True}, headers={"Origin": None}).status_code == 403
    assert client.post(sent, json={"disposable": True}).json()["status"] in (
        "approved", "running", "exited")
    assert client.get(f"/api/projects/{pid}").json()["disposable_deletes"] is True
    # A card that is no disposable delete takes no such word.
    plain = proposed(client, cid, "pytest -q")
    assert plain["disposable"] is None
    assert client.post(f"/api/commands/{plain['id']}/approve",
                       json={"disposable": True}).status_code == 422
    assert approve(client, plain["id"]).status_code == 200
    wait_run(client, cid, run_id)
    assert [line for line, _ in executor.started] == ["rm -rf build", "pytest -q"]


def test_at_auto_edit_a_delete_found_disposable_runs_without_a_card_and_says_so(
        make_client, wait_run, project_dir):
    executor = ScriptedExecutor([Script([""])])
    client, _ = make_client([cmd("rm -rf build"), text("done")], executor=executor)
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    client.patch(f"/api/projects/{pid}", json={"disposable_deletes": True}, headers=OWN)
    given(client, BUILD)
    cid, run_id = start_in_mode(client, project_dir, "auto_edit")
    (ran,) = wait_run(client, cid, run_id)["commands"]
    assert (ran["status"], ran["disposable"]) == (
        "exited", {"what": "build folder build", "unasked": True})
