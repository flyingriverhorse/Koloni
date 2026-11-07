"""Working copies beyond the acceptance set (slice 19b): what the runner does with a copy
that tests/test_copy_scenarios.py does not ask about - an agent below an agent with a copy,
copies kept up to date, changes as records that can be reverted, what a command did, a
decision made over a file that moved on, a turn nobody watches, a restart.

Whole turns on the scripted model; commands are real ones, run in the copy.
"""

import asyncio
import os
import shutil
import time
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app import copies
from app.agent import AgentRunner
from app.claims import Claims
from app.command_runner import CommandRunner
from app.config import load_settings
from app.db.models import Agent, Conversation, FileChange, Merge, Message, Project, Run, ToolCall
from app.db.session import make_engine, make_session_factory, upgrade_db
from app.executors.host import copy_python_path
from app.main import create_app
from app.model_client import ModelUnavailable
from tests.conftest import Gate
from tests.fakes import Script, ScriptedExecutor, ScriptedModel
from tests.keyed import TestClient
from tests.test_chat_flow import text
from tests.test_claim_scenarios import agent, calls, setup, two, write
from tests.test_copy_later_scenarios import MAKES, again, interrupted
from tests.test_copy_scenarios import files, one, run, seen
from tests.test_parallel import until
from tests.test_spawn import call, step
from tests.test_trigger_scenarios import allow, run_now, trigger

ORIGIN = "http://127.0.0.1:8790"


def read(path, id="r"):
    return call("read_file", {"path": path}, id)


def edit(path, old, new, id="e"):
    return call("edit_file", {"path": path, "old_string": old, "new_string": new}, id)


def python(code, id="c"):
    return run(f'python -c "{code}"', id)


def merges(snap):
    return [m["status"] for m in snap["merges"]]


def revert(client, snap, path, last=True):
    """Revert the last (or first) change to a file that is in the project."""
    made = [f for f in snap["file_changes"] if f["path"] == path and f["status"] == "applied"]
    return client.post(f"/api/file-changes/{made[-1 if last else 0]['id']}/revert")


def test_the_files_of_an_agent_below_go_on_to_the_agent_whose_copy_it_changed_them_in(tmp_path):
    table = Claims()
    table.take(tmp_path, "a.txt", "below", line=("owner", "lead"))
    table.take(tmp_path, "b.txt", "owner", line=("lead",))
    table.take(tmp_path, "b.txt", "below", line=("owner", "lead"))
    waiting = table.wait(tmp_path, "a.txt", "other")
    table.release("below", to="owner")
    assert table.of(tmp_path) == [("a.txt", "owner"), ("b.txt", "owner")]
    # whoever waited for it waits for that agent now, and has the file when that is done
    assert (waiting.state, waiting.holder) == ("waiting", "owner")
    table.release("owner")
    assert waiting.state == "held" and table.of(tmp_path) == [("a.txt", "other")]


def test_an_agent_below_one_with_a_copy_works_in_that_copy_and_goes_in_with_it(
    make_client, wait_run, project_dir
):
    above = Gate()
    client, model, cid, run_id = setup(make_client, project_dir, {
        "Lead": [step(call("spawn_agent", {"role": "Coder", "task": "A"}, "s")), text("done")],
        "Coder": [step(write("a.txt", "A")),
                  step(call("spawn_agent", {"role": "Coder", "task": "B"}, "s2")),
                  above.step(text("A done"))],
        "Coder 2": [step(read("a.txt")), step(write("b.txt", "B")), text("B done")],
    })
    above.wait_partial()            # the one below is done; the one above is still at work
    snap = until(client, cid, lambda s: agent(s, "Coder 2")["status"] == "completed")
    assert agent(snap, "Coder")["copy"] == {"state": "own"}
    assert agent(snap, "Coder 2")["copy"] == {"state": "parent"}
    # it read what the agent above it had changed, and nothing of either is in the project
    assert calls(snap, "Coder 2", "read_file")[0][0] == "succeeded"
    assert not (project_dir / "a.txt").exists() and not (project_dir / "b.txt").exists()
    assert snap["merges"] == []
    # what it changed is held by the agent whose copy it is in, until that is taken in
    held = agent(snap, "Coder")["id"]
    assert snap["claims"] == [{"path": "a.txt", "agent_id": held},
                              {"path": "b.txt", "agent_id": held}]
    assert "the changes are taken into the project when Coder's work is over" in calls(
        snap, "Coder 2", "write_file")[0][1]
    above.release()
    snap = wait_run(client, cid, run_id)
    (merge,) = snap["merges"]
    assert merge["agent_id"] == held and merge["status"] == "applied"
    assert files(merge) == {"a.txt": "applied", "b.txt": "applied"}
    assert (project_dir / "b.txt").read_text(encoding="utf-8") == "B"
    assert snap["claims"] == [] and all(f["status"] == "applied" for f in snap["file_changes"])


def test_what_one_agent_put_in_the_project_is_in_the_other_agents_copy(
    make_client, wait_run, project_dir
):
    first, second = Gate(), Gate()
    client, model, cid, run_id = setup(make_client, project_dir, {
        "Lead": [two(), text("done")],
        "Coder": [step(edit("hello.py", "hi", "hello")), first.step(text("A done"))],
        "Coder 2": [step(write("b.txt", "two")), second.step(step(read("hello.py"))),
                    text("B done")],
    })
    first.wait_partial()
    second.wait_partial()           # both have their copies, made from the same project
    first.release()
    until(client, cid, lambda s: merges(s) == ["applied"])
    second.release()
    snap = wait_run(client, cid, run_id)
    ((status, shown),) = calls(snap, "Coder 2", "read_file")
    assert status == "succeeded" and "print('hello')" in shown
    assert merges(snap) == ["applied", "applied"]
    assert (project_dir / "hello.py").read_text(encoding="utf-8") == "print('hello')\n"


def test_changes_taken_from_a_copy_are_records_that_revert_like_any_other(
    make_client, wait_run, project_dir
):
    client, model, cid, run_id = one(make_client, project_dir, [
        step(write("n.txt", "one\n")), step(edit("n.txt", "one", "two", "e1")),
        step(edit("hello.py", "hi", "hello", "e2")), text("A done"),
    ])
    snap = wait_run(client, cid, run_id)
    assert [(f["path"], f["kind"], f["status"]) for f in snap["file_changes"]] == [
        ("n.txt", "create", "applied"), ("n.txt", "modify", "applied"),
        ("hello.py", "modify", "applied")]
    assert (project_dir / "n.txt").read_text(encoding="utf-8") == "two\n"
    # each of the agent's changes is one, as it made it: taken back last first
    assert revert(client, snap, "n.txt", last=False).status_code == 409
    assert revert(client, snap, "n.txt").status_code == 200
    assert (project_dir / "n.txt").read_text(encoding="utf-8") == "one\n"
    assert revert(client, snap, "n.txt", last=False).status_code == 200
    assert not (project_dir / "n.txt").exists()
    assert revert(client, snap, "hello.py").status_code == 200
    assert (project_dir / "hello.py").read_text(encoding="utf-8") == "print('hi')\n"


def test_what_a_command_did_in_the_copy_is_taken_too(make_client, wait_run, project_dir):
    code = ("import os;open('made.txt','w').write('by a command');os.remove('hello.py');"
            "open('blob.bin','wb').write(bytes([255,0,254]));"
            "open('a.txt','a').write(' and more')")
    client, model, cid, run_id = one(make_client, project_dir, [
        step(write("a.txt", "A")), step(python(code)), text("A done"),
    ])
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed"
    (merge,) = snap["merges"]
    assert {f["path"]: (f["kind"], f["state"]) for f in merge["files"]} == {
        "a.txt": ("new", "applied"), "blob.bin": ("new", "applied"),
        "hello.py": ("deleted", "applied"), "made.txt": ("new", "applied")}
    assert (project_dir / "made.txt").read_text(encoding="utf-8") == "by a command"
    assert (project_dir / "a.txt").read_text(encoding="utf-8") == "A and more"
    assert (project_dir / "blob.bin").read_bytes() == bytes([255, 0, 254])
    assert not (project_dir / "hello.py").exists()
    # what is not text has no diff and no record; the rest are records like any other,
    # what the command did under the call that opened the agent
    assert next(f for f in merge["files"] if f["path"] == "blob.bin")["diff"] is None
    opened = agent(snap, "Coder")["tool_call_id"]
    assert sorted((f["path"], f["kind"], f["tool_call_id"] == opened)
                  for f in snap["file_changes"]) == [
        ("a.txt", "create", False), ("a.txt", "modify", True),
        ("hello.py", "delete", True), ("made.txt", "create", True)]
    assert all(f["status"] == "applied" for f in snap["file_changes"])
    assert revert(client, snap, "hello.py").status_code == 200
    assert (project_dir / "hello.py").read_text(encoding="utf-8") == "print('hi')\n"


