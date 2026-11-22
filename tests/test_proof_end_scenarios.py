"""Kanıtlı bitiş (S1): after a turn that changed code KOLONİ runs the project's tests once on the
work as it now stands, sends a failure back to the Orchestrator at most twice, and writes under
the answer what was checked and what was not ("checked" message). It took over 89m's Claude Code
Stop hook, for every provider."""

import json
import time

import pytest

from app import proof
from app.agent import proof_mixin
from app.agent.proof_mixin import PROOF_CALL, TESTS_FAILED_LEAD
from app.model_anthropic import to_anthropic
from app.model_client import StepResult, ToolCallRequest
from tests.conftest import scaled
from tests.fakes import Script, ScriptedExecutor
from tests.test_agent_writes import wait_status, write
from tests.test_chat_flow import text
from tests.test_claude_native import claude_app  # noqa: F401  (a fixture)

OWN = {"Origin": "http://127.0.0.1:8790"}
NUDGE = TESTS_FAILED_LEAD.split("(")[0]  # "Not the end yet: KOLONİ ran the project's tests "


def begin(client, root, mode="full_auto", content="fix the greeting", parts=None, **project):
    """A chat in a project whose Lead writes itself, at `mode`, its first message sent; `parts`:
    the user's test commands by part."""
    pid = client.post("/api/projects", json={"root_path": str(root)}).json()["id"]
    assert client.patch(f"/api/projects/{pid}", json=project, headers=OWN).status_code == 200
    for path, command in (parts or {}).items():
        assert client.put(f"/api/projects/{pid}/map/test", json={
            "path": path, "command": command}, headers=OWN).status_code == 200
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(f"/api/conversations/{cid}", json={"permission_mode": mode,
                 "lead_hands_code": False}, headers=OWN)
    run_id = client.post(f"/api/conversations/{cid}/messages",
                         json={"content": content}).json()["run"]["id"]
    return cid, run_id


def run(command, id="r1"):
    return StepResult("", [ToolCallRequest(id, "run_command", json.dumps({"command": command}))],
                      1, 1)


def proof_calls(snap):
    return [c for c in snap["tool_calls"] if c["provider_call_id"].startswith(PROOF_CALL)]


def checked(snap):
    (one,) = [m for m in snap["messages"] if m["role"] == "checked"] or [None]
    return one and one["checked"]


def texts(snap):
    return [row["text"] for row in checked(snap) or []]


def told(model):
    """How often the Lead was told the tests failed, in its last request."""
    return sum(NUDGE in str(m.get("content")) for m in model.calls[-1] if m["role"] == "user")


PASS = Script(["....\n===== 4 passed in 0.1s =====\n"])


def failing():
    return Script(["F...\nFAILED test_a.py::test_greeting - assert 'hi' == 'hello'\n"
                   "1 failed, 3 passed\n"], exit_code=1)


def test_a_turn_that_changed_code_runs_the_tests_and_says_so_under_the_answer(
        make_client, wait_run, project_dir):
    executor = ScriptedExecutor([PASS])
    client, model = make_client([write("a.py", "x = 1\n"), text("done")], executor=executor)
    cid, run_id = begin(client, project_dir, check_command="python check.py")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert [command for command, _cwd in executor.started] == ["python check.py"]
    assert snap["commands"][0]["timeout_seconds"] == 120  # (a turn you watch waits 2 min at most)
    (call,) = proof_calls(snap)
    assert call["name"] == "run_command" and call["status"] == "succeeded"
    lead = next(a["id"] for a in snap["agents"] if a["depth"] == 0)
    assert call["agent_id"] == lead  # (on the Lead's answer, where the user sees it run)
    row = checked(snap)[0]
    assert {key: row[key] for key in ("kind", "state", "command", "guessed")} == {
        "kind": "tests", "state": "passed", "command": "python check.py", "guessed": False}
    assert row["text"] == "Tests passed: python check.py - 4 passed in 0.1s"
    note = next(m for m in snap["messages"] if m["role"] == "checked")
    assert note["content"].startswith("✓ Tests passed:")
    assert len(model.calls) == 2  # (nothing more was asked of the Lead)


