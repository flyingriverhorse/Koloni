"""Working copies' acceptance set (slice 19b): each sub-agent works in a copy of its own.

Written before the code. The user's rule: agents that work in different places get a working
copy each. A sub-agent's changes are made in its copy, where its commands run too; the
project gets them when its work is over - asked for once per agent where the user is asked,
never over what changed in the project meanwhile, and not at all after Stop. File claims
(slice 19a) go on holding across the copies.
"""

import threading
import time
from dataclasses import replace

import pytest

pytest.importorskip("app.copies")  # written before the code: skipped until it exists

import app.agent as agent_module  # noqa: E402
from app import copies  # noqa: E402
from app.config import load_settings  # noqa: E402
from app.db.models import Merge  # noqa: E402
from tests.conftest import Gate  # noqa: E402
from tests.test_chat_flow import text  # noqa: E402
from tests.test_claim_scenarios import agent, calls, setup, two, waits, write  # noqa: E402
from tests.test_parallel import until  # noqa: E402
from tests.test_spawn import call, role_id, step  # noqa: E402
from tests.test_topic_scenarios import calls_of  # noqa: E402
from tests.test_trigger_scenarios import run_now, trigger  # noqa: E402

ORIGIN = "http://127.0.0.1:8790"


def run(command, id="c"):
    return call("run_command", {"command": command}, id)


def exists(path):
    return run(f"python -c \"import os;print('THERE' if os.path.exists('{path}') else 'ABSENT')\"")


def files(merge):
    return {f["path"]: f["state"] for f in merge["files"]}


def seen(merge):
    """What the card shows of each file it asks about: Apply sends it back."""
    return {f["path"]: f["shown"] for f in merge["files"]
            if f["state"] in ("ready", "merged", "conflict")}


def one(make_client, project_dir, coder, lead=None, **conversation):
    """A lead that opens one Coder."""
    return setup(make_client, project_dir, {
        "Lead": lead or [step(call("spawn_agent", {"role": "Coder", "task": "do it"}, "s")),
                         text("done")],
        "Coder": coder,
    }, **conversation)


def test_each_agent_works_in_its_own_copy_and_the_project_gets_both(
    make_client, wait_run, project_dir
):
    first, second = Gate(), Gate()
    client, model, cid, run_id = setup(make_client, project_dir, {
        "Lead": [two(), step(call("read_file", {"path": "half.py"}, "r")), text("done")],
        "Coder": [step(write("half.py", "def broken(:\n")), first.step(text("A done"))],
        "Coder 2": [step(write("b.txt", "two")), second.step(step(exists("half.py"))),
                    text("B done")],
    })
    first.wait_partial()            # the Coder has written half a file and is still at work
    second.release()
    snap = until(client, cid, lambda s: [m["status"] for m in s["merges"]] == ["applied"])
    # the other one's command did not see it, and neither does the project yet
    ((status, said),) = calls(snap, "Coder 2", "run_command")
    assert status == "succeeded" and "ABSENT" in said
    assert not (project_dir / "half.py").exists()
    assert agent(snap, "Coder")["copy"] == {"state": "own"}
    assert agent(snap, "Lead")["copy"] is None
    # the one that is done is in the project already
    assert (project_dir / "b.txt").read_text(encoding="utf-8") == "two"
    first.release()
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed"
    assert (project_dir / "half.py").read_text(encoding="utf-8") == "def broken(:\n"
    assert [m["status"] for m in snap["merges"]] == ["applied", "applied"]
    assert all(f["status"] == "applied" for f in snap["file_changes"])
    # the lead got its answer after the project had the change: it reads the file there
    ((status, said),) = calls(snap, "Lead", "read_file")
    assert status == "succeeded" and "broken" in said


def test_where_the_user_is_asked_there_is_one_card_for_an_agent(
    make_client, wait_run, project_dir
):
    client, model, cid, run_id = one(make_client, project_dir, [
        step(write("a.txt", "A")), step(write("b.txt", "B", "w2")), text("A done"),
    ], permission_mode="ask")
    snap = until(client, cid, lambda s: [m["status"] for m in s["merges"]] == ["pending"])
    (card,) = snap["merges"]
    assert files(card) == {"a.txt": "ready", "b.txt": "ready"}
    assert snap["runs"][0]["status"] == "waiting_approval"
    # nothing was asked change by change, and nothing is in the project yet
    assert not [f for f in snap["file_changes"] if f["status"] == "proposed"]
    assert not (project_dir / "a.txt").exists()
    assert client.post(f"/api/merges/{card['id']}/approve").status_code == 200
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed"
    assert (project_dir / "a.txt").read_text(encoding="utf-8") == "A"
    assert (project_dir / "b.txt").read_text(encoding="utf-8") == "B"
    assert snap["merges"][0]["status"] == "applied" and snap["claims"] == []


def test_a_card_that_is_turned_down_leaves_the_project_as_it_was(
    make_client, wait_run, project_dir
):
    client, model, cid, run_id = one(make_client, project_dir, [
        step(call("edit_file", {"path": "hello.py", "old_string": "hi", "new_string": "yo"},
                  "e")), step(write("a.txt", "A")), text("A done"),
    ], permission_mode="ask")
    snap = until(client, cid, lambda s: [m["status"] for m in s["merges"]] == ["pending"])
    assert client.post(f"/api/merges/{snap['merges'][0]['id']}/reject").status_code == 200
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed"
    assert (project_dir / "hello.py").read_text(encoding="utf-8") == "print('hi')\n"
    assert not (project_dir / "a.txt").exists()
    assert snap["merges"][0]["status"] == "rejected" and snap["claims"] == []
    # the lead is told: it does not go on as if the change were there
    assert "not applied" in calls(snap, "Lead", "spawn_agent")[0][1]


