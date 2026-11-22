"""Kanıtlı bitiş S6 (plan decision 10): at a watched turn's end KOLONİ runs the tests related to
the changed files first - the answer waits for those only - and the whole suite goes on in the
background, as a pull request's CI does: "Full tests running" under the answer and on the status
line, the row written again when it ends. A failure then offers Fix it; nothing starts by itself.
Turns nobody watches, and work in a copy, wait as before. KOLONİ's own runs at once and the test
processes each may start are Settings › The app's; the user can stop a running check."""

import asyncio
import time

import pytest

from app import proof
from app.agent import proof_later_mixin
from app.db.models import Message
from tests.conftest import scaled
from tests.fakes import Script, ScriptedExecutor
from tests.test_agent_writes import write
from tests.test_chat_flow import text
from tests.test_proof_end_scenarios import (
    OWN,
    PASS,
    SAVED,
    begin,
    checked,
    failing,
    guess,
    proof_calls,
    run,
    texts,
    told,
)

PYTEST = "python -m pytest -q"


@pytest.fixture
def soon(monkeypatch):
    """The answer waits a moment, not a minute, for a whole suite with no related tests: only
    where a held run is to go on after it (on a slow runner a quick one may go on too)."""
    monkeypatch.setattr(proof_later_mixin, "DETACH_SECONDS", 0.2)


def until(read, seconds=10.0):
    deadline = time.monotonic() + scaled(seconds)
    while not (found := read()):
        assert time.monotonic() < deadline, "never came"
        time.sleep(0.02)
    return found


def rows_of(client, cid, run_id):
    snap = client.get(f"/api/conversations/{cid}").json()
    found = [m["checked"] for m in snap["messages"] if m["role"] == "checked"
             and m["run_id"] == run_id]
    return found[0] if found else []


def with_tests(root, *names):
    for name in names:
        (root / "tests").mkdir(exist_ok=True)
        (root / "tests" / name).write_text("def test_it():\n    pass\n", encoding="utf-8")


def held(gate, *chunks, code=0):
    return Script(list(chunks) or ["....\n"], exit_code=code, hold=gate)


@pytest.mark.usefixtures("soon")
def test_a_long_run_goes_on_after_the_answer_and_updates_checked(
        make_client, wait_run, project_dir, gate):
    executor = ScriptedExecutor([held(gate, "....\n", "===== 4 passed in 9s =====\n")])
    client, model = make_client([write("a.py", "x = 1\n"), text("done")], executor=executor)
    cid, run_id = begin(client, project_dir, check_command="python check.py")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    (ran,) = snap["commands"]
    assert ran["status"] == "running" and ran["timeout_seconds"] == 600  # (CHECK_SECONDS)
    (row,) = until(lambda: [one for one in rows_of(client, cid, run_id) if one["started_at"]])
    assert (row["state"], row["text"]) == ("running", "Full tests running: python check.py")
    note = next(m for m in snap["messages"] if m["role"] == "checked")
    assert note["content"].startswith("… Full tests")
    assert len(model.calls) == 2  # (the answer came: nothing more was asked of the Lead)
    gate.release()
    (row,) = until(lambda: [one for one in rows_of(client, cid, run_id)
                            if one["state"] != "running"])
    assert (row["state"], row["text"]) == ("passed", "Tests passed: python check.py - 4 passed in 9s")
    snap = client.get(f"/api/conversations/{cid}").json()
    again = next(m for m in snap["messages"] if m["role"] == "checked")
    assert again["id"] == note["id"] and again["content"].startswith("✓ Tests passed")
    (call,) = proof_calls(snap)
    assert call["status"] == "succeeded" and snap["commands"][0]["exit_code"] == 0


def test_related_tests_first_then_the_whole_suite_in_the_background(
        make_client, wait_run, project_dir, gate):
    with_tests(project_dir, "test_a.py", "test_b.py")
    executor = ScriptedExecutor([Script(["1 passed\n"]), held(gate, "2 passed\n")])
    client, model = make_client([write("a.py", "x = 1\n"), text("done")], executor=executor)
    cid, run_id = begin(client, project_dir, check_command=PYTEST)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert [command for command, _cwd in executor.started] == [f"{PYTEST} tests/test_a.py", PYTEST]
    first, full = until(lambda: (r := rows_of(client, cid, run_id)) and r[1]["started_at"] and r)
    assert (first["state"], first["text"]) == (
        "passed", f"Related tests passed: {PYTEST} tests/test_a.py - 1 passed")
    assert (full["state"], full["text"]) == ("running", f"Full tests running: {PYTEST}")
    gate.release()
    until(lambda: rows_of(client, cid, run_id)[1]["state"] == "passed")
    assert len(model.calls) == 2


