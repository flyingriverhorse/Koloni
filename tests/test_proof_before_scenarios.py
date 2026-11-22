"""Kanıtlı bitiş S7 (plan decisions 14b, 19): a failing test that passes alone once is flaky (noted
in the project's memory, not sent back); one that fails on the code as it was before the turn too
was failing before (said, not sent back); a whole suite that passed is held to the project's last
green state; a bug fix's new test must fail on the old code. A fake model and a scripted executor."""

import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app import copies, proof_before
from app.agent import before_mixin
from app.db.models import Memory
from tests.fakes import Script, ScriptedExecutor
from tests.test_agent_writes import write
from tests.test_chat_flow import text
from tests.test_proof_end_scenarios import PASS, begin, checked, run, texts

pytestmark = pytest.mark.no_po

PYTEST = "python -m pytest -q"
ONE = "tests/test_a.py::test_x"
TWO = "tests/test_b.py::test_y"


def failing(*ids):
    lines = "".join(f"FAILED {one} - assert 1 == 2\n" for one in ids)
    return Script([f"{lines}=== {len(ids)} failed, 3 passed in 0.1s ===\n"], exit_code=1)


def passing(n=4, skipped=0):
    return Script([f"{n} passed" + (f", {skipped} skipped" if skipped else "") + " in 0.1s\n"])


def rows_of(snap, run_id):
    return [r["text"] for m in snap["messages"] if m["role"] == "checked" and m["run_id"] == run_id
            for r in m["checked"]]


def lines(executor):
    return [command for command, _cwd in executor.started]


def told(model, at):
    return json.dumps(model.calls[at], ensure_ascii=False)


def throwaways(client) -> list[Path]:
    where = copies.folder(client.app.state.runner.settings.runtime_root)
    return [one for one in where.iterdir() if one.name.startswith("before-")] if where and (
        where.exists()) else []


def notes(client, test):
    with client.app.state.session_factory() as session:
        return session.scalars(select(Memory.text).where(
            Memory.about == f"flaky test: {test}", Memory.status == "active")).all()


def test_a_test_that_passes_alone_is_flaky_noted_and_not_sent_back(make_client, wait_run,
                                                                     project_dir):
    executor = ScriptedExecutor([failing(ONE), passing(1)])
    client, model = make_client([write("a.py", "x = 1\n"), text("done")], executor=executor)
    cid, run_id = begin(client, project_dir, check_command=PYTEST)
    rows = texts(wait_run(client, cid, run_id))
    assert lines(executor) == [PYTEST, proof_before.alone(PYTEST, [ONE])]
    assert before_mixin.FLAKY.format(id=ONE) in rows, rows
    assert len(model.calls) == 2  # (nothing sent back)
    (said,) = notes(client, ONE)
    assert said.endswith("seen 1 times"), said


def test_a_flaky_note_counts_its_times(make_client, wait_run, project_dir):
    executor = ScriptedExecutor([failing(ONE), passing(1), failing(ONE), passing(1)])
    client, _model = make_client([write("a.py", "x = 1\n"), text("done"),
                                  write("a.py", "x = 2\n", "w2"), text("again")], executor=executor)
    cid, run_id = begin(client, project_dir, check_command=PYTEST)
    wait_run(client, cid, run_id)
    posted = client.post(f"/api/conversations/{cid}/messages", json={"content": "more"}).json()
    wait_run(client, cid, posted["run"]["id"])
    (said,) = notes(client, ONE)
    assert said.endswith("seen 2 times"), said


def test_failures_already_there_before_send_nothing_back(make_client, wait_run, project_dir):
    (project_dir / ".venv").mkdir()
    (project_dir / ".venv" / "kept.txt").write_text("the project's own\n", encoding="utf-8")
    executor = ScriptedExecutor([failing(ONE), failing(ONE), failing(ONE)])
    client, model = make_client([write("a.py", "x = 1\n"), text("done")], executor=executor)
    cid, run_id = begin(client, project_dir, check_command=PYTEST)
    rows = texts(wait_run(client, cid, run_id))
    assert before_mixin.BEFORE.format(n=1, m=0) in rows, rows
    assert len(model.calls) == 2  # (nothing sent back: not this turn's)
    # (The old code's run was in a throwaway copy - gone after; the project and its linked
    # .venv untouched.)
    assert executor.started[2][1] != str(project_dir)
    assert throwaways(client) == []
    assert (project_dir / ".venv" / "kept.txt").read_text(encoding="utf-8") == "the project's own\n"
    assert (project_dir / "a.py").read_text(encoding="utf-8") == "x = 1\n"


def test_a_new_failure_beside_an_old_one_names_only_the_new(make_client, wait_run, project_dir):
    executor = ScriptedExecutor([failing(ONE, TWO), failing(ONE, TWO), failing(ONE), passing()])
    client, model = make_client([write("a.py", "x = 1\n"), text("done"),
                                 write("a.py", "x = 2\n", "w2"), text("fixed")], executor=executor)
    cid, run_id = begin(client, project_dir, check_command=PYTEST)
    rows = texts(wait_run(client, cid, run_id))
    assert before_mixin.BEFORE.format(n=1, m=1) in rows, rows
    nudge = told(model, 2)
    assert before_mixin.NOT_YOURS.format(ids=ONE).strip() in nudge