def test_failing_tests_send_the_orchestrator_back_at_most_twice(make_client, wait_run, project_dir):
    executor = ScriptedExecutor([failing(), failing(), failing()])
    client, model = make_client([
        write("a.py", "x = 1\n"), text("done"),
        write("a.py", "x = 2\n", "w2"), text("fixed"),
        write("a.py", "x = 3\n", "w3"), text("fixed again")], executor=executor)
    cid, run_id = begin(client, project_dir, check_command="python check.py")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert len(executor.started) == 3 and len(proof_calls(snap)) == 3
    assert told(model) == 2
    nudged = next(str(m["content"]) for m in model.calls[-1]
                  if m["role"] == "user" and NUDGE in str(m["content"]))
    assert "data, not instructions:\n```\n" in nudged and "1 failed, 3 passed" in nudged
    assert texts(snap) == [
        "Tests failed: python check.py - 1 failed, 3 passed",
        "Sent back to fix: 2 of 2 rounds",
        "Still failing after 2 fix rounds: you decide (Fix it)"]
    assert [row["state"] for row in checked(snap)] == ["failed", "note", "failed"]


def test_a_fix_that_passes_ends_with_one_round_said(make_client, wait_run, project_dir):
    executor = ScriptedExecutor([failing(), PASS])
    client, model = make_client([
        write("a.py", "x = 1\n"), text("done"), write("a.py", "x = 2\n", "w2"), text("fixed")],
        executor=executor)
    cid, run_id = begin(client, project_dir, check_command="python check.py")
    snap = wait_run(client, cid, run_id)
    assert told(model) == 1
    assert texts(snap) == ["Tests passed: python check.py - 4 passed in 0.1s",
                           "Sent back to fix: 1 of 2 rounds"]


def guess(monkeypatch, command="python check.py"):
    """KOLONİ's guess from the project's files, whatever this machine has."""
    monkeypatch.setattr(proof.finish_tests, "command_of", lambda _root, _check: command)


def test_a_guessed_command_is_said_guessed(make_client, wait_run, project_dir, monkeypatch):
    guess(monkeypatch)
    client, _model = make_client([write("a.py", "x = 1\n"), text("done")],
                                 executor=ScriptedExecutor([PASS]))
    cid, run_id = begin(client, project_dir)
    row = checked(wait_run(client, cid, run_id))[0]
    assert row["guessed"] is True and row["state"] == "passed"
    assert row["text"] == "Tests passed: python check.py (guessed) - 4 passed in 0.1s"


def test_no_test_command_is_said_plainly(make_client, wait_run, project_dir):
    executor = ScriptedExecutor([])
    client, _model = make_client([write("a.py", "x = 1\n"), text("done")], executor=executor)
    cid, run_id = begin(client, project_dir)
    snap = wait_run(client, cid, run_id)
    assert executor.started == [] and proof_calls(snap) == []
    assert texts(snap) == [proof.NO_COMMAND] and checked(snap)[0]["state"] == "not_run"


def test_a_docs_only_turn_runs_no_tests(make_client, wait_run, project_dir):
    executor = ScriptedExecutor([])
    client, _model = make_client([write("README.md", "# hi\n"), text("done")], executor=executor)
    cid, run_id = begin(client, project_dir, check_command="python check.py")
    snap = wait_run(client, cid, run_id)
    assert executor.started == []
    assert texts(snap) == ["No tests: only documents, slides, diagrams or data changed"]


