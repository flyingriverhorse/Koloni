"""A trigger's end (K-tetik-bitis), its skip when nothing changed (K-tetik-degismedi) and the
Lead's proposed trigger (slice 69). Time is handed to the scheduler (`tick(now)`); the git
repositories are made here, in a temporary folder."""

import asyncio
import subprocess
from datetime import UTC, date, datetime, timedelta

import pytest

from app import triggers as kept
from app.db.models import Trigger
from tests.conftest import Gate
from tests.keyed import TestClient
from tests.test_chat_flow import text
from tests.test_spawn import call, step
from tests.test_triggers import MESSAGE, ORIGIN, T0, one, run_now, setup, tick, trigger, until


def finished(client, trigger_id, count):
    """Wait until the trigger's newest `count` runs have all ended (its `ended` has run)."""
    return until(lambda: (runs := one(client, trigger_id)["runs"]) and len(runs) >= count
                 and all(run["outcome"] for run in runs), "the turn's end on its trigger")


def repository(root):
    for argv in (["git", "init", "-q"], ["git", "add", "-A"],
                 ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "x"]):
        subprocess.run(argv, cwd=root, check=True, capture_output=True, timeout=30)


def later(days):
    """A day by this machine's clock, `days` from today: an end date must not be past."""
    return (date.today() + timedelta(days=days)).isoformat()


# --- the end ------------------------------------------------------------------------------


def test_after_its_runs_a_trigger_ends_and_says_why(make_client, project_dir):
    client, _model, pid, cid = setup(make_client, project_dir, {"Lead": [text("one"), text("two")]})
    made = trigger(client, pid, cid, ends={"runs": 2})
    assert (made["ends"], made["ran"]) == ({"runs": 2}, 0)
    (first,) = tick(client, T0)
    finished(client, made["id"], 1)
    assert one(client, made["id"])["enabled"] is True
    (second,) = tick(client, T0 + timedelta(minutes=60))
    finished(client, made["id"], 2)
    after = one(client, made["id"])
    assert (after["enabled"], after["off_because"], after["ran"]) == (
        False, "ended: 2 runs done", 2)
    assert after["changes"][0]["what"] == "switched off"
    assert after["changes"][0]["detail"] == "ended: 2 runs done"
    assert tick(client, T0 + timedelta(minutes=120)) == []
    # Switched on again: its runs are counted anew.
    assert client.patch(f"/api/triggers/{made['id']}", json={"enabled": True}).json()["ran"] == 0


def test_after_its_last_day_a_trigger_ends_and_says_why(make_client, project_dir):
    client, _model, pid, cid = setup(make_client, project_dir, {"Lead": [text("one")]})
    last = later(1)
    made = trigger(client, pid, cid, ends={"until": last})
    noon = datetime.fromisoformat(last).replace(hour=12, tzinfo=UTC)
    client.app.state.triggers.zone = UTC
    # On its last day it runs; the day after, it ends instead.
    (ran,) = tick(client, noon)
    finished(client, made["id"], 1)
    assert tick(client, noon + timedelta(days=1)) == []
    after = one(client, made["id"])
    assert (after["enabled"], after["off_because"]) == (False, f"ended: its last day, {last}, is over")


def test_a_webhook_past_its_end_starts_nothing(make_client, project_dir):
    client, _model, pid, cid = setup(make_client, project_dir, {"Lead": []})
    made = client.post(f"/api/projects/{pid}/triggers", json={
        "name": "hook", "kind": "webhook", "conversation_id": cid, "message": MESSAGE,
        "ends": {"runs": 1}}).json()
    with client.app.state.session_factory() as session:
        session.get(Trigger, made["id"]).ran = 1
        session.commit()
    here = TestClient(client.app, base_url=ORIGIN, client=("127.0.0.1", 50000))
    assert here.post(f"/api/hooks/{made['key']}", content=b"").status_code == 409
    assert one(client, made["id"])["off_because"] == "ended: 1 run done"


@pytest.mark.parametrize("ends", [
    {"runs": 0}, {"runs": 1001}, {"runs": True}, {"runs": "10"}, {"until": "tomorrow"},
    {"until": "2026-02-30"}, {"runs": 3, "until": "2030-01-01"}, {"when": "done"}, "10 runs", [],
])
def test_an_end_is_one_of_a_closed_few(ends):
    with pytest.raises(kept.Invalid):
        kept.check_ends(ends, date(2026, 10, 27))