def test_last_turns_failures_fixed_now_are_said(make_client, wait_run, project_dir):
    executor = ScriptedExecutor([failing(ONE), failing(ONE), failing(ONE), passing()])
    client, _model = make_client([write("a.py", "x = 1\n"), text("done"),
                                  write("a.py", "x = 2\n", "w2"), text("fixed")], executor=executor)
    cid, run_id = begin(client, project_dir, check_command=PYTEST)
    wait_run(client, cid, run_id)
    posted = client.post(f"/api/conversations/{cid}/messages", json={"content": "fix it"}).json()
    rows = rows_of(wait_run(client, cid, posted["run"]["id"]), posted["run"]["id"])
    assert any(one.startswith("1 were failing at the last run (") for one in rows), rows


@pytest.mark.parametrize(("old", "said", "state"), [
    (failing("tests/test_bug.py::test_calc"), before_mixin.CAUGHT, "passed"),
    (passing(1), before_mixin.NOT_CAUGHT, "failed")])
def test_a_bugfix_test_on_the_old_code(make_client, wait_run, project_dir, old, said, state):
    # (its related tests first, S6: the new test's file - then the whole suite, then the old code)
    executor = ScriptedExecutor([passing(1), passing(), old])
    client, _model = make_client([write("calc.py", "x = 1\n"),
                                  write("tests/test_bug.py", "def test_calc(): pass\n", "w2"),
                                  text("fixed")], executor=executor)
    cid, run_id = begin(client, project_dir, check_command=PYTEST, content="fix the crash in calc")
    rows = checked(wait_run(client, cid, run_id))
    assert (said, state) in [(r["text"], r["state"]) for r in rows], rows
    assert executor.started[2][0] == proof_before.alone(PYTEST, ["tests/test_bug.py"])
    assert executor.started[2][1] != str(project_dir) and throwaways(client) == []


def test_a_command_that_changed_the_project_means_no_before_run(make_client, wait_run,
                                                                 project_dir):
    executor = ScriptedExecutor([PASS, failing(ONE), failing(ONE), passing()])
    client, _model = make_client([write("a.py", "x = 1\n"), run("python gen.py"), text("done"),
                                  write("a.py", "x = 2\n", "w2"), text("fixed")], executor=executor)
    cid, run_id = begin(client, project_dir, check_command=PYTEST)
    rows = texts(wait_run(client, cid, run_id))
    assert before_mixin.NO_BEFORE.format(why=before_mixin.CHANGED_BY_COMMAND) in rows, rows
    assert len(executor.started) == 4  # (the agent's, the suite, alone, the suite again: no old)


def test_the_last_green_state_holds_a_drop_in_tests_and_a_rise_in_skipped(make_client, wait_run,
                                                                          project_dir):
    executor = ScriptedExecutor([passing(4), passing(3, skipped=2)])
    client, model = make_client([write("a.py", "x = 1\n"), text("done"),
                                 write("a.py", "x = 2\n", "w2"), text("done"),
                                 text("I left it so")], executor=executor)
    cid, run_id = begin(client, project_dir, check_command=PYTEST)
    wait_run(client, cid, run_id)
    posted = client.post(f"/api/conversations/{cid}/messages", json={"content": "more"}).json()
    rows = rows_of(wait_run(client, cid, posted["run"]["id"]), posted["run"]["id"])
    assert "Tests went from 4 to 3 (1 removed)" in rows and "Skipped rose from 0 to 2" in rows
    assert "Tests went from 4 to 3 (1 removed)" in told(model, 4)


def test_a_drop_the_answer_says_why_is_the_new_green_state(make_client, wait_run, project_dir):
    executor = ScriptedExecutor([passing(4), passing(3)])
    client, _model = make_client([write("a.py", "x = 1\n"), text("done"),
                                  write("a.py", "x = 2\n", "w2"),
                                  text("I removed the obsolete test of the old parser")],
                                 executor=executor)
    cid, run_id = begin(client, project_dir, check_command=PYTEST)
    wait_run(client, cid, run_id)
    posted = client.post(f"/api/conversations/{cid}/messages", json={"content": "more"}).json()
    rows = rows_of(wait_run(client, cid, posted["run"]["id"]), posted["run"]["id"])
    assert not any(one.startswith("Tests went from") for one in rows), rows
    with client.app.state.session_factory() as session:
        from app.db.models import Project
        (green,) = session.scalars(select(Project.tests_green)).all()
    assert next(iter(green.values()))["ran"] == 3


def test_a_test_that_passed_at_the_last_green_run_and_fails_now_is_a_regression(
        make_client, wait_run, project_dir):
    executor = ScriptedExecutor([passing(4), failing(ONE), failing(ONE), passing(4), passing(4)])
    client, model = make_client([write("a.py", "x = 1\n"), text("done"),
                                 write("a.py", "x = 2\n", "w2"), text("done"),
                                 write("a.py", "x = 3\n", "w3"), text("fixed")], executor=executor)
    cid, run_id = begin(client, project_dir, check_command=PYTEST)
    wait_run(client, cid, run_id)
    posted = client.post(f"/api/conversations/{cid}/messages", json={"content": "more"}).json()
    snap = wait_run(client, cid, posted["run"]["id"])
    second = [r["text"] for m in snap["messages"] if m["role"] == "checked"
              and m["run_id"] == posted["run"]["id"] for r in m["checked"]]
    assert before_mixin.REGRESSION.format(id=ONE) in second or "Tests passed" in " ".join(second)
    assert "FAILED" in told(model, 4)  # (sent back: new on the old code, so this turn's)