def test_a_card_waiting_for_the_user_holds_its_files(make_client, wait_run, project_dir):
    second = Gate()
    client, model, cid, run_id = setup(make_client, project_dir, {
        "Lead": [two(), text("done")],
        "Coder": [step(write("shared.txt", "one")), text("A done")],
        "Coder 2": [second.step(step(write("shared.txt", "two"))), text("B done")],
    }, permission_mode="ask")
    snap = until(client, cid, lambda s: [m["status"] for m in s["merges"]] == ["pending"])
    second.release()
    snap = until(client, cid, lambda s: waits(s, "Coder 2") is not None)
    assert waits(snap, "Coder 2") == ("Coder", "shared.txt")
    assert client.post(f"/api/merges/{snap['merges'][0]['id']}/approve").status_code == 200
    snap = until(client, cid, lambda s: calls(s, "Coder 2", "write_file")[0][0] == "failed")
    assert "read it again" in calls(snap, "Coder 2", "write_file")[0][1]
    snap = wait_run(client, cid, run_id)
    assert (project_dir / "shared.txt").read_text(encoding="utf-8") == "one"


def test_what_changed_in_the_project_meanwhile_is_not_written_over(
    make_client, wait_run, project_dir
):
    """A command is not held by file claims: what it changed in the copy is found when the
    copy is taken into the project."""
    first = Gate()
    client, model, cid, run_id = one(make_client, project_dir, [
        step(write("a.txt", "A")),
        step(run("python -c \"open('hello.py','w').write('FROM THE COPY')\"")),
        first.step(text("A done")),
    ])
    first.wait_partial()
    (project_dir / "hello.py").write_text("THE USER'S OWN", encoding="utf-8")
    first.release()
    snap = until(client, cid, lambda s: [m["status"] for m in s["merges"]] == ["pending"])
    assert files(snap["merges"][0]) == {"a.txt": "applied", "hello.py": "conflict"}
    assert snap["runs"][0]["status"] == "waiting_approval"      # asked, even in full auto
    assert (project_dir / "a.txt").read_text(encoding="utf-8") == "A"
    assert (project_dir / "hello.py").read_text(encoding="utf-8") == "THE USER'S OWN"
    assert client.post(f"/api/merges/{snap['merges'][0]['id']}/reject").status_code == 200
    snap = wait_run(client, cid, run_id)
    assert (project_dir / "hello.py").read_text(encoding="utf-8") == "THE USER'S OWN"
    assert (project_dir / "a.txt").read_text(encoding="utf-8") == "A"


def copies_left(settings_env):
    held_in = copies.folder(load_settings(settings_env).runtime_root)
    return list(held_in.iterdir()) if held_in.is_dir() else []


@pytest.mark.parametrize("how", ["stop", "stop_everything"])
@pytest.mark.parametrize("mode", ["full_auto", "ask"])
def test_stop_keeps_an_unfinished_agents_work_for_the_user_and_nothing_in_the_project(
    make_client, wait_run, project_dir, settings_env, mode, how
):
    """6 Nov (the user's word): Stop, or Stop everything, mid-work keeps a sub-agent's half
    work in its copy behind a kept card, at every level - the project gets it only at the
    user's Take in."""
    first = Gate()
    client, model, cid, run_id = one(make_client, project_dir, [
        step(write("a.txt", "A")), first.step(text("A done")),
    ], permission_mode=mode)
    first.wait_partial()
    if how == "stop":
        assert client.post(f"/api/runs/{run_id}/cancel").status_code in (200, 202)
    else:
        assert client.post("/api/hold").json()["held"] is True
    snap = wait_run(client, cid, run_id)
    first.release()
    assert snap["runs"][0]["status"] in ("cancelled", "interrupted")
    assert not (project_dir / "a.txt").exists()
    assert snap["claims"] == []
    (kept,) = snap["merges"]
    assert kept["status"] == "kept" and files(kept) == {"a.txt": "ready"}
    assert len(copies_left(settings_env)) == 1
    assert client.post(f"/api/merges/{kept['id']}/approve").status_code == 200
    assert (project_dir / "a.txt").read_text(encoding="utf-8") == "A"
    assert copies_left(settings_env) == []


def test_stop_drops_the_copy_of_an_agent_that_changed_nothing(
    make_client, wait_run, project_dir, settings_env
):
    first = Gate()
    client, model, cid, run_id = one(make_client, project_dir, [
        step(call("list_dir", {}, "l")), first.step(text("A done")),
    ])
    first.wait_partial()
    assert client.post(f"/api/runs/{run_id}/cancel").status_code in (200, 202)
    snap = wait_run(client, cid, run_id)
    first.release()
    assert snap["runs"][0]["status"] == "cancelled"
    assert snap["merges"] == [] and copies_left(settings_env) == []


@pytest.mark.parametrize("how", ["stop", "stop_everything"])
def test_stop_while_a_finished_agents_card_waits_keeps_its_work_for_the_user(
    make_client, wait_run, project_dir, settings_env, how
):
    """6 Nov: Stop must not lose work - a finished agent's Take in card that waits becomes a
    kept card, the project untouched until the user takes it in."""
    client, model, cid, run_id = one(make_client, project_dir, [
        step(write("a.txt", "A")), text("A done"),
    ], permission_mode="ask")
    (card,) = until(client, cid, lambda s: [m["status"] for m in s["merges"]] == ["pending"])[
        "merges"]
    if how == "stop":
        assert client.post(f"/api/runs/{run_id}/cancel").status_code in (200, 202)
    else:
        assert client.post("/api/hold").json()["held"] is True
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] in ("cancelled", "interrupted")
    (kept,) = snap["merges"]
    assert kept["id"] == card["id"] and kept["status"] == "kept"
    assert files(kept) == {"a.txt": "ready"} and snap["claims"] == []
    assert not (project_dir / "a.txt").exists() and len(copies_left(settings_env)) == 1
    assert client.post(f"/api/merges/{kept['id']}/approve").status_code == 200
    assert (project_dir / "a.txt").read_text(encoding="utf-8") == "A"
    assert copies_left(settings_env) == []


