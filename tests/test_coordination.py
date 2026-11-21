"""Coordination (A): agents at work beside each other, each in a copy of its own, do each other
no harm. One way into the project at a time - a Take in waits while a branch merges - and a copy
made meanwhile, or one already made, gets what went in."""

import os
import re
import shutil
import sys
import threading
import time
from pathlib import Path

import pytest

import app.agent as agent_module
from app import copies, git
from app.agent import ALONGSIDE, AgentRunner, recover_copies
from app.commands import (
    KILLS_BY_NAME,
    NAMES_PROJECT,
    OUT_OF_COPY,
    copy_reason,
    harm_class,
    harms,
    installs,
    runs_another,
)
from app.db.models import Agent
from app.tools import ON_BRANCH_PROPERTY, OPENED_TOGETHER
from tests.conftest import Gate, scaled
from tests.fakes import Script, ScriptedExecutor
from tests.test_agent_commands import cmd
from tests.test_agent_writes import wait_status
from tests.test_chat_flow import text
from tests.test_claim_scenarios import ORIGIN, calls, setup, two, write
from tests.test_dal_takim import on_branch, repo, run, runtime, worktrees  # noqa: F401
from tests.test_full_auto_harm import why_asked
from tests.test_full_auto_reads import LIVE
from tests.test_judge_scenarios import RULE, begin, judging, verdict_line  # noqa: F401
from tests.test_parallel import until
from tests.test_spawn import call, spawn, step
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
        assert looked.wait(scaled(LONG))  # (the Coder 2's Take in has looked at its copy)
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


@needs_git
def test_a_stop_while_a_branch_merges_waits_for_git_and_the_merge_is_on_record(
    make_client, wait_run, repo, monkeypatch  # noqa: F811
):
    merging, go = threading.Event(), threading.Event()
    real = git.merge_branch

    def merge_branch(*args, **kwargs):
        merging.set()
        assert go.wait(scaled(LONG))  # (held until the Stop is in)
        return real(*args, **kwargs)

    monkeypatch.setattr(git, "merge_branch", merge_branch)
    client, cid, run_id = on_branch(make_client, repo, [step(edit("two", "TWO-agent")),
                                                        text("A done")])
    assert merging.wait(scaled(LONG))
    assert client.post(f"/api/runs/{run_id}/cancel").status_code == 202
    go.set()
    snap = wait_run(client, cid, run_id, timeout=LONG)
    # (git merged: the way in was held until it was over, and what it did is on record)
    assert lines(repo)[1] == "TWO-agent"
    assert [m["status"] for m in snap["merges"]] == ["applied"]
    assert run(repo, "branch", "--list", "koloni/*") == "" and len(worktrees(repo)) == 1


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


# --- what a copy's command is asked ----------------------------------------------------------

# By a name that is not KOLONİ's own (python, node, uvicorn): the user's words may let it run.
KILLS = ["taskkill /IM notepad.exe /F", "taskkill /f /im chrome.exe", "taskkill //F //IM x.exe",
         "pkill vite", "killall ruby", "Stop-Process -Name java", "spps -n code",
         "kill -Name java"]
# By a name KOLONİ itself may run under, a filter, a wildcard, or a process looked up (by its
# port, say: 8790 is KOLONİ's) - always asked.
KILLS_KOLONI = [
    "taskkill /IM python.exe /F", "taskkill /f /im node.exe", "taskkill /FI \"PID gt 0\" /F",
    "pkill -f uvicorn", "pkill -f server", "killall node", "Stop-Process -Name python",
    "spps -n node", "kill -Name pythonw", "taskkill /IM py.exe", "Stop-Process -Name *",
    "Stop-Process -Name node -ErrorAction 0", "Stop-Process -Name node -InformationAction Ignore",
    "Stop-Process -Name node -ia 0", "Stop-Process -Name $n",
    "Stop-Process -Id (Get-Process python).Id -Force",
    "Stop-Process -InputObject (Get-Process python)", "(Get-Process python).Kill()",
    "$p = Get-Process python; $p.Kill()", "Get-Process node | % { $_.Kill() }",
    "kill $(pgrep node)", "pgrep node | xargs kill", "lsof -ti:3000 | xargs kill -9",
    "kill -9 $(lsof -t -i:8000)",
    "Get-NetTCPConnection -LocalPort 8000 | % { Stop-Process -Id $_.OwningProcess -Force }",
    "Stop-Process -Id (Get-NetTCPConnection -LocalPort 8790).OwningProcess -Force",
    'wmic process where name="node.exe" delete', "wmic process where processid=1 call terminate",
    "Invoke-CimMethod -Query \"select * from Win32_Process\" -MethodName Terminate",
    "fuser -k 8000/tcp", "npx kill-port 3000", "npx -y kill-port 8790", "fkill node",
]
KILLS_HANDED = ["Get-Process python | Stop-Process", 'cmd /c "taskkill /IM x.exe"']
BY_ID = ["taskkill /PID 1234 /F", "kill 1234", "kill -9 1234", "Stop-Process -Id 1234",
         "Stop-Process 1234", "Stop-Process -Force 1234", "Stop-Process -Id:1234",
         "$p = Start-Process python -PassThru; Stop-Process -Id $p.Id"]