def test_failing_related_tests_send_the_orchestrator_back_before_the_whole_suite(
        make_client, wait_run, project_dir):
    with_tests(project_dir, "test_a.py")
    executor = ScriptedExecutor([failing(), Script(["1 passed\n"]), PASS])
    client, model = make_client([write("a.py", "x = 1\n"), text("done"),
                                 write("a.py", "x = 2\n", "w2"), text("fixed")], executor=executor)
    cid, run_id = begin(client, project_dir, check_command=PYTEST)
    wait_run(client, cid, run_id)
    assert told(model) == 1
    assert [command for command, _cwd in executor.started] == [
        f"{PYTEST} tests/test_a.py", f"{PYTEST} tests/test_a.py", PYTEST]
    rows = until(lambda: (r := rows_of(client, cid, run_id)) and r[1]["state"] != "running" and r)
    assert [one["text"] for one in rows] == [
        f"Related tests passed: {PYTEST} tests/test_a.py - 1 passed",
        f"Tests passed: {PYTEST} - 4 passed in 0.1s", "Sent back to fix: 1 of 2 rounds"]


def test_related_tests_failing_at_the_last_round_leave_the_whole_suite_unrun(
        make_client, wait_run, project_dir):
    with_tests(project_dir, "test_a.py")
    executor = ScriptedExecutor([failing(), failing(), failing()])
    client, _model = make_client([write("a.py", "x = 1\n"), text("done"),
                                  write("a.py", "x = 2\n", "w2"), text("fixed"),
                                  write("a.py", "x = 3\n", "w3"), text("fixed again")],
                                 executor=executor)
    cid, run_id = begin(client, project_dir, check_command=PYTEST)
    snap = wait_run(client, cid, run_id)
    assert len(executor.started) == 3
    assert texts(snap) == [
        f"Related tests failed: {PYTEST} tests/test_a.py - 1 failed, 3 passed",
        proof.FULL_HELD, "Sent back to fix: 2 of 2 rounds",
        "Still failing after 2 fix rounds: you decide (Fix it)"]


def test_a_quick_whole_suite_with_no_related_tests_still_sends_a_failure_back(
        make_client, wait_run, project_dir):
    # (No related step for python check.py: the answer waits DETACH_SECONDS for the whole suite,
    # and a failure inside it goes back as before.)
    executor = ScriptedExecutor([failing(), PASS])
    client, model = make_client([write("a.py", "x = 1\n"), text("done"),
                                 write("a.py", "x = 2\n", "w2"), text("fixed")], executor=executor)
    cid, run_id = begin(client, project_dir, check_command="python check.py")
    snap = wait_run(client, cid, run_id)
    assert told(model) == 1 and texts(snap)[0].startswith("Tests passed")


@pytest.mark.usefixtures("soon")
def test_a_background_failure_offers_fix_it_and_starts_nothing(
        make_client, wait_run, project_dir, gate):
    executor = ScriptedExecutor([held(gate, "F\n", "1 failed, 3 passed\n", code=1)])
    client, model = make_client([write("a.py", "x = 1\n"), text("done")], executor=executor)
    cid, run_id = begin(client, project_dir, check_command="python check.py")
    wait_run(client, cid, run_id)
    gate.release()
    (row,) = until(lambda: [one for one in rows_of(client, cid, run_id)
                            if one["state"] == "failed"])
    assert row["text"] == "Tests failed: python check.py - 1 failed, 3 passed"
    assert row["command"] == "python check.py"  # (what Fix it names)
    time.sleep(0.2)
    snap = client.get(f"/api/conversations/{cid}").json()
    assert len(snap["runs"]) == 1 and len(model.calls) == 2


@pytest.mark.usefixtures("soon")
def test_a_background_result_after_a_later_change_says_so(make_client, wait_run, project_dir, gate):
    executor = ScriptedExecutor([held(gate, "4 passed\n")])
    client, _model = make_client([write("a.py", "x = 1\n"), text("done"),
                                  write("b.py", "y = 1\n", "w2"), text("more")], executor=executor)
    cid, run_id = begin(client, project_dir, check_command="python check.py")
    wait_run(client, cid, run_id)
    until(lambda: rows_of(client, cid, run_id)[0]["started_at"])
    # (A later turn changes the project with no check of its own to take the run's place.)
    pid = client.get(f"/api/conversations/{cid}").json()["conversation"]["project_id"]
    client.patch(f"/api/projects/{pid}", json={"after_change": "nothing"}, headers=OWN)
    later = client.post(f"/api/conversations/{cid}/messages", json={"content": "and b"}).json()
    wait_run(client, cid, later["run"]["id"])
    gate.release()
    (row,) = until(lambda: [one for one in rows_of(client, cid, run_id)
                            if one["state"] != "running"])
    assert (row["state"], row["text"]) == (
        "note", "Tests passed: python check.py - 4 passed - the project changed while they ran")


