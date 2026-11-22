"""Kanıtlı bitiş S9: where the project already measures coverage, the end check's whole suite gets
report flags only - its row keeps its own command - and the share of the changed lines run is said;
flags its runner does not know are dropped and it runs again; one gone on after the answer is read
as it ends. A fake model, and an executor that writes the report where the flags say."""

import json
import re
from pathlib import Path

import pytest

from app.agent import coverage_mixin
from tests.fakes import Script, ScriptedExecutor
from tests.test_agent_writes import write
from tests.test_chat_flow import text
from tests.test_proof_end_scenarios import PASS, begin, checked, texts

pytestmark = pytest.mark.no_po

PYTEST = "python -m pytest -q"
_OUT = re.compile(r"--cov-report=json:(?:\"([^\"]+)\"|'([^']+)'|(\S+))")


class Measuring(ScriptedExecutor):
    """As pytest-cov would: the report written where the run's flags say, its lines as given."""

    def __init__(self, scripts, ran: dict[str, tuple[list[int], list[int]]]):
        super().__init__(scripts)
        self.ran = ran

    async def start(self, command_id, command, cwd, *args, **kwargs):
        if found := _OUT.search(command):
            # (from the folder it runs in, as pytest-cov reads it)
            out = Path(cwd) / next(one for one in found.groups() if one)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps({"files": {path: {
                "executed_lines": yes, "missing_lines": no}
                for path, (yes, no) in self.ran.items()}}), encoding="utf-8")
        return await super().start(command_id, command, cwd, *args, **kwargs)


def with_cov(project_dir):
    (project_dir / "pyproject.toml").write_text(
        '[project.optional-dependencies]\ndev = ["pytest", "pytest-cov"]\n', encoding="utf-8")


THREE = "x = 1\ny = 2\nz = 3\n"


def test_the_whole_suite_says_the_share_of_the_changed_lines_run(make_client, wait_run,
                                                                 project_dir):
    with_cov(project_dir)
    executor = Measuring([PASS], {"a.py": ([1, 2], [3])})
    client, _model = make_client([write("a.py", THREE), text("done")], executor=executor)
    cid, run_id = begin(client, project_dir, check_command=PYTEST)
    rows = texts(wait_run(client, cid, run_id))
    (line, _cwd), = executor.started
    assert line.startswith(f"{PYTEST} --cov=. --cov-report=json:") and ".koloni" in line
    assert rows == [f"Tests passed: {PYTEST} - 4 passed in 0.1s",  # (its own name, no flags)
                    coverage_mixin.MEASURED.format(p=67, tool="pytest-cov")], rows
    assert not list((project_dir / ".koloni" / "tmp").glob("coverage-*"))  # (read, then gone)


def test_no_tool_no_row_and_no_flags(make_client, wait_run, project_dir):
    executor = ScriptedExecutor([PASS])
    client, _model = make_client([write("a.py", THREE), text("done")], executor=executor)
    cid, run_id = begin(client, project_dir, check_command=PYTEST)
    rows = texts(wait_run(client, cid, run_id))
    assert executor.started[0][0] == PYTEST
    assert not any(one.startswith("Coverage") for one in rows), rows


def test_flags_the_runner_does_not_know_run_it_again_without(make_client, wait_run, project_dir):
    with_cov(project_dir)
    unknown = Script(["ERROR: usage: pytest [options]\npytest: error: unrecognized arguments: "
                      "--cov=.\n"], exit_code=4)
    executor = ScriptedExecutor([unknown, PASS])
    client, _model = make_client([write("a.py", THREE), text("done")], executor=executor)
    cid, run_id = begin(client, project_dir, check_command=PYTEST)
    rows = texts(wait_run(client, cid, run_id))
    assert executor.started[1][0] == PYTEST
    assert rows == [f"Tests passed: {PYTEST} - 4 passed in 0.1s", coverage_mixin.NOT_MEASURED.format(
        why=coverage_mixin.FLAGS_FAILED)], rows