def test_a_kept_copys_secret_file_stays_refused_after_a_restart(
    make_client, wait_run, project_dir, settings_env, monkeypatch
):
    """Review M2: after a restart the turn's secrets are gone from memory - the file that held
    one was shown ready, its diff (the secret) on record, and Take in wrote it in."""
    from app.agent import AgentRunner

    monkeypatch.setattr(AgentRunner, "given_spellings", lambda self, run_id=None: ["s3cr3t-value"])
    first = Gate()
    client, model, cid, run_id = one(make_client, project_dir, [
        step(write("token.txt", "key s3cr3t-value\n"), write("a.txt", "A", "w2")),
        first.step(text("A done")),
    ])
    first.wait_partial()
    assert client.post(f"/api/runs/{run_id}/cancel").status_code in (200, 202)
    (kept,) = wait_run(client, cid, run_id)["merges"]
    first.release()
    assert files(kept) == {"token.txt": "refused", "a.txt": "ready"}
    monkeypatch.undo()
    client.__exit__(None, None, None)  # (a restart: nothing of the turn's secrets in memory)
    client, _model = make_client({})
    client.headers["Origin"] = ORIGIN
    (kept,) = client.get(f"/api/conversations/{cid}").json()["merges"]
    assert kept["status"] == "kept"
    assert files(kept) == {"token.txt": "refused", "a.txt": "ready"}
    assert "s3cr3t" not in str(kept)
    assert client.post(f"/api/merges/{kept['id']}/approve").status_code == 200
    assert (project_dir / "a.txt").read_text(encoding="utf-8") == "A"
    assert not (project_dir / "token.txt").exists()


def test_stop_keeps_the_copy_whole_where_it_cannot_be_looked_at(
    make_client, wait_run, project_dir, settings_env, monkeypatch
):
    """Review L1: the look for its kept card failed - the copy was dropped, unsaid."""
    from app.agent import AgentRunner

    async def fails(self, owner, copy):
        raise RuntimeError("cannot look")

    monkeypatch.setattr(AgentRunner, "_keep_stopped", fails)
    first = Gate()
    client, model, cid, run_id = one(make_client, project_dir, [
        step(write("a.txt", "A")), first.step(text("A done")),
    ])
    first.wait_partial()
    assert client.post(f"/api/runs/{run_id}/cancel").status_code in (200, 202)
    snap = wait_run(client, cid, run_id)
    first.release()
    (kept,) = snap["merges"]
    assert kept["status"] == "kept" and len(copies_left(settings_env)) == 1
    assert not (project_dir / "a.txt").exists()


def test_a_second_stop_while_the_half_work_is_kept_does_not_lose_it(
    make_client, wait_run, project_dir, settings_env, monkeypatch
):
    """B-405's guard for a plain copy too: Stop pressed again while the copy is being looked
    at for its kept card - the turn's end does not delete it under the card."""
    looking, real = threading.Event(), agent_module._kept_files

    def slow(*args, **kwargs):
        looking.set()
        time.sleep(0.5)  # (the second Stop comes now)
        return real(*args, **kwargs)

    monkeypatch.setattr(agent_module, "_kept_files", slow)
    first = Gate()
    client, model, cid, run_id = one(make_client, project_dir, [
        step(write("a.txt", "A")), first.step(text("A done")),
    ])
    first.wait_partial()
    assert client.post(f"/api/runs/{run_id}/cancel").status_code == 202
    assert looking.wait(20)
    assert client.post(f"/api/runs/{run_id}/cancel").status_code in (202, 409)
    snap = wait_run(client, cid, run_id)
    first.release()
    (kept,) = snap["merges"]
    assert kept["status"] == "kept" and files(kept) == {"a.txt": "ready"}
    assert len(copies_left(settings_env)) == 1 and not (project_dir / "a.txt").exists()


def looping(tag):
    """Past the step limit (25): the agent stops with what it had changed."""
    return [step(call("list_dir", {}, f"{tag}{n}")) for n in range(25)]


@pytest.mark.parametrize("mode", ["full_auto", "auto_edit", "ask"])
def test_agents_that_stop_unfinished_keep_their_work_and_do_not_hold_up_the_lead(
    make_client, wait_run, project_dir, mode
):
    """B-322 (live): two Coders stopped at the step limit with half-done work, and the Lead's
    calls waited on their Take in cards for 20 minutes. The Lead hears at once that each one
    stopped and which files wait for the user; the turn ends with nobody's word, and the work
    is neither lost nor in the project before the user takes it in."""
    client, model, cid, run_id = setup(make_client, project_dir, {
        "Lead": [two(), text("done")],
        "Coder": [step(write("a.txt", "A")), *looping("a"), text("never said")],
        "Coder 2": [step(write("b.txt", "B")), *looping("b"), text("never said")],
    }, permission_mode=mode)
    snap = wait_run(client, cid, run_id, timeout=20)
    assert snap["runs"][0]["status"] == "completed"
    told = {result.split(" stopped after ")[0]: result
            for _status, result in calls(snap, "Lead", "spawn_agent")}
    for name, path in (("Coder", "a.txt"), ("Coder 2", "b.txt")):
        assert f"({path})" in told[name] and "Take in" in told[name]
    kept = {m["files"][0]["path"]: m for m in snap["merges"]}
    assert sorted(kept) == ["a.txt", "b.txt"]
    assert all(m["status"] == "kept" and m["kept_in"] for m in kept.values())
    assert not (project_dir / "a.txt").exists() and not (project_dir / "b.txt").exists()
    # the user's Take in, after the turn
    assert client.post(f"/api/merges/{kept['a.txt']['id']}/approve").status_code == 200
    assert (project_dir / "a.txt").read_text(encoding="utf-8") == "A"