@pytest.mark.usefixtures("soon")
def test_a_newer_turn_takes_the_place_of_an_older_background_run(
        make_client, wait_run, project_dir, gate):
    executor = ScriptedExecutor([held(gate), PASS])
    client, _model = make_client([write("a.py", "x = 1\n"), text("done"),
                                  write("b.py", "y = 1\n", "w2"), text("more")], executor=executor)
    cid, run_id = begin(client, project_dir, check_command="python check.py")
    wait_run(client, cid, run_id)
    until(lambda: rows_of(client, cid, run_id)[0]["started_at"])
    later = client.post(f"/api/conversations/{cid}/messages", json={"content": "and b"}).json()
    wait_run(client, cid, later["run"]["id"])
    (row,) = until(lambda: [one for one in rows_of(client, cid, run_id)
                            if one["state"] != "running"])
    assert (row["state"], row["text"]) == ("not_run", proof.SUPERSEDED)
    # (its own run may have gone on after its answer too, on a slow machine: its end is waited for)
    until(lambda: rows_of(client, cid, later["run"]["id"])[0]["state"] == "passed")
    snap = client.get(f"/api/conversations/{cid}").json()
    assert snap["commands"][0]["status"] == "killed"


def test_only_a_watched_turn_whose_work_is_in_the_project_may_go_on():
    # (A recipe's or a branch's copy is taken in or set aside under the run: its tests cannot go
    # on after the answer. How such a turn waits: S1's scenarios, `cannot_go_on`.)
    from types import SimpleNamespace

    def may(waits, place):
        return proof_later_mixin.ProofLaterMixin._may_go_on(SimpleNamespace(
            _answer_waits=lambda _ctx: waits, _works_in=lambda _ctx: place), None)
    assert may(True, None)
    assert not may(True, "the Lead's copy") and not may(False, None)


@pytest.mark.usefixtures("soon")
def test_a_background_run_past_its_limit_is_timed_out(make_client, wait_run, project_dir, gate,
                                                      monkeypatch):
    import app.agent

    monkeypatch.setattr(app.agent, "CHECK_SECONDS", 1)  # (10 min: one second here)
    client, _model = make_client([write("a.py", "x = 1\n"), text("done")],
                                 executor=ScriptedExecutor([held(gate)]))
    cid, run_id = begin(client, project_dir, check_command="python check.py")
    wait_run(client, cid, run_id)
    (row,) = until(lambda: [one for one in rows_of(client, cid, run_id)
                            if one["state"] != "running"])
    assert row["state"] == "timed_out" and row["text"].startswith("Tests timed out after"), row
    assert client.get(f"/api/conversations/{cid}").json()["commands"][0]["status"] == "timed_out"


def status_of(client, cid, run_id):
    snap = client.get(f"/api/conversations/{cid}").json()
    return next(r["status"] for r in snap["runs"] if r["id"] == run_id)


def approve_write(client, cid, path):
    def proposed():
        snap = client.get(f"/api/conversations/{cid}").json()
        return [f for f in snap["file_changes"] if f["path"] == path and f["status"] == "proposed"]
    (change,) = until(proposed)
    answer = client.post(f"/api/file-changes/{change['id']}/approve", headers=OWN)
    assert answer.status_code == 200 and answer.json()["status"] == "applied", answer.text


SETTINGS = ".vscode/settings.json"  # (a standing file: it steers later work)


@pytest.mark.usefixtures("soon")
def test_a_standing_file_the_suite_writes_after_its_turn_is_taken_back_with_no_card(
        make_client, wait_run, project_dir, gate):
    # (Review B2, probe A: a card here set the finished turn waiting again and held the slot.)
    executor = ScriptedExecutor([Script(["4 passed\n"], hold=gate, writes={SETTINGS: "{}\n"})])
    client, _model = make_client([write("a.py", "x = 1\n"), text("done")], executor=executor)
    cid, run_id = begin(client, project_dir, check_command="python check.py")
    wait_run(client, cid, run_id)
    until(lambda: rows_of(client, cid, run_id)[0]["started_at"])
    gate.release()
    (row,) = until(lambda: [one for one in rows_of(client, cid, run_id)
                            if one["state"] != "running"])
    assert row["state"] == "passed" and status_of(client, cid, run_id) == "completed"
    assert not (project_dir / SETTINGS).exists()  # (the tests' own write: not the work's)
    snap = client.get(f"/api/conversations/{cid}").json()
    (noted,) = [c for c in snap["tool_calls"]
                if c["name"] == "write_file" and SETTINGS in (c["result"] or "")]
    assert noted["status"] == "denied" and "its turn was over" in noted["result"], noted
    assert not client.app.state.runner._test_slot.locked()