def test_nothing_runs_nothing_and_still_writes_checked(make_client, wait_run, project_dir):
    executor = ScriptedExecutor([PASS])  # (the Lead's own run, before its change)
    client, model = make_client([run("python -m pytest -q"), write("a.py", "x = 1\n"),
                                 text("done")], executor=executor)
    cid, run_id = begin(client, project_dir, check_command="python check.py",
                        after_change="nothing")
    snap = wait_run(client, cid, run_id)
    assert len(executor.started) == 1 and proof_calls(snap) == []
    assert texts(snap) == ["Not checked: After a change is set to Nothing",
                           "An agent ran python -m pytest -q before the last change: passed"]
    assert len(model.calls) == 3


def test_a_turn_that_changed_nothing_gets_no_checked(make_client, wait_run, project_dir):
    client, _model = make_client([text("nothing to change")], executor=ScriptedExecutor([]))
    cid, run_id = begin(client, project_dir, check_command="python check.py")
    assert checked(wait_run(client, cid, run_id)) is None


def test_a_guess_at_ask_waits_on_one_card_and_the_next_round_is_not_asked_again(
        make_client, wait_run, project_dir, monkeypatch):
    guess(monkeypatch)
    executor = ScriptedExecutor([failing(), PASS])
    client, _model = make_client([
        write("a.py", "x = 1\n"), text("done"), write("a.py", "x = 2\n", "w2"), text("fixed")],
        executor=executor)
    cid, run_id = begin(client, project_dir, mode="auto_edit")
    snap = wait_status(client, cid, "waiting_approval")
    (asked,) = [c for c in snap["commands"] if c["status"] == "proposed"]
    assert asked["command"] == "python check.py" and executor.started == []
    assert client.post(f"/api/commands/{asked['id']}/approve", json={"remember": False},
                       headers=OWN).status_code == 200
    snap = wait_run(client, cid, run_id)  # (no second card: it would wait here)
    assert len(executor.started) == 2
    assert texts(snap)[0] == "Tests passed: python check.py (guessed) - 4 passed in 0.1s"


def test_the_users_own_command_runs_unasked_in_a_watched_turn(make_client, wait_run, project_dir):
    executor = ScriptedExecutor([PASS])
    client, _model = make_client([write("a.py", "x = 1\n"), text("done")], executor=executor)
    cid, run_id = begin(client, project_dir, mode="auto_edit", check_command="python check.py")
    snap = wait_run(client, cid, run_id)
    assert len(executor.started) == 1 and checked(snap)[0]["state"] == "passed"


def test_a_fresh_pass_by_the_lead_is_not_run_again(make_client, wait_run, project_dir):
    executor = ScriptedExecutor([PASS])  # (the Lead's own run, after its change)
    client, _model = make_client([write("a.py", "x = 1\n"), run("python check.py"),
                                  text("done")], executor=executor)
    cid, run_id = begin(client, project_dir, check_command="python check.py")
    snap = wait_run(client, cid, run_id)
    assert len(executor.started) == 1 and proof_calls(snap) == []
    assert texts(snap) == [
        "Tests passed: python check.py - run by the Orchestrator after the last change"]


def test_a_pass_before_the_last_change_is_run_again(make_client, wait_run, project_dir):
    executor = ScriptedExecutor([PASS, PASS])
    client, _model = make_client([run("python check.py"), write("a.py", "x = 1\n"),
                                  text("done")], executor=executor)
    cid, run_id = begin(client, project_dir, check_command="python check.py")
    snap = wait_run(client, cid, run_id)
    assert len(executor.started) == 2 and len(proof_calls(snap)) == 1


def test_exit_0_with_a_failure_counted_is_failed(make_client, wait_run, project_dir):
    executor = ScriptedExecutor([Script(["1 failed, 3 passed\n"], exit_code=0)])
    client, model = make_client([write("a.py", "x = 1\n"), text("done"), text("I cannot fix it")],
                                executor=executor)
    cid, run_id = begin(client, project_dir, check_command="python check.py | tail -1")
    snap = wait_run(client, cid, run_id)
    assert told(model) == 1  # (its answer with no call ends the turn)
    assert checked(snap)[0]["state"] == "failed"


