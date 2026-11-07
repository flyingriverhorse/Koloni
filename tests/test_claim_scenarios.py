"""File claims' acceptance set (slice 19a): two agents do not change one file at a time.

Written before the code. The user's rule: "if they work on the same file, one waits until
the other has finished". An agent that is about to change a file holds it until its own work
is done; another agent that wants the same file waits - it is not refused, and it does not
write over what the first one did. Different files do not wait for each other.
"""

from importlib.util import find_spec

import pytest

pytest.importorskip("app.claims")  # written before the code: skipped until it exists

# Since slice 19b a sub-agent changes files in a working copy of its own, and the project
# gets them when its work is over: where a scenario looked into the project while the agent
# was still at work, or after Stop, it looks at what holds since then.
COPIES = find_spec("app.copies") is not None

from tests.conftest import Gate  # noqa: E402
from tests.test_chat_flow import text  # noqa: E402
from tests.test_parallel import until  # noqa: E402
from tests.test_spawn import call, step  # noqa: E402

ORIGIN = "http://127.0.0.1:8790"


def write(path, content, id="w"):
    return call("write_file", {"path": path, "content": content}, id)


def two(task_a="do A", task_b="do B"):
    """One step that opens two Coders at once: "Coder" and "Coder 2"."""
    return step(call("spawn_agent", {"role": "Coder", "task": task_a}, "s1"),
                call("spawn_agent", {"role": "Coder", "task": task_b}, "s2"))


def setup(make_client, project_dir, scripts, **conversation):
    client, model = make_client(scripts)
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    settings = {"permission_mode": "full_auto", "spawn_approval": "never",
                "spawn_max_parallel": 2, **conversation}
    assert client.patch(f"/api/conversations/{cid}", json=settings).status_code == 200
    run = client.post(f"/api/conversations/{cid}/messages", json={"content": "go"}).json()["run"]
    return client, model, cid, run["id"]


def agent(snap, name):
    return next(a for a in snap["agents"] if a["name"] == name)


def waits(snap, name):
    """What the named agent is waiting for, or None: {"agent_name", "path"}."""
    held = agent(snap, name).get("waiting_for") if any(
        a["name"] == name for a in snap["agents"]) else None
    return (held["agent_name"], held["path"]) if held else None


def calls(snap, name, tool):
    wanted = agent(snap, name)["id"]
    return [(t["status"], t["result"] or "") for t in snap["tool_calls"]
            if t["agent_id"] == wanted and t["name"] == tool]


def test_the_second_agent_waits_for_the_first_to_finish_with_the_file(
    make_client, wait_run, project_dir
):
    first, second = Gate(), Gate()
    client, model, cid, run_id = setup(make_client, project_dir, {
        "Lead": [two(), text("done")],
        "Coder": [step(write("shared.txt", "one")), first.step(text("A done"))],
        "Coder 2": [second.step(step(write("shared.txt", "two"))), text("B done")],
    })
    first.wait_partial()            # the Coder has written the file and is still at work
    second.release()                # now the other one reaches for the same file
    snap = until(client, cid, lambda s: waits(s, "Coder 2") is not None)
    assert waits(snap, "Coder 2") == ("Coder", "shared.txt")
    assert agent(snap, "Coder 2")["status"] == "blocked"
    assert {"path": "shared.txt", "agent_id": agent(snap, "Coder")["id"]} in snap["claims"]
    if not COPIES:
        assert (project_dir / "shared.txt").read_text(encoding="utf-8") == "one"
    # waiting, not refused: the call is still open
    assert calls(snap, "Coder 2", "write_file")[0][0] in ("running", "pending")
    first.release()
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed"
    # it did not write over what the first one left: it is told to look again
    ((status, said),) = calls(snap, "Coder 2", "write_file")
    assert status == "failed" and "Coder" in said and "read it again" in said
    assert (project_dir / "shared.txt").read_text(encoding="utf-8") == "one"
    assert snap["claims"] == [] and waits(snap, "Coder 2") is None