def test_apply_on_a_conflict_takes_the_copys_file_and_can_be_taken_back(
    make_client, wait_run, project_dir
):
    first = Gate()
    client, model, cid, run_id = one(make_client, project_dir, [
        step(edit("hello.py", "hi", "from the copy")), first.step(text("A done")),
    ])
    first.wait_partial()
    (project_dir / "hello.py").write_text("THE USER'S OWN\n", encoding="utf-8")
    first.release()
    snap = until(client, cid, lambda s: merges(s) == ["pending"])
    (shown,) = snap["merges"][0]["files"]
    # the card shows both sides of it - of the lines that clash, where git merged it
    # (slice 30) - and whose side is taken is the user's to say: nothing is chosen for them
    assert shown["state"] == "conflict"
    assert "-THE USER'S OWN" in (shown.get("clash") or shown["diff"])
    card = snap["merges"][0]["id"]
    assert client.post(f"/api/merges/{card}/approve").status_code == 409
    assert (project_dir / "hello.py").read_text(encoding="utf-8") == "THE USER'S OWN\n"
    assert client.post(f"/api/merges/{card}/approve", json={
        "choices": {"hello.py": "agent"}, "shown": seen(snap["merges"][0])}).status_code == 200
    snap = wait_run(client, cid, run_id)
    assert merges(snap) == ["applied"] and "not applied" not in calls(
        snap, "Lead", "spawn_agent")[0][1]
    assert (project_dir / "hello.py").read_text(encoding="utf-8") == "print('from the copy')\n"
    assert revert(client, snap, "hello.py").status_code == 200
    assert (project_dir / "hello.py").read_text(encoding="utf-8") == "THE USER'S OWN\n"


def test_a_file_that_changed_while_the_card_was_shown_is_asked_about_again(
    make_client, wait_run, project_dir
):
    """B-56, by a Take in that shows no files (no "shown" sent): as the card was last shown."""
    client, model, cid, run_id = one(make_client, project_dir, [
        step(write("a.txt", "A")), step(write("b.txt", "B", "w2")), text("A done"),
    ], permission_mode="ask")
    snap = until(client, cid, lambda s: merges(s) == ["pending"])
    card = snap["merges"][0]["id"]
    (project_dir / "a.txt").write_text("made here meanwhile", encoding="utf-8")
    said = client.post(f"/api/merges/{card}/approve")
    # the yes was to the card as shown, and a file of it moved: none of it is taken
    assert said.status_code == 409
    assert said.json()["detail"] == (
        "a.txt changed since you looked: nothing was taken in. Check the card again")
    assert (project_dir / "a.txt").read_text(encoding="utf-8") == "made here meanwhile"
    assert not (project_dir / "b.txt").exists()
    snap = client.get(f"/api/conversations/{cid}").json()
    assert files(snap["merges"][0]) == {"a.txt": "conflict", "b.txt": "ready"}
    assert snap["runs"][0]["status"] == "waiting_approval"
    assert [c["path"] for c in snap["claims"]] == ["a.txt", "b.txt"]
    assert client.post(f"/api/merges/{card}/reject").status_code == 200
    snap = wait_run(client, cid, run_id)
    assert merges(snap) == ["rejected"]
    assert (project_dir / "a.txt").read_text(encoding="utf-8") == "made here meanwhile"
    told = calls(snap, "Lead", "spawn_agent")[0][1]
    assert "not applied to the project: a.txt, b.txt. " in told
    assert {f["path"]: f["status"] for f in snap["file_changes"]} == {
        "a.txt": "rejected", "b.txt": "rejected"}


def test_apply_of_a_card_as_the_user_saw_it_takes_nothing_once_a_file_of_it_moved(
    make_client, wait_run, project_dir
):
    """B-56: Apply sends what the card showed ("shown"); a file not as that is shown again,
    and only an Apply of the card as it is now is taken - its choices made on it."""
    client, model, cid, run_id = one(make_client, project_dir, [
        step(write("a.txt", "A")), step(write("b.txt", "B", "w2")), text("A done"),
    ], permission_mode="ask")
    snap = until(client, cid, lambda s: merges(s) == ["pending"])
    card = snap["merges"][0]
    seen = {f["path"]: f["shown"] for f in card["files"]}
    (project_dir / "a.txt").write_text("made here meanwhile", encoding="utf-8")
    said = client.post(f"/api/merges/{card['id']}/approve", json={"shown": seen})
    assert said.status_code == 409 and said.json()["detail"].startswith("a.txt changed since")
    assert not (project_dir / "b.txt").exists()
    fresh = client.get(f"/api/conversations/{cid}").json()["merges"][0]
    assert files(fresh) == {"a.txt": "conflict", "b.txt": "ready"}
    assert "made here meanwhile" in fresh["files"][0]["diff"]
    # the old card again, with a choice made for the file as it is now: still nothing
    said = client.post(f"/api/merges/{card['id']}/approve",
                       json={"shown": seen, "choices": {"a.txt": "agent"}})
    assert said.status_code == 409
    assert (project_dir / "a.txt").read_text(encoding="utf-8") == "made here meanwhile"
    assert not (project_dir / "b.txt").exists()
    now = {f["path"]: f["shown"] for f in fresh["files"]}
    done = client.post(f"/api/merges/{card['id']}/approve",
                       json={"shown": now, "choices": {"a.txt": "agent"}})
    assert done.status_code == 200 and done.json()["status"] == "applied"
    assert (project_dir / "a.txt").read_text(encoding="utf-8") == "A"
    assert (project_dir / "b.txt").read_text(encoding="utf-8") == "B"
    wait_run(client, cid, run_id)


def two_files(make_client, project_dir, second="b.txt"):
    """A card of a.txt and another file; what it showed of them, by path."""
    client, model, cid, run_id = one(make_client, project_dir, [
        step(write("a.txt", "A")), step(write(second, "B", "w2")), text("A done"),
    ], permission_mode="ask")
    snap = until(client, cid, lambda s: merges(s) == ["pending"])
    card = snap["merges"][0]
    return client, snap, cid, run_id, card["id"], {f["path"]: f["shown"] for f in card["files"]}


def test_a_file_the_copy_got_after_the_card_is_not_taken_and_the_answer_says_what_was(
    make_client, wait_run, project_dir
):
    client, snap, cid, run_id, card, seen = two_files(make_client, project_dir)
    (here(client, snap) / "late.txt").write_text("late", encoding="utf-8")
    said = client.post(f"/api/merges/{card}/approve", json={"shown": seen})
    assert said.status_code == 409 and said.json()["detail"] == (
        "a.txt, b.txt taken in; late.txt changed since you looked and was not. "
        "Check the card again")
    assert (project_dir / "b.txt").read_text(encoding="utf-8") == "B"
    assert not (project_dir / "late.txt").exists()
    fresh = client.get(f"/api/conversations/{cid}").json()["merges"][0]
    assert files(fresh) == {"a.txt": "applied", "b.txt": "applied", "late.txt": "ready"}
    assert client.post(f"/api/merges/{card}/reject").status_code == 200
    wait_run(client, cid, run_id)


def test_a_file_of_the_card_that_is_refused_since_is_said_and_nothing_is_taken(
    make_client, wait_run, project_dir, tmp_path
):
    """Its path in the project now runs through a link: it is no file to take any more."""
    client, snap, cid, run_id, card, seen = two_files(make_client, project_dir, "sub/new.txt")
    (tmp_path / "elsewhere").mkdir()
    copies._link(project_dir / "sub", tmp_path / "elsewhere")
    said = client.post(f"/api/merges/{card}/approve", json={"shown": seen})
    assert said.status_code == 409 and said.json()["detail"].startswith(
        "sub/new.txt changed since you looked: nothing was taken in")
    assert not (project_dir / "a.txt").exists()
    fresh = client.get(f"/api/conversations/{cid}").json()["merges"][0]
    assert files(fresh) == {"a.txt": "ready", "sub/new.txt": "refused"}
    assert client.post(f"/api/merges/{card}/reject").status_code == 200
    wait_run(client, cid, run_id)


def test_choices_from_a_page_that_does_not_say_what_its_card_showed_are_refused(
    make_client, wait_run, project_dir
):
    client, snap, cid, run_id, card, seen = two_files(make_client, project_dir)
    said = client.post(f"/api/merges/{card}/approve", json={"choices": {"a.txt": "agent"}})
    assert said.status_code == 409
    assert said.json()["detail"] == "Reload the page: this card is from before an update"
    assert not (project_dir / "a.txt").exists()
    assert client.post(f"/api/merges/{card}/reject").status_code == 200
    wait_run(client, cid, run_id)


def test_a_file_the_project_keeps_rewriting_does_not_hold_up_the_rest_when_its_own_is_kept(
    make_client, wait_run, project_dir
):
    """A log or a database the project writes all the time: keeping the project's whole file
    writes nothing, so it is not held to how the card showed it."""
    client, snap, cid, run_id, card, seen = two_files(make_client, project_dir)
    (project_dir / "a.txt").write_text("v1", encoding="utf-8")
    assert client.post(f"/api/merges/{card}/approve", json={"shown": seen}).status_code == 409
    fresh = client.get(f"/api/conversations/{cid}").json()["merges"][0]
    assert files(fresh) == {"a.txt": "conflict", "b.txt": "ready"}
    (project_dir / "a.txt").write_text("v2", encoding="utf-8")     # and again
    now = {f["path"]: f["shown"] for f in fresh["files"]}
    said = client.post(f"/api/merges/{card}/approve",
                       json={"shown": now, "choices": {"a.txt": "project"}})
    assert said.status_code == 200
    assert (project_dir / "a.txt").read_text(encoding="utf-8") == "v2"
    assert (project_dir / "b.txt").read_text(encoding="utf-8") == "B"
    wait_run(client, cid, run_id)