def test_no_tests_collected_is_not_a_pass(make_client, wait_run, project_dir):
    executor = ScriptedExecutor([Script(["no tests ran in 0.01s\n"], exit_code=5)])
    client, model = make_client([write("a.py", "x = 1\n"), text("done")], executor=executor)
    cid, run_id = begin(client, project_dir, check_command="python -m pytest -q")
    row = checked(wait_run(client, cid, run_id))[0]
    assert (row["state"], row["text"]) == (
        "not_run", "Tests ran none: python -m pytest -q collected no test")
    assert len(model.calls) == 2


def test_a_command_that_could_not_start_sends_nothing_back(make_client, wait_run, project_dir):
    executor = ScriptedExecutor([Script(start_error="Docker is not running")])
    client, model = make_client([write("a.py", "x = 1\n"), text("done")], executor=executor)
    cid, run_id = begin(client, project_dir, check_command="python check.py")
    row = checked(wait_run(client, cid, run_id))[0]
    assert (row["state"], row["text"]) == ("not_run", "Tests could not start: Docker is not running")
    assert len(model.calls) == 2


def test_a_test_that_never_ends_is_timed_out_and_the_turn_ends(
        make_client, wait_run, project_dir, monkeypatch, gate):
    # (A turn the user watches waits END_WAIT_SECONDS for them - 120 s; 1 s here.)
    monkeypatch.setattr(proof_mixin, "END_WAIT_SECONDS", 1)
    executor = ScriptedExecutor([Script(["running\n"], hold=gate)])
    client, model = make_client([write("a.py", "x = 1\n"), text("done"),
                                 write("a.py", "x = 2\n", "w2"), text("again")],
                                executor=executor)
    cid, run_id = begin(client, project_dir, check_command="python check.py")
    snap = wait_run(client, cid, run_id)
    row = checked(snap)[0]
    assert row["state"] == "timed_out" and row["text"].startswith(
        "Tests not waited for: still running at 0:01"), row
    assert len(executor.killed) == 1 and len(model.calls) == 2  # (stopped; nothing sent back)
    # The next turn it is not run again while you watch: it ran past the wait last time.
    again = client.post(f"/api/conversations/{cid}/messages", json={"content": "more"}).json()
    snap = wait_run(client, cid, again["run"]["id"])
    assert len(executor.started) == 1
    (row,) = [m["checked"] for m in snap["messages"]
              if m["role"] == "checked" and m["run_id"] == again["run"]["id"]][0]
    assert row["state"] == "not_run" and "ran past 0:01" in row["text"], row


def test_stop_during_the_final_run_ends_the_turn(make_client, wait_run, project_dir, gate):
    client, _model = make_client([write("a.py", "x = 1\n"), text("done")],
                                 executor=ScriptedExecutor([Script(["running\n"], hold=gate)]))
    cid, run_id = begin(client, project_dir, check_command="python check.py")
    deadline = time.monotonic() + scaled(10)
    while not [c for c in client.get(f"/api/conversations/{cid}").json()["commands"]
               if c["status"] == "running"]:
        assert time.monotonic() < deadline, "the tests never started"
        time.sleep(0.02)
    client.post(f"/api/runs/{run_id}/cancel")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "cancelled"
    assert texts(snap) == ["Tests not finished: stopped"]