@pytest.mark.usefixtures("soon")
def test_a_newer_turns_approved_standing_write_survives_the_older_run_it_ends(
        make_client, wait_run, project_dir, gate):
    # (Review B1, probe B: the superseded run took back what the newer turn wrote meanwhile.)
    client, _model = make_client([write("a.py", "x = 1\n"), text("done"),
                                  write(SETTINGS, '{"a": 1}\n', "w2"), text("more")],
                                 executor=ScriptedExecutor([held(gate), PASS, PASS]))
    cid, run_id = begin(client, project_dir, check_command="python check.py")
    wait_run(client, cid, run_id)
    until(lambda: rows_of(client, cid, run_id)[0]["started_at"])
    later = client.post(f"/api/conversations/{cid}/messages", json={"content": "and"}).json()
    approve_write(client, cid, SETTINGS)
    wait_run(client, cid, later["run"]["id"])
    until(lambda: rows_of(client, cid, run_id)[0]["text"] == proof.SUPERSEDED)
    assert (project_dir / SETTINGS).read_text(encoding="utf-8") == '{"a": 1}\n'
    # (Never taken back at all - not only put there again by the newer turn's own run.)
    snap = client.get(f"/api/conversations/{cid}").json()
    assert not [c for c in snap["tool_calls"] if c["name"] == "write_file"
                and SETTINGS in (c["result"] or "") and "taken back" in c["result"]], [
        (c["status"], c["result"]) for c in snap["tool_calls"] if c["name"] == "write_file"]


@pytest.mark.usefixtures("soon")
def test_a_later_turns_standing_write_survives_the_run_ending_after_it(
        make_client, wait_run, project_dir, gate):
    # (Review B1, probe C: the later turn checks nothing - the old run ends on its own.)
    client, _model = make_client([write("a.py", "x = 1\n"), text("done"),
                                  write(SETTINGS, '{"a": 1}\n', "w2"), text("more")],
                                 executor=ScriptedExecutor([held(gate, "4 passed\n")]))
    cid, run_id = begin(client, project_dir, check_command="python check.py")
    wait_run(client, cid, run_id)
    until(lambda: rows_of(client, cid, run_id)[0]["started_at"])
    pid = client.get(f"/api/conversations/{cid}").json()["conversation"]["project_id"]
    client.patch(f"/api/projects/{pid}", json={"after_change": "nothing"}, headers=OWN)
    later = client.post(f"/api/conversations/{cid}/messages", json={"content": "and"}).json()
    approve_write(client, cid, SETTINGS)
    wait_run(client, cid, later["run"]["id"])
    gate.release()
    (row,) = until(lambda: [one for one in rows_of(client, cid, run_id)
                            if one["state"] != "running"])
    assert row["text"].endswith(proof.CHANGED_WHILE) and row["state"] == "note", row
    assert (project_dir / SETTINGS).read_text(encoding="utf-8") == '{"a": 1}\n'


@pytest.mark.usefixtures("soon")
def test_the_tests_own_later_write_over_another_turns_is_still_taken_back(
        make_client, wait_run, project_dir, gate):
    # (Review round 2, probe D: what another turn wrote stands only while its bytes are there -
    # by path alone, a planted test's own write over it stood: `.git/config` with a hooksPath.)
    client, _model = make_client([write("a.py", "x = 1\n"), text("done"),
                                  write(SETTINGS, '{"a": 1}\n', "w2"), text("more")],
                                 executor=ScriptedExecutor([held(gate, "4 passed\n")]))
    cid, run_id = begin(client, project_dir, check_command="python check.py")
    wait_run(client, cid, run_id)
    until(lambda: rows_of(client, cid, run_id)[0]["started_at"])
    pid = client.get(f"/api/conversations/{cid}").json()["conversation"]["project_id"]
    client.patch(f"/api/projects/{pid}", json={"after_change": "nothing"}, headers=OWN)
    later = client.post(f"/api/conversations/{cid}/messages", json={"content": "and"}).json()
    approve_write(client, cid, SETTINGS)
    wait_run(client, cid, later["run"]["id"])
    (project_dir / SETTINGS).write_text('{"evil": 1}\n', encoding="utf-8")  # (as the suite would)
    gate.release()
    until(lambda: [one for one in rows_of(client, cid, run_id) if one["state"] != "running"])
    snap = client.get(f"/api/conversations/{cid}").json()
    (taken,) = [c for c in snap["tool_calls"] if c["name"] == "write_file"
                and SETTINGS in (c["result"] or "") and "taken back" in c["result"]]
    # (Round 3: back to what the record left - the approved file - not to before the run.)
    assert (project_dir / SETTINGS).read_text(encoding="utf-8") == '{"a": 1}\n'
    assert "put back to what the last recorded change left there" in taken["result"], taken


@pytest.mark.usefixtures("soon")
def test_a_hook_the_suite_writes_on_no_record_is_taken_back(
        make_client, wait_run, project_dir, gate):
    # (Review round 2, probe E: nothing on record wrote it - it is the tests'.)
    client, _model = make_client([write("a.py", "x = 1\n"), text("done")],
                                 executor=ScriptedExecutor([held(gate, "4 passed\n")]))
    cid, run_id = begin(client, project_dir, check_command="python check.py")
    wait_run(client, cid, run_id)
    until(lambda: rows_of(client, cid, run_id)[0]["started_at"])
    hooks = project_dir / ".git" / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    (hooks / "pre-commit").write_text("#!/bin/sh\necho planted\n", encoding="utf-8")
    gate.release()
    until(lambda: [one for one in rows_of(client, cid, run_id) if one["state"] != "running"])
    assert not (hooks / "pre-commit").exists()