def unattended(make_client, project_dir, coder, commands=()):
    client, model = make_client({
        "Lead": [step(call("spawn_agent", {"role": "Coder", "task": "do it"}, "s")),
                 text("done")],
        "Coder": coder,
    })
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    rules = [allow(client, cid, command) for command in commands]
    made = trigger(client, pid, cid, permissions={"write": True, "commands": rules, "agents": 1})
    return client, cid, run_now(client, made["id"])


def test_nobody_watching_what_a_failed_agent_changed_is_not_taken_and_stays_on_record(
    make_client, wait_run, project_dir
):
    client, cid, run_id = unattended(make_client, project_dir, [
        step(write("a.txt", "A")), ModelUnavailable("the model is gone")])
    snap = wait_run(client, cid, run_id, timeout=10)
    assert next(r for r in snap["runs"] if r["id"] == run_id)["status"] == "completed"
    assert not (project_dir / "a.txt").exists()
    (merge,) = snap["merges"]
    assert merge["status"] == "discarded" and files(merge) == {"a.txt": "refused"}
    assert "did not finish" in merge["files"][0]["note"]
    assert "not applied to the project: a.txt" in calls(snap, "Lead", "spawn_agent")[0][1]
    # thrown away with the copy: nobody was there to reject it
    assert snap["file_changes"][0]["status"] == "discarded" and snap["claims"] == []


def test_nobody_watching_a_conflict_is_not_written_over_and_the_rest_is_taken(
    make_client, wait_run, project_dir
):
    held = Gate()
    client, cid, run_id = unattended(make_client, project_dir, [
        step(edit("hello.py", "hi", "hello")), step(write("a.txt", "A")),
        held.step(text("A done"))])
    held.wait_partial()
    (project_dir / "hello.py").write_text("THE USER'S OWN", encoding="utf-8")
    held.release()
    snap = wait_run(client, cid, run_id, timeout=10)
    (merge,) = snap["merges"]
    assert merge["status"] == "applied"
    assert files(merge) == {"a.txt": "applied", "hello.py": "conflict"}
    assert (project_dir / "hello.py").read_text(encoding="utf-8") == "THE USER'S OWN"
    assert "hello.py (changed in the project meanwhile)" in calls(
        snap, "Lead", "spawn_agent")[0][1]


def test_nobody_watching_a_protected_file_a_command_made_in_the_copy_is_refused_when_taken(
    make_client, wait_run, project_dir
):
    script = ("import os\nos.makedirs('.github/workflows')\n"
              "open('.github/workflows/x.yml', 'w').write('on: push')\n")
    client, cid, run_id = unattended(make_client, project_dir, [
        step(write("make.py", script)), step(run("python make.py")), text("A done"),
    ], commands=["python make.py"])
    snap = wait_run(client, cid, run_id, timeout=15)
    assert calls(snap, "Coder", "run_command")[0][0] == "succeeded"
    (merge,) = snap["merges"]
    assert files(merge) == {".github/workflows/x.yml": "refused", "make.py": "applied"}
    assert "no trigger allows" in merge["files"][0]["note"]
    assert not (project_dir / ".github").exists()
    assert (project_dir / "make.py").read_text(encoding="utf-8") == script
    assert ".github/workflows/x.yml (.github:" in calls(snap, "Lead", "spawn_agent")[0][1]
    # it is nowhere but in the copy, which is kept for that: the user's to discard
    assert merge["status"] == "kept"
    assert (Path(merge["kept_in"]) / ".github" / "workflows" / "x.yml").is_file()
    assert client.post(f"/api/merges/{merge['id']}/reject").status_code == 200
    assert not Path(merge["kept_in"]).exists()


def test_in_a_copy_file_tools_read_what_is_shared_and_do_not_write_what_is_left_out(
    make_client, wait_run, project_dir
):
    (project_dir / ".venv" / "lib").mkdir(parents=True)
    (project_dir / ".venv" / "lib" / "dep.py").write_text("DEP = 1\n", encoding="utf-8")
    client, model, cid, run_id = one(make_client, project_dir, [
        step(write("a.txt", "A")), step(read(".venv/lib/dep.py")),
        step(call("search", {"pattern": "DEP", "path": ".venv/lib"}, "se")),
        step(write("build/out.txt", "x", "w2")), step(write(".git/hooks/pre-commit", "x", "w3")),
        step(python("import os;print(os.environ['PYTHONPATH'])")), text("A done"),
    ])
    snap = wait_run(client, cid, run_id)
    assert "DEP = 1" in calls(snap, "Coder", "read_file")[0][1]
    assert ".venv/lib/dep.py:1: DEP = 1" in calls(snap, "Coder", "search")[0][1]
    made, built, hooked = calls(snap, "Coder", "write_file")
    assert made[0] == "succeeded" and "git does not work in the copy" in made[1]
    assert built[0] == "failed" and "not part of a working copy" in built[1]
    assert hooked[0] == "failed" and not (project_dir / ".git").exists()
    # its commands find the copy's own code first
    out = calls(snap, "Coder", "run_command")[0][1]
    here = str(copies.folder(client.app.state.settings.runtime_root) / agent(snap, "Coder")["id"])
    assert here in out
    assert not (copies.folder(client.app.state.settings.runtime_root)
                / agent(snap, "Coder")["id"]).exists()      # and the copy is gone


def test_the_copys_own_code_comes_first_on_the_python_path(tmp_path):
    (tmp_path / "src").mkdir()
    assert copy_python_path(tmp_path, "was").split(os.pathsep) == [
        str(tmp_path), str(tmp_path / "src"), "was"]
    assert copy_python_path(tmp_path / "src", None) == str(tmp_path / "src")


def test_a_project_whose_commands_run_in_docker_gets_copies_too(
    make_client, wait_run, project_dir
):
    """The container is handed the copy, and where its linked folders really are."""
    (project_dir / "node_modules" / "pkg").mkdir(parents=True)
    held, executor = Gate(), ScriptedExecutor([Script(chunks=["ok\n"])])
    client, model = make_client({
        "Lead": [step(call("spawn_agent", {"role": "Coder", "task": "do it"}, "s")),
                 text("done")],
        "Coder": [step(write("a.txt", "A")), step(run("pytest -q")), held.step(text("A done"))],
    }, executor=executor)
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    assert client.patch(f"/api/projects/{pid}", json={
        "exec_location": "docker", "docker_image": "python:3.12"}).status_code == 200
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    assert client.patch(f"/api/conversations/{cid}", json={
        "permission_mode": "full_auto", "spawn_approval": "never"}).status_code == 200
    run_id = client.post(f"/api/conversations/{cid}/messages", json={"content": "go"}).json()[
        "run"]["id"]
    held.wait_partial()
    snap = client.get(f"/api/conversations/{cid}").json()
    assert agent(snap, "Coder")["copy"] == {"state": "own"}
    assert not (project_dir / "a.txt").exists()
    assert executor.locations == ["docker"]
    assert executor.started == [("pytest -q", str(here(client, snap)))]
    assert executor.copies == [
        (here(client, snap), {"node_modules": project_dir / "node_modules"})]
    held.release()
    snap = wait_run(client, cid, run_id)
    assert merges(snap) == ["applied"] and snap["file_changes"][0]["status"] == "applied"
    assert (project_dir / "a.txt").read_text(encoding="utf-8") == "A"


def test_an_agent_that_goes_on_after_its_changes_were_taken_gets_a_copy_again(
    make_client, wait_run, project_dir
):
    client, model, cid, run_id = setup(make_client, project_dir, {
        "Lead": [step(call("spawn_agent", {"role": "Coder", "task": "A"}, "s")),
                 step(call("message_agent", {"to": "Coder", "message": "one more"}, "m")),
                 text("done")],
        "Coder": [step(write("a.txt", "A")), text("A done"),
                  step(read("a.txt")), step(write("b.txt", "B", "w2")), text("B done")],
    })
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed"
    assert merges(snap) == ["applied", "applied"]
    assert calls(snap, "Coder", "read_file")[0][0] == "succeeded"   # of the project, by then
    assert (project_dir / "b.txt").read_text(encoding="utf-8") == "B"
    assert snap["claims"] == [] and all(f["status"] == "applied" for f in snap["file_changes"])


def test_a_decision_on_changes_is_the_users_own_and_is_taken_once(
    make_client, wait_run, project_dir
):
    client, model, cid, run_id = one(make_client, project_dir, [
        step(write("a.txt", "A")), text("A done")], permission_mode="ask")
    snap = until(client, cid, lambda s: merges(s) == ["pending"])
    card = snap["merges"][0]["id"]
    assert client.post("/api/merges/nope/approve").status_code == 404
    # a request that does not say it is from the app's own page is not the user's: an
    # agent's command cannot say yes to its own changes
    del client.headers["Origin"]
    assert client.post(f"/api/merges/{card}/approve").status_code == 403
    assert not (project_dir / "a.txt").exists()
    client.headers["Origin"] = ORIGIN
    assert client.post(f"/api/merges/{card}/approve").status_code == 200
    wait_run(client, cid, run_id)
    assert client.post(f"/api/merges/{card}/reject").status_code == 409
    assert (project_dir / "a.txt").read_text(encoding="utf-8") == "A"