def test_an_end_date_is_today_or_later_and_none_is_no_end():
    today = date(2026, 10, 27)
    assert kept.check_ends({"until": "2026-10-27"}, today) == {"until": "2026-10-27"}
    assert kept.check_ends({"runs": 10}, today) == {"runs": 10}
    assert kept.check_ends(None, today) is None
    with pytest.raises(kept.Invalid, match="today or later"):
        kept.check_ends({"until": "2026-10-26"}, today)


def test_no_end_is_said_on_its_record_and_an_end_changed_counts_anew(make_client, project_dir):
    client, _model, pid, cid = setup(make_client, project_dir, {"Lead": []})
    made = trigger(client, pid, cid)
    # The "no end" the form warns of: nothing ends it, and its record says so.
    assert made["ends"] is None
    assert "no end" in made["changes"][0]["detail"]
    with client.app.state.session_factory() as session:
        session.get(Trigger, made["id"]).ran = 4
        session.commit()
    changed = client.patch(f"/api/triggers/{made['id']}", json={"ends": {"runs": 10}}).json()
    assert (changed["ends"], changed["ran"]) == ({"runs": 10}, 0)
    assert "ends after 10 runs" in changed["changes"][0]["detail"]
    # Left out, it stays; sent as null, there is no end again.
    assert client.patch(f"/api/triggers/{made['id']}", json={"name": "w2"}).json()["ends"] == {"runs": 10}
    assert client.patch(f"/api/triggers/{made['id']}", json={"ends": None}).json()["ends"] is None
    refused = client.patch(f"/api/triggers/{made['id']}", json={"ends": {"when": "done"}})
    assert refused.status_code == 422 and "ends is" in refused.json()["detail"]


# --- nothing changed ----------------------------------------------------------------------


def test_a_schedule_is_skipped_while_nothing_changed_and_runs_once_something_did(
        make_client, project_dir):
    client, _model, pid, cid = setup(make_client, project_dir, {"Lead": [
        text("one"), text("two"), text("three")]})
    repository(project_dir)
    made = trigger(client, pid, cid)
    tick(client, T0)
    finished(client, made["id"], 1)
    # The same HEAD, the same files, the same settings: skipped, and said why.
    assert tick(client, T0 + timedelta(minutes=60)) == []
    skipped = one(client, made["id"])["runs"][0]
    assert (skipped["outcome"], skipped["note"], skipped["run_id"]) == (
        "skipped_same", "nothing changed since the last run", None)
    # A file changed (not committed): it runs.
    (project_dir / "hello.py").write_bytes(b"print('bye')\n")
    assert len(tick(client, T0 + timedelta(minutes=120))) == 1
    finished(client, made["id"], 3)
    assert tick(client, T0 + timedelta(minutes=180)) == []
    # Its own settings changed: it runs too.
    client.patch(f"/api/triggers/{made['id']}", json={"message": MESSAGE + " again"})
    assert len(tick(client, T0 + timedelta(minutes=240))) == 1


def test_a_file_changed_again_is_a_change_though_git_lists_it_the_same(tmp_path):
    root = tmp_path / "p"
    root.mkdir()
    (root / "a.txt").write_bytes(b"one\n")
    repository(root)
    (root / "a.txt").write_bytes(b"two\n")
    before = kept.git.state(root)
    (root / "a.txt").write_bytes(b"three, longer\n")
    assert before is not None and kept.git.state(root) != before


def test_a_project_that_is_no_repository_is_never_skipped(make_client, project_dir):
    client, _model, pid, cid = setup(make_client, project_dir, {"Lead": [text("one"), text("two")]})
    made = trigger(client, pid, cid)
    tick(client, T0)
    finished(client, made["id"], 1)
    assert len(tick(client, T0 + timedelta(minutes=60))) == 1


def test_run_even_if_nothing_changed_runs(make_client, project_dir):
    client, _model, pid, cid = setup(make_client, project_dir, {"Lead": [text("one"), text("two")]})
    repository(project_dir)
    made = trigger(client, pid, cid, run_unchanged=True)
    assert made["run_unchanged"] is True
    tick(client, T0)
    finished(client, made["id"], 1)
    assert len(tick(client, T0 + timedelta(minutes=60))) == 1