@pytest.mark.usefixtures("soon")
def test_a_command_of_a_later_turn_beneath_the_run_says_the_project_changed(
        make_client, wait_run, project_dir, gate):
    # (Review item 1: no file on record - a formatter, a codegen - yet the project changed.)
    executor = ScriptedExecutor([held(gate, "4 passed\n"), PASS])
    client, _model = make_client([write("a.py", "x = 1\n"), text("done"),
                                  run("python fmt.py"), text("formatted")], executor=executor)
    cid, run_id = begin(client, project_dir, check_command="python check.py")
    wait_run(client, cid, run_id)
    until(lambda: rows_of(client, cid, run_id)[0]["started_at"])
    later = client.post(f"/api/conversations/{cid}/messages", json={"content": "fmt"}).json()
    wait_run(client, cid, later["run"]["id"])
    gate.release()
    (row,) = until(lambda: [one for one in rows_of(client, cid, run_id)
                            if one["state"] != "running"])
    assert (row["state"], row["text"]) == (
        "note", f"Tests passed: python check.py - 4 passed{proof.CHANGED_WHILE}")


@pytest.mark.usefixtures("soon")
def test_a_newer_pass_ends_only_the_same_suite(make_client, wait_run, project_dir, gate):
    # (Review item 2: another command, or another folder, is not the one it takes the place of.)
    client, _model = make_client([write("a.py", "x = 1\n"), text("done"),
                                  write("b.py", "y = 1\n", "w2"), text("more")],
                                 executor=ScriptedExecutor([held(gate, "4 passed\n"), PASS]))
    cid, run_id = begin(client, project_dir, check_command="python check.py")
    wait_run(client, cid, run_id)
    until(lambda: rows_of(client, cid, run_id)[0]["started_at"])
    pid = client.get(f"/api/conversations/{cid}").json()["conversation"]["project_id"]
    client.patch(f"/api/projects/{pid}", json={"check_command": "python other.py"}, headers=OWN)
    client.put("/api/test-load", json={"runs_at_once": 2}, headers=OWN)
    later = client.post(f"/api/conversations/{cid}/messages", json={"content": "and"}).json()
    wait_run(client, cid, later["run"]["id"])
    assert rows_of(client, cid, run_id)[0]["state"] == "running"
    gate.release()
    (row,) = until(lambda: [one for one in rows_of(client, cid, run_id)
                            if one["state"] != "running"])
    assert row["text"].startswith("Tests passed: python check.py"), row


@pytest.mark.usefixtures("soon")
def test_stopped_while_waiting_for_the_machine_it_says_so(make_client, wait_run, project_dir):
    # (Review item 3: its clock is from its start - and one that never started says that.)
    client, _model = make_client([write("a.py", "x = 1\n"), text("done")],
                                 executor=ScriptedExecutor([]))
    slot = client.app.state.runner._test_slot
    client.portal.call(slot.acquire)  # (another run holds the machine)
    try:
        cid, run_id = begin(client, project_dir, check_command="python check.py")
        wait_run(client, cid, run_id)
        assert client.post(f"/api/runs/{run_id}/check/stop", headers=OWN).status_code == 200
        (row,) = until(lambda: [one for one in rows_of(client, cid, run_id)
                                if one["state"] != "running"])
    finally:
        client.portal.call(slot.release)
    assert row["text"] == "Full tests stopped by you before they started - not checked"


def test_a_lower_limit_holds_new_runs_until_enough_going_end():
    # (Review item 4: the ones going under the old limit still count.)
    import asyncio

    async def go() -> list[str]:
        slots, said = proof_later_mixin.Slots(2), []
        await slots.acquire()
        await slots.acquire()
        slots.limit = 1

        async def third():
            await slots.acquire()
            said.append("third")
        waiting = asyncio.ensure_future(third())
        slots.release()
        await asyncio.sleep(0.05)
        said.append("one released")
        slots.release()
        await asyncio.wait_for(waiting, 5)
        return said
    assert asyncio.run(go()) == ["one released", "third"]


@pytest.mark.usefixtures("soon")
def test_a_project_is_not_deleted_under_a_run_waiting_for_the_machine(
        make_client, wait_run, project_dir):
    # (Review item 5: it would start later in a folder no longer KOLONİ's.)
    client, _model = make_client([write("a.py", "x = 1\n"), text("done")],
                                 executor=ScriptedExecutor([]))
    slot = client.app.state.runner._test_slot
    client.portal.call(slot.acquire)
    try:
        cid, run_id = begin(client, project_dir, check_command="python check.py")
        wait_run(client, cid, run_id)
        pid = client.get(f"/api/conversations/{cid}").json()["conversation"]["project_id"]
        refused = client.delete(f"/api/projects/{pid}", headers=OWN)
        assert refused.status_code == 409 and refused.json()["detail"] == (
            proof_later_mixin.BUSY_HERE)
        assert client.post(f"/api/runs/{run_id}/check/stop", headers=OWN).status_code == 200
        until(lambda: rows_of(client, cid, run_id)[0]["state"] != "running")
        assert client.delete(f"/api/projects/{pid}", headers=OWN).status_code == 204
    finally:
        client.portal.call(slot.release)