# --- the review's fix round ------------------------------------------------------------------


def here(client, snap, name="Coder"):
    """Where the named agent's working copy is."""
    held = copies.folder(client.app.state.settings.runtime_root)
    return held / agent(snap, name)["id"] / copies.TREE


OUT = ("import os\nos.makedirs('ext')\nopen('ext/a.bin', 'wb').write(bytes([255, 0]))\n"
       "open('ext/big.txt', 'w').write('x' * (1024 * 1024 + 1))\nos.remove('old/f.bin')\n")


def links_out(tmp_path, project_dir):
    """A project with a link of its own to a folder outside it (never part of a copy), and
    a folder with a file the agent's command deletes in the copy."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep", encoding="utf-8")
    copies._link(project_dir / "ext", outside)
    (project_dir / "old").mkdir()
    (project_dir / "old" / "f.bin").write_bytes(b"\xfe")
    return outside


def becomes_a_link(tmp_path, project_dir):
    """While the agent is at work the project's folder becomes a link to another one."""
    other = tmp_path / "other"
    other.mkdir()
    (other / "f.bin").write_bytes(b"\xfe")
    shutil.rmtree(project_dir / "old")
    copies._link(project_dir / "old", other)
    return other


def nothing_left_the_project(snap, project_dir, outside, other):
    (merge,) = snap["merges"]
    assert files(merge) == {"ext/a.bin": "refused", "ext/big.txt": "refused",
                            "make.py": "applied", "old/f.bin": "refused"}
    # what was refused is nowhere but in the copy, which is kept for that
    assert merge["status"] == "kept"
    assert all("through a link" in f["note"] for f in merge["files"] if f["state"] == "refused")
    # nothing behind a link is read for a card either
    assert all(f["diff"] is None for f in merge["files"] if f["state"] == "refused")
    assert sorted(p.name for p in outside.iterdir()) == ["keep.txt"]
    assert (other / "f.bin").read_bytes() == b"\xfe"
    assert (project_dir / "make.py").is_file()
    told = calls(snap, "Lead", "spawn_agent")[0][1]
    assert "not applied to the project: ext/a.bin, ext/big.txt, old/f.bin (it leads out" in told


def test_taking_in_never_writes_or_deletes_through_a_link_of_the_projects(
    make_client, wait_run, project_dir, tmp_path
):
    """Not text, too large for a record, or deleted: none of them leaves the project."""
    outside, held = links_out(tmp_path, project_dir), Gate()
    client, model, cid, run_id = one(make_client, project_dir, [
        step(write("make.py", OUT)), step(run("python make.py")), held.step(text("A done"))])
    held.wait_partial()
    other = becomes_a_link(tmp_path, project_dir)
    held.release()
    snap = wait_run(client, cid, run_id, timeout=15)
    assert snap["runs"][0]["status"] == "completed"         # full auto: nobody was asked
    nothing_left_the_project(snap, project_dir, outside, other)


def test_nobody_watching_taking_in_never_writes_or_deletes_through_a_link_either(
    make_client, wait_run, project_dir, tmp_path
):
    outside, held = links_out(tmp_path, project_dir), Gate()
    client, cid, run_id = unattended(make_client, project_dir, [
        step(write("make.py", OUT)), step(run("python make.py")), held.step(text("A done")),
    ], commands=["python make.py"])
    held.wait_partial()
    other = becomes_a_link(tmp_path, project_dir)
    held.release()
    snap = wait_run(client, cid, run_id, timeout=15)
    nothing_left_the_project(snap, project_dir, outside, other)


def unreadable_once(monkeypatch):
    real, failed = copies.Copy.changes, []

    def changes(self, *given):
        if not failed:
            failed.append(True)
            raise PermissionError(13, "Access is denied")
        return real(self, *given)

    monkeypatch.setattr(copies.Copy, "changes", changes)


def test_a_copy_that_cannot_be_read_is_kept_and_put_before_the_user(
    make_client, wait_run, project_dir, monkeypatch
):
    unreadable_once(monkeypatch)
    client, model, cid, run_id = one(make_client, project_dir, [
        step(write("a.txt", "A")), text("A done")])
    snap = until(client, cid, lambda s: merges(s) == ["pending"])       # full auto, and asked
    (card,) = snap["merges"]
    assert files(card) == {"a.txt": "ready"}
    assert "could not be read: Access is denied" in card["files"][0]["note"]
    assert not (project_dir / "a.txt").exists()
    assert (here(client, snap) / "a.txt").read_text(encoding="utf-8") == "A"
    assert snap["file_changes"][0]["status"] == "in_copy"
    assert agent(snap, "Coder")["status"] == "completed"
    assert client.post(f"/api/merges/{card['id']}/approve").status_code == 200
    snap = wait_run(client, cid, run_id)
    assert merges(snap) == ["applied"] and snap["runs"][0]["status"] == "completed"
    assert (project_dir / "a.txt").read_text(encoding="utf-8") == "A"
    assert not here(client, snap).exists()


def test_nobody_watching_a_copy_that_cannot_be_read_is_not_taken_and_is_on_record(
    make_client, wait_run, project_dir, monkeypatch
):
    unreadable_once(monkeypatch)
    client, cid, run_id = unattended(make_client, project_dir, [
        step(write("a.txt", "A")), text("A done")])
    snap = wait_run(client, cid, run_id, timeout=10)
    assert next(r for r in snap["runs"] if r["id"] == run_id)["status"] == "completed"
    (merge,) = snap["merges"]
    assert merge["status"] == "discarded" and files(merge) == {"a.txt": "refused"}
    assert "could not be read" in merge["files"][0]["note"]
    assert not (project_dir / "a.txt").exists()
    assert snap["file_changes"][0]["status"] == "discarded"
    assert "a.txt (the working copy could not be read" in calls(snap, "Lead", "spawn_agent")[0][1]


def test_a_fault_at_one_file_loses_neither_it_nor_the_copy(
    make_client, wait_run, project_dir, monkeypatch
):
    real, failed = AgentRunner._apply_file, []

    def apply_file(self, ctx, copy, ws, path, *how):
        if path == "b.txt" and not failed:
            failed.append(True)
            raise RuntimeError("the disk is full")
        return real(self, ctx, copy, ws, path, *how)

    monkeypatch.setattr(AgentRunner, "_apply_file", apply_file)
    client, model, cid, run_id = one(make_client, project_dir, [
        step(write("a.txt", "A")), step(write("b.txt", "B", "w2")), text("A done")])
    snap = until(client, cid, lambda s: merges(s) == ["pending"])
    (card,) = snap["merges"]
    assert files(card) == {"a.txt": "applied", "b.txt": "ready"}
    assert "the disk is full" in card["files"][1]["note"]
    assert (project_dir / "a.txt").read_text(encoding="utf-8") == "A"
    assert not (project_dir / "b.txt").exists()
    assert (here(client, snap) / "b.txt").read_text(encoding="utf-8") == "B"
    assert client.post(f"/api/merges/{card['id']}/approve").status_code == 200
    snap = wait_run(client, cid, run_id)
    assert merges(snap) == ["applied"]
    assert files(snap["merges"][0]) == {"a.txt": "applied", "b.txt": "applied"}
    assert (project_dir / "b.txt").read_text(encoding="utf-8") == "B"
    assert all(f["status"] == "applied" for f in snap["file_changes"])


def test_apply_writes_what_the_card_showed_and_nothing_else(make_client, wait_run, project_dir):
    client, model, cid, run_id = one(make_client, project_dir, [
        step(write("a.txt", "A")), step(write("b.txt", "B", "w2")), text("A done"),
    ], permission_mode="ask")
    snap = until(client, cid, lambda s: merges(s) == ["pending"])
    card, copy = snap["merges"][0]["id"], here(client, snap)
    # after the card was shown the copy moves on: one file changes, one more appears
    (copy / "a.txt").write_text("NOT WHAT WAS SHOWN", encoding="utf-8")
    (copy / "late.txt").write_text("late", encoding="utf-8")
    said = client.post(f"/api/merges/{card}/approve")
    assert said.status_code == 409 and said.json()["detail"].startswith("a.txt, late.txt changed")
    said = client.get(f"/api/conversations/{cid}").json()["merges"][0]
    assert files(said) == {"a.txt": "ready", "b.txt": "ready", "late.txt": "ready"}
    assert "+NOT WHAT WAS SHOWN" in said["files"][0]["diff"]
    assert not any((project_dir / name).exists() for name in ("a.txt", "b.txt", "late.txt"))
    assert copy.is_dir()
    # shown as it is now, the yes is to that
    assert client.post(f"/api/merges/{card}/approve").status_code == 200
    snap = wait_run(client, cid, run_id)
    assert merges(snap) == ["applied"]
    assert (project_dir / "b.txt").read_text(encoding="utf-8") == "B"
    assert (project_dir / "a.txt").read_text(encoding="utf-8") == "NOT WHAT WAS SHOWN"
    assert (project_dir / "late.txt").read_text(encoding="utf-8") == "late"


