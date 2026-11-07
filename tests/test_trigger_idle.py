"""93-B2: a schedule whose runs find nothing slows down - after three in a row its times are
spaced x2, then x4, at most x8 - and is back to its own as soon as a run finds something or
the user touches it. Never a webhook. Time is handed to the scheduler (`tick(now)`)."""

from datetime import datetime, timedelta

from app.api import triggers as api
from tests.keyed import TestClient
from tests.test_chat_flow import text
from tests.test_spawn import call, step
from tests.test_trigger_ends import finished
from tests.test_triggers import ORIGIN, T0, one, setup, tick, trigger

HOUR = timedelta(minutes=60)


def at(snap):
    return datetime.fromisoformat(snap["next_at"])


def test_runs_that_find_nothing_space_a_schedule_out_and_one_that_finds_something_ends_it(
    make_client, project_dir
):
    found = step(call("remember", {"text": "the build is red"}, "m"))
    client, _model, pid, cid = setup(make_client, project_dir, {"Lead": [
        *[text(f"nothing {n}") for n in range(6)], found, text("noted")]})
    tid = trigger(client, pid, cid)["id"]  # every 60 minutes, reads only
    moments, count = [T0, T0 + HOUR, T0 + 2 * HOUR], 0
    for moment in moments:
        assert len(tick(client, moment)) == 1
        count += 1
        finished(client, tid, count)
    snap = one(client, tid)
    assert snap["runs"][0]["note"] == "found nothing: no file changed, no note kept"
    assert snap["idle"] == 3
    # Three in a row: its next time is the second of its own.
    assert (snap["slowed"], at(snap)) == (3, T0 + 4 * HOUR)
    assert tick(client, T0 + 3 * HOUR) == []
    # x4, then x8 - and no further.
    for moment, slowed, then in ((T0 + 4 * HOUR, 4, 8), (T0 + 8 * HOUR, 5, 16),
                                 (T0 + 16 * HOUR, 6, 24)):
        assert len(tick(client, moment)) == 1
        count += 1
        finished(client, tid, count)
        snap = one(client, tid)
        assert (snap["slowed"], at(snap)) == (slowed, T0 + then * HOUR)
    # One that keeps a note found something: its own times again.
    assert len(tick(client, T0 + 24 * HOUR)) == 1
    finished(client, tid, count + 1)
    snap = one(client, tid)
    assert (snap["slowed"], at(snap), snap["runs"][0]["note"]) == (None, T0 + 25 * HOUR, None)
    assert snap["idle"] == 0


def test_the_user_s_touch_puts_a_slowed_schedule_back_on_its_own_times(
    make_client, project_dir, monkeypatch
):
    client, _model, pid, cid = setup(make_client, project_dir, {"Lead": [
        text(f"nothing {n}") for n in range(4)]})
    tid = trigger(client, pid, cid)["id"]
    for count, moment in enumerate((T0, T0 + HOUR, T0 + 2 * HOUR), 1):
        tick(client, moment)
        finished(client, tid, count)
    assert (one(client, tid)["slowed"], at(one(client, tid))) == (3, T0 + 4 * HOUR)
    # "Back to every 60 minutes" sends nothing but the touch, at 11:30 by the scheduler's clock.
    monkeypatch.setattr(api, "now", lambda: T0 + 2.5 * HOUR)
    back = client.patch(f"/api/triggers/{tid}", json={}).json()
    assert (back["slowed"], at(back)) == (None, T0 + 3 * HOUR)
    assert len(tick(client, T0 + 3 * HOUR)) == 1
    finished(client, tid, 4)
    assert at(one(client, tid)) == T0 + 4 * HOUR


def test_a_webhook_is_never_slowed_down(make_client, wait_run, project_dir):
    client, _model, pid, cid = setup(make_client, project_dir, {"Lead": [
        text(f"nothing {n}") for n in range(4)]})
    made = trigger(client, pid, cid, kind="webhook", config={})
    here = TestClient(client.app, base_url=ORIGIN, client=("127.0.0.1", 50000))
    for count in range(1, 5):
        started = here.post(f"/api/hooks/{made['key']}", content="x")
        assert started.status_code == 202, started.text
        wait_run(client, cid, started.json()["run_id"])
        finished(client, made["id"], count)
    snap = one(client, made["id"])
    assert (snap["slowed"], snap["next_at"], snap["runs"][0]["note"]) == (None, None, None)