def test_agents_on_different_files_do_not_wait_for_each_other(
    make_client, wait_run, project_dir
):
    first = Gate()
    client, model, cid, run_id = setup(make_client, project_dir, {
        "Lead": [two(), text("done")],
        "Coder": [step(write("a.txt", "one")), first.step(text("A done"))],
        "Coder 2": [step(write("b.txt", "two")), text("B done")],
    })
    first.wait_partial()
    snap = until(client, cid, lambda s: agent(s, "Coder 2")["status"] == "completed")
    assert agent(snap, "Coder")["status"] == "running"
    assert (project_dir / "b.txt").read_text(encoding="utf-8") == "two"
    first.release()
    wait_run(client, cid, run_id)


def test_after_waiting_an_agent_reads_again_and_then_makes_its_change(
    make_client, wait_run, project_dir
):
    first, second, both_read = Gate(), Gate(), Gate()
    edit = call("edit_file", {"path": "hello.py", "old_string": "print", "new_string": "PRINT"},
                "e1")
    client, model, cid, run_id = setup(make_client, project_dir, {
        "Lead": [two(), text("done")],
        "Coder": [step(call("read_file", {"path": "hello.py"}, "r")),
                  both_read.step(step(call("edit_file", {"path": "hello.py", "old_string": "'hi'",
                                                         "new_string": "'hello'"}, "e"))),
                  first.step(text("A done"))],
        "Coder 2": [step(call("read_file", {"path": "hello.py"}, "r1")),
                    second.step(step(edit)),
                    step(call("read_file", {"path": "hello.py"}, "r2")),
                    step(call("edit_file", {"path": "hello.py", "old_string": "print",
                                            "new_string": "PRINT"}, "e2")),
                    text("B done")],
    })
    # the order the scenario is about: Coder 2 has read the file before the Coder changes it
    until(client, cid, lambda s: any(a["name"] == "Coder 2" for a in s["agents"])
          and [status for status, _ in calls(s, "Coder 2", "read_file")] == ["succeeded"])
    both_read.release()
    first.wait_partial()
    second.release()
    until(client, cid, lambda s: waits(s, "Coder 2") is not None)
    first.release()
    snap = wait_run(client, cid, run_id)
    statuses =[status for status, _ in calls(snap, "Coder 2", "edit_file")]
    assert statuses == ["failed", "succeeded"], statuses
    # both changes are in the file: neither was lost
    assert (project_dir / "hello.py").read_text(encoding="utf-8") == "PRINT('hello')\n"


def test_a_sub_agent_takes_up_a_file_the_agent_it_works_for_was_changing(
    make_client, wait_run, project_dir
):
    """The lead waits for its sub-agent anyway: the file is not held against it."""
    client, model, cid, run_id = setup(make_client, project_dir, {
        "Lead": [step(write("shared.txt", "lead")),
                 step(call("spawn_agent", {"role": "Coder", "task": "go on with it"}, "s")),
                 step(write("shared.txt", "lead again", "w2")), text("done")],
        "Coder": [step(write("shared.txt", "coder")), text("A done")],
    })
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed"
    assert calls(snap, "Coder", "write_file") != [] and waits(snap, "Coder") is None
    # nobody ever waited; each wrote over a file it had not read again and was told so,
    # or wrote it - but the turn did not hang
    assert all(a["status"] == "completed" for a in snap["agents"])


def test_two_agents_waiting_for_each_other_do_not_wait_for_ever(
    make_client, wait_run, project_dir
):
    first, second = Gate(), Gate()
    client, model, cid, run_id = setup(make_client, project_dir, {
        "Lead": [two(), text("done")],
        "Coder": [step(write("a.txt", "A")), first.step(step(write("b.txt", "A", "w2"))),
                  text("A done")],
        "Coder 2": [step(write("b.txt", "B")), second.step(step(write("a.txt", "B", "w2"))),
                    text("B done")],
    })
    first.wait_partial()
    second.wait_partial()
    first.release()                 # the Coder now waits for b.txt, which Coder 2 holds
    until(client, cid, lambda s: waits(s, "Coder") == ("Coder 2", "b.txt"))
    second.release()                # and Coder 2 reaches for a.txt, which the Coder holds
    snap = wait_run(client, cid, run_id, timeout=10)
    assert snap["runs"][0]["status"] == "completed"
    _first, (status, said) = calls(snap, "Coder 2", "write_file")
    assert status == "failed" and "waiting for you" in said     # told at once, not held
    assert (project_dir / "a.txt").read_text(encoding="utf-8") == "A"
    assert (project_dir / "b.txt").read_text(encoding="utf-8") == "B"
    assert snap["claims"] == []


