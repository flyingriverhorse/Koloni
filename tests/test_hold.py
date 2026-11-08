"""Stop everything (K-hepsini-durdur, `app.api.hold`): every turn of every chat stops, what
starts by itself waits until Resume, the user's own messages do not, and the hold outlives a
restart. Time is handed to the triggers (`tick`), as in tests/test_triggers.py."""

import asyncio
import threading
import time
from datetime import datetime, timedelta

from app.api import hold
from app.db.models import now
from app.model_client import ModelUnavailable
from tests.conftest import Gate
from tests.keyed import TestClient
from tests.test_agent_writes import edit
from tests.test_away_scenarios import card, evening, night
from tests.test_chat_flow import text
from tests.test_spawn import call, step
from tests.test_triggers import (
    ORIGIN,
    T0,
    one,
    place,
    run_of,
    setup,
    started,  # noqa: F401  (a fixture)
    tick,
    trigger,
)


def tasks(client, pid):
    return {t["title"]: t for t in client.get(f"/api/projects/{pid}/backlog").json()}


def until(check, seconds=5.0):
    deadline = time.monotonic() + seconds
    while not (seen := check()):
        assert time.monotonic() < deadline, "never came"
        time.sleep(0.02)
    return seen


def test_stop_everything_stops_every_turn_holds_what_starts_by_itself_and_resume_lets_it_go(
    make_client, wait_run, project_dir, gate
):
    task_gate, mine_gate = Gate(), Gate()
    client, model, pid, cid = setup(make_client, project_dir, {"Lead": [
        gate.step(text("unattended")), task_gate.step(text("task")), mine_gate.step(text("busy")),
        text("mine"), text("two done"), text("next time")]})
    other = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    clock = trigger(client, pid, cid, catch_up=True)
    hook = trigger(client, pid, cid, kind="webhook", config={})
    here = TestClient(client.app, base_url=ORIGIN, client=("127.0.0.1", 50000))
    try:
        # a trigger's turn, a backlog task's turn, a turn of the user's and one queued behind it
        (unattended,) = tick(client, T0)
        gate.wait_partial()
        client.post(f"/api/projects/{pid}/backlog", json={"title": "one"})
        client.put(f"/api/projects/{pid}/backlog/auto", json={"on": True})
        task_gate.wait_partial()
        busy = client.post(f"/api/conversations/{other}/messages",
                           json={"content": "a turn of my own"}).json()["run"]["id"]
        mine_gate.wait_partial()
        queued = client.post(f"/api/conversations/{other}/messages",
                             json={"content": "and one after it"}).json()["run"]
        assert queued["status"] == "queued"
        before = client.get("/api/hold").json()
        assert (before["held"], before["running"], before["triggers"], before["backlogs"]) == (
            False, 4, 2, [project_dir.name])

        # from the app's own page only
        assert client.post("/api/hold", headers={"Origin": "http://evil.example"}).status_code == 403
        held = client.post("/api/hold").json()
    finally:
        for one_gate in (gate, task_gate, mine_gate):
            one_gate.release()
    task_chat = tasks(client, pid)["one"]["conversation_id"]
    assert held["held"] is True and held["since"] and held["running"] == 0
    assert {(s["run_id"], s["conversation_id"]) for s in held["stopped"]} == {
        (unattended, cid), (busy, other), (queued["id"], other),
        (client.get(f"/api/conversations/{task_chat}").json()["runs"][0]["id"], task_chat)}
    # B-175: each with its project and when its turn was sent, to tell chats of one title apart
    assert {s["project"] for s in held["stopped"]} == {project_dir.name}
    assert all(s["created_at"] <= held["since"] for s in held["stopped"])
    snap = client.get(f"/api/conversations/{other}").json()
    assert {run_of(snap, busy)["status"], run_of(snap, queued["id"])["status"]} == {"cancelled"}
    # the backlog that works itself is held, not switched off; the task stopped is todo again
    assert client.get(f"/api/projects/{pid}/backlog/auto").json().items() >= {"on": True, "halt": None}.items()
    assert tasks(client, pid)["one"]["status"] == "todo"

    # while held nothing starts by itself: no next task, no trigger, whichever way
    client.post(f"/api/projects/{pid}/backlog", json={"title": "two"})
    assert tasks(client, pid)["two"]["conversation_id"] is None
    assert tick(client, T0 + timedelta(hours=1)) == []
    assert here.post(f"/api/hooks/{hook['key']}", content="x").status_code == 409
    assert client.post(f"/api/triggers/{clock['id']}/run").status_code == 409
    # but the user's own message runs - and its end starts no task either
    mine = client.post(f"/api/conversations/{other}/messages",
                       json={"content": "mine, while held"}).json()["run"]["id"]
    assert run_of(wait_run(client, other, mine), mine)["status"] == "completed"
    assert tasks(client, pid)["two"]["conversation_id"] is None
    assert client.get("/api/hold").json()["held"] is True

    assert client.post("/api/hold/resume", headers={"Origin": "http://evil.example"}).status_code == 403
    resumed = client.post("/api/hold/resume").json()
    assert (resumed["held"], resumed["stopped"]) == (False, [])
    # R147: what it stopped stays stopped, and Resume says so
    said = "4 stopped turns stay stopped - send a message to go on."
    assert held["stays_stopped"] == said and resumed["stays_stopped"] == said
    assert client.get("/api/hold").json()["stays_stopped"] is None
    # the backlog goes on with its next task never worked on
    two = until(lambda: tasks(client, pid)["two"]["conversation_id"])
    wait_run(client, two, client.get(f"/api/conversations/{two}").json()["runs"][0]["id"])
    # the hour missed while held is not made up for, though the trigger catches up: it waits
    assert tick(client, T0 + timedelta(hours=1, minutes=1)) == []
    next_at = datetime.fromisoformat(one(client, clock["id"])["next_at"])
    assert next_at > T0 + timedelta(hours=1)
    (again,) = tick(client, next_at)
    assert run_of(wait_run(client, cid, again), again)["status"] == "completed"