def test_two_turns_ending_at_once_run_their_tests_one_after_the_other(
        make_client, wait_run, tmp_path, gate):
    executor = ScriptedExecutor([Script(["4 passed\n"], hold=gate), Script(["4 passed\n"])])
    client, model = make_client([write("a.py", "x = 1\n"), text("done"),
                                 write("a.py", "x = 1\n", "w2"), text("done")], executor=executor)
    first, second = tmp_path / "one", tmp_path / "two"
    first.mkdir()
    second.mkdir()
    cid1, run1 = begin(client, first, check_command="python check.py")
    deadline = time.monotonic() + scaled(10)
    while len(executor.started) < 1:
        assert time.monotonic() < deadline, "the first tests never started"
        time.sleep(0.02)
    cid2, run2 = begin(client, second, check_command="python check.py")
    while len(model.calls) < 4:  # (the second Lead has answered: its tests wait for the first's)
        assert time.monotonic() < deadline, "the second turn never answered"
        time.sleep(0.02)
    time.sleep(0.2)
    assert len(executor.started) == 1
    gate.release()
    one, two = wait_run(client, cid1, run1), wait_run(client, cid2, run2)
    (ran1,), (ran2,) = one["commands"], two["commands"]
    assert ran2["started_at"] >= ran1["ended_at"]


def test_proof_calls_stay_out_of_the_leads_history_and_its_thinking_is_kept(
        make_client, wait_run, project_dir):
    thought = {"content": [{"type": "thinking", "thinking": "check it", "signature": "sig"},
                           {"type": "text", "text": "done"}], "after": "before it"}
    answer = StepResult("done", [], 1, 1, blocks=thought)
    client, model = make_client([write("a.py", "x = 1\n"), answer,
                                 write("a.py", "x = 2\n", "w2"), text("fixed")],
                                executor=ScriptedExecutor([failing(), PASS]))
    model.replays_blocks = True  # (as Anthropic's client: its answers go back as they came)
    cid, run_id = begin(client, project_dir, check_command="python check.py")
    wait_run(client, cid, run_id)
    sent = model.calls[2]  # (the step after the nudge)
    assert PROOF_CALL not in json.dumps(sent, default=str)
    (replayed,) = [m for m in sent if m["role"] == "assistant" and m.get("blocks")]
    assert "tool_calls" not in replayed or not replayed["tool_calls"]
    _system, messages = to_anthropic(sent)
    said = next(m for m in messages if m["role"] == "assistant" and m["content"][0].get(
        "type") == "thinking")
    assert said["content"][0]["signature"] == "sig"


def test_the_next_turn_reads_the_last_tests_from_the_record(make_client, wait_run, project_dir):
    client, model = make_client([write("a.py", "x = 1\n"), text("done"), text("ok")],
                                executor=ScriptedExecutor([PASS]))
    cid, run_id = begin(client, project_dir, check_command="python -m pytest -q")
    wait_run(client, cid, run_id)
    again = client.post(f"/api/conversations/{cid}/messages", json={"content": "and?"}).json()
    wait_run(client, cid, again["run"]["id"])
    assert any('- last tests: "python -m pytest -q" exit 0, "4 passed in 0.1s"' in str(
        m.get("content")) for m in model.calls[-1])


def test_a_part_runs_in_its_own_folder(make_client, wait_run, project_dir):
    (project_dir / "web").mkdir()
    (project_dir / "web" / "package.json").write_text('{"name": "web"}', encoding="utf-8")
    executor = ScriptedExecutor([PASS])
    client, _model = make_client([write("web/a.js", "x = 1\n"), text("done")], executor=executor)
    cid, run_id = begin(client, project_dir, parts={"web/": "npm test"})
    snap = wait_run(client, cid, run_id)
    (ran,) = snap["commands"]
    assert (ran["command"], ran["cwd"]) == ("npm test", "web")
    assert checked(snap)[0]["text"] == "Tests passed: npm test - 4 passed in 0.1s"


@pytest.mark.parametrize("after", ["check", "tests"])
def test_tests_only_and_check_it_both_run_the_tests(make_client, wait_run, project_dir, after):
    executor = ScriptedExecutor([PASS])
    client, _model = make_client([write("a.py", "x = 1\n"), text("done")], executor=executor)
    cid, run_id = begin(client, project_dir, check_command="python check.py", after_change=after)
    assert checked(wait_run(client, cid, run_id))[0]["state"] == "passed"