def test_a_project_that_cannot_be_copied_is_worked_in_as_before_and_not_copied_again(
    make_client, wait_run, project_dir, monkeypatch
):
    tried, held = [], Gate()

    def make(*given):
        tried.append(given)
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(copies, "make", make)
    client, model, cid, run_id = setup(make_client, project_dir, {
        "Lead": [step(call("spawn_agent", {"role": "Coder", "task": "A"}, "s")), text("done")],
        "Coder": [step(write("a.txt", "A")),
                  step(call("spawn_agent", {"role": "Coder", "task": "B"}, "s2")),
                  held.step(step(write("c.txt", "C", "w3"))), text("A done")],
        "Coder 2": [step(write("b.txt", "B")), text("B done")],
    })
    held.wait_partial()
    snap = client.get(f"/api/conversations/{cid}").json()
    assert agent(snap, "Coder")["copy"] == {"state": "failed"}
    assert agent(snap, "Coder 2")["copy"] == {"state": "failed"}
    assert calls(snap, "Coder", "write_file") == [("succeeded", "applied: a.txt (+1 -0)")]
    assert (project_dir / "a.txt").read_text(encoding="utf-8") == "A"   # in the project at once
    held.release()
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed" and snap["merges"] == []
    assert (project_dir / "c.txt").read_text(encoding="utf-8") == "C"
    assert len(tried) == 1
    assert all(f["status"] == "applied" for f in snap["file_changes"])


def test_what_stop_kept_stays_on_record_in_its_copy(make_client, wait_run, project_dir):
    """6 Nov: Stop keeps a copy with changes for the user's Take in - nothing discarded."""
    first = Gate()
    client, model, cid, run_id = one(make_client, project_dir, [
        step(write("a.txt", "A")), first.step(text("A done"))])
    first.wait_partial()
    assert client.post(f"/api/runs/{run_id}/cancel").status_code in (200, 202)
    snap = wait_run(client, cid, run_id)
    first.release()
    assert [f["status"] for f in snap["file_changes"]] == ["in_copy"]
    assert [m["status"] for m in snap["merges"]] == ["kept"]


def test_a_copy_is_not_deleted_under_a_command_that_is_still_being_killed(
    make_client, wait_run, project_dir
):
    """A second Stop does not wait for the kill: the copy goes when the command has, and
    stays for the next start if it could not be killed."""
    for outcome in ("gone", "alive"):
        first, kills = Gate(), []
        client, model, cid, run_id = one(make_client, project_dir, [
            # (A command alone: a copy with no change, which Stop does not keep - 6 Nov.)
            step(run("python -V")), first.step(text("A done"))])
        first.wait_partial()
        snap = client.get(f"/api/conversations/{cid}").json()
        copy = here(client, snap)

        def ending(root, copy=copy, kills=kills):
            assert root == copy
            kills.append(asyncio.get_running_loop().create_future())
            return kills[-1:]

        client.app.state.runner.commands.ending = ending
        assert client.post(f"/api/runs/{run_id}/cancel").status_code in (200, 202)
        snap = wait_run(client, cid, run_id)
        first.release()
        assert kills and copy.is_dir() and snap["claims"] == []
        (kill,) = kills
        if outcome == "gone":
            kill.get_loop().call_soon_threadsafe(kill.set_result, None)
            deadline = time.monotonic() + 5
            while copy.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            assert not copy.exists()
        else:
            kill.get_loop().call_soon_threadsafe(kill.set_exception, TimeoutError())
            time.sleep(0.3)
            assert copy.is_dir()


def test_a_kill_under_way_is_known_by_where_its_command_ran(tmp_path):
    async def scenario():
        runner = CommandRunner(None, None, None, None)
        release = asyncio.Event()

        class Running:
            async def kill(self):
                await release.wait()

            async def close(self):
                pass

        ending = asyncio.ensure_future(runner._end(Running(), True, tmp_path))
        await asyncio.sleep(0)
        ending.cancel()                              # a second Stop: it does not wait
        assert await ending is True
        (kill,) = runner.ending(tmp_path)
        assert runner.ending(tmp_path / "other") == []
        release.set()
        await kill
        await asyncio.sleep(0)
        assert runner.ending(tmp_path) == []

    asyncio.run(scenario())


def short_name(path):
    """A folder's 8.3 name, or None where the disk keeps none."""
    import ctypes

    held = ctypes.create_unicode_buffer(600)
    if not ctypes.windll.kernel32.GetShortPathNameW(str(path), held, 600):
        return None
    return held.value.rsplit("\\", 1)[-1] if held.value != str(path) else None


@pytest.mark.skipif(os.name != "nt", reason="only Windows has 8.3 names")
def test_a_linked_folder_is_not_written_into_by_its_short_name(
    make_client, wait_run, project_dir
):
    (project_dir / "node_modules" / "pkg").mkdir(parents=True)
    short = short_name(project_dir / "node_modules")
    if short is None or short.casefold() == "node_modules":
        pytest.skip("this disk keeps no 8.3 names")
    client, model, cid, run_id = one(make_client, project_dir, [
        step(write("a.txt", "A")), step(write(f"{short}/pkg/mine.js", "y", "w2")),
        text("A done")])
    snap = wait_run(client, cid, run_id)
    made, refused = calls(snap, "Coder", "write_file")
    assert made[0] == "succeeded"
    assert refused[0] == "failed" and "shares with the project" in refused[1]
    assert not (project_dir / "node_modules" / "pkg" / "mine.js").exists()


def test_an_agent_is_told_once_and_in_full_that_it_works_in_a_copy(
    make_client, wait_run, project_dir
):
    client, model, cid, run_id = setup(make_client, project_dir, {
        "Lead": [step(call("spawn_agent", {"role": "Coder", "task": "A"}, "s")), text("done")],
        "Coder": [step(write("a.txt", "A")), step(write("b.txt", "B", "w2")),
                  step(call("spawn_agent", {"role": "Coder", "task": "B"}, "s2")),
                  text("A done")],
        "Coder 2": [step(write("c.txt", "C")), text("B done")],
    })
    snap = wait_run(client, cid, run_id)
    first, second = calls(snap, "Coder", "write_file")
    assert first == ("succeeded", (
        "applied: a.txt (+1 -0)\n\nFrom here on you work in a copy of the project of your "
        "own: your file tools and commands run there, agents outside it do not see what you "
        "change, and the changes are taken into the project when your work is over. git does "
        "not work in the copy. The copy is your working folder, in the project's place: your "
        "report names files by their paths relative to it. "
        "node_modules, .venv and venv are the project's own, shared "
        "with it: your file tools read there and do not write there. A command that deletes "
        "there deletes the project's: such a command is asked about every time."))
    assert second == ("succeeded", "applied: b.txt (+1 -0)")
    ((_, below),) = calls(snap, "Coder 2", "write_file")
    assert below.startswith(
        "applied: c.txt (+1 -0)\n\nFrom here on you work in Coder's copy of the project: ")
    assert "taken into the project when Coder's work is over. git does not work" in below


# --- the second review's fix round -----------------------------------------------------------


def unreadable(monkeypatch):
    def changes(self, *given):
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(copies.Copy, "changes", changes)


def test_a_copy_whose_listing_failed_still_shows_a_conflict_as_one(
    make_client, wait_run, project_dir, monkeypatch
):
    """Only the listing failed: each file on record is still compared, and shown."""
    unreadable_once(monkeypatch)
    held = Gate()
    client, model, cid, run_id = one(make_client, project_dir, [
        step(edit("hello.py", "hi", "from the copy")), held.step(text("A done"))])
    held.wait_partial()
    (project_dir / "hello.py").write_text("THE USER'S OWN\n", encoding="utf-8")
    held.release()
    snap = until(client, cid, lambda s: merges(s) == ["pending"])
    (shown,) = snap["merges"][0]["files"]
    assert shown["state"] == "conflict"
    assert "-THE USER'S OWN" in (shown.get("clash") or shown["diff"])
    assert "could not be read" in shown["note"]
    assert (project_dir / "hello.py").read_text(encoding="utf-8") == "THE USER'S OWN\n"
    assert client.post(f"/api/merges/{snap['merges'][0]['id']}/reject").status_code == 200
    wait_run(client, cid, run_id)
    assert (project_dir / "hello.py").read_text(encoding="utf-8") == "THE USER'S OWN\n"