def test_a_stopped_agents_kept_card_says_its_check_did_not_run(make_client, wait_run, project_dir):
    """B-322: with a check command on the project, the card says no check ran on it."""
    client, model = make_client({
        "Lead": [step(call("spawn_agent", {"role": "Coder", "task": "do it"}, "s")), text("done")],
        "Coder": [step(write("a.txt", "A")), *looping("a")]})
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    assert client.patch(f"/api/projects/{pid}", json={"check_command": "python -V"}).status_code == 200
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(f"/api/conversations/{cid}", json={"permission_mode": "full_auto",
                                                    "spawn_approval": "never"})
    run_id = client.post(f"/api/conversations/{cid}/messages", json={"content": "go"}).json()["run"]["id"]
    (kept,) = wait_run(client, cid, run_id, timeout=20)["merges"]
    assert kept["check"]["state"] == "not_run" and "stopped before it finished" in kept["check"]["note"]


GO_ON = [step(call("spawn_agent", {"role": "Coder", "task": "A"}, "s")),
         step(call("message_agent", {"to": "Coder", "message": "go on"}, "m")), text("done")]


def a_txt(snap):
    return [f["status"] for f in snap["file_changes"] if f["path"] == "a.txt"]


def test_an_agent_that_goes_on_after_it_stopped_gets_its_kept_copy_back(
    make_client, wait_run, project_dir
):
    """B-322: told to go on, the Coder is in its own copy again - it reads and changes what it
    wrote there - and the project gets its work once, through the one Take in."""
    client, model, cid, run_id = one(make_client, project_dir, [
        step(write("a.txt", "A")), *looping("a")[:24],  # (its 25th step is its last)
        step(call("read_file", {"path": "a.txt"}, "r")),
        step(call("edit_file", {"path": "a.txt", "old_string": "A", "new_string": "A2"}, "e")),
        text("A2 done"),
    ], lead=GO_ON, permission_mode="ask")
    snap = until(client, cid, lambda s: "pending" in [m["status"] for m in s["merges"]],
                 timeout=20)
    assert [status for status, _said in calls(snap, "Coder", "read_file")] == ["succeeded"]
    assert [status for status, _said in calls(snap, "Coder", "edit_file")] == ["succeeded"]
    # the kept card is withdrawn: one card holds all of it, and nothing is in the project yet
    assert sorted(m["status"] for m in snap["merges"]) == ["discarded", "pending"]
    assert not any(m["files"] for m in snap["merges"] if m["status"] == "discarded")
    assert not (project_dir / "a.txt").exists()
    card = next(m for m in snap["merges"] if m["status"] == "pending")
    assert client.post(f"/api/merges/{card['id']}/approve").status_code == 200
    snap = wait_run(client, cid, run_id)
    assert (project_dir / "a.txt").read_text(encoding="utf-8") == "A2"
    assert a_txt(snap) == ["applied", "applied"]
    assert "kept" not in [m["status"] for m in snap["merges"]]  # nothing kept after
    for change in reversed([f for f in snap["file_changes"] if f["path"] == "a.txt"]):
        assert client.post(f"/api/file-changes/{change['id']}/revert").status_code == 200
    assert not (project_dir / "a.txt").exists()


def test_stop_while_a_stopped_agent_goes_on_keeps_its_work_for_the_user(
    make_client, wait_run, project_dir
):
    """B-322: its copy given back, the card is withdrawn - a Stop then does not throw away
    what the card held: it is kept for the user again."""
    gate = Gate()
    client, model, cid, run_id = one(make_client, project_dir, [
        step(write("a.txt", "A")), *looping("a")[:24], gate.step(text("never said")),
    ], lead=GO_ON)
    gate.wait_partial()
    assert client.post(f"/api/runs/{run_id}/cancel").status_code in (200, 202)
    snap = wait_run(client, cid, run_id)
    gate.release()
    (kept,) = [m for m in snap["merges"] if m["status"] == "kept"]
    assert [f["path"] for f in kept["files"]] == ["a.txt"] and kept["kept_in"]
    assert client.post(f"/api/merges/{kept['id']}/approve").status_code == 200
    assert (project_dir / "a.txt").read_text(encoding="utf-8") == "A"


def gated_go_on(make_client, project_dir, coder):
    """A Coder that writes a.txt and b.txt and stops; the Lead waits to tell it to go on."""
    gate = Gate()
    client, model, cid, run_id = one(make_client, project_dir, [
        step(write("a.txt", "A"), write("b.txt", "B", "w1")), *looping("a")[:24], *coder,
    ], lead=[GO_ON[0], gate.step(GO_ON[1]), GO_ON[2]], permission_mode="ask")
    gate.wait_partial()
    (kept,) = client.get(f"/api/conversations/{cid}").json()["merges"]
    return client, cid, run_id, gate, kept


def test_after_the_user_discarded_its_kept_card_a_stopped_agent_can_go_on(
    make_client, wait_run, project_dir
):
    """B-322: its card turned down, the Coder goes on in a new copy - and may write the file
    again, which is not "as it last read it" any more."""
    client, cid, run_id, gate, kept = gated_go_on(make_client, project_dir, [
        step(write("a.txt", "A2", "w2")), text("A2 done")])
    assert client.post(f"/api/merges/{kept['id']}/reject").status_code == 200
    gate.release()
    snap = until(client, cid, lambda s: "pending" in [m["status"] for m in s["merges"]],
                 timeout=20)
    status, said = calls(snap, "Coder", "write_file")[-1]
    assert status == "succeeded" and "Your earlier changes are not in this copy" in said
    card = next(m for m in snap["merges"] if m["status"] == "pending")
    assert client.post(f"/api/merges/{card['id']}/approve").status_code == 200
    wait_run(client, cid, run_id)
    assert (project_dir / "a.txt").read_text(encoding="utf-8") == "A2"