def test_a_suite_gone_on_after_the_answer_is_measured_as_it_ends(make_client, wait_run,
                                                                 project_dir, gate, monkeypatch):
    from app.agent import proof_later_mixin
    from tests.test_proof_background_scenarios import held, rows_of, until
    monkeypatch.setattr(proof_later_mixin, "DETACH_SECONDS", 0.2)
    with_cov(project_dir)
    executor = Measuring([held(gate, "4 passed in 9s\n")], {"a.py": ([1, 2, 3], [])})
    client, _model = make_client([write("a.py", THREE), text("done")], executor=executor)
    cid, run_id = begin(client, project_dir, check_command=PYTEST)
    wait_run(client, cid, run_id)
    until(lambda: rows_of(client, cid, run_id)[0]["started_at"])
    gate.release()
    rows = until(lambda: (r := rows_of(client, cid, run_id)) and r[0]["state"] != "running" and r)
    assert [r["text"] for r in rows] == [f"Tests passed: {PYTEST} - 4 passed in 9s",
                                         coverage_mixin.MEASURED.format(p=100, tool="pytest-cov")]


def test_the_rows_command_is_the_run_without_its_flags(make_client, wait_run, project_dir):
    # (S1's reuse and S7's green state know the run by it: never by its flags)
    with_cov(project_dir)
    executor = Measuring([PASS], {"a.py": ([1, 2, 3], [])})
    client, _model = make_client([write("a.py", THREE), text("done")], executor=executor)
    cid, run_id = begin(client, project_dir, check_command=PYTEST)
    (row, cover) = checked(wait_run(client, cid, run_id))
    assert (row["command"], cover["command"], cover["kind"]) == (PYTEST, PYTEST, "coverage")


def test_a_flagged_run_stands_for_its_command_when_nothing_changed_since(make_client, wait_run,
                                                                        project_dir):
    # (S1's reuse knows KOLONİ's run with coverage flags as the command itself: not run again)
    from app import proof
    from tests.test_proof_end_scenarios import failing
    with_cov(project_dir)
    executor = Measuring([failing()], {"a.py": ([1, 2, 3], [])})
    client, _model = make_client([write("a.py", THREE), text("done"), text("left as it is")],
                                 executor=executor)
    cid, run_id = begin(client, project_dir, check_command=PYTEST, fix_rounds=1)
    rows = texts(wait_run(client, cid, run_id))
    assert len(executor.started) == 1 and proof.STILL_FAILING.format(most=1) in rows, rows
    assert coverage_mixin.MEASURED.format(p=100, tool="pytest-cov") in rows, rows  # (said again)


def test_your_own_command_keeps_its_leave_with_the_flags(make_client, wait_run, project_dir):
    # (Auto-edit: your test command runs unasked - with coverage's report flags too, no card)
    with_cov(project_dir)
    executor = Measuring([PASS], {"a.py": ([1, 2, 3], [])})
    client, _model = make_client([write("a.py", THREE), text("done")], executor=executor)
    cid, run_id = begin(client, project_dir, mode="auto_edit", check_command=PYTEST)
    rows = texts(wait_run(client, cid, run_id))
    assert rows[1] == coverage_mixin.MEASURED.format(p=100, tool="pytest-cov"), rows


def test_a_threshold_the_flags_turned_on_runs_it_again_without(make_client, wait_run, project_dir):
    with_cov(project_dir)
    below = Script(["....\n4 passed\nFAIL Required test coverage of 90% not reached. "
                    "Total coverage: 67.00%\n"], exit_code=1)
    executor = ScriptedExecutor([below, PASS])
    client, _model = make_client([write("a.py", THREE), text("done")], executor=executor)
    cid, run_id = begin(client, project_dir, check_command=PYTEST)
    rows = texts(wait_run(client, cid, run_id))
    assert [one for one, _cwd in executor.started][1:] == [PYTEST]
    assert rows == [f"Tests passed: {PYTEST} - 4 passed in 0.1s", coverage_mixin.NOT_MEASURED.format(
        why=coverage_mixin.FLAGS_FAILED)], rows