def test_apply_goes_by_the_bytes_the_diff_was_made_from(
    make_client, wait_run, project_dir, monkeypatch
):
    """The project's file changes right after its diff was read: the yes was not to that."""
    import app.agent

    real, changed = app.agent._merge_file, []

    def merge_file(*given):
        found = real(*given)
        if not changed:
            changed.append(True)
            (project_dir / "a.txt").write_text("THE USER'S OWN", encoding="utf-8")
        return found

    monkeypatch.setattr(app.agent, "_merge_file", merge_file)
    monkeypatch.setattr(app.agent.merge, "_merge_file", merge_file)
    monkeypatch.setattr(app.agent.spawn_mixin, "_merge_file", merge_file)
    client, model, cid, run_id = one(make_client, project_dir, [
        step(write("a.txt", "A")), text("A done")], permission_mode="ask")
    snap = until(client, cid, lambda s: merges(s) == ["pending"])
    (shown,) = snap["merges"][0]["files"]
    assert shown["state"] == "ready" and "THE USER'S OWN" not in shown["diff"]
    said = client.post(f"/api/merges/{snap['merges'][0]['id']}/approve")
    assert said.status_code == 409
    assert files(client.get(f"/api/conversations/{cid}").json()["merges"][0]) == {
        "a.txt": "conflict"}
    assert (project_dir / "a.txt").read_text(encoding="utf-8") == "THE USER'S OWN"
    assert client.post(f"/api/merges/{snap['merges'][0]['id']}/reject").status_code == 200
    wait_run(client, cid, run_id)


def test_a_file_the_copy_no_longer_has_is_not_said_to_be_in_the_project(
    make_client, wait_run, project_dir
):
    client, model, cid, run_id = one(make_client, project_dir, [
        step(write("a.txt", "A")), step(write("b.txt", "B", "w2")), text("A done"),
    ], permission_mode="ask")
    snap = until(client, cid, lambda s: merges(s) == ["pending"])
    (here(client, snap) / "a.txt").unlink()         # after the card was shown
    # it has left the card: the card is not as the user saw it, and nothing is taken
    assert client.post(f"/api/merges/{snap['merges'][0]['id']}/approve").status_code == 409
    assert not (project_dir / "b.txt").exists()
    assert client.post(f"/api/merges/{snap['merges'][0]['id']}/approve").status_code == 200
    snap = wait_run(client, cid, run_id)
    assert merges(snap) == ["applied"] and files(snap["merges"][0]) == {"b.txt": "applied"}
    assert not (project_dir / "a.txt").exists()
    assert {f["path"]: f["status"] for f in snap["file_changes"]} == {
        "a.txt": "discarded", "b.txt": "applied"}


def test_a_copy_that_can_never_be_read_ends_with_what_was_taken_and_is_kept(
    make_client, wait_run, project_dir, monkeypatch
):
    """Nothing on the card is left to take and the copy still cannot be looked at: the turn
    goes on, and the copy stays - a command may have made files in it that no card listed."""
    unreadable(monkeypatch)
    client, model, cid, run_id = one(make_client, project_dir, [
        step(write("a.txt", "A")), step(python("open('made.txt','w').write('m')")),
        text("A done")])
    snap = until(client, cid, lambda s: merges(s) == ["pending"])
    copy = here(client, snap)
    assert client.post(f"/api/merges/{snap['merges'][0]['id']}/approve").status_code == 200
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed"
    (merge,) = snap["merges"]
    assert merge["status"] == "kept" and files(merge) == {"a.txt": "applied"}
    assert merge["kept_in"] == str(copy)
    assert (project_dir / "a.txt").read_text(encoding="utf-8") == "A"
    assert [f["status"] for f in snap["file_changes"]] == ["applied"]
    assert (copy / "made.txt").read_text(encoding="utf-8") == "m"
    told = calls(snap, "Lead", "spawn_agent")[0][1]
    assert "could not be read" in told and str(copy) in told
    assert snap["claims"] == []


def test_a_fault_while_the_changes_are_put_on_record_keeps_the_copy_without_its_links(
    make_client, wait_run, project_dir, monkeypatch
):
    (project_dir / "node_modules" / "pkg").mkdir(parents=True)

    def record(self, *given):
        raise RuntimeError("the database is locked")

    monkeypatch.setattr(AgentRunner, "_record_merge", record)
    client, model, cid, run_id = one(make_client, project_dir, [
        step(write("a.txt", "A")), text("A done")], permission_mode="ask")
    snap = wait_run(client, cid, run_id)
    copy = here(client, snap)
    assert (copy / "a.txt").read_text(encoding="utf-8") == "A"      # not thrown away
    assert not (copy / "node_modules").exists()                     # and leads nowhere
    assert (project_dir / "node_modules" / "pkg").is_dir()
    assert not (project_dir / "a.txt").exists()
    (merge,) = snap["merges"]
    assert merge["status"] == "kept" and merge["kept_in"] == str(copy)
    assert [f["status"] for f in snap["file_changes"]] == ["in_copy"]
    assert snap["claims"] == []


def test_a_folder_that_could_not_be_deleted_does_not_keep_the_agent_from_a_new_copy(
    make_client, wait_run, project_dir, monkeypatch
):
    monkeypatch.setattr(copies, "remove", lambda *given: None)
    client, model, cid, run_id = setup(make_client, project_dir, {
        "Lead": [step(call("spawn_agent", {"role": "Coder", "task": "A"}, "s")),
                 step(call("message_agent", {"to": "Coder", "message": "one more"}, "m")),
                 text("done")],
        "Coder": [step(write("a.txt", "A")), text("A done"),
                  step(write("b.txt", "B", "w2")), text("B done")],
    })
    snap = wait_run(client, cid, run_id)
    assert merges(snap) == ["applied", "applied"]
    assert agent(snap, "Coder")["copy"] == {"state": "own"}
    assert (project_dir / "b.txt").read_text(encoding="utf-8") == "B"


# --- the first command (slice 19c) -----------------------------------------------------------


def commands(snap):
    return [(c["command"], c["status"]) for c in snap["commands"]]


def test_a_command_that_is_asked_about_gets_the_agent_its_copy_when_it_may_run(
    make_client, wait_run, project_dir
):
    made = "open('made.txt','w').write('m')"
    client, model, cid, run_id = one(make_client, project_dir, [
        step(python("print('no')", "c1")), step(python(made, "c2")), text("A done"),
    ], permission_mode="ask")
    snap = until(client, cid, lambda s: [st for _c, st in commands(s)] == ["proposed"])
    assert agent(snap, "Coder")["copy"] is None                 # proposed: nothing is copied
    assert client.post(f"/api/commands/{snap['commands'][0]['id']}/reject").status_code == 200
    snap = until(client, cid, lambda s: [st for _c, st in commands(s)] == ["rejected", "proposed"])
    assert agent(snap, "Coder")["copy"] is None                 # refused: no copy for nothing
    assert not copies.folder(client.app.state.settings.runtime_root).exists()
    assert client.post(f"/api/commands/{snap['commands'][1]['id']}/approve",
                       json={}).status_code == 200
    snap = until(client, cid, lambda s: merges(s) == ["pending"])
    assert agent(snap, "Coder")["copy"] == {"state": "own"}
    assert not (project_dir / "made.txt").exists()
    assert files(snap["merges"][0]) == {"made.txt": "ready"}
    # the agent is told where it is with the first thing it did there
    said = calls(snap, "Coder", "run_command")[1][1]
    assert said.startswith("exit code 0") and "you work in a copy of the project of your own" in said
    assert client.post(f"/api/merges/{snap['merges'][0]['id']}/approve").status_code == 200
    snap = wait_run(client, cid, run_id)
    assert (project_dir / "made.txt").read_text(encoding="utf-8") == "m"


def test_in_a_copy_with_links_a_command_that_deletes_is_asked_at_full_auto_too(
    make_client, wait_run, project_dir
):
    """K-70-junction: the copy's node_modules is the project's own, linked in - before the
    copy is made by the command (its first) and after."""
    (project_dir / "node_modules" / "pkg").mkdir(parents=True)
    (project_dir / "node_modules" / "pkg" / "index.js").write_text("dep", encoding="utf-8")
    client, model, cid, run_id = one(make_client, project_dir, [
        step(run("rm -rf node_modules", "c1")), step(write("a.txt", "A")),
        step(run("Remove-Item -Recurse node_modules", "c2")), text("A done")])
    for number in (1, 2):
        snap = until(client, cid, lambda s, n=number: [st for _c, st in commands(s)][-1:] == [
            "proposed"] and len(commands(s)) == n)
        assert "Deletes" in snap["commands"][-1]["danger"]
        assert client.post(f"/api/commands/{snap['commands'][-1]['id']}/reject").status_code == 200
    snap = wait_run(client, cid, run_id)
    assert [st for _c, st in commands(snap)] == ["rejected", "rejected"]
    assert (project_dir / "node_modules" / "pkg" / "index.js").read_text(encoding="utf-8") == "dep"


def test_in_a_copy_the_agent_is_told_its_copys_folder_and_a_command_naming_the_project_is_asked(
    make_client, wait_run, project_dir
):
    """K-kopya-istem: from a copy, the project's own path leads into the project itself."""
    straight = f"python -c \"open(r'{project_dir}/x.txt','w')\""
    client, model, cid, run_id = one(make_client, project_dir, [
        step(write("a.txt", "A")), step(run(straight, "c1")), text("A done")])
    snap = until(client, cid, lambda s: commands(s) == [(straight, "proposed")])
    assert client.post(f"/api/commands/{snap['commands'][0]['id']}/reject").status_code == 200
    snap = wait_run(client, cid, run_id)
    assert not (project_dir / "x.txt").exists()
    first, *later = (request[0]["content"] for request in model.calls_of["Coder"])
    told = "working inside one project folder: {}\n"
    assert told.format(project_dir) in first                    # no copy yet
    assert later and all(told.format(here(client, snap)) in one for one in later)


