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
_OUT = re.compile(r"--cov-report=json:\"?([^\"\s]+)\"?")


class Measuring(ScriptedExecutor):
    """As pytest-cov would: the report written where the run's flags say, its lines as given."""

    def __init__(self, scripts, ran: dict[str, tuple[list[int], list[int]]]):
        super().__init__(scripts)
        self.ran = ran

    async def start(self, command_id, command, cwd, *args, **kwargs):
        if found := _OUT.search(command):
            out = Path(cwd) / found.group(1)  # (from the folder it runs in, as pytest-cov reads it)
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
