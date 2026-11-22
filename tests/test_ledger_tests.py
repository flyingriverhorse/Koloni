"""What counts as a test run that failed, before a recipe's fix step and at any check's pass
(`ledger.failed_tests`): the test tool is what a part of the line runs - past `cd <dir> &&`,
`VAR=val`, `time`, `timeout`, a runner or a shell's `-c` - never a command that only names it; a
lint script is none; pytest's exit 4 / 5, a run that never started tests and one that runs none
(`-h`, `--version`, `--collect-only`, 0 counted) give no verdict, nor does one whose exit is masked
(`; true`, `|| true`, a pipe). A later pass clears a failure only as the same line in the same
folder, or as a whole run of the same tool there, however it is spelled (`pytest`, `python -m
pytest`) - never a narrower one (a path, `-k`, `::`)."""

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
    # (review of S4: wrapped, chained and other test runs)
    "make test", 'bash -c "pytest -q"', "timeout 600 pytest", "uv run --frozen pytest",
    "python -X utf8 -m pytest", "./gradlew test", "echo x && pytest", "python3 -m pytest -q",
    "py -3 -m pytest", "cmd /c pytest -q", 'pwsh -NoProfile -Command "pytest -q"',
    # (review of S1b: the test lines KOLONİ may find and run, each read as one)
    "bundle exec rspec", "composer test", "mix test", "swift test", "ctest --test-dir build",
])
def test_a_test_tool_after_what_may_stand_before_it_is_a_test_run(command):
    assert ledger.read_test(command) is not None


@pytest.mark.parametrize("command", [
    "echo pytest", "grep -rn pytest .", "cat pytest.ini", "cd tests && grep -rn pytest .",
    "tox -e lint", "nox -s lint", "npm run test:lint", "yarn test-lint", "git log pytest",
])
def test_a_command_that_only_names_a_test_tool_or_lints_is_none(command):
    assert ledger.read_test(command) is None


@pytest.mark.parametrize(("command", "read"), [
    ("pytest -q", ("pytest", False)), ("python -m pytest -q", ("pytest", False)),
    ("py -3 -m pytest", ("pytest", False)), ("npx vitest run", ("vitest", False)),
    ("vitest run", ("vitest", False)), ("npm run test", ("npm test", False)),
    ("pytest -q > out.txt 2>&1; true", ("pytest", True)), ("pytest -q || true", ("pytest", True)),
    ("pytest -q || exit 0", ("pytest", True)), ("pytest -q | tail -1", ("pytest", True)),
    ('bash -c "pytest -q; true"', ("pytest", True)), ("cd web && pytest && echo ok", ("pytest", False)),
])
def test_a_test_run_is_read_as_its_tool_and_whether_its_exit_is_masked(command, read):
    assert ledger.read_test(command) == read


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