@pytest.mark.parametrize("first", [True, False], ids=["before its copy", "in its copy"])
def test_from_a_copy_a_command_run_in_the_project_by_a_listed_parent_is_refused(
    make_client, wait_run, tmp_path, first
):
    """Review of batch-11: the folder holding the project is one to write in (slice 75), and
    a copy's command with the project as its cwd ran there at Full auto, past Take in."""
    project_dir = tmp_path / "desk" / "proj"  # (the test's home is in tmp_path: not listed)
    project_dir.mkdir(parents=True)
    (project_dir / "hello.py").write_text("print('hi')\n", encoding="utf-8")
    into = step(call("run_command", {"command": "python -c \"open('x.txt','w').write('x')\"",
                                     "cwd": str(project_dir)}, "c2"))
    coder = [into, text("A done")] if first else [step(write("a.txt", "A")), into, text("A done")]
    client, model = make_client({
        "Lead": [step(call("spawn_agent", {"role": "Coder", "task": "do it"}, "s")), text("done")],
        "Coder": coder})
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    patched = client.patch(f"/api/conversations/{cid}", json={
        "permission_mode": "full_auto", "spawn_approval": "never",
        "also_in": [str(project_dir.parent)]})
    assert patched.status_code == 200, patched.text
    run_id = client.post(f"/api/conversations/{cid}/messages",
                         json={"content": "go"}).json()["run"]["id"]
    snap = wait_run(client, cid, run_id)
    ((status, said),) = calls(snap, "Coder", "run_command")
    assert status == "failed" and "is a file of the project itself" in said
    assert snap["commands"] == [] and not (project_dir / "x.txt").exists()


def test_unattended_a_command_naming_the_project_from_a_copy_is_refused_though_ticked(
    make_client, wait_run, project_dir
):
    straight = f"python fix.py {project_dir}"  # (plain: a rule can hold it)
    client, _model = make_client({
        "Lead": [step(call("spawn_agent", {"role": "Coder", "task": "do it"}, "s")),
                 text("done")],
        "Coder": [step(write("a.txt", "A")), step(run(straight)), text("A done")]})
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    made = trigger(client, pid, cid, permissions={
        "write": True, "commands": [allow(client, cid, straight)], "agents": 1})
    snap = wait_run(client, cid, run_now(client, made["id"]))
    (refused,) = [t for t in snap["tool_calls"] if t["name"] == "run_command"]
    assert refused["status"] == "denied" and "the project folder" in refused["result"]
    assert snap["commands"] == []


def test_in_a_copy_without_links_a_delete_and_kolonis_own_runtime_in_the_project_run_unasked(
    make_client, wait_run, project_dir, settings_env
):
    """No dependency folder to go through, before the copy is made or after; and KOLONİ on
    its own repository: its runtime (the copy, a skill's script) is not the project's."""
    runtime = project_dir / "runtime"
    settings_env["KOLONI_RUNTIME_ROOT"] = str(runtime)
    (project_dir / "build").mkdir()
    client, model, cid, run_id = one(make_client, project_dir, [
        step(run("rmdir build", "c1")), step(run(f'python -c "print(1)" {runtime}', "c2")),
        text("A done")])
    # (K-fullauto-sorma: the delete is a card at Full auto for deleting, not for the copy -
    # its card says what `danger` says, nothing of a dependency folder or the project)
    snap = until(client, cid, lambda s: commands(s) == [("rmdir build", "proposed")])
    (asked,) = [t for t in snap["tool_calls"] if t["name"] == "run_command"]
    assert asked["why_asked"] == "Deletes files or disks."
    client.post(f"/api/commands/{snap['commands'][0]['id']}/approve", json={})
    snap = wait_run(client, cid, run_id)
    assert [st for _c, st in commands(snap)] == ["exited", "exited"]


def test_a_command_in_a_project_too_big_to_copy_runs_in_the_project(
    make_client, wait_run, project_dir, monkeypatch
):
    monkeypatch.setattr(copies, "MAX_FILES", 0)
    client, model, cid, run_id = one(make_client, project_dir, [
        step(python("open('made.txt','w').write('m')")), text("A done")])
    snap = wait_run(client, cid, run_id)
    assert agent(snap, "Coder")["copy"] == {"state": "too_big"} and snap["merges"] == []
    assert (project_dir / "made.txt").read_text(encoding="utf-8") == "m"


# --- a restart ---------------------------------------------------------------------------------


def on_record(s, project):
    s.add(Project(id="p", name="p", root_path=str(project)))
    s.flush()
    s.add(Conversation(id="c", project_id="p"))
    s.flush()
    s.add(Run(id="r", conversation_id="c", status="waiting_approval"))
    s.flush()
    s.add(Message(id="m", conversation_id="c", run_id="r", role="assistant", content=""))
    s.flush()


def an_agent(s, id, status="completed", copy="own", parent=None):
    s.add(Agent(id=id, run_id="r", role_name="Coder", name=id, tools=[], depth=2 if parent else 1,
                parent_agent_id=parent, status=status, copy={"state": copy}))
    s.add(ToolCall(id=f"t-{id}", run_id="r", agent_id=id, message_id="m", seq=1,
                   provider_call_id="x", name="write_file", arguments="{}", status="succeeded"))
    s.flush()


def a_change(s, id, by, path, kind="create"):
    s.add(FileChange(id=id, run_id="r", agent_id=by, tool_call_id=f"t-{by}", path=path,
                     kind=kind, after_content="A", after_sha="x", status="in_copy"))
    s.flush()


def test_closing_the_app_keeps_the_copies_whose_changes_wait_or_are_being_made(
    settings_env, project_dir
):
    """An ordinary stop of the app is a restart too: it does not discard like Stop."""
    held = Gate()
    app = create_app(load_settings(settings_env), model=ScriptedModel({
        "Lead": [two(), text("done")],
        "Coder": [step(write("a.txt", "A")), text("A done")],
        "Coder 2": [step(write("b.txt", "B")), held.step(text("B done"))],
    }))
    with TestClient(app, base_url="http://127.0.0.1:8790") as client:
        client.headers["Origin"] = ORIGIN
        pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
        cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
        assert client.patch(f"/api/conversations/{cid}", json={
            "permission_mode": "ask", "spawn_approval": "never",
            "spawn_max_parallel": 2}).status_code == 200
        client.post(f"/api/conversations/{cid}/messages", json={"content": "go"})
        snap = until(client, cid, lambda s: merges(s) == ["pending"])
        held.wait_partial()
        asked, at_work = here(client, snap), here(client, snap, "Coder 2")
    held.release()
    for _start in range(2):
        with TestClient(create_app(load_settings(settings_env)),
                        base_url="http://127.0.0.1:8790") as client:
            snap = client.get(f"/api/conversations/{cid}").json()
        assert (asked / "a.txt").read_text(encoding="utf-8") == "A"
        assert (at_work / "b.txt").read_text(encoding="utf-8") == "B"
        assert sorted(merges(snap)) == ["kept", "kept"]
        # each is where it was, and is shown to be taken or discarded
        assert {m["kept_in"]: files(m) for m in snap["merges"]} == {
            str(asked): {"a.txt": "ready"}, str(at_work): {"b.txt": "ready"}}
        assert {f["status"] for f in snap["file_changes"]} == {"in_copy"}
        assert not (project_dir / "a.txt").exists()


def at_work(settings_env, project_dir, coder, unattended=False):
    """A turn whose Coder is still at work when the app is closed; the conversation's id."""
    held = Gate()
    app_ = create_app(load_settings(settings_env), model=ScriptedModel({
        "Lead": [step(call("spawn_agent", {"role": "Coder", "task": "do it"}, "s")),
                 text("done")],
        "Coder": [*coder, held.step(text("A done"))],
    }))
    with TestClient(app_, base_url="http://127.0.0.1:8790") as client:
        client.headers["Origin"] = ORIGIN
        pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
        cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
        if unattended:
            made = trigger(client, pid, cid,
                           permissions={"write": True, "commands": [], "agents": 1})
            run_now(client, made["id"])
        else:
            assert client.patch(f"/api/conversations/{cid}", json={
                "permission_mode": "full_auto", "spawn_approval": "never"}).status_code == 200
            client.post(f"/api/conversations/{cid}/messages", json={"content": "go"})
        held.wait_partial()
    held.release()
    return cid


def card_of(client, cid):
    (card,) = client.get(f"/api/conversations/{cid}").json()["merges"]
    return card


def kept_folders(settings_env):
    return list(copies.folder(load_settings(settings_env).runtime_root).iterdir())


def test_after_a_restart_what_only_a_command_made_is_kept_and_can_be_taken(
    settings_env, project_dir
):
    """No change is on record of it: the copy itself says what it holds."""
    cid = at_work(settings_env, project_dir, [step(run(MAKES))])
    with again(settings_env) as client:
        card = card_of(client, cid)
        assert card["status"] == "kept" and files(card) == {"made.txt": "ready"}
        assert card["kept_in"] == str(kept_folders(settings_env)[0] / copies.TREE)
        assert "+by a command" in card["files"][0]["diff"]
        assert client.post(f"/api/merges/{card['id']}/approve").status_code == 200
        snap = client.get(f"/api/conversations/{cid}").json()
        assert snap["merges"][0]["status"] == "applied" and snap["merges"][0]["kept_in"] is None
        assert (project_dir / "made.txt").read_text(encoding="utf-8") == "by a command"
        assert [(f["path"], f["status"]) for f in snap["file_changes"]] == [
            ("made.txt", "applied")]
        assert kept_folders(settings_env) == []