@pytest.mark.parametrize("command", KILLS)
def test_stopping_programs_by_name_in_the_project_is_harm_the_users_words_may_let_run(command):
    assert harms(command) == KILLS_BY_NAME and harm_class(command) == "soft"


@pytest.mark.parametrize("command", KILLS_KOLONI)
def test_stopping_what_may_be_koloni_itself_is_always_asked(command):
    assert harms(command) == KILLS_BY_NAME and harm_class(command) == "always", command


@pytest.mark.parametrize("command", KILLS_HANDED)
def test_stopping_programs_by_name_handed_on_is_asked_at_every_level(command):
    assert harms(command) == KILLS_BY_NAME and harm_class(command) == "always"
    assert runs_another(command)


@pytest.mark.parametrize("command", KILLS + KILLS_KOLONI + KILLS_HANDED)
def test_from_a_copy_stopping_programs_by_name_is_always_asked(command):
    assert copy_reason(command, False, "/work/proj", "/work/rt") == KILLS_BY_NAME


@pytest.mark.parametrize("command", BY_ID)
def test_stopping_a_program_by_its_id_is_no_harm(command):
    assert harms(command) == "" and copy_reason(command, True, "/work/proj", "/work/rt") == ""


@pytest.mark.parametrize("command", [
    "rm -rf taskkill /etc", 'rm -rf "my-taskkill" /home', "rm -rf x; echo taskkill /home"])
def test_only_taskkills_own_switches_are_no_paths(command):
    assert harm_class(command) == "always"


def places(tmp_path):
    """A project, KOLONİ's runtime, this copy's own tree in its copies folder, the folder, and
    one of the project's worktrees."""
    root = tmp_path / "runtime"
    held = copies.folders(root)[0]
    return tmp_path / "proj", root, held / "a" / "tree", held, tmp_path / "wt" / "x"


def asked_in_copy(tmp_path, command, cwd="."):
    project, runtime, own, _held, worktree = places(tmp_path)  # noqa: F811
    return copy_reason(command, True, str(project), runtime, own, cwd,
                       [str(project), str(worktree)])


def test_a_copys_command_naming_another_copy_a_worktree_or_above_it_is_asked(tmp_path):
    _project, _runtime, own, held, worktree = places(tmp_path)
    for command, named in [
        ("cp x ../../b/tree/y", "../../b/tree/y"), (r"echo x > ..\base.json", r"..\base.json"),
        (f"Set-Content {held / 'b' / 'tree' / 'x.txt'} hi", str(held)),
        (f"Copy-Item x {worktree}/y", str(worktree)), ("cd src; cp x ../../y", "../../y"),
        ("cd ..; ls", ".."), ("ls -la ../..", "../.."),
        # (by its own full path, and up out of it)
        (f"cp x {own}/../../b/tree/y", f"{own}/../../b/tree/y"),
        # (quoted, glued to an option or a redirect)
        ('cp x --target-directory="../../b/tree"', "../../b/tree"),
        ('echo x >"../base.json"', "../base.json"),
        ('Copy-Item x -Destination:"../../b/tree/y"', "../../b/tree/y"),
    ]:
        assert asked_in_copy(tmp_path, command) == OUT_OF_COPY.format(path=named), command
    # (from where it runs: a folder of the copy)
    assert asked_in_copy(tmp_path, "cp x ../y", "src") == ""
    assert asked_in_copy(tmp_path, "cp x ../../y", "src") == OUT_OF_COPY.format(path="../../y")