def test_the_hold_outlives_a_restart(started, project_dir):  # noqa: F811
    client = started([])
    pid, cid = place(client, project_dir)
    trigger(client, pid, cid)
    assert client.post("/api/hold").json()["held"] is True
    client = started([text("one")])
    assert client.get("/api/hold").json()["held"] is True
    assert tick(client, T0, starting=True) == [] and tick(client, T0) == []
    assert client.post("/api/hold/resume").json()["held"] is False
    assert client.get("/api/hold").json()["held"] is False


def test_stop_everything_cuts_the_nights_job_and_holds_its_next_until_resume(
    make_client, wait_run, project_dir, gate
):
    client, _model, pid, cid, run_id = evening(make_client, project_dir, [
        edit(), gate.step(text("never")), text("two done")])
    wait_run(client, cid, run_id)
    client.post(f"/api/away/{card(client, cid)['id']}/start")
    gate.wait_partial()
    try:
        held = client.post("/api/hold").json()
    finally:
        gate.release()
    # the job at work is stopped as Stop all stops it - and listed; the night is held, not over
    one, two = night(client, pid)["jobs"]
    assert (one["state"], one["why"]) == ("stopped", "Stopped by you: Stop everything.")
    assert one["conversation_id"] in {s["conversation_id"] for s in held["stopped"]}
    assert held["nights"] == [project_dir.name] and night(client, pid)["status"] == "running"
    # the clock's look starts no next job while held
    client.app.state.triggers.tick(now())
    assert night(client, pid)["jobs"][1]["conversation_id"] is None
    client.post("/api/hold/resume")
    two = until(lambda: night(client, pid)["jobs"][1]["conversation_id"])
    wait_run(client, two, client.get(f"/api/conversations/{two}").json()["runs"][0]["id"])
    assert until(lambda: (n := night(client, pid))["status"] == "ended" and n)["jobs"][1][
        "state"] == "done"