def test_only_a_schedule_that_looks_at_nothing_outside_is_skipped():
    def made(kind="schedule", run_unchanged=False, **leave):
        return Trigger(kind=kind, run_unchanged=run_unchanged,
                       permissions={"write": False, "commands": [], "agents": 0, **leave})

    assert kept.may_skip(made())
    assert not kept.may_skip(made("files"))
    assert not kept.may_skip(made("webhook"))
    assert not kept.may_skip(made(run_unchanged=True))
    assert not kept.may_skip(made(web=True))
    assert not kept.may_skip(made(hosts=["example.com"]))
    # A command looks past the repository; a reminder is wanted however the files stand.
    assert not kept.may_skip(made(commands=["rule-id"]))
    assert not kept.may_skip(made(notify=True))


# --- the Lead proposes one (slice 69) ------------------------------------------------------

FRIDAYS = {"name": "Dependencies", "kind": "schedule", "config": {"at": "17:00", "days": ["fri"]},
           "message": "Look over the dependencies. Change nothing."}


def proposed(make_client, project_dir, wait_run, args, more=()):
    client, _model, pid, cid = setup(make_client, project_dir, {"Lead": [
        step(call("propose_trigger", args, "p1")), text("Proposed."), *more]})
    run_id = client.post(f"/api/conversations/{cid}/messages",
                         json={"content": "check the dependencies on Fridays"}).json()["run"]["id"]
    snap = wait_run(client, cid, run_id)
    (said,) = [t for t in snap["tool_calls"] if t["name"] == "propose_trigger"]
    return client, pid, cid, snap, said


def test_propose_trigger_puts_a_card_and_makes_nothing(make_client, project_dir, wait_run):
    # Whatever it says of its own leave or budget is not read.
    client, pid, cid, snap, said = proposed(make_client, project_dir, wait_run, {
        **FRIDAYS, "permissions": {"write": True, "agents": 4}, "budget": {"steps": 200}})
    assert said["status"] == "succeeded", said["result"]
    assert "Fridays at 17:00" in said["result"] and "ends after 10 runs" in said["result"]
    assert client.get(f"/api/projects/{pid}/triggers").json() == []
    (card,) = snap["trigger_proposals"]
    assert (card["status"], card["ends"], card["kind"], card["trigger_id"]) == (
        "proposed", {"runs": 10}, "schedule", None)
    assert client.get(f"/api/conversations/{cid}/trigger-proposals").json() == [card]


def test_approve_makes_it_with_the_safest_leave_once(make_client, project_dir, wait_run):
    client, pid, cid, snap, _said = proposed(make_client, project_dir, wait_run, {
        **FRIDAYS, "ends": {"runs": 3}})
    (card,) = snap["trigger_proposals"]
    approved = client.post(f"/api/trigger-proposals/{card['id']}/approve")
    assert approved.status_code == 201, approved.text
    made = approved.json()
    assert made["permissions"] == {"write": False, "commands": [], "agents": 0}
    assert made["budget"] == {"steps": 15, "minutes": 10, "per_day": 24}
    assert (made["config"], made["ends"], made["conversation_id"]) == (
        {"at": "17:00", "days": ["fri"]}, {"runs": 3}, cid)
    (card,) = client.get(f"/api/conversations/{cid}/trigger-proposals").json()
    assert (card["status"], card["trigger_id"]) == ("approved", made["id"])
    assert client.post(f"/api/trigger-proposals/{card['id']}/approve").status_code == 409
    assert len(client.get(f"/api/projects/{pid}/triggers").json()) == 1


def test_approve_and_reject_only_from_the_apps_own_page(make_client, project_dir, wait_run):
    client, pid, _cid, snap, _said = proposed(make_client, project_dir, wait_run, FRIDAYS)
    (card,) = snap["trigger_proposals"]
    del client.headers["Origin"]
    assert client.post(f"/api/trigger-proposals/{card['id']}/approve").status_code == 403
    assert client.post(f"/api/trigger-proposals/{card['id']}/reject").status_code == 403
    assert client.get(f"/api/projects/{pid}/triggers").json() == []
    client.headers["Origin"] = ORIGIN
    assert client.post(f"/api/trigger-proposals/{card['id']}/reject").json()["status"] == "rejected"
    assert client.post(f"/api/trigger-proposals/{card['id']}/approve").status_code == 409