def test_a_copys_command_naming_its_own_copy_or_below_is_not_asked(tmp_path):
    _project, _runtime, own, _held, _worktree = places(tmp_path)
    for command in [f"python {own}/x.py > {own}/out.txt", *LIVE, "git log HEAD..main",
                    "git diff main...HEAD", f"cd {own}/src && pytest", "cd src; cp x ../y",
                    "cd src && cd .. && pytest"]:
        assert asked_in_copy(tmp_path, command) == "", command


def test_before_its_copy_is_made_every_copy_is_anothers(tmp_path):
    project, runtime, own, held, _worktree = places(tmp_path)  # noqa: F811
    said = copy_reason(f"type {own}/x.txt", False, str(project), runtime)
    assert said == OUT_OF_COPY.format(path=str(held))


def spellings(path):
    """A full path as a command may write it, doubled and dotted separators and all."""
    forms = [re.sub(r"[\\/]", lambda one: one[0] * 2, path),  # (`C:\\Users\\...`)
             re.sub(r"(?<=.)[\\/]", lambda one: f"{one[0]}.{one[0]}", path),  # (`C:\.\Users`)
             path.replace(os.sep, os.sep * 2, 1)]  # (one doubled anywhere)
    if sys.platform == "win32":
        head, _sep, tail = path.rpartition("\\")
        forms += [path.replace("\\", "//"), f"/{path[0]}{path[2:]}".replace("\\", "//"),
                  f"{head}.\\{tail}"]  # (`proj.\x`: Windows drops a name's last dots)
    return forms


def test_a_full_path_with_doubled_or_dotted_separators_is_still_seen(tmp_path):
    project, runtime, own, held, worktree = places(tmp_path)  # noqa: F811
    for path, said in [(str(project / "x"), NAMES_PROJECT.format(root=str(project))),
                       (str(held / "b" / "tree" / "x"), OUT_OF_COPY.format(path=str(held)))]:
        for spelt in spellings(path):
            for command in (f"cp y {spelt}", f"python -c \"open('{spelt}','w')\""):
                assert asked_in_copy(tmp_path, command) == said, command


def test_a_copies_folder_by_the_users_environment_is_still_seen(tmp_path, monkeypatch):
    # (conftest puts the user's data folder at <tmp>/user-data: here it is under their home)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "user-data"))
    project, runtime, own, _held, _worktree = places(tmp_path)  # noqa: F811
    users = copies.folders(runtime)[-1]  # (the user's data folder's: `copies._both`)
    rest = users.relative_to(tmp_path).as_posix()
    spelt = [f"$HOME/{rest}", f"${{HOME}}/{rest}", f"~/{rest}"]
    if sys.platform == "win32":
        local = users.relative_to(tmp_path / "user-data")
        spelt += [f"%LOCALAPPDATA%\\{local}", f"$env:LOCALAPPDATA/{local.as_posix()}",
                  f"%USERPROFILE%\\{users.relative_to(tmp_path)}"]
    for one in spelt:
        command = f"cp y {one}/b/tree/x"
        said = copy_reason(command, False, str(project), runtime, own)
        assert said == OUT_OF_COPY.format(path=str(users)), command


@pytest.mark.parametrize("command", [
    'cmd /c "npm i x"', 'powershell -c "pip install x"', "npm --prefix web install x",
    "pnpm --filter web add x", "pnpm -C web i", "yarn --cwd web add x", "yarn", "npm update",
    "npm up x", "npm rebuild", "npm dedupe", "npm prune", "npm link ../lib", "yarn up x",
    "yarn upgrade", "pnpm update", "poetry update", "pip3.12 install x", "py -m pip install x",
    "python -I -m pip install x", "python3 -m pip uninstall x", "pipenv install x",
])
def test_an_install_however_it_is_written_is_one(command):
    assert installs(command), command


@pytest.mark.parametrize("command", [
    "npm run build", "npm test", "yarn test", "yarn --version", "pip list", "pip --version",
    "npx create-vite x", "pnpm dlx x", "python -m pytest", "py -m venv env", "npm run install-x",
])
def test_what_installs_nothing_is_none(command):
    assert installs(command) == "", command


@pytest.mark.parametrize("command", ["python -m venv --clear .venv", "virtualenv .venv",
                                     "py -m venv --clear venv"])
def test_in_a_copy_with_links_making_a_venv_anew_is_asked(command):
    assert "rebuild" in copy_reason(command, True, "/work/proj", "/work/rt")