def test_no_night_starts_while_held(make_client, wait_run, project_dir):
    client, _model, pid, cid, run_id = evening(make_client, project_dir, [])
    wait_run(client, cid, run_id)
    client.post("/api/hold")
    answer = client.post(f"/api/away/{card(client, cid)['id']}/start")
    assert answer.status_code == 409 and "Resume first" in answer.json()["detail"]


def test_a_turn_slow_to_stop_is_stopped_once_and_its_cleanup_ends(
    make_client, wait_run, project_dir, monkeypatch
):
    begun, cleaned = threading.Event(), []

    async def slow_to_stop(on_delta):
        begun.set()
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            await asyncio.sleep(0.5)  # its cleanup: longer than Stop everything waits
            cleaned.append("done")
            raise

    monkeypatch.setattr(hold, "WAIT_SECONDS", 0.1)
    client, model, pid, cid = setup(make_client, project_dir, {"Lead": [slow_to_stop]})
    run_id = client.post(f"/api/conversations/{cid}/messages",
                         json={"content": "go"}).json()["run"]["id"]
    assert begun.wait(5)
    held = client.post("/api/hold").json()
    # given up waiting: not listed yet, but said to be stopping
    assert (held["stopped"], held["stopping"]) == ([], 1)
    assert run_of(wait_run(client, cid, run_id), run_id)["status"] == "cancelled"
    assert cleaned == ["done"]
    assert client.get("/api/hold").json()["stopping"] == 0


def test_a_nights_job_that_waits_for_the_users_word_is_stopped_too_not_failed(
    make_client, wait_run, project_dir, gate
):
    # At "ask" job one waits for its command; job two works on, held open
    run = step(call("run_command", {"command": "echo hi"}))
    client, _model, pid, cid, run_id = evening(make_client, project_dir, [
        edit(), run, edit(id="w2"), gate.step(text("two done"))], mode="ask")
    wait_run(client, cid, run_id)
    client.post(f"/api/away/{card(client, cid)['id']}/start")
    until(lambda: night(client, pid)["jobs"][0]["state"] == "waits")
    gate.wait_partial()
    try:
        client.post("/api/hold")
    finally:
        gate.release()
    one, two = night(client, pid)["jobs"]
    for job in (one, two):
        until(lambda job=job: client.get(f"/api/conversations/{job['conversation_id']}").json()[
            "runs"][-1]["status"] == "cancelled")
    one, two = night(client, pid)["jobs"]
    assert [(job["state"], job["why"]) for job in (one, two)] == [
        ("stopped", "Stopped by you: Stop everything.")] * 2


def test_a_users_turn_that_fails_in_a_tasks_chat_while_held_leaves_the_run_on(
    make_client, wait_run, project_dir
):
    # (K-symphony: a task's own turn that fails has its fix round; the user's own is theirs)
    client, _model, pid, cid = setup(make_client, project_dir, {"Lead": [
        text("one done"), ModelUnavailable("the model is down"), text("two done")]})
    client.post(f"/api/projects/{pid}/backlog", json={"title": "one"})
    client.put(f"/api/projects/{pid}/backlog/auto", json={"on": True})
    chat = until(lambda: tasks(client, pid)["one"]["conversation_id"])
    wait_run(client, chat, client.get(f"/api/conversations/{chat}").json()["runs"][0]["id"])
    client.post("/api/hold")
    client.post(f"/api/projects/{pid}/backlog", json={"title": "two"})
    # the user's own message in the task's chat, while held: it runs - and fails
    mine = client.post(f"/api/conversations/{chat}/messages",
                       json={"content": "one more thing"}).json()["run"]["id"]
    assert run_of(wait_run(client, chat, mine), mine)["status"] == "failed"
    assert client.get(f"/api/projects/{pid}/backlog/auto").json().items() >= {"on": True, "halt": None}.items()
    assert tasks(client, pid)["one"]["status"] == "review"
    client.post("/api/hold/resume")
    assert until(lambda: tasks(client, pid)["two"]["conversation_id"])