def test_a_trigger_made_in_the_form_from_the_card_closes_the_card(make_client, project_dir, wait_run):
    client, pid, cid, snap, _said = proposed(make_client, project_dir, wait_run, FRIDAYS)
    (card,) = snap["trigger_proposals"]
    made = trigger(client, pid, cid, proposal_id=card["id"], ends={"runs": 5},
                   permissions={"write": True, "commands": [], "agents": 1})
    (card,) = client.get(f"/api/conversations/{cid}/trigger-proposals").json()
    assert (card["status"], card["trigger_id"]) == ("approved", made["id"])
    assert made["permissions"]["write"] is True  # the user's own leave, in the form


@pytest.mark.parametrize("args, why", [
    ({**FRIDAYS, "kind": "webhook", "config": {}}, "a webhook is not proposed"),
    ({**FRIDAYS, "config": {"every_minutes": 1}}, "every_minutes"),
    ({**FRIDAYS, "ends": {"when": "done"}}, "ends is"),
])
def test_what_cannot_be_proposed_is_refused(make_client, project_dir, wait_run, args, why):
    client, pid, _cid, snap, said = proposed(make_client, project_dir, wait_run, args)
    assert said["status"] == "failed" and why in said["result"]
    assert snap["trigger_proposals"] == []


def test_a_turn_nobody_watches_proposes_no_trigger(make_client, project_dir):
    client, _model, pid, cid = setup(make_client, project_dir, {"Lead": [
        step(call("propose_trigger", FRIDAYS, "p1")), text("done")]})
    made = trigger(client, pid, cid)
    tick(client, T0)
    finished(client, made["id"], 1)
    snap = client.get(f"/api/conversations/{cid}").json()
    (said,) = [t for t in snap["tool_calls"] if t["name"] == "propose_trigger"]
    assert said["status"] == "failed" and "a turn the user started" in said["result"]
    assert snap["trigger_proposals"] == []


# --- the review's round (K-tetik fixes) -----------------------------------------------------


def test_the_apps_own_look_reads_git_off_its_loop_also_at_startup(make_client, project_dir,
                                                                 monkeypatch):
    client, _model, pid, cid = setup(make_client, project_dir, {"Lead": [text("one")]})
    repository(project_dir)
    made = trigger(client, pid, cid)
    with client.app.state.session_factory() as session:  # due, as after KOLONİ was off
        session.get(Trigger, made["id"]).next_at = T0 - timedelta(hours=1)
        session.commit()
    where, state = [], kept.git.state

    def looked(root):
        try:
            asyncio.get_running_loop()
            where.append("loop")
        except RuntimeError:
            where.append("thread")
        return state(root)

    monkeypatch.setattr(kept.git, "state", looked)
    triggers = client.app.state.triggers
    started = asyncio.run_coroutine_threadsafe(triggers.look(T0, starting=True),
                                               triggers._loop).result(30)
    assert len(started) == 1 and where == ["thread"]


def test_a_look_while_its_own_turn_runs_is_busy_and_the_key_is_kept_once_it_completes(
        make_client, project_dir):
    gate = Gate()
    client, _model, pid, cid = setup(make_client, project_dir, {"Lead": [
        text("one"), gate.step(text("two")), text("three")]})
    repository(project_dir)
    made = trigger(client, pid, cid)
    tick(client, T0)
    finished(client, made["id"], 1)

    def last_key():
        with client.app.state.session_factory() as session:
            return session.get(Trigger, made["id"]).last_key

    first = last_key()
    assert first is not None
    # Changed, so the next time runs: held open, the key kept is still the last completed run's.
    (project_dir / "hello.py").write_bytes(b"print('bye')\n")
    assert len(tick(client, T0 + timedelta(minutes=60))) == 1
    gate.wait_partial()
    assert last_key() == first
    # Due again while that run works, nothing changed since it started: busy, not "nothing changed".
    assert tick(client, T0 + timedelta(minutes=120)) == []
    assert one(client, made["id"])["runs"][0]["outcome"] == "skipped_busy"
    gate.release()
    finished(client, made["id"], 3)
    assert last_key() not in (None, first)
    assert tick(client, T0 + timedelta(minutes=180)) == []
    assert one(client, made["id"])["runs"][0]["outcome"] == "skipped_same"