def test_a_part_is_measured_from_its_own_folder(make_client, wait_run, project_dir):
    # (coverage.py names a part's files from the part's folder: the project's paths are matched)
    web = project_dir / "web"
    web.mkdir()
    with_cov(web)
    executor = Measuring([PASS], {"a.py": ([1, 2], [3])})
    client, _model = make_client([write("web/a.py", THREE), text("done")], executor=executor)
    cid, run_id = begin(client, project_dir, parts={"web/": PYTEST})
    rows = texts(wait_run(client, cid, run_id))
    (line, _cwd), = executor.started
    assert "/.koloni/tmp/coverage-" in line and "../" not in line, line  # (never ../.koloni)
    assert coverage_mixin.MEASURED.format(p=67, tool="pytest-cov") in rows, rows



def test_a_parts_run_under_a_folder_with_a_space_and_parentheses_is_known_by_its_command(
        make_client, wait_run, tmp_path):
    # (S9 re-check: the part's report path is whole and quoted - "My Project (copy)" - and the run
    # is still known by its command, from what KOLONİ built it from, never read back from it)
    from sqlalchemy import select

    from app import proof
    from app.db.models import Command
    project_dir = tmp_path / "My Project (copy)"
    web = project_dir / "web"
    web.mkdir(parents=True)
    with_cov(web)
    executor = Measuring([PASS], {"a.py": ([1, 2], [3])})
    client, _model = make_client([write("web/a.py", THREE), text("done")], executor=executor)
    cid, run_id = begin(client, project_dir, parts={"web/": PYTEST})
    rows = texts(wait_run(client, cid, run_id))
    (line, _cwd), = executor.started
    assert "My Project (copy)" in line and "/.koloni/tmp/coverage-" in line, line
    assert coverage_mixin.MEASURED.format(p=67, tool="pytest-cov") in rows, rows
    with client.app.state.session_factory() as session:
        (ran,) = session.scalars(select(Command).where(Command.run_id == run_id)).all()
        assert ran.command == line and proof._known_as(session, ran) == PYTEST


def test_flags_that_failed_are_not_tried_each_turn_till_the_settings_change(make_client, wait_run,
                                                                            project_dir):
    # (S9 review: a threshold the flags turned on ran the whole suite twice every turn)
    with_cov(project_dir)
    below = Script(["....\n4 passed\nFAIL Required test coverage of 90% not reached. "
                    "Total coverage: 67.00%\n"], exit_code=1)
    executor = ScriptedExecutor([below, PASS, PASS, PASS, PASS])
    client, _model = make_client([write("a.py", THREE), text("done"),
                                  write("a.py", "x = 2\n", "w2"), text("done"),
                                  write("a.py", "x = 3\n", "w3"), text("done")], executor=executor)
    cid, run_id = begin(client, project_dir, check_command=PYTEST)
    wait_run(client, cid, run_id)
    assert [one for one, _cwd in executor.started][1:] == [PYTEST]  # (once again, without)

    def turn():
        from tests.test_proof_background_scenarios import rows_of
        posted = client.post(f"/api/conversations/{cid}/messages", json={"content": "more"})
        made = posted.json()["run"]["id"]
        wait_run(client, cid, made)
        return [one["text"] for one in rows_of(client, cid, made)]
    rows = turn()
    assert [one for one, _cwd in executor.started][2:] == [PYTEST], executor.started
    assert coverage_mixin.NOT_MEASURED.format(why=coverage_mixin.FAILED_BEFORE) in rows, rows
    with_cov(project_dir)  # (the same settings: still not tried)
    (project_dir / ".coveragerc").write_text("[report]\nfail_under = 0\n", encoding="utf-8")
    turn()
    assert "--cov" in executor.started[3][0], executor.started  # (they changed: tried again)
