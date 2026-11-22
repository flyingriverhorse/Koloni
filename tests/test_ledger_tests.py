"""What counts as a test run that failed, before a recipe's fix step (`ledger.failed_tests`):
the test tool is the command's first real word - after `cd <dir> &&`, `VAR=val`, `time` or a
runner - never a command that only names it; a lint script is none, and pytest's exit 5 (no
tests collected) no failure. Each test command's last run counts, not only the last of all."""

import pytest

from app import ledger
from app.db.models import Agent, Command, Conversation, Message, Project, Run, ToolCall
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
def factory(tmp_path):
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
        s.flush()
        s.add(Message(id="m", conversation_id="c", run_id="r", agent_id="t", role="assistant"))
        s.commit()
    return factory


def record(s, *commands):
    """Commands the Tester ran, in order: (command, exit code, output[, its call's status])."""
    for command, code, output, *said in commands:
        call = None
        if said:
            call = ToolCall(run_id="r", agent_id="t", message_id="m", seq=0, provider_call_id="p",
                            name="run_command", arguments="{}", status=said[0])
            s.add(call)
            s.flush()
        s.add(Command(run_id="r", agent_id="t", tool_call_id=call and call.id, command=command,
                      location="host", status="exited", exit_code=code, output=output,
                      timeout_seconds=60))
        s.flush()
    s.commit()


@pytest.fixture
def ran(factory):
    """Commands one agent ran (`record`); the failed run found."""
    def found(*commands):
        with factory() as s:
            record(s, *commands)
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


# Claude Code reports an exit code only of a command that failed ("Exit code 1" read from its
# words); of one that passed, none (its call "succeeded"); of one it ended - its timeout - none,
# its call "failed" (`model_native`, `observe_mixin._observe_command`).
@pytest.mark.parametrize(("code", "output", "said", "failed"), [
    (None, "3 passed in 0.12s", "succeeded", False),
    (1, "Exit code 1\n2 failed, 3 passed", "succeeded", True),
    (None, "2 failed, 3 passed", "succeeded", True),
    (None, "Command timed out after 2m 0s", "failed", True),
])
def test_a_run_with_no_exit_code_reported_fails_only_where_it_or_its_cli_says_so(
        ran, code, output, said, failed):
    assert (ran(("python -m pytest -q", code, output, said)) == "python -m pytest -q") is failed


def test_a_run_with_no_exit_code_reported_is_said_as_such_never_failed_or_passed(factory):
    with factory() as s:
        record(s, ("pytest -q", None, "3 passed in 0.12s", "succeeded"))
        assert ledger.did(s, "t") == ("What it did, from KOLONİ's record: read 0 files, wrote 0, "
                                      "ran 1 command, last test run: no exit code reported, 0 web.")
        assert ledger.of_turn(s, "r") == (
            f'{ledger.HEAD}\n- commands: "pytest -q" (no exit code reported)\n'
            '- last tests: "pytest -q" no exit code reported, "3 passed in 0.12s"')
        record(s, ("pytest -q", None, "1 failed, 2 passed", "succeeded"))
        assert "ran 2 commands (1 failed), last test run failed (no exit code reported)" in (
            ledger.did(s, "t"))
        assert ledger.failed_line(ledger.failed_tests(s, "t")) == (
            "last test run failed (no exit code reported): pytest -q")