def test_claude_code_lead_is_checked_once_by_the_end_gate(claude_app, wait_run, project_dir):  # noqa: F811
    # (89m's Stop hook is gone: KOLONİ runs the tests once, at the Lead's end, for every CLI.)
    (project_dir / "check.py").write_text("print('3 passed')\n", encoding="utf-8")
    client, provider, _ = claude_app([{
        "tool": "Write", "input": {"file_path": "PROJECT/a.py", "content": "x"},
        "write": ["a.py", "x"], "result": "ok"}, {"say": "done"}])
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    client.patch(f"/api/projects/{pid}", json={"check_command": "python check.py"}, headers=OWN)
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(f"/api/conversations/{cid}", json={
        "permission_mode": "full_auto", "provider_id": provider["id"], "lead_hands_code": False},
        headers=OWN)
    run_id = client.post(f"/api/conversations/{cid}/messages",
                         json={"content": "fix the greeting"}).json()["run"]["id"]
    snap = wait_run(client, cid, run_id, timeout=30)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert "Stop" not in claude_app.record()["init"]["request"]["hooks"]
    (call,) = proof_calls(snap)
    assert call["status"] == "succeeded"
    assert texts(snap) == ["Tests passed: python check.py - 3 passed"]


def test_a_trigger_turn_runs_only_what_its_trigger_allows(make_client, wait_run, project_dir):
    from tests.test_triggers import allow, leave, run_now, setup, trigger

    executor = ScriptedExecutor([PASS])
    client, _model, pid, cid = setup(make_client, project_dir, [
        write("a.py", "x = 1\n"), text("done"), write("a.py", "x = 2\n", "w2"), text("done")],
        executor=executor)
    client.patch(f"/api/projects/{pid}", json={"check_command": "python check.py",
                                               "lead_work": "itself"})
    made = trigger(client, pid, cid, permissions=leave(write=True))
    first = run_now(client, made["id"])
    snap = wait_run(client, cid, first)
    (row,) = [m["checked"] for m in snap["messages"] if m["role"] == "checked"][0]
    assert row["state"] == "not_run" and row["text"].startswith("Tests not run: ")
    assert "python check.py" in row["text"] and executor.started == []
    # Its trigger's leave for this very command: it runs, unasked.
    assert client.patch(f"/api/triggers/{made['id']}", json={"permissions": leave(
        write=True, commands=[allow(client, cid, "python check.py")])}).status_code == 200
    second = run_now(client, made["id"])
    snap = wait_run(client, cid, second)
    rows = [m["checked"] for m in snap["messages"]
            if m["role"] == "checked" and m["run_id"] == second][0]
    assert rows[0]["state"] == "passed" and len(executor.started) == 1


ONE_JOB = {"jobs": [{"title": "one"}], "kept_out": []}


def away_job(make_client, project_dir, mode, **project):
    """An Away night of one job whose Lead edits hello.py; the job's chat id, once looked at."""
    from tests.test_agent_writes import edit
    from tests.test_away_scenarios import evening, go_away, looked_at, night
    from tests.test_backlog_auto import until

    (project_dir / "check.py").write_text("print('3 passed')\n", encoding="utf-8")
    client, _model, pid, cid, run_id = evening(
        make_client, project_dir, [edit(), text("one done"), text("good morning")], mode=mode,
        plan=ONE_JOB, lead_work="itself", **project)
    until(lambda: client.get(f"/api/conversations/{cid}").json()["runs"][0]["status"]
          == "completed")
    assert go_away(client, cid).status_code in (200, 201)
    found = until(lambda: (n := night(client, pid)) and looked_at(n) and n, seconds=30)
    return client, pid, found["jobs"][0]


def job_rows(client, job):
    snap = client.get(f"/api/conversations/{job['conversation_id']}").json()
    return snap, [m["checked"] for m in snap["messages"] if m["role"] == "checked"]