def test_a_partly_applied_kept_card_is_not_given_back(make_client, wait_run, project_dir):
    """B-322: what of the card is in the project already is the user's word on it: the Coder
    goes on in a new copy, and the card stays for the rest."""
    client, cid, run_id, gate, kept = gated_go_on(make_client, project_dir, [
        step(write("c.txt", "C", "w2")), text("C done")])
    with client.app.state.runner._factory() as session:  # (as after an Apply that took a.txt)
        merge = session.get_one(Merge, kept["id"])
        merge.files = [{**one, "state": "applied"} if one["path"] == "a.txt" else one
                       for one in merge.files]
        session.commit()
    gate.release()
    snap = until(client, cid, lambda s: "pending" in [m["status"] for m in s["merges"]],
                 timeout=20)
    assert next(m for m in snap["merges"] if m["id"] == kept["id"])["status"] == "kept"
    status, said = calls(snap, "Coder", "write_file")[-1]
    assert status == "succeeded" and "not in this copy: b.txt went" in said


def stopped_at_its_roles_steps(make_client, project_dir, coder, raise_to=None,
                               mode="full_auto"):
    """A Coder whose role lets it take three steps stops; then, the role's limit raised to
    `raise_to` (or left as it is), the Lead tells it to go on."""
    gate = Gate()
    client, model = make_client({"Lead": [GO_ON[0], gate.step(GO_ON[1]), GO_ON[2]],
                                 "Coder": coder})
    client.headers["Origin"] = ORIGIN
    assert client.patch(f"/api/roles/{role_id(client, 'Coder')}",
                        json={"max_steps": 3}).status_code == 200
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    assert client.patch(f"/api/conversations/{cid}", json={
        "permission_mode": mode, "spawn_approval": "never"}).status_code == 200
    run_id = client.post(f"/api/conversations/{cid}/messages",
                         json={"content": "go"}).json()["run"]["id"]
    gate.wait_partial()
    if raise_to is not None:
        assert client.patch(f"/api/roles/{role_id(client, 'Coder')}",
                            json={"max_steps": raise_to}).status_code == 200
    gate.release()
    return client, model, cid, run_id


@pytest.mark.parametrize("raise_to, said, steps", [
    (10, "Coder replied:", 9),
    # the 3 it took count: of 5, it has 2 left
    (5, "Coder could not reply: stopped at its role's limit of 5 steps", 5),
])
def test_a_stopped_agent_goes_on_under_its_roles_limit_as_it_stands_now(
    make_client, wait_run, project_dir, raise_to, said, steps
):
    """B-325 (live): the role's limit raised from 3 to 10 and the Coder told to go on, it
    stopped at 3 steps again - it was held to the limit its role had when it was made. Now
    the limit as it stands holds, over all its steps: the 3 it took leave it 7."""
    client, model, cid, run_id = stopped_at_its_roles_steps(make_client, project_dir, [
        step(write("a.txt", "A")), *looping("a")[:2],  # (3 steps: the role's limit)
        *looping("b")[:5], text("all done"),           # (6 more: 9 in all)
    ], raise_to=raise_to)
    snap = wait_run(client, cid, run_id, timeout=20)
    ((_status, told),) = calls(snap, "Lead", "message_agent")
    assert told.startswith(said), told
    assert len(model.calls_of["Coder"]) == steps


def test_below_full_auto_a_stopped_agent_with_no_steps_left_is_not_told_to_go_on(
    make_client, wait_run, project_dir
):
    """B-325: the role's limit as it was, the Coder has no step left: the Lead is told so, and
    what to ask the user (K-devam-butce), and no step of its model is asked for."""
    client, model, cid, run_id = stopped_at_its_roles_steps(make_client, project_dir, [
        step(write("a.txt", "A")), *looping("a")[:2], text("never said")], mode="auto_edit")
    snap = wait_run(client, cid, run_id, timeout=20)
    assert snap["runs"][0]["status"] == "completed"
    ((status, said),) = calls(snap, "Lead", "message_agent")
    assert status == "failed" and said.startswith(
        AT_ROLES_LIMIT.format(n=3, given="", how=KEPT_CARD)), said
    assert len(model.calls_of["Coder"]) == 3
    assert agent(snap, "Coder")["steps_given"] == 0
    # nothing reached it: its kept card is the user's still
    (kept,) = snap["merges"]
    assert kept["status"] == "kept" and [f["path"] for f in kept["files"]] == ["a.txt"]


AT_ROLES_LIMIT = ("Coder is at its role's limit of {n} steps{given}; more steps are the user's "
                  "to give: ask them to {how}")
KEPT_CARD = "press Continue on its kept work's card, or to raise the limit in the role's settings"
RAISE = "raise the limit in the role's settings. Nothing was sent to it."


def given_lines(snap):
    """K-devam-butce: KOLONİ's lines in the chat on a budget of steps given."""
    return [m["content"] for m in snap["messages"]
            if m["role"] == "agent" and m["from_agent_id"] is None and "more steps" in m["content"]]