def record(s, *commands, cwd="."):
    """Commands the Tester ran, in order: (command, exit code, output[, its call's status])."""
    for command, code, output, *said in commands:
        call = None
        if said:
            call = ToolCall(run_id="r", agent_id="t", message_id="m", seq=0, provider_call_id="p",
                            name="run_command", arguments="{}", status=said[0])
            s.add(call)
            s.flush()
        s.add(Command(run_id="r", agent_id="t", tool_call_id=call and call.id, command=command,
                      cwd=cwd, location="host", status="exited", exit_code=code, output=output,
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


def test_the_same_tool_passing_after_it_failed_is_no_failure_however_it_is_spelled(ran):
    # (Review of S4: `pytest -q` not on PATH, then `python -m pytest -q` passed.)
    assert ran(("pytest -q", 1, "1 failed"), ("python -m pytest -q", 0, "4 passed")) is None
    assert ran(("npx vitest run", 1, "1 failed"), ("vitest run", 0, "4 passed")) is None


@pytest.mark.parametrize(("code", "output"), [
    (127, "bash: pytest: command not found"), (9009, ""),
    (1, "'pytest' is not recognized as an internal or external command"),
    (1, "/usr/bin/python: No module named pytest"), (4, "ERROR: file or directory not found: x"),
])
def test_a_run_that_never_started_tests_gives_no_verdict(ran, code, output):
    assert ran(("pytest -q", code, output)) is None
    # (...and hides no failure before it)
    assert ran(("pytest -q", 1, "2 failed"), ("pytest -q", code, output)) == "pytest -q"


def test_a_masked_exit_is_no_pass_but_a_failure_it_counts_is_one(ran):
    assert ran(("pytest -q > out.txt 2>&1; true", 0, "")) is None
    assert ran(("pytest -q", 1, "1 failed"), ("pytest -q || true", 0, "")) == "pytest -q"
    assert ran(("pytest -q | tail -1", 0, "1 failed, 2 passed")) == "pytest -q | tail -1"


def test_no_tests_collected_lint_and_a_grep_with_no_match_are_no_failure(ran):
    assert ran(("python -m pytest tests/none", 5, "no tests ran"), ("npm run test:lint", 1, ""),
               ("grep -rn pytest .", 1, "")) is None


UNITTEST_FAILED = "F\nFAIL: test_x (test_bf037.T.test_x)\nRan 1 test in 0.001s\n\nFAILED (failures=1)\n"


def test_a_help_after_a_failing_run_of_its_tool_clears_nothing(ran):
    # (CL-305 B, in the browser: the Tester's unittest failed, then `-h` exited 0 - and was a pass.)
    assert ran(("python -m unittest -q test_bf037", 1, UNITTEST_FAILED),
               ("python -m unittest -h", 0, "usage: python -m unittest [-h] [-v] [-q]")) == (
        "python -m unittest -q test_bf037")


@pytest.mark.parametrize(("failing", "none"), [
    ("pytest -q", "pytest --collect-only -q"), ("pytest -q", "pytest --co"),
    ("pytest -q", "python -m pytest --version"), ("pytest -q", "pytest -V"),
    ("pytest -q", "pytest -h"), ("pytest -q", "pytest --help"), ("pytest -q", "pytest --fixtures"),
    ("pytest -q", "pytest --markers"), ("go test ./...", "go test -list ."),
    ("cargo test", "cargo test -- --list"), ("npx jest", "npx jest --listTests"),
    ("npx vitest run", "npx vitest list"), ("dotnet test", "dotnet test --list-tests"),
])
def test_a_form_that_runs_no_tests_is_no_verdict(ran, failing, none):
    assert ran((none, 0, "")) is None
    assert ran((failing, 1, "1 failed"), (none, 0, "")) == failing


def test_a_run_that_counts_no_test_is_no_verdict(ran):
    assert ran(("npx jest", 1, "Tests:       0 total")) is None
    assert ran(("npx jest", 1, "Tests:       1 failed, 1 total"),
               ("npx jest", 0, "Tests:       0 total")) == "npx jest"


@pytest.mark.parametrize("narrow", [
    "pytest -q tests/test_ok.py", "pytest -q -k ok", "pytest -q tests/test_x.py::test_ok",
    "python -m pytest -m slow", "python -m unittest -q test_ok", "npx vitest run -t adds",
    "npx jest --testNamePattern=adds", "go test -run TestOk ./...", "cargo test -p one",
    "dotnet test --filter Name=Ok", "./gradlew test --tests Ok", "npx playwright test --grep ok",
    "npx jest -o",
])
def test_a_narrower_pass_clears_no_wider_failure(ran, narrow):
    failing = ledger.read_test(narrow)[0]
    whole = {"pytest": "pytest -q", "unittest": "python -m unittest", "vitest": "npx vitest run",
             "jest": "npx jest", "go test": "go test ./...", "cargo test": "cargo test",
             "dotnet test": "dotnet test", "gradle test": "./gradlew test",
             "playwright test": "npx playwright test"}[failing]
    assert ran((whole, 1, "1 failed"), (narrow, 0, "2 passed")) == whole


def test_the_same_line_or_a_whole_run_clears_a_narrower_failure(ran):
    assert ran(("pytest -q tests/test_x.py", 1, "1 failed"), ("pytest  -q tests/test_x.py", 0, "1 passed")) is None
    assert ran(("pytest -q tests/test_x.py", 1, "1 failed"), ("python -m pytest", 0, "4 passed")) is None
    # (Where its output goes picks no test: `2>&1`, `> out.txt` are no path of its.)
    assert ran(("pytest -q", 1, "1 failed"), ("python -m pytest -q 2>&1", 0, "4 passed")) is None
    assert ran(("pytest -q", 1, "1 failed"), ("pytest -q -n 2 > out.txt 2>&1", 0, "4 passed")) is None


NAMED_FAILED = "F\nFAILED tests/test_a.py::test_x - assert 1 == 2\n1 failed, 3 passed\n"
THREE_PASSED = "...\n3 passed in 0.1s\n"


# Review of the R2 fix: a pass that leaves tests out, or reads its options from elsewhere, is a
# narrower one - with `=` as spaced; and a `cd ..` after a `cd` that may have failed (`;`) is no
# folder known.
@pytest.mark.parametrize("narrow", [
    "pytest -q --ignore=tests/test_a.py", "pytest -q --deselect=tests/test_a.py::test_x",
    "pytest -q --ignore-glob=*test_a*", "pytest -q -c other.ini", "pytest -q --config-file=other.ini",
    "pytest -q -o addopts=-ktest_ok", "pytest -q --override-ini=testpaths=tests/ok",
    "pytest -q --rootdir=sub", "PYTEST_ADDOPTS=-ktest_ok pytest -q",
    "$env:PYTEST_ADDOPTS='-k test_ok'; pytest -q", "export PYTEST_ADDOPTS=-kok && pytest -q",
    "pytest -q --lf", "pytest -q --deselect tests/test_a.py::test_x", "pytest -q --ignore tests/test_a.py",
    "pushd sub && pytest -q", "cd sub; cd ..; pytest -q",
])
def test_a_pass_that_leaves_tests_out_clears_nothing(ran, narrow):
    assert ran(("pytest -q", 1, NAMED_FAILED), (narrow, 0, THREE_PASSED)) == "pytest -q", narrow


# ...and one by paths alone clears a failure whose every failing test lies under them, where it
# really ran tests; `-p no:<plugin>` picks none. (`-x` stops at a failure: passing, it ran all.)
@pytest.mark.parametrize("wide", [
    "pytest tests", "pytest tests/", "pytest -p no:cacheprovider", "python -m pytest -q tests/",
    "pytest -q ./tests/test_a.py", "pytest -q -x", "pytest -q -pno:randomly",
])
def test_a_pass_that_runs_every_failing_test_clears_it(ran, wide):
    assert ran(("pytest -q", 1, NAMED_FAILED), (wide, 0, THREE_PASSED)) is None, wide


@pytest.mark.parametrize(("failed", "passed"), [
    (NAMED_FAILED, "...\n"),  # (no count: no tests known to have run)
    ("1 failed, 3 passed\n", THREE_PASSED),  # (it names no failing test)
    ("FAILED tests/test_a.py::test_x\nFAILED src/test_b.py::test_y\n2 failed\n", THREE_PASSED),
])
def test_a_pass_by_paths_holds_where_a_failing_test_is_not_known_under_them(ran, failed, passed):
    assert ran(("pytest -q", 1, failed), ("pytest -q tests", 0, passed)) == "pytest -q"


def test_a_pass_in_another_folder_clears_nothing(factory):
    with factory() as s:
        record(s, ("pytest -q", 1, "1 failed"))
        record(s, ("pytest -q", 0, "4 passed"), cwd="web")
        record(s, ("cd web && pytest -q", 0, "4 passed"))
        assert ledger.failed_tests(s, "t").command == "pytest -q"
        record(s, ("cd web && pytest -q", 1, "1 failed"))
        record(s, ("pytest -q", 0, "4 passed"), cwd="web")  # (where the `cd` went: the same)
        assert ledger.failed_tests(s, "t").command == "pytest -q"
        record(s, ("pytest", 0, "5 passed"), cwd="")  # (the project's root, said either way)
        assert ledger.failed_tests(s, "t") is None


def test_what_it_did_says_no_pass_of_a_run_that_ran_no_tests(factory):
    with factory() as s:
        record(s, ("python -m unittest -q test_bf037", 1, UNITTEST_FAILED),
               ("python -m unittest -h", 0, "usage: python -m unittest [-h]"))
        said = ledger.did(s, "t")
        assert "last test run failed (exit 1)" in said and "-h" not in said, said


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


def test_a_masked_run_is_said_to_give_no_verdict(factory):
    with factory() as s:
        record(s, ("pytest -q || true", 0, ""))
        assert "last test run: no verdict (its exit was masked)" in ledger.did(s, "t")


# R2 (review of S4): what a failed run names as failing, and whether the report's "Already
# failing before" lines cover every one of it.
@pytest.mark.parametrize(("output", "names"), [
    ("FAILED tests/test_repro.py::test_calc_2 - ZeroDivisionError\n1 failed, 3 passed",
     ["tests/test_repro.py::test_calc_2"]),
    ("tests/a.py::test_x FAILED\nERROR tests/b.py::test_y[1] - E\n", ["tests/a.py::test_x", "tests/b.py::test_y[1]"]),
    (" FAIL  src/a.test.ts > sums > adds two\n Test Files  1 failed", ["src/a.test.ts > sums > adds two"]),
    ("--- FAIL: TestAdd (0.00s)\nFAIL", ["TestAdd"]),
    ("2 failed, 3 passed", []),
    # (CL-316: pytest's coloured line)
    ("\x1b[31mFAILED\x1b[0m test_calc054.py::\x1b[1mtest_x\x1b[0m - assert 1 == 2\n",
     ["test_calc054.py::test_x"]),
])
def test_the_tests_a_failed_run_names(output, names):
    assert ledger.failing_named(output) == names


def test_a_coloured_run_is_read_as_a_plain_one(ran, factory):
    from tests.test_proof import COLOURED
    # (Its exit masked, a failure it counts is one; and passing, it clears one.)
    assert ran(("pytest -q | tail -3", 0, COLOURED["failed"])) == "pytest -q | tail -3"
    assert ran(("pytest -q", 1, COLOURED["failed"]), ("pytest -q", 0, COLOURED["passed"])) is None
    with factory() as s:
        record(s, ("pytest -q", 0, COLOURED["passed"]))
        assert ledger.of_turn(s, "r").endswith('- last tests: "pytest -q" exit 0, "1 passed in 0.01s"')


@pytest.mark.parametrize(("before", "covered"), [
    (["test_calc_2"], True), (["tests/test_repro.py::test_calc_2 (a flaky one)"], True),
    (["test_old_flaky in tests/test_legacy.py"], False), (["test_calc_20"], False), ([], False),
])
def test_already_failing_before_covers_only_the_tests_it_names(factory, before, covered):
    with factory() as s:
        record(s, ("pytest -q", 1, "FAILED tests/test_repro.py::test_calc_2 - E\n1 failed"))
        assert ledger.covered(ledger.failed_tests(s, "t"), before) is covered
        # (A run that names no failing test is covered by none.)
        record(s, ("pytest -q", 1, "1 failed"))
        assert ledger.covered(ledger.failed_tests(s, "t"), before) is False


class _Run:  # (a failed run's output, as `covered` reads it)
    def __init__(self, output):
        self.output = output


REPRO = "FAILED tests/test_repro.py::test_calc_2 - ZeroDivisionError\n1 failed"
TWO_X = "FAILED tests/a.py::test_x - E\nFAILED tests/b.py::test_x - E\n2 failed"
VITEST = " FAIL  src/a.test.ts > App > renders\n Test Files  1 failed"
JEST = "  ● App › works\n Tests: 1 failed"


# Review of S4 (re-review): a name is matched with its file or suite where the run gives them; a
# bare name only where it is the one failing test of that name.
@pytest.mark.parametrize(("output", "before", "covered"), [
    (REPRO, ["tests/other.py::test_calc_2"], False),
    (REPRO, ["test_calc_2 in tests/other.py"], False),
    (REPRO, ["test_calc_2"], True),
    (REPRO, ["tests/test_repro.py::test_calc_2"], True),
    (TWO_X, ["test_x"], False),
    (TWO_X, ["tests/a.py::test_x", "tests/b.py::test_x"], True),
    (VITEST, ["login renders slowly"], False),
    (VITEST, ["renders"], False),
    (VITEST, ["App > renders"], True),
    (VITEST, ["src/a.test.ts > App > renders"], True),
    (JEST, ["it works"], False),
    (JEST, ["App › works"], True),
])
def test_a_name_is_matched_with_its_file_or_suite(output, before, covered):
    assert ledger.covered(_Run(output), before) is covered


def test_a_test_the_reproduce_step_showed_failing_is_never_already_failing_before():
    # (Review of S4: a Tester's honest "the reproduction test_calc_2 was failing before the fix".)
    said = ["the reproduction test_calc_2 was failing before the fix"]
    assert ledger.covered(_Run(REPRO), said) is True
    assert ledger.covered(_Run(REPRO), said, never={"tests/test_repro.py::test_calc_2"}) is False


def test_the_tests_some_agents_runs_named_failing(factory):
    with factory() as s:
        record(s, ("echo FAILED tests/x.py::test_no", 0, "FAILED tests/x.py::test_no"),
               ("python -m pytest -q tests/test_repro.py", 1, REPRO))
        assert ledger.failing_of(s, ["t"]) == {"tests/test_repro.py::test_calc_2"}
        assert ledger.failing_of(s, []) == set()


@pytest.mark.parametrize(("commands", "checked"), [
    ([("ls", "exited"), ("git status", "exited"), ("cat a.py", "exited")], False),
    ([("pytest -q", "blocked"), ("pytest -q", "failed_to_start"), ("pytest -q", "rejected")], False),
    ([("ls", "exited"), ("pytest -q", "exited")], True),
    ([("python check.py", "timed_out")], True),
    # (CL-305: commands that check nothing - a Tester that ran only these ran no test.)
    ([('python -c "pass"', "exited"), ("echo ok", "exited"), ("true", "exited"), (":", "exited"),
      ("cd .", "exited"), ("python --version", "exited"), ("pytest -V", "exited"),
      ("pytest --collect-only -q", "exited"), ("npm --help", "exited"),
      ("python -c \"print('ok')\"", "exited"), ("echo ok && cd . && git status", "exited"),
      ('python -c "pass" 2>&1', "exited"), ("echo ok > done.txt", "exited")], False),
    ([("cd tests && python -m pytest -q", "exited")], True),
    ([('python -c "import calc; assert calc.x == 1"', "exited")], True),
    ([("python -c \"print(__import__('calc').x)\"", "exited")], True),
])
def test_a_check_ran_is_a_command_that_started_and_is_no_mere_read(factory, commands, checked):
    with factory() as s:
        for command, status in commands:
            s.add(Command(run_id="r", agent_id="t", command=command, location="host", status=status,
                          timeout_seconds=60))
        s.commit()
        assert ledger.ran_check(s, "t") is checked


def ran_one(s, command, code=0, output=""):
    s.add(Command(run_id="r", agent_id="t", command=command, location="host", status="exited",
                  exit_code=code, output=output, timeout_seconds=60))
    s.commit()


# Review of the R3 fix: no project test command known - these check nothing either, a test run
# that ran none by its output too.
@pytest.mark.parametrize(("command", "code", "output"), [
    ('python -c "import sys"', 0, ""), ('node -e ""', 0, ""), ("exit 0", 0, ""),
    ("cmd /c rem", 0, ""), ("Write-Output ok", 0, "ok"), ("pytest --co -q", 0, ""),
    ("pytest -k nothing_matches", 5, "3 deselected in 0.01s"),
    ("npm test -- --passWithNoTests", 0, "No tests found, exiting with code 0"),
    ('python -c "print(1+1)"', 0, "2"), ("node -v", 0, "v22.0.0"), ("sleep 1", 0, ""),
    ("whoami", 0, "me"), ('python -c "0"', 0, ""),
    # (A test run that never started: its program, or pytest, not there.)
    ("python -m pytest -q", 1, "/usr/bin/python: No module named pytest"),
    ("pytest -q", 127, "bash: pytest: command not found"),
])
def test_a_command_that_checks_nothing_is_no_check(factory, command, code, output):
    with factory() as s:
        ran_one(s, command, code, output)
        assert ledger.ran_check(s, "t") is False, command


# ...and on code where the project has a test command (`test_lines`), only a test run that really
# ran tests is one: its runner counted some, else its exit code and output - the project's own
# line by its exit code.
@pytest.mark.parametrize(("command", "code", "output", "checked"), [
    ("python check.py", 0, "all good", False), ("node -e \"require('./calc')\"", 0, "", False),
    ("pytest -q", 0, "3 passed in 0.1s", True), ("pytest -q", 1, "1 failed, 2 passed", True),
    ("pytest -k nothing_matches", 5, "3 deselected in 0.01s", False),
    ("python -m pytest -q", 1, "/usr/bin/python: No module named pytest", False),
    ("make check", 127, "bash: make: command not found", False),
    ("cargo test", 0, "running...", True), ("cargo test", 0, "", False),
    ("make check", 0, "", True),
])
def test_a_check_of_code_runs_tests(factory, command, code, output, checked):
    with factory() as s:
        ran_one(s, command, code, output)
        assert ledger.ran_check(s, "t", {"make check"}) is checked, command


def test_the_test_lines_a_check_of_code_is_held_to(factory, tmp_path):
    from app.db.models import FileChange, Project
    with factory() as s:
        project = s.get_one(Project, "p")
        assert ledger.test_lines(s, "r", project) is None  # (none known)
        project.test_commands = {"./": "make check", "web/": ""}
        project.tests_found = {"api": {"command": "go  test ./..."}}
        assert ledger.test_lines(s, "r", project) == {"make check", "go test ./..."}
        s.add(FileChange(run_id="r", agent_id="t", path="README.md", before_content="a",
                         after_content="b", after_sha="0", kind="edit", status="applied"))
        s.commit()
        assert ledger.test_lines(s, "r", project) is None  # (only a document changed)
        project.test_commands, project.tests_found = {}, {}
        (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
        s.add(FileChange(run_id="r", agent_id="t", path="calc.py", before_content="a",
                         after_content="b", after_sha="0", kind="edit", status="applied"))
        s.commit()
        assert ledger.test_lines(s, "r", project) == {"python -m pytest -q"}  # (its files name one)


def test_a_declined_check_is_named(factory):
    with factory() as s:
        assert ledger.declined(s, "t") is None
        s.add(Command(run_id="r", agent_id="t", command="pytest -q", location="host",
                      status="rejected", timeout_seconds=60))
        s.commit()
        assert ledger.declined(s, "t") == "pytest -q"
