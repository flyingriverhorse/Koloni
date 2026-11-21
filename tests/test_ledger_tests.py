"""What counts as a test run that failed, before a recipe's fix step (`ledger.failed_tests`):
the test tool is the command's first real word - after `cd <dir> &&`, `VAR=val`, `time` or a
runner - never a command that only names it; a lint script is none, and pytest's exit 5 (no
tests collected) no failure. Each test command's last run counts, not only the last of all."""

import pytest

from app import ledger
from app.db.models import Agent, Command, Conversation, Project, Run
from app.db.session import make_engine, make_session_factory, upgrade_db


@pytest.mark.parametrize("command", [
    "pytest -q", "python -m pytest", "py -3 -m pytest tests", "py -3.12 -m pytest",
    ".venv/Scripts/python.exe -m pytest", "uv run pytest", "uv run python -m pytest",
    "poetry run pytest", "npx vitest run", "npm test", "npm run test", "time pytest",
    "CI=1 pytest -x", "CI=1 PYTHONPATH=. python -m pytest", "cd backend && pytest",
    'cd "my app" && npm test', "cd web && CI=true npx vitest", "tox -e py312",
    "pytest -s tests/test_lint.py",
])
def test_a_test_tool_after_what_may_stand_before_it_is_a_test_run(command):
    assert ledger.RUNS_TESTS.match(command)


@pytest.mark.parametrize("command", [
    "echo pytest", "grep -rn pytest .", "cat pytest.ini", "cd tests && grep -rn pytest .",
    "tox -e lint", "nox -s lint", "npm run test:lint", "yarn test-lint", "git log pytest",
])
def test_a_command_that_only_names_a_test_tool_or_lints_is_none(command):
    assert not ledger.RUNS_TESTS.match(command)


@pytest.fixture
def ran(tmp_path):
    """Commands one agent ran, in order: (command, exit code, output); the failed run found."""
    db = tmp_path / "l.db"
    upgrade_db(db)
    factory = make_session_factory(make_engine(db))
    with factory() as s:
        s.add(Project(id="p", name="p", root_path=str(tmp_path)))
        s.flush()
        s.add(Conversation(id="c", project_id="p"))
        s.flush()
        s.add(Run(id="r", conversation_id="c", status="running"))
        s.flush()
        s.add(Agent(id="t", run_id="r", role_name="Tester", tools=[]))
        s.commit()

    def found(*commands):
        with factory() as s:
            for command, code, output in commands:
                s.add(Command(run_id="r", agent_id="t", command=command, location="host",
                              status="exited", exit_code=code, output=output, timeout_seconds=60))
                s.flush()
            s.commit()
            failed = ledger.failed_tests(s, "t")
            return failed and failed.command
    return found


def test_a_passing_run_of_another_test_command_hides_no_failing_one(ran):
    assert ran(("pytest -q", 1, "2 failed, 3 passed"), ("npm test", 0, "5 passed")) == "pytest -q"


def test_the_same_command_passing_after_it_failed_is_no_failure(ran):
    assert ran(("pytest -q", 1, "2 failed"), ("pytest  -q", 0, "5 passed")) is None


def test_no_tests_collected_lint_and_a_grep_with_no_match_are_no_failure(ran):
    assert ran(("python -m pytest tests/none", 5, "no tests ran"), ("npm run test:lint", 1, ""),
               ("grep -rn pytest .", 1, "")) is None