def test_koloni_s_variables_reach_the_command_on_the_host_and_in_docker(tmp_path):
    import asyncio
    import sys

    from app.executors.docker import docker_argv
    from app.executors.host import HostExecutor

    argv = docker_argv("c", "img", tmp_path, tmp_path, False, "pytest",
                       env={"PYTEST_XDIST_AUTO_NUM_WORKERS": "2"})
    assert argv[argv.index("PYTEST_XDIST_AUTO_NUM_WORKERS=2") - 1] == "-e"

    async def printed() -> str:
        command = (f'"{sys.executable}" -c "import os; '
                   f'print(os.environ[\'PYTEST_XDIST_AUTO_NUM_WORKERS\'])"')
        running = await HostExecutor().start("k", command if sys.platform != "win32" else
                                             f"& {command}", tmp_path,
                                             env={"PYTEST_XDIST_AUTO_NUM_WORKERS": "3"})
        said = "".join([chunk async for chunk in running])
        await running.wait()
        await running.close()
        return said
    assert asyncio.run(printed()).strip() == "3"


@pytest.mark.usefixtures("soon")
def test_stop_this_check_stops_a_background_run(make_client, wait_run, project_dir, gate):
    executor = ScriptedExecutor([held(gate)])
    client, _model = make_client([write("a.py", "x = 1\n"), text("done")], executor=executor)
    cid, run_id = begin(client, project_dir, check_command="python check.py")
    wait_run(client, cid, run_id)
    until(lambda: rows_of(client, cid, run_id)[0]["started_at"])
    assert client.post(f"/api/runs/{run_id}/check/stop", headers=OWN).status_code == 200
    (row,) = until(lambda: [one for one in rows_of(client, cid, run_id)
                            if one["state"] != "running"])
    assert row["state"] == "not_run" and row["text"].startswith("Full tests stopped by you at 0:")
    assert row["text"].endswith(" - not checked")
    snap = client.get(f"/api/conversations/{cid}").json()
    assert snap["commands"][0]["status"] == "killed" and len(executor.killed) == 1
    assert proof_calls(snap)[0]["status"] != "succeeded"
    assert client.post(f"/api/runs/{run_id}/check/stop", headers=OWN).status_code == 409


@pytest.mark.usefixtures("soon")
def test_stop_everything_stops_a_background_run_too(make_client, wait_run, project_dir, gate):
    executor = ScriptedExecutor([held(gate)])
    client, _model = make_client([write("a.py", "x = 1\n"), text("done")], executor=executor)
    cid, run_id = begin(client, project_dir, check_command="python check.py")
    wait_run(client, cid, run_id)
    until(lambda: rows_of(client, cid, run_id)[0]["started_at"])
    assert client.post("/api/hold", headers=OWN).status_code == 200
    (row,) = until(lambda: [one for one in rows_of(client, cid, run_id)
                            if one["state"] != "running"])
    assert (row["state"], row["text"]) == ("not_run", proof.STOPPED)


def test_stop_this_check_during_the_related_run_lets_the_turn_end_unchecked(
        make_client, wait_run, project_dir, gate):
    with_tests(project_dir, "test_a.py")
    executor = ScriptedExecutor([held(gate)])
    client, model = make_client([write("a.py", "x = 1\n"), text("done")], executor=executor)
    cid, run_id = begin(client, project_dir, check_command=PYTEST)
    until(lambda: [c for c in client.get(f"/api/conversations/{cid}").json()["commands"]
                   if c["status"] == "running"])
    assert client.post(f"/api/runs/{run_id}/check/stop", headers=OWN).status_code == 200
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    rows = checked(snap)
    assert rows[0]["text"].startswith("Related tests stopped by you at 0:"), rows
    assert rows[1]["text"] == proof.NOT_RUN.format(why=proof_later_mixin.YOU_STOPPED)
    assert len(executor.started) == 1 and len(model.calls) == 2


def test_stop_this_check_is_the_users_from_the_apps_page(make_client, wait_run, project_dir):
    client, _model = make_client([write("a.py", "x = 1\n"), text("done")],
                                 executor=ScriptedExecutor([PASS]))
    cid, run_id = begin(client, project_dir, check_command="python check.py")
    wait_run(client, cid, run_id)
    assert client.post(f"/api/runs/{run_id}/check/stop").status_code == 403
    assert client.post(f"/api/runs/{run_id}/check/stop", headers=OWN).status_code == 409