def test_a_change_waiting_for_the_users_yes_holds_the_file_too(
    make_client, wait_run, project_dir
):
    if COPIES:
        pytest.skip("asked once per agent since 19b: tests/test_copy_scenarios.py, "
                    "test_a_card_waiting_for_the_user_holds_its_files")
    second = Gate()
    client, model, cid, run_id = setup(make_client, project_dir, {
        "Lead": [two(), text("done")],
        "Coder": [step(write("shared.txt", "one")), text("A done")],
        "Coder 2": [second.step(step(write("shared.txt", "two"))), text("B done")],
    }, permission_mode="ask")
    snap = until(client, cid, lambda s: any(
        f["status"] == "proposed" for f in s["file_changes"]))
    second.release()
    snap = until(client, cid, lambda s: waits(s, "Coder 2") is not None)
    # one change is put before the user, not two for the same file
    proposed = [f for f in snap["file_changes"] if f["status"] == "proposed"]
    assert [f["path"] for f in proposed] == ["shared.txt"]
    assert client.post(f"/api/file-changes/{proposed[0]['id']}/approve").status_code == 200
    snap = wait_run(client, cid, run_id)
    assert (project_dir / "shared.txt").read_text(encoding="utf-8") == "one"
    assert [f["path"] for f in snap["file_changes"]] == ["shared.txt"]


def test_an_agent_that_waits_for_a_file_gives_its_place_to_another(
    make_client, wait_run, project_dir
):
    first, second = Gate(), Gate()
    client, model, cid, run_id = setup(make_client, project_dir, {
        "Lead": [step(call("spawn_agent", {"role": "Coder", "task": "A"}, "s1"),
                      call("spawn_agent", {"role": "Coder", "task": "B"}, "s2"),
                      call("spawn_agent", {"role": "Coder", "task": "C"}, "s3")),
                 text("done")],
        "Coder": [step(write("shared.txt", "one")), first.step(text("A done"))],
        "Coder 2": [second.step(step(write("shared.txt", "two"))), text("B done")],
        "Coder 3": [step(write("c.txt", "three")), text("C done")],
    })  # two at a time: the third is queued until a place is free
    first.wait_partial()
    second.release()
    until(client, cid, lambda s: waits(s, "Coder 2") is not None)
    # the one that waits holds no place: the third gets to work and finishes
    snap = until(client, cid, lambda s: agent(s, "Coder 3")["status"] == "completed")
    assert agent(snap, "Coder")["status"] == "running"
    assert (project_dir / "c.txt").read_text(encoding="utf-8") == "three"
    first.release()
    wait_run(client, cid, run_id)


def test_stop_ends_a_turn_in_which_an_agent_waits_for_a_file(
    make_client, wait_run, project_dir
):
    first, second = Gate(), Gate()
    client, model, cid, run_id = setup(make_client, project_dir, {
        "Lead": [two(), text("done")],
        "Coder": [step(write("shared.txt", "one")), first.step(text("A done"))],
        "Coder 2": [second.step(step(write("shared.txt", "two"))), text("B done")],
    })
    first.wait_partial()
    second.release()
    until(client, cid, lambda s: waits(s, "Coder 2") is not None)
    assert client.post(f"/api/runs/{run_id}/cancel").status_code in (200, 202)
    snap = wait_run(client, cid, run_id)
    first.release()
    assert snap["runs"][0]["status"] == "cancelled"
    assert snap["claims"] == []
    assert all(a["status"] != "blocked" and not a.get("waiting_for") for a in snap["agents"])
    if COPIES:      # Stop leaves nothing of an unfinished agent in the project
        assert not (project_dir / "shared.txt").exists()
    else:
        assert (project_dir / "shared.txt").read_text(encoding="utf-8") == "one"