def test_after_a_restart_apply_writes_what_the_card_showed(settings_env, project_dir):
    cid = interrupted(settings_env, project_dir)
    with again(settings_env) as client:
        card = card_of(client, cid)
        assert files(card) == {"a.txt": "ready"}
        (project_dir / "a.txt").write_text("THE USER'S OWN", encoding="utf-8")   # since
        assert client.post(f"/api/merges/{card['id']}/approve").status_code == 409
        said = card_of(client, cid)
        assert said["status"] == "kept" and files(said) == {"a.txt": "conflict"}
        assert "-THE USER'S OWN" in said["files"][0]["diff"]
        assert (project_dir / "a.txt").read_text(encoding="utf-8") == "THE USER'S OWN"
        assert len(kept_folders(settings_env)) == 1
        # shown as it is now, the yes is to that - with whose file is taken (slice 30:
        # nothing is chosen for the user) - and it can be taken back
        assert client.post(f"/api/merges/{card['id']}/approve").status_code == 409
        assert client.post(f"/api/merges/{card['id']}/approve", json={
            "choices": {"a.txt": "agent"}, "shown": seen(said)}).json()["status"] == "applied"
        assert (project_dir / "a.txt").read_text(encoding="utf-8") == "A"
        snap = client.get(f"/api/conversations/{cid}").json()
        assert revert(client, snap, "a.txt").status_code == 200
        assert (project_dir / "a.txt").read_text(encoding="utf-8") == "THE USER'S OWN"


def test_after_a_restart_a_kept_folder_deleted_by_hand_is_said_to_be_gone(
    settings_env, project_dir
):
    cid = interrupted(settings_env, project_dir)
    with again(settings_env) as client:
        assert card_of(client, cid)["status"] == "kept"
    (folder,) = kept_folders(settings_env)
    shutil.rmtree(folder)
    with again(settings_env) as client:
        card = card_of(client, cid)
        assert card["status"] == "discarded" and card["kept_in"] is None
        assert files(card) == {"a.txt": "refused"}
        assert card["files"][0]["note"] == "the folder its files were kept in is gone"
        snap = client.get(f"/api/conversations/{cid}").json()
        assert [f["status"] for f in snap["file_changes"]] == ["discarded"]
        assert client.post(f"/api/merges/{card['id']}/approve").status_code == 409


def test_after_a_restart_a_turn_nobody_watched_still_does_not_get_its_protected_paths(
    settings_env, project_dir
):
    cid = at_work(settings_env, project_dir, [step(write("notes.txt", "seen"))], unattended=True)
    (folder,) = kept_folders(settings_env)
    (folder / "tree" / ".claude").mkdir()           # as a command of its would have made it
    (folder / "tree" / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
    with again(settings_env) as client:
        card = card_of(client, cid)
        assert files(card) == {".claude/settings.json": "refused", "notes.txt": "ready"}
        assert "no trigger allows" in card["files"][0]["note"]
        assert client.post(f"/api/merges/{card['id']}/approve").status_code == 200
        assert (project_dir / "notes.txt").read_text(encoding="utf-8") == "seen"
        assert not (project_dir / ".claude").exists()
        # what was refused is nowhere but in the copy: it stays until Discard
        assert card_of(client, cid)["status"] == "kept"
        assert (folder / "tree" / ".claude" / "settings.json").is_file()


def test_a_copy_stop_threw_away_is_not_kept_at_the_next_start_though_its_folder_was_left(
    settings_env, project_dir, monkeypatch
):
    """Its command could not be killed, say: the folder is still there, and is no kept work."""
    monkeypatch.setattr(copies, "remove", lambda *given: None)
    held = Gate()
    app_ = create_app(load_settings(settings_env), model=ScriptedModel({
        "Lead": [step(call("spawn_agent", {"role": "Coder", "task": "do it"}, "s")),
                 text("done")],
        # (A command that changes nothing: since 6 Nov Stop keeps a copy with changes.)
        "Coder": [step(run("python -V")), held.step(text("A done"))],
    }))
    with TestClient(app_, base_url="http://127.0.0.1:8790") as client:
        client.headers["Origin"] = ORIGIN
        pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
        cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
        assert client.patch(f"/api/conversations/{cid}", json={
            "permission_mode": "full_auto", "spawn_approval": "never"}).status_code == 200
        run_id = client.post(f"/api/conversations/{cid}/messages",
                             json={"content": "go"}).json()["run"]["id"]
        held.wait_partial()
        assert client.post(f"/api/runs/{run_id}/cancel").status_code in (200, 202)
        until(client, cid, lambda s: s["runs"][0]["status"] == "cancelled")
        held.release()
        assert len(kept_folders(settings_env)) == 1
    monkeypatch.undo()
    with again(settings_env) as client:
        assert client.get(f"/api/conversations/{cid}").json()["merges"] == []
        assert kept_folders(settings_env) == []


def test_a_restart_keeps_a_copy_whose_changes_never_reached_the_project(tmp_path, settings):
    upgrade_db(settings.db_path)
    factory = make_session_factory(make_engine(settings.db_path))
    project = tmp_path / "proj"
    (project / "node_modules").mkdir(parents=True)
    (project / "node_modules" / "dep.js").write_text("dep", encoding="utf-8")
    (project / "hello.py").write_text("x", encoding="utf-8")
    asked, at_work, done = (copies.make(project, settings.runtime_root, name)
                            for name in ("asked", "atwork", "done"))
    (asked.root / "a.txt").write_text("A", encoding="utf-8")
    (at_work.root / "b.txt").write_text("B", encoding="utf-8")
    with factory() as s:
        on_record(s, project)
        # its card was waiting for the user
        an_agent(s, "asked")
        a_change(s, "f1", "asked", "a.txt")
        s.add(Merge(id="g", run_id="r", agent_id="asked", status="pending", files=[
            {"path": "a.txt", "kind": "new", "state": "ready"},
            {"path": "in.txt", "kind": "new", "state": "applied"}]))
        # it was at work, an agent below it in its copy
        an_agent(s, "atwork", status="running")
        an_agent(s, "below", status="running", copy="parent", parent="atwork")
        a_change(s, "f2", "below", "b.txt")
        a_change(s, "f3", "below", "b.txt", kind="modify")
        a_change(s, "f4", "atwork", "hello.py", kind="delete")
        # everything of it had reached the project
        an_agent(s, "done")
        # and one whose folder is not there any more
        an_agent(s, "lost")
        a_change(s, "f5", "lost", "c.txt")
        s.add(Merge(id="h", run_id="r", agent_id="lost", status="pending", files=[]))
        s.commit()
    for _start in range(2):         # and the start after that one keeps them too
        create_app(settings)
        assert not done.root.exists()
        # the user's work is where it was - without the links into the project
        assert (asked.root / "a.txt").read_text(encoding="utf-8") == "A"
        assert (at_work.root / "b.txt").read_text(encoding="utf-8") == "B"
        assert not (asked.root / "node_modules").exists()
        assert (project / "node_modules" / "dep.js").read_text(encoding="utf-8") == "dep"
        with factory() as s:
            assert s.get_one(Run, "r").status == "interrupted"
            merge = s.get_one(Merge, "g")
            assert merge.status == "interrupted"
            # what the copy itself holds that the project lacks, as a card shows it
            assert [(f["path"], f["state"]) for f in merge.files] == [
                ("a.txt", "ready"), ("in.txt", "applied")]
            assert merge.kept_in == str(asked.root)
            (made,) = s.scalars(select(Merge).where(Merge.agent_id == "atwork")).all()
            assert made.status == "interrupted" and made.kept_in == str(at_work.root)
            # (the deletion on record was never made in the copy: it is not shown)
            assert [(f["path"], f["kind"], f["state"]) for f in made.files] == [
                ("b.txt", "new", "ready")]
            # nobody rejected them, and they are where they were
            assert {c.id: c.status for c in s.scalars(select(FileChange))} == {
                "f1": "in_copy", "f2": "in_copy", "f3": "in_copy", "f4": "in_copy",
                "f5": "discarded"}
            assert s.get_one(Merge, "h").status == "discarded"
            assert s.scalar(select(func.count()).select_from(Merge)) == 3


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")
def test_a_script_made_runnable_in_the_copy_is_runnable_in_the_project(
    make_client, wait_run, project_dir
):
    code = "import os;open('run.sh','w').write('echo hi');os.chmod('run.sh',0o755)"
    client, model, cid, run_id = one(make_client, project_dir, [
        step(write("a.md", "A")), step(python(code)), text("A done"),
    ])
    assert wait_run(client, cid, run_id)["runs"][0]["status"] == "completed"
    assert (project_dir / "run.sh").stat().st_mode & 0o111 == 0o111
    assert (project_dir / "a.md").stat().st_mode & 0o111 == 0