def test_a_streak_of_skips_is_written_once(make_client, project_dir):
    client, _model, pid, cid = setup(make_client, project_dir, {"Lead": [text("one")]})
    repository(project_dir)
    made = trigger(client, pid, cid)
    tick(client, T0)
    finished(client, made["id"], 1)
    for hours in (1, 2, 3):
        assert tick(client, T0 + timedelta(hours=hours)) == []
    assert [run["outcome"] for run in one(client, made["id"])["runs"]] == ["skipped_same", "completed"]


def test_switched_on_past_its_last_day_it_is_refused_until_the_day_is_changed(make_client,
                                                                             project_dir):
    client, _model, pid, cid = setup(make_client, project_dir, {"Lead": []})
    made = trigger(client, pid, cid, enabled=False)
    with client.app.state.session_factory() as session:
        session.get(Trigger, made["id"]).ends = {"until": later(-1)}
        session.commit()
    refused = client.patch(f"/api/triggers/{made['id']}", json={"enabled": True})
    assert refused.status_code == 422
    assert refused.json()["detail"] == "its last day is over: change its last day"
    assert client.patch(f"/api/triggers/{made['id']}", json={
        "enabled": True, "ends": {"until": later(2)}}).json()["enabled"] is True


def test_an_end_date_is_at_most_a_year_ahead():
    today = date(2026, 10, 27)
    assert kept.check_ends({"until": "2027-10-27"}, today) == {"until": "2027-10-27"}
    with pytest.raises(kept.Invalid, match="a year ahead"):
        kept.check_ends({"until": "2027-10-28"}, today)


def test_a_turn_proposes_at_most_three_and_a_card_makes_a_trigger_only_in_its_own_chat(
        make_client, project_dir, wait_run):
    client, _model, pid, cid = setup(make_client, project_dir, {"Lead": [
        step(*[call("propose_trigger", {**FRIDAYS, "name": f"n{i}"}, f"p{i}") for i in range(4)]),
        text("Proposed.")]})
    run_id = client.post(f"/api/conversations/{cid}/messages",
                         json={"content": "propose four"}).json()["run"]["id"]
    snap = wait_run(client, cid, run_id)
    statuses = [(t["status"], t["result"]) for t in snap["tool_calls"] if t["name"] == "propose_trigger"]
    assert [status for status, _ in statuses] == ["succeeded"] * 3 + ["failed"]
    assert "at most 3 triggers" in statuses[-1][1]
    card = snap["trigger_proposals"][0]
    other = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    refused = client.post(f"/api/projects/{pid}/triggers", json={
        "name": "x", "kind": "schedule", "conversation_id": other, "message": MESSAGE,
        "config": {"every_minutes": 60}, "proposal_id": card["id"]})
    assert refused.status_code == 422 and "proposed in" in refused.json()["detail"]


def test_a_files_proposal_that_names_too_much_is_refused_at_once(make_client, project_dir,
                                                                 wait_run, monkeypatch):
    monkeypatch.setattr(kept, "MAX_FILES", 1)
    (project_dir / "a.py").write_bytes(b"")
    _client, _pid, _cid, snap, said = proposed(make_client, project_dir, wait_run, {
        **FRIDAYS, "kind": "files", "config": {"glob": "*.py"}})
    assert said["status"] == "failed" and "more than" in said["result"]
    assert snap["trigger_proposals"] == []


def test_nothing_changed_while_its_own_turn_runs_is_said_busy(make_client, project_dir):
    gate = Gate()
    client, _model, pid, cid = setup(make_client, project_dir, {"Lead": [
        text("one"), gate.step(text("two"))]})
    repository(project_dir)
    made = trigger(client, pid, cid)
    tick(client, T0)
    finished(client, made["id"], 1)
    # The user's Run now, held open, on the same files: the next time is busy, not "nothing changed".
    run_now(client, made["id"])
    gate.wait_partial()
    assert tick(client, T0 + timedelta(minutes=60)) == []
    assert one(client, made["id"])["runs"][0]["outcome"] == "skipped_busy"
    gate.release()