def test_an_away_job_checks_its_own_copy(make_client, project_dir):
    client, _pid, job = away_job(make_client, project_dir, "full_auto",
                                 check_command="python check.py")
    snap, (rows,) = job_rows(client, job)
    assert job["state"] == "done" and rows[0]["state"] == "passed", (job, rows)
    (ran,) = [c for c in snap["commands"] if c["command"] == "python check.py"]
    assert ran["exit_code"] == 0
    # (in the job's copy: the project is as it was)
    assert (project_dir / "hello.py").read_bytes() == b"print('hi')\n"


def test_an_away_job_at_full_auto_runs_a_guess_unasked(make_client, project_dir, monkeypatch):
    guess(monkeypatch)
    client, _pid, job = away_job(make_client, project_dir, "full_auto")
    _snap, (rows,) = job_rows(client, job)
    assert rows[0]["guessed"] is True and rows[0]["state"] == "passed", rows


def test_an_away_job_at_ask_leaves_the_card_to_when_away(make_client, project_dir, monkeypatch):
    from tests.test_away_scenarios import night
    from tests.test_backlog_auto import until

    guess(monkeypatch)
    client, pid, job = away_job(make_client, project_dir, "ask")
    # (as the Lead's own command would: a command still waits for the user while they are away)
    assert job["state"] == "waits", job
    ((ask,),) = [job["asks"]]
    assert ask["kind"] == "commands" and "python check.py" in json.dumps(job), job
    assert client.post(f"/api/commands/{ask['id']}/approve", json={"remember": False}
                       ).status_code == 200
    until(lambda: night(client, pid)["jobs"][0]["state"] == "done")
    _snap, (rows,) = job_rows(client, job)
    assert rows[0]["state"] == "passed" and rows[0]["guessed"] is True, rows


def test_a_turn_that_fails_before_its_end_says_the_tests_were_not_run(
        make_client, wait_run, project_dir):
    executor = ScriptedExecutor([])
    client, _model = make_client([write("a.py", "x = 1\n"), RuntimeError("its model broke")],
                                 executor=executor)
    cid, run_id = begin(client, project_dir, check_command="python check.py")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "failed" and executor.started == []
    assert texts(snap) == ["Tests not run: the turn failed before its end"]


def test_a_to_do_task_waits_for_its_tests_to_the_commands_limit(make_client, wait_run, project_dir):
    # (Nobody waits on a To-do task's answer: its tests are not cut at a watched turn's 2 minutes.)
    client, _model = make_client([write("a.py", "x = 1\n"), text("done")],
                                 executor=ScriptedExecutor([PASS]))
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    assert client.patch(f"/api/projects/{pid}", json={
        "check_command": "python check.py", "lead_work": "itself"}, headers=OWN).status_code == 200
    assert client.put(f"/api/projects/{pid}/backlog/choice", json={"permission_mode": "full_auto"},
                      headers=OWN).status_code == 200
    client.post(f"/api/projects/{pid}/backlog", json={"title": "greeting"}, headers=OWN)
    cid = client.post(f"/api/projects/{pid}/backlog/next", headers=OWN).json()["conversation_id"]
    run_id = client.get(f"/api/conversations/{cid}").json()["runs"][0]["id"]
    snap = wait_run(client, cid, run_id)
    (ran,) = snap["commands"]
    assert ran["timeout_seconds"] == 600 and checked(snap)[0]["state"] == "passed", snap["commands"]


def test_a_requirements_change_runs_the_tests(make_client, wait_run, project_dir):
    # (A .txt, but a dependency list: config, which the tests read - not a document.)
    executor = ScriptedExecutor([PASS])
    client, _model = make_client([write("requirements.txt", "requests==2.32.3\n"), text("done")],
                                 executor=executor)
    cid, run_id = begin(client, project_dir, check_command="python check.py")
    assert checked(wait_run(client, cid, run_id))[0]["state"] == "passed"
    assert len(executor.started) == 1