def chat(make_client, folder, scripts, executor):
    """A chat at Full auto whose Lead runs commands and opens sub-agents unasked, its first
    message sent: the client, the chat's and the run's ids."""
    client, _model = make_client(scripts, executor=executor)
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(folder)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    assert client.patch(f"/api/conversations/{cid}", json={
        "permission_mode": "full_auto", "spawn_approval": "never", "lead_hands_code": False,
    }).status_code == 200
    posted = client.post(f"/api/conversations/{cid}/messages", json={"content": "go"}).json()
    return client, cid, posted["run"]["id"]


def test_an_install_into_a_linked_copy_waits_at_full_auto_and_the_leads_own_runs(
    make_client, wait_run, project_dir
):
    (project_dir / "node_modules").mkdir()  # (linked into the copy: the project's own)
    executor = ScriptedExecutor([Script(["added 1 package\n"])])
    client, cid, run_id = chat(make_client, project_dir, {
        "Lead": [cmd("npm install left-pad", "k1"), spawn("Coder", "add left-pad"),
                 text("done")],
        "Coder": [cmd("npm install left-pad", "k2"), text("left it")]}, executor)
    snap = wait_status(client, cid, "waiting_approval")
    leads, coders = snap["commands"]
    assert leads["status"] == "exited" and coders["status"] == "proposed"
    assert why_asked(snap, coders) == installs("npm install left-pad")
    assert client.post(f"/api/commands/{coders['id']}/reject").status_code == 200
    wait_run(client, cid, run_id)
    assert [command for command, _cwd in executor.started] == ["npm install left-pad"]


@pytest.mark.no_po
@pytest.mark.parametrize("command, said", [
    ("cp x ../../b/tree/y", OUT_OF_COPY.format(path="../../b/tree/y")),
    # (a delete the user's words allow takes no install past its card)
    ("rm notes.txt; npm install left-pad", installs("npm install left-pad")),
])
def test_at_full_auto_a_sub_agents_command_out_of_its_copy_or_into_shared_folders_waits(
    judging, wait_run, project_dir, command, said  # noqa: F811
):
    (project_dir / ".venv").mkdir()  # (linked into the copy: the project's own)
    client, _model, judge, executor = judging(
        {"Lead": [spawn("Coder", "tidy up"), text("done")],
         "Coder": [cmd(command, id="k1"), text("left it")]},
        [verdict_line("run", RULE)], [])
    _, cid, run_id = begin(client, project_dir, "tidy up",
                           rules=f"{RULE} You may delete notes.txt and copy files anywhere.")
    snap = wait_status(client, cid, "waiting_approval")
    (asked,) = snap["commands"]
    assert asked["status"] == "proposed" and why_asked(snap, asked) == said
    assert judge.calls == []  # (asked at every level: not put to the check of the user's words)
    assert client.post(f"/api/commands/{asked['id']}/reject").status_code == 200
    wait_run(client, cid, run_id)
    assert executor.started == []


# --- what agents are told ---------------------------------------------------------------------


@pytest.mark.parametrize("linked", [True, False])
def test_an_agent_in_a_copy_is_told_others_work_beside_it(
    make_client, wait_run, project_dir, monkeypatch, linked
):
    (project_dir / ".venv").mkdir()
    if not linked:  # (as a CLI's copy without the project's dependency folders)
        monkeypatch.setattr(agent_module, "_links_in_copy", lambda model: False)
    client, _model, cid, run_id = setup(make_client, project_dir, {
        "Lead": [spawn("Coder", "write a"), text("done")],
        "Coder": [step(write("a.txt", "A")), text("A done")]})
    snap = wait_run(client, cid, run_id)
    ((_status, told),) = calls(snap, "Coder", "write_file")
    assert ALONGSIDE in told and "never kill programs by name" in told
    assert ("do not install into them or rebuild them" in told) is linked
    assert told.index(ALONGSIDE) < told.index("node_modules, .venv and venv")


def test_the_orchestrator_is_told_to_give_each_its_own_files_and_leave_koloni_branches(
    make_client, wait_run, project_dir
):
    client, model, cid, run_id = setup(make_client, project_dir, {"Lead": [text("done")]})
    wait_run(client, cid, run_id)
    (spawn_agent,) = [one["function"] for one in model.tool_args[0]
                      if one["function"]["name"] == "spawn_agent"]
    assert OPENED_TOGETHER in spawn_agent["description"]
    assert spawn_agent["description"].index(OPENED_TOGETHER) < spawn_agent["description"].index(
        "Available roles")
    # (offered where the project is on a git branch: `_no_branch_here`)
    assert ON_BRANCH_PROPERTY["description"].endswith(
        "never delete, rename or switch to them; KOLONİ removes them.")