def test_a_restart_settles_a_running_checked_row(make_client, wait_run, project_dir):
    from app.agent import recover_interrupted

    client, _model = make_client([write("a.py", "x = 1\n"), text("done")],
                                 executor=ScriptedExecutor([PASS]))
    cid, run_id = begin(client, project_dir, check_command="python check.py")
    wait_run(client, cid, run_id)
    factory = client.app.state.session_factory
    with factory() as session:  # (as a process that ended under its background run left it)
        note = session.query(Message).filter_by(run_id=run_id, role="checked").one()
        rows = [{**note.blocks["rows"][0], "state": "running", "text": "Full tests running: x",
                 "started_at": "2026-11-22T10:00:00+00:00"}, *note.blocks["rows"][1:]]
        note.blocks, note.content = {"rows": rows}, proof.checked_text(rows)
        session.commit()
    recover_interrupted(factory)
    (row,) = rows_of(client, cid, run_id)
    assert (row["state"], row["text"]) == ("not_run", "Tests not finished: KOLONİ restarted")
    with factory() as session:
        assert session.query(Message).filter_by(run_id=run_id, role="checked").one().content == (
            "– Tests not finished: KOLONİ restarted")


@pytest.mark.usefixtures("soon")
def test_a_to_do_turn_never_goes_on_in_the_background(make_client, wait_run, project_dir, gate):
    # (Nobody waits on its answer, and its fix rounds need the result: it waits for the run.)
    client, _model = make_client([write("a.py", "x = 1\n"), text("done")],
                                 executor=ScriptedExecutor([held(gate, "4 passed\n")]))
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    assert client.patch(f"/api/projects/{pid}", json={
        "check_command": "python check.py", "lead_work": "itself"}, headers=OWN).status_code == 200
    assert client.put(f"/api/projects/{pid}/backlog/choice", json={"permission_mode": "full_auto"},
                      headers=OWN).status_code == 200
    client.post(f"/api/projects/{pid}/backlog", json={"title": "greeting"}, headers=OWN)
    cid = client.post(f"/api/projects/{pid}/backlog/next", headers=OWN).json()["conversation_id"]
    run_id = client.get(f"/api/conversations/{cid}").json()["runs"][0]["id"]
    until(lambda: client.get(f"/api/conversations/{cid}").json()["commands"])
    time.sleep(0.6)  # (three times the answer's wait: a watched turn would have gone on)
    assert client.get(f"/api/conversations/{cid}").json()["runs"][0]["status"] == "running"
    gate.release()
    assert checked(wait_run(client, cid, run_id))[0]["state"] == "passed"


def test_test_load_get_put_bounds(client):
    assert client.get("/api/test-load").json() == {"runs_at_once": 1, "workers": 2}
    for wrong in ({"runs_at_once": 0}, {"runs_at_once": 5}, {"workers": 0}, {"workers": 17},
                  {"workers": "3"}):
        assert client.put("/api/test-load", json=wrong, headers=OWN).status_code == 422, wrong
    assert client.put("/api/test-load", json={"workers": 4}, headers=OWN).json() == {
        "runs_at_once": 1, "workers": 4}
    assert client.put("/api/test-load", json={"runs_at_once": 2}).status_code == 403


def test_workers_reach_koloni_runs_only(make_client, wait_run, project_dir):
    executor = ScriptedExecutor([PASS, PASS, PASS])
    client, _model = make_client([run("python other.py"), write("a.py", "x = 1\n"), text("done"),
                                  write("a.py", "x = 2\n", "w2"), text("done")], executor=executor)
    cid, run_id = begin(client, project_dir, check_command="python check.py")
    wait_run(client, cid, run_id)
    assert executor.extra_envs == [{}, {"PYTEST_XDIST_AUTO_NUM_WORKERS": "2"}]
    client.put("/api/test-load", json={"workers": 5}, headers=OWN)
    again = client.post(f"/api/conversations/{cid}/messages", json={"content": "more"}).json()
    wait_run(client, cid, again["run"]["id"])
    assert executor.extra_envs[-1] == {"PYTEST_XDIST_AUTO_NUM_WORKERS": "5"}


@pytest.mark.usefixtures("soon")
def test_runs_at_once_lets_two_runs_go_together(make_client, wait_run, tmp_path, gate):
    executor = ScriptedExecutor([held(gate, "4 passed\n"), held(gate, "4 passed\n")])
    client, _model = make_client([write("a.py", "x = 1\n"), text("done"),
                                  write("a.py", "x = 1\n", "w2"), text("done")], executor=executor)
    assert client.put("/api/test-load", json={"runs_at_once": 2}, headers=OWN).status_code == 200
    first, second = tmp_path / "one", tmp_path / "two"
    first.mkdir()
    second.mkdir()
    cid1, run1 = begin(client, first, check_command="python check.py")
    cid2, run2 = begin(client, second, check_command="python check.py")
    until(lambda: len(executor.started) == 2)  # (both at once, the first still held)
    gate.release()
    for cid, run_id in ((cid1, run1), (cid2, run2)):
        wait_run(client, cid, run_id)
        until(lambda c=cid, r=run_id: rows_of(client, c, r)[0]["state"] == "passed")


# --- S1b with S6: a guessed whole suite gone on after the answer ---------------------------

def found_of(client, root):
    return next(p for p in client.get("/api/projects").json()
                if p["root_path"] == str(root))["tests_found"]