def test_at_full_auto_the_leads_go_on_never_lifts_a_roles_limit_but_the_users_continue_does(
    make_client, wait_run, project_dir
):
    """B-401 (live: app 8, role 12, Full auto): the Coder stopped at the app's limit, the
    Orchestrator's go on ran it to its role's 12, and its second go on gave it 25 more - past
    the role's limit, no card for the user. A role's limit is the user's safety stop: the
    Lead's go on is refused there at every level; the user's Continue on its kept card lifts it.
    Here the app's 4 (the Lead's steps), the role's 6, Continue's 2."""
    gate = Gate()
    client, model = make_client({
        "Lead": [GO_ON[0], GO_ON[1],
                 step(call("message_agent", {"to": "Coder", "message": "go on"}, "m2")),
                 gate.step(text("done"))],
        "Coder": [step(write("a.txt", "A")), *looping("a")[:3],  # (the app's 4)
                  *looping("b")[:2],                              # (to the role's 6)
                  step(write("b.txt", "B", "w2")), text("B done")],  # (the user's 2)
    })
    client.headers["Origin"] = ORIGIN
    runner = client.app.state.runner
    runner.settings = replace(runner.settings, max_steps=4)
    assert client.patch(f"/api/roles/{role_id(client, 'Coder')}",
                        json={"max_steps": 6}).status_code == 200
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    assert client.patch(f"/api/projects/{pid}", json={"continue_steps": 2}).status_code == 200
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    assert client.patch(f"/api/conversations/{cid}", json={
        "permission_mode": "full_auto", "spawn_approval": "never"}).status_code == 200
    run_id = client.post(f"/api/conversations/{cid}/messages",
                         json={"content": "go"}).json()["run"]["id"]
    gate.wait_partial()
    snap = client.get(f"/api/conversations/{cid}").json()
    (first, second) = calls(snap, "Lead", "message_agent")
    assert first[1].startswith("Coder could not reply: stopped at its role's limit of 6 steps")
    # (the 2 its role let it take of the app's 4; its kept card has Continue)
    assert second[0] == "failed" and second[1].startswith(AT_ROLES_LIMIT.format(
        n=6, given=", and KOLONİ gave it 2 more once in this turn already",
        how=KEPT_CARD)), second[1]
    assert len(model.calls_of["Coder"]) == 6 and agent(snap, "Coder")["steps_given"] == 0
    assert given_lines(snap) == []
    # the user's Continue on its kept card: the 2 more past its role's 6
    (kept,) = [m for m in snap["merges"] if m["status"] == "kept"]
    assert client.post(f"/api/merges/{kept['id']}/continue").status_code == 202
    until(client, cid, lambda s: "applied" in [m["status"] for m in s["merges"]], timeout=20)
    gate.release()
    snap = wait_run(client, cid, run_id, timeout=20)
    assert (project_dir / "b.txt").read_text(encoding="utf-8") == "B"
    assert len(model.calls_of["Coder"]) == 8 and agent(snap, "Coder")["steps_given"] == 2
    assert given_lines(snap) == ["Coder gets 2 more steps (your Continue)."]


def test_in_a_later_turn_the_leads_go_on_with_a_coder_at_its_roles_limit_is_refused(
    make_client, wait_run, project_dir
):
    """B-327 (live): "devam et" in the next turn - the Lead goes on with the Coder of the turn
    before (`_go_on`): its 3 steps then count against its role's 3 now. B-401: at Full auto too,
    the Lead is told more steps are the user's to give; its model is asked for nothing."""
    client, model = make_client({
        "Lead": [GO_ON[0], text("done"), GO_ON[1], text("done again")],
        "Coder": [step(write("a.txt", "A")), *looping("a")[:2],  # (3 steps: the role's limit)
                  text("never said")],
    })
    client.headers["Origin"] = ORIGIN
    assert client.patch(f"/api/roles/{role_id(client, 'Coder')}",
                        json={"max_steps": 3}).status_code == 200
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    assert client.patch(f"/api/conversations/{cid}", json={
        "permission_mode": "full_auto", "spawn_approval": "never"}).status_code == 200
    first = client.post(f"/api/conversations/{cid}/messages", json={"content": "go"}).json()["run"]
    wait_run(client, cid, first["id"], timeout=20)
    second = client.post(f"/api/conversations/{cid}/messages",
                         json={"content": "devam et"}).json()["run"]
    snap = wait_run(client, cid, second["id"], timeout=20)
    ((status, said),) = calls_of(snap, second["id"], "message_agent")
    assert status == "failed" and AT_ROLES_LIMIT.format(n=3, given="", how=RAISE) in said, said
    assert len(model.calls_of["Coder"]) == 3 and given_lines(snap) == []


def test_continue_on_a_stopped_agents_card_gives_it_the_steps_and_it_goes_on_in_its_copy(
    make_client, wait_run, project_dir
):
    """K-devam-butce (B-323): the user's Continue on the kept card of a Coder stopped at the
    app's 25 steps: it gets 25 more, goes on in its kept copy (the card is withdrawn), and its
    work, done, goes in as any go on's (B-322). After the turn the card offers no Continue."""
    gate = Gate()
    client, model, cid, run_id = one(make_client, project_dir, [
        step(write("a.txt", "A")), *looping("a"),        # (26 steps: stopped at 25)
        step(write("b.txt", "B", "w2")), text("B done"),
    ], lead=[GO_ON[0], gate.step(GO_ON[2])])
    gate.wait_partial()
    (kept,) = client.get(f"/api/conversations/{cid}").json()["merges"]
    assert kept["status"] == "kept" and agent(
        client.get(f"/api/conversations/{cid}").json(), "Coder")["error"] == "step_limit"
    assert client.post(f"/api/merges/{kept['id']}/continue").status_code == 202
    snap = until(client, cid, lambda s: "applied" in [m["status"] for m in s["merges"]],
                 timeout=20)
    assert {m["status"]: m["files"] for m in snap["merges"]}["discarded"] == []  # withdrawn
    gate.release()
    snap = wait_run(client, cid, run_id, timeout=20)
    assert (project_dir / "a.txt").read_text(encoding="utf-8") == "A"
    assert (project_dir / "b.txt").read_text(encoding="utf-8") == "B"
    assert len(model.calls_of["Coder"]) == 28 and agent(snap, "Coder")["steps_given"] == 25
    assert given_lines(snap) == ["Coder gets 25 more steps (your Continue)."]
    # (a card decided, or of a turn that is over, is not one to continue)
    refused = client.post(f"/api/merges/{kept['id']}/continue")
    assert refused.status_code == 409 and "no longer kept" in refused.json()["detail"]


def continue_pressed_mid_turn(make_client, project_dir, coder_end, lead_rest=()):
    """A Coder stopped at 25 steps, its Lead held at its answer; the user presses Continue and
    the Coder is held mid-budget (`coder_gate`), b.txt written."""
    lead_gate, coder_gate = Gate(), Gate()
    client, model, cid, run_id = one(make_client, project_dir, [
        step(write("a.txt", "A")), *looping("a"),
        step(write("b.txt", "B", "w2")), coder_gate.step(coder_end),
    ], lead=[GO_ON[0], lead_gate.step(text("done")), *lead_rest])
    lead_gate.wait_partial()
    (kept,) = client.get(f"/api/conversations/{cid}").json()["merges"]
    assert client.post(f"/api/merges/{kept['id']}/continue").status_code == 202
    coder_gate.wait_partial()
    return client, model, cid, run_id, lead_gate, coder_gate


def test_the_lead_waits_at_its_end_for_a_continue_the_user_pressed_and_reads_what_came(
    make_client, wait_run, project_dir
):
    """K-devam-butce (review): the Lead answers while the Coder runs on the user's Continue:
    its turn waits for the Coder as for any sub-agent it did not wait for, the Coder's reply
    is left for it as a note and read in a step more, and the work is taken in."""
    client, model, cid, run_id, lead_gate, coder_gate = continue_pressed_mid_turn(
        make_client, project_dir, text("B done"), lead_rest=(text("read it"),))
    lead_gate.release()
    coder_gate.release()
    snap = wait_run(client, cid, run_id, timeout=20)
    assert snap["runs"][0]["status"] == "completed"
    assert (project_dir / "b.txt").read_text(encoding="utf-8") == "B"
    assert len(model.calls_of["Lead"]) == 3  # (spawn, its answer, the step that reads the note)
    lead, coder = agent(snap, "Lead"), agent(snap, "Coder")
    (note,) = [m for m in snap["messages"] if m["role"] == "agent"
               and m["from_agent_id"] == coder["id"] and m["agent_id"] == lead["id"]]
    assert note["content"].startswith("Coder replied:") and "B done" in note["content"]
    assert [m["content"] for m in snap["messages"] if m["agent_id"] == lead["id"]
            and m["role"] == "assistant"][-1] == "read it"


def test_stop_during_a_continue_the_user_pressed_keeps_its_work_for_the_user(
    make_client, wait_run, project_dir
):
    client, model, cid, run_id, lead_gate, coder_gate = continue_pressed_mid_turn(
        make_client, project_dir, text("never said"))
    assert client.post(f"/api/runs/{run_id}/cancel").status_code in (200, 202)
    snap = wait_run(client, cid, run_id)
    lead_gate.release()
    coder_gate.release()
    assert agent(snap, "Coder")["status"] == "cancelled"
    (kept,) = [m for m in snap["merges"] if m["status"] == "kept"]
    assert sorted(f["path"] for f in kept["files"]) == ["a.txt", "b.txt"] and kept["kept_in"]
    assert not (project_dir / "a.txt").exists()


def test_a_card_of_a_turn_that_is_over_offers_no_continue(make_client, wait_run, project_dir):
    client, model, cid, run_id = one(make_client, project_dir, [
        step(write("a.txt", "A")), *looping("a")])
    (kept,) = wait_run(client, cid, run_id, timeout=20)["merges"]
    refused = client.post(f"/api/merges/{kept['id']}/continue")
    assert refused.status_code == 409 and refused.json()["detail"].startswith("its turn is over")


def test_continue_steps_is_the_projects_setting(make_client, project_dir):
    client, _model = make_client({})
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    assert client.get(f"/api/projects/{pid}").json()["continue_steps"] == 25
    assert client.patch(f"/api/projects/{pid}", json={"continue_steps": 40}).status_code == 200
    assert client.get(f"/api/projects/{pid}").json()["continue_steps"] == 40
    for wrong in (0, 201, "40"):
        assert client.patch(f"/api/projects/{pid}", json={"continue_steps": wrong}).status_code == 422
    del client.headers["Origin"]  # the user's to say, from the app's own page
    assert client.patch(f"/api/projects/{pid}", json={"continue_steps": 30}).status_code == 403


def test_a_kept_card_takes_in_nothing_of_a_new_copy_that_was_turned_down(
    make_client, wait_run, project_dir
):
    """B-322: where the kept copy cannot be given back (as after a restart), the agent goes on
    in a new copy, told that its earlier work waits on a card; turning that copy down, then
    applying the card, puts in the card's work alone."""
    gate = Gate()
    client, model, cid, run_id = one(make_client, project_dir, [
        step(write("a.txt", "A")), *looping("a")[:24],
        step(write("a.txt", "A2", "w2")), text("A2 done"),
    ], lead=[GO_ON[0], gate.step(GO_ON[1]), GO_ON[2]], permission_mode="ask")
    gate.wait_partial()
    getattr(client.app.state.runner, "_kept_live", {}).clear()  # (lost, as at a restart)
    gate.release()
    snap = until(client, cid, lambda s: "pending" in [m["status"] for m in s["merges"]],
                 timeout=20)
    status, said = calls(snap, "Coder", "write_file")[-1]
    assert status == "succeeded" and "Your earlier changes are not in this copy: a.txt" in said
    new = next(m for m in snap["merges"] if m["status"] == "pending")
    assert client.post(f"/api/merges/{new['id']}/reject").status_code == 200
    snap = wait_run(client, cid, run_id)
    kept = next(m for m in snap["merges"] if m["status"] == "kept")
    assert client.post(f"/api/merges/{kept['id']}/approve").status_code == 200
    assert (project_dir / "a.txt").read_text(encoding="utf-8") == "A"
    snap = client.get(f"/api/conversations/{cid}").json()
    assert sorted(a_txt(snap)) == ["applied", "rejected"]