@pytest.mark.usefixtures("soon")
def test_a_guessed_suite_gone_on_after_the_answer_is_saved_as_it_ends(
        make_client, wait_run, project_dir, gate, monkeypatch):
    # (A slow suite always goes on after the answer: saved only in the turn, it never would be.)
    guess(monkeypatch, PYTEST)
    executor = ScriptedExecutor([held(gate, "....\n", "===== 4 passed in 9s =====\n")])
    client, _model = make_client([write("a.py", "x = 1\n"), text("done")], executor=executor)
    cid, run_id = begin(client, project_dir)
    wait_run(client, cid, run_id)
    until(lambda: rows_of(client, cid, run_id)[0]["started_at"])
    assert found_of(client, project_dir) == {}
    gate.release()
    rows = until(lambda: (r := rows_of(client, cid, run_id)) and r[0]["state"] != "running" and r)
    assert [row["text"] for row in rows] == [
        f"Tests passed: {PYTEST} (guessed) - 4 passed in 9s", SAVED], rows
    assert found_of(client, project_dir)["."]["command"] == PYTEST


@pytest.mark.usefixtures("soon")
def test_a_guessed_suite_stopped_after_the_answer_saves_nothing(
        make_client, wait_run, project_dir, gate, monkeypatch):
    guess(monkeypatch, PYTEST)
    executor = ScriptedExecutor([held(gate, "....\n", "===== 4 passed in 9s =====\n")])
    client, _model = make_client([write("a.py", "x = 1\n"), text("done")], executor=executor)
    cid, run_id = begin(client, project_dir)
    wait_run(client, cid, run_id)
    until(lambda: rows_of(client, cid, run_id)[0]["started_at"])
    assert client.post(f"/api/runs/{run_id}/check/stop", headers=OWN).status_code == 200
    (row,) = until(lambda: [one for one in rows_of(client, cid, run_id)
                            if one["state"] != "running"])
    assert row["state"] == "not_run" and found_of(client, project_dir) == {}, row


@pytest.mark.usefixtures("soon")
def test_a_save_that_breaks_still_says_how_the_suite_ended(make_client, wait_run, project_dir,
                                                           gate, monkeypatch):
    # (Review of the integration: the row stayed "running", and Stop this check then said 409.)
    from app.agent import found_mixin

    def broken(*_args, **_kw):
        raise RuntimeError("database is locked")
    monkeypatch.setattr(found_mixin.FoundMixin, "_found_saved", broken)
    guess(monkeypatch, PYTEST)
    executor = ScriptedExecutor([held(gate, "....\n", "===== 4 passed in 9s =====\n")])
    client, _model = make_client([write("a.py", "x = 1\n"), text("done")], executor=executor)
    cid, run_id = begin(client, project_dir)
    wait_run(client, cid, run_id)
    until(lambda: rows_of(client, cid, run_id)[0]["started_at"])
    gate.release()
    rows = until(lambda: (r := rows_of(client, cid, run_id)) and r[0]["state"] != "running" and r)
    assert [(row["state"], row["text"]) for row in rows] == [
        ("passed", f"Tests passed: {PYTEST} (guessed) - 4 passed in 9s")], rows
    assert found_of(client, project_dir) == {}


class Yielding(ScriptedExecutor):
    """As a real executor: starting a process yields to the loop once."""

    async def start(self, *args, **kwargs):
        await asyncio.sleep(0)
        return await super().start(*args, **kwargs)


@pytest.mark.usefixtures("soon")
@pytest.mark.parametrize(("at_once", "executor_of"), [
    (1, ScriptedExecutor), (2, ScriptedExecutor), (1, Yielding), (2, Yielding)])
def test_two_suites_of_one_turn_do_not_unmake_each_others_pass(make_client, wait_run, project_dir,
                                                              gate, at_once, executor_of):
    # (Another of KOLONİ's own test runs is no change beneath a run: it said "the project changed
    # while they ran" of the first suite's pass every time.)
    (project_dir / "web").mkdir()
    (project_dir / "web" / "package.json").write_text('{"name": "web"}', encoding="utf-8")
    (project_dir / "api").mkdir()
    (project_dir / "api" / "pom.xml").write_text("<project/>", encoding="utf-8")
    executor = executor_of([held(gate, "4 passed\n"), held(gate, "4 passed\n")])
    client, _model = make_client([write("web/a.js", "x\n"), write("api/A.java", "class A {}\n",
                                                                  "w2"), text("done")],
                                 executor=executor)
    assert client.put("/api/test-load", json={"runs_at_once": at_once},
                      headers=OWN).status_code == 200
    cid, run_id = begin(client, project_dir, parts={"web/": "python w.py", "api/": "python a.py"})
    wait_run(client, cid, run_id)
    until(lambda: rows_of(client, cid, run_id)[0]["started_at"])
    gate.release()
    rows = until(lambda: (r := rows_of(client, cid, run_id)) and len(
        [one for one in r if one["kind"] == "tests" and one["state"] != "running"]) == 2 and r)
    assert [row["state"] for row in rows] == ["passed", "passed"], rows