@pytest.mark.parametrize("mode", ["auto_edit", "full_auto"])
def test_a_copy_holding_a_file_that_stands_over_later_turns_is_asked_about(
    make_client, wait_run, project_dir, mode
):
    """What is taken unasked is taken; `.claude/` waits on the card, at every level."""
    client, model, cid, run_id = one(make_client, project_dir, [
        step(write("notes.txt", "seen")), step(write(".claude/x", "{}", "w2")), text("A done"),
    ], permission_mode=mode)
    snap = until(client, cid, lambda s: [m["status"] for m in s["merges"]] == ["pending"])
    assert (project_dir / "notes.txt").read_text(encoding="utf-8") == "seen"
    assert not (project_dir / ".claude").exists()
    assert files(snap["merges"][0]) == {"notes.txt": "applied", ".claude/x": "ready"}
    (asked,) = [f for f in snap["merges"][0]["files"] if f["path"] == ".claude/x"]
    assert "at every permission level" in asked["note"]
    assert client.post(f"/api/merges/{snap['merges'][0]['id']}/approve").status_code == 200
    wait_run(client, cid, run_id)
    assert (project_dir / ".claude" / "x").read_text(encoding="utf-8") == "{}"


def test_a_turn_nobody_watches_never_waits_and_keeps_its_protected_paths(
    make_client, wait_run, project_dir
):
    client, model = make_client({
        "Lead": [step(call("spawn_agent", {"role": "Coder", "task": "do it"}, "s")),
                 text("done")],
        "Coder": [step(write("notes.txt", "seen")),
                  step(write(".claude/settings.json", "{}", "w2")), text("A done")],
    })
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    made = trigger(client, pid, cid,
                   permissions={"write": True, "commands": [], "agents": 1})
    run_id = run_now(client, made["id"])
    snap = wait_run(client, cid, run_id, timeout=10)
    assert next(r for r in snap["runs"] if r["id"] == run_id)["status"] == "completed"
    assert (project_dir / "notes.txt").read_text(encoding="utf-8") == "seen"
    assert not (project_dir / ".claude").exists()
    assert not [m for m in snap["merges"] if m["status"] == "pending"]


def test_a_linked_folder_is_the_projects_own_and_outlives_the_copy(
    make_client, wait_run, project_dir
):
    (project_dir / "node_modules" / "pkg").mkdir(parents=True)
    (project_dir / "node_modules" / "pkg" / "index.js").write_text("x", encoding="utf-8")
    client, model, cid, run_id = one(make_client, project_dir, [
        step(write("a.txt", "A")), step(exists("node_modules/pkg/index.js")),
        step(write("node_modules/pkg/mine.js", "y", "w2")), text("A done"),
    ])
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed"
    assert "THERE" in calls(snap, "Coder", "run_command")[0][1]
    # the agent's file tools do not write into what is shared with the project
    assert [status for status, _ in calls(snap, "Coder", "write_file")] == ["succeeded", "failed"]
    # the copy is gone; what the link pointed at is not
    assert (project_dir / "node_modules" / "pkg" / "index.js").read_text(encoding="utf-8") == "x"
    assert not (project_dir / "node_modules" / "pkg" / "mine.js").exists()
    assert (project_dir / "a.txt").read_text(encoding="utf-8") == "A"


def test_a_project_too_big_to_copy_is_worked_in_as_before(
    make_client, wait_run, project_dir, monkeypatch
):
    import app.copies

    monkeypatch.setattr(app.copies, "MAX_FILES", 0)
    first = Gate()
    client, model, cid, run_id = one(make_client, project_dir, [
        step(write("a.txt", "A")), first.step(text("A done")),
    ])
    first.wait_partial()
    snap = until(client, cid, lambda s: agent(s, "Coder")["copy"] == {"state": "too_big"})
    assert (project_dir / "a.txt").read_text(encoding="utf-8") == "A"   # in the project at once
    first.release()
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed" and snap["merges"] == []


def test_a_venv_an_agent_made_in_its_copy_is_said_to_stay_out_and_a_linked_one_is_not(
    make_client, wait_run, project_dir
):
    # B-383 (live): Take in left the Coder's .venv out, as it should, and nobody said so.
    (project_dir / "node_modules").mkdir()
    client, model, cid, run_id = one(make_client, project_dir, [
        step(write("a.txt", "A")),
        step(run("python -c \"import os;os.makedirs('.venv/Lib')\"")), text("A done"),
    ])
    snap = wait_run(client, cid, run_id)
    ((status, said),) = calls(snap, "Lead", "spawn_agent")
    assert status == "succeeded" and (
        "The .venv made in the copy stays out of the project: make it there with "
        "`python -m venv .venv`.") in said
    assert "node_modules" not in said  # (the project's own, linked in)
    assert (project_dir / "a.txt").exists() and not (project_dir / ".venv").exists()
    # (R184: the Lead did not pass it on - the user reads it in KOLONİ's own line, once.)
    assert [m["content"] for m in snap["messages"] if m["role"] == "koloni"] == [
        "The .venv made in the copy stays out of the project: make it there with "
        "`python -m venv .venv`."]


def test_the_folders_left_in_a_copy_are_named_three_at_most(tmp_path):
    from app.copies import left_in

    for name in ("venv", "dist", "node_modules", "build", "__pycache__", "src"):
        (tmp_path / name).mkdir()
    assert left_in(tmp_path) == (
        "The build, dist, node_modules made in the copy stay out of the project: make them "
        "there with its build and `npm install`.")
    assert left_in(tmp_path / "nowhere") == ""
