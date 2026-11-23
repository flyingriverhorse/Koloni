"""Kanıtlı bitiş (S1), what needs no model: the kind of each changed file, the tests' command(s), a
test run's row, a turn's changes on record, and whether a test run on record is fresh enough to
stand for this turn's (`app.proof`)."""

import json
from datetime import timedelta
from types import SimpleNamespace

import pytest

from app import proof
from app.db.models import (
    Agent,
    Command,
    Conversation,
    FileChange,
    Message,
    Project,
    Run,
    ToolCall,
    now,
)
from app.db.session import make_engine, make_session_factory, upgrade_db


@pytest.mark.parametrize(("path", "kind"), [
    ("app.py", "code"), ("src/main.ts", "code"), ("lib/x.js", "code"), ("LICENSE", "code"),
    ("docs/conf.py", "code"), ("bin/run", "code"),
    ("requirements.txt", "config"), ("requirements-dev.txt", "config"),
    ("constraints-ci.txt", "config"), ("pyproject.toml", "config"), ("setup.py", "config"),
    ("setup.cfg", "config"), ("tox.ini", "config"), ("pytest.ini", "config"),
    ("tests/conftest.py", "config"), ("package.json", "config"), ("package-lock.json", "config"),
    ("pnpm-lock.yaml", "config"), ("yarn.lock", "config"), ("tsconfig.app.json", "config"),
    ("vite.config.ts", "config"), ("vitest.config.mts", "config"), ("Makefile", "config"),
    ("Dockerfile", "config"), ("docker-compose.dev.yml", "config"), (".env", "config"),
    (".env.local", "config"), (".github/workflows/ci.yml", "config"),
    ("sub/.github/workflows/x.txt", "config"), ("conf/app.yaml", "config"), ("a.json", "config"),
    ("README.md", "docs"), ("notes.txt", "docs"), ("guide.rst", "docs"), ("a.adoc", "docs"),
    ("report.docx", "docs"), ("deck.pptx", "slides"), ("talk.odp", "slides"),
    ("flow.drawio", "diagram"), ("a.drawio.xml", "diagram"), ("seq.mmd", "diagram"),
    ("x.puml", "diagram"), ("logo.svg", "diagram"),
    ("data.csv", "data"), ("analysis.ipynb", "data"), ("sheet.xlsx", "data"),
    ("App.tsx", "ui"), ("index.html", "ui"), ("style.css", "ui"), ("C.vue", "ui"),
    ("Windows\\Path.MD", "docs"),
])
def test_kind_of(path, kind):
    assert proof.kind_of(path) == kind


def test_needs_tests():
    assert proof.needs_tests(["README.md"]) is False
    assert proof.needs_tests(["README.md", "deck.pptx", "data.csv", "flow.drawio"]) is False
    assert proof.needs_tests(["README.md", "app.py"]) is True
    assert proof.needs_tests([]) is False
    assert proof.needs_tests(["requirements.txt"]) is True
    assert proof.needs_tests(["index.html"]) is True


def _project(root, check=None, tests=None):
    return SimpleNamespace(root_path=str(root), check_command=check, test_commands=tests or {})


def _map(*parts):
    return {"parts": [{"path": path, "guess": guess} for path, guess in parts]}


def test_test_runs_take_the_users_command_then_each_parts_then_the_guess(tmp_path):
    assert proof.test_runs(_project(tmp_path, check=" make check "), _map(("./", "pytest"))) == [
        proof.TestRun("make check", ".", True)]
    assert proof.test_runs(_project(tmp_path, tests={"web/": "npm test"}),
                           _map(("./", "pytest"), ("web/", None))) == [
        proof.TestRun("pytest", ".", False), proof.TestRun("npm test", "web", True)]
    # (the user's "no test" for a part: none run there)
    assert proof.test_runs(_project(tmp_path, tests={"./": ""}), _map(("./", "pytest"))) == []
    assert proof.test_runs(_project(tmp_path), None) == []
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    assert proof.test_runs(_project(tmp_path), None) == [
        proof.TestRun("python -m pytest -q", ".", False)]


RUN = proof.TestRun("pytest -q", ".", True)

# CL-316 (BULGU C): pytest's real output with `--color=yes` (and `FORCE_COLOR`, as Playwright starts
# KOLONİ) - a code stands before each number - and the same runs without colour.
COLOURED = {
    "passed": ("\x1b[32m.\x1b[0m\x1b[32m" + " " * 72 + "[100%]\x1b[0m\n\x1b[32m\x1b[32m\x1b[1m1 "
               "passed\x1b[0m\x1b[32m in 0.01s\x1b[0m\x1b[0m\n"),
    "skipped": ("\x1b[33ms\x1b[0m\x1b[33m" + " " * 72 + "[100%]\x1b[0m\n\x1b[33m\x1b[33m\x1b[1m1 "
                "skipped\x1b[0m\x1b[33m in 0.01s\x1b[0m\x1b[0m\n"),
    "failed": ("\x1b[31mF\x1b[0m\x1b[31m" + " " * 72 + "[100%]\x1b[0m\n\x1b[1m\x1b[31mE       assert "
               "1 == 2\x1b[0m\n\x1b[1m\x1b[31mtest_calc054.py\x1b[0m:5: AssertionError\n\x1b[36m\x1b[1m"
               "=========================== short test summary info ===========================\x1b"
               "[0m\n\x1b[31mFAILED\x1b[0m test_calc054.py::\x1b[1mtest_x\x1b[0m - assert 1 == 2\n\x1b"
               "[31m\x1b[31m\x1b[1m1 failed\x1b[0m\x1b[31m in 0.05s\x1b[0m\x1b[0m\n"),
}
PLAIN = {
    "passed": "." + " " * 72 + "[100%]\n1 passed in 0.01s\n",
    "skipped": "s" + " " * 72 + "[100%]\n1 skipped in 0.01s\n",
    "failed": ("F" + " " * 72 + "[100%]\nE       assert 1 == 2\ntest_calc054.py:5: AssertionError\n"
               "=========================== short test summary info ===========================\n"
               "FAILED test_calc054.py::test_x - assert 1 == 2\n1 failed in 0.05s\n"),
}


@pytest.mark.parametrize("outputs", [COLOURED, PLAIN], ids=["colour", "plain"])
@pytest.mark.parametrize(("kind", "code", "state", "text"), [
    ("passed", 0, "passed", "Tests passed: pytest -q - 1 passed in 0.01s"),
    ("skipped", 0, "not_run", "Tests skipped only: pytest -q - 1 skipped in 0.01s"),
    ("failed", 1, "failed", "Tests failed: pytest -q - 1 failed in 0.05s"),
    ("failed", 0, "failed", "Tests failed: pytest -q - 1 failed in 0.05s"),  # (its exit masked)
])
def test_a_coloured_run_is_read_as_a_plain_one(outputs, kind, code, state, text):
    made = proof.tests_row(RUN, code, outputs[kind], "exited", "")
    assert (made["state"], made["text"]) == (state, text)


def test_tests_row_states():
    passed = proof.tests_row(RUN, 0, "....\n===== 4 passed in 0.1s =====\n", "exited", "")
    assert passed["state"] == "passed" and passed["kind"] == "tests"
    assert passed["text"] == "Tests passed: pytest -q - 4 passed in 0.1s"
    assert passed["command"] == "pytest -q" and passed["guessed"] is False
    failed = proof.tests_row(RUN, 0, "x\n1 failed, 3 passed\n", "exited", "")
    assert failed["state"] == "failed" and failed["text"] == (
        "Tests failed: pytest -q - 1 failed, 3 passed")
    assert proof.tests_row(RUN, 2, "boom", "exited", "")["text"] == "Tests failed: pytest -q - exit 2"
    none = proof.tests_row(RUN, 5, "no tests ran", "exited", "")
    assert (none["state"], none["text"]) == ("not_run", "Tests ran none: pytest -q collected no test")
    timed = proof.tests_row(RUN, None, "", "timed_out", "error: timed out")
    assert (timed["state"], timed["text"]) == ("timed_out", "Tests timed out after 10 min: pytest -q")
    waited = proof.tests_row(RUN, None, "", "timed_out", "error: timed out", seconds=120)
    assert waited["state"] == "timed_out" and waited["text"].startswith(
        "Tests not waited for: still running at 2:00")
    guessed = proof.tests_row(proof.TestRun("npm test", ".", False), 0, "5 passed", "exited", "")
    assert guessed["text"] == "Tests passed: npm test (guessed) - 5 passed" and guessed["guessed"]
    missing = proof.tests_row(RUN, 1, "bash: pytest: command not found", "exited", "")
    assert (missing["state"], missing["text"]) == (
        "not_run", "Tests could not start: bash: pytest: command not found")
    unstarted = proof.tests_row(RUN, None, "", "failed_to_start", "error: Docker is not running")
    assert unstarted["text"] == "Tests could not start: Docker is not running"
    stopped = proof.tests_row(RUN, None, "", "killed", "error: the command was stopped")
    assert (stopped["state"], stopped["text"]) == ("not_run", "Tests not finished: stopped")


def test_checked_text_one_line_a_row():
    rows = [proof.row("tests", "passed", "Tests passed: a"), proof.row("tests", "failed", "b"),
            proof.row("tests", "running", "c"), proof.row("rounds", "note", "d"),
            proof.row("tests", "timed_out", "e"), proof.row("tests", "not_run", "f")]
    assert proof.checked_text(rows) == "✓ Tests passed: a\n✗ b\n… c\n– d\n– e\n– f"


# --- on record ------------------------------------------------------------------------------

@pytest.fixture
def factory(tmp_path):
    db = tmp_path / "p.db"
    upgrade_db(db)
    factory = make_session_factory(make_engine(db))
    with factory() as s:
        s.add(Project(id="p", name="p", root_path=str(tmp_path)))
        s.flush()
        s.add(Conversation(id="c", project_id="p"))
        s.flush()
        s.add(Run(id="r", conversation_id="c", status="running"))
        s.flush()
        s.add_all([Agent(id="lead", run_id="r", role_name="Orchestrator", tools=[]),
                   Agent(id="coder", run_id="r", role_name="Coder", tools=[], depth=1)])
        s.flush()
        s.add(Message(id="m", conversation_id="c", run_id="r", agent_id="lead", role="assistant"))
        s.commit()
    return factory


def change(s, path, before, after, agent="lead", status="applied", at=None, kind="modify"):
    s.add(FileChange(run_id="r", agent_id=agent, path=path, kind=kind, before_content=before,
                     after_content=after, after_sha="x", status=status,
                     created_at=at or now()))
    s.commit()


def ran(s, command, code, at, agent="lead", cwd=".", output="3 passed"):
    s.add(Command(run_id="r", agent_id=agent, command=command, cwd=cwd, location="host",
                  status="exited", exit_code=code, output=output, timeout_seconds=60,
                  started_at=at - timedelta(seconds=1), ended_at=at))
    s.commit()


def test_changes_merge_rows_per_path_and_skip_scratch(factory):
    with factory() as s:
        change(s, "a.py", "1\n", "1\n2\n")
        change(s, "a.py", "1\n2\n", "1\n2\n3\n")
        change(s, ".koloni/tmp/x.txt", None, "x")
        change(s, "b.py", "gone\n", "", kind="delete")
        change(s, "c.py", None, "x\n", status="proposed")  # (not kept: never in)
        found = {one.path: one for one in proof.changes(s, "r", "lead")}
    assert set(found) == {"a.py", "b.py"}
    assert (found["a.py"].added, found["a.py"].removed, found["a.py"].deleted) == (2, 0, False)
    assert found["b.py"].deleted and found["b.py"].kind == "code"
    assert all(one.in_project for one in found.values())


def made(path, deleted=False, in_project=True, existed=True):
    return proof.Change(path, proof.kind_of(path), 1, 0, deleted, "lead", in_project, existed)


@pytest.mark.parametrize(("paths", "untested"), [
    (["app/a.py"], ["app/a.py"]),
    (["app/a.py", "tests/test_a.py"], []),
    (["README.md"], []),
    (["src/x.ts", "src/x.test.ts"], []),  # (a .test. file is a test)
    (["src/App.tsx", "src/App.css"], ["src/App.tsx"]),  # (a screen's script, not its style)
    (["pkg/calc.go", "pkg/calc_test.go"], []),
    (["logo.png", ".gitignore", "LICENSE", "pyproject.toml"], []),  # (no source of a language)
])
def test_untested_names_source_changed_without_a_test(paths, untested):
    assert proof.untested([made(path) for path in paths]) == untested


def test_untested_skips_what_is_gone_or_not_in_the_project_and_a_waiting_test_counts():
    assert proof.untested([made("app/a.py", deleted=True)]) == []
    assert proof.untested([made("app/a.py", in_project=False)]) == []
    # (a test a sub-agent wrote that still waits in Ready for you: written for the change)
    assert proof.untested([made("app/a.py"), made("tests/test_a.py", in_project=False)]) == []
    assert [one.path for one in proof.new_tests([made("tests/test_a.py", deleted=True)])] == []


def test_removed_tests(factory):
    assert proof.removed_tests([made("tests/test_a.py", deleted=True), made("app/a.py", deleted=True),
                                made("tests/test_b.py")]) == ["tests/test_a.py"]
    # (one the turn made and deleted again was never the project's)
    assert proof.removed_tests([made("tests/test_new.py", deleted=True, existed=False)]) == []
    with factory() as s:
        change(s, "tests/test_old.py", "def test_x(): pass\n", "", kind="delete")
        change(s, "tests/test_tmp.py", None, "x\n", kind="create")
        change(s, "tests/test_tmp.py", "x\n", "", kind="delete")
        assert proof.removed_tests(proof.changes(s, "r", "lead")) == ["tests/test_old.py"]


def test_a_copy_waiting_for_take_in_is_not_in_project(factory):
    with factory() as s:
        change(s, "a.py", "1\n", "2\n", agent="coder", status="in_copy")
        change(s, "b.py", "1\n", "2\n", status="in_copy")  # (the Lead's own copy: an Away job's)
        found = {one.path: one for one in proof.changes(s, "r", "lead")}
        assert found["a.py"].in_project is False and found["a.py"].agent_id == "coder"
        assert found["b.py"].in_project is True
        # (where the Coder works in the Lead's own copy, its work is where the tests run)
        assert all(one.in_project for one in proof.changes(s, "r", "lead", ("coder",)))


def test_a_pass_before_the_last_change_is_not_fresh(factory):
    at = now()
    with factory() as s:
        ran(s, "pytest  -q", 0, at - timedelta(seconds=30))
        change(s, "a.py", "1\n", "2\n", at=at)
        assert proof.fresh(s, "r", "lead", RUN, proof.last_change(s, "r")) is None
        ran(s, "pytest -q", 0, at + timedelta(seconds=5))
        found = proof.fresh(s, "r", "lead", RUN, proof.last_change(s, "r"))
        assert found is not None and found.exit_code == 0
        # (another folder's run is another run)
        assert proof.fresh(s, "r", "lead", proof.TestRun("pytest -q", "web", True), at) is None


def test_a_pass_in_a_copy_is_not_reused(factory):
    at = now()
    with factory() as s:
        change(s, "a.py", "1\n", "2\n", at=at - timedelta(seconds=30))
        ran(s, "pytest -q", 0, at, agent="coder")  # (a sub-agent's: in its own copy)
        assert proof.fresh(s, "r", "lead", RUN, proof.last_change(s, "r")) is None


def test_a_run_with_no_exit_code_is_never_fresh(factory):
    at = now()
    with factory() as s:
        s.add(Command(run_id="r", agent_id="lead", command="pytest -q", cwd=".", location="host",
                      status="exited", exit_code=None, output="", timeout_seconds=60,
                      started_at=at, ended_at=at, origin="cli"))
        s.commit()
        assert proof.fresh(s, "r", "lead", RUN, None) is None


def test_a_run_over_the_wait_last_time_is_said_slow(factory):
    at = now()
    with factory() as s:
        assert proof.too_slow(s, "p", RUN, 120) is None
        ran(s, "pytest -q", 0, at)
        assert proof.too_slow(s, "p", RUN, 120) is None
        s.add(Command(run_id="r", agent_id="lead", command="pytest -q", cwd=".", location="host",
                      status="timed_out", output="", timeout_seconds=120,
                      started_at=at + timedelta(seconds=1), ended_at=at + timedelta(seconds=121)))
        s.commit()
        assert proof.too_slow(s, "p", RUN, 120) is not None
        # (a quick run after it - an agent's, the user's - lets it run again)
        ran(s, "pytest -q", 0, at + timedelta(seconds=200))
        assert proof.too_slow(s, "p", RUN, 120) is None
        assert json.dumps(proof.row("tests", "note", "x"))  # (a row is plain JSON)


# --- fix round (review of 22 Nov) -----------------------------------------------------------

def test_a_run_started_before_the_last_change_is_not_fresh(factory):
    # (It ended after the change, but did not see it: a Take in, a sub-agent's write meanwhile.)
    at = now()
    with factory() as s:
        s.add(Command(run_id="r", agent_id="lead", command="pytest -q", cwd=".", location="host",
                      status="exited", exit_code=0, output="3 passed", timeout_seconds=60,
                      started_at=at - timedelta(seconds=10), ended_at=at))
        s.commit()
        change(s, "a.py", "1\n", "2\n", at=at - timedelta(seconds=5))
        assert proof.fresh(s, "r", "lead", RUN, proof.last_change(s, "r")) is None


def test_a_line_started_in_the_same_clock_tick_after_a_pass_unmakes_it(factory):
    # (review of S1b: Windows' clock ticks ~15 ms - a later line may carry the pass's own start)
    at = now()
    with factory() as s:
        change(s, "a.py", "1\n", "2\n", at=at - timedelta(seconds=30))
        ran(s, "pytest -q", 0, at)
        assert proof.fresh(s, "r", "lead", RUN, proof.last_change(s, "r")) is not None
        s.add(Command(run_id="r", agent_id="lead", command="python fmt.py", cwd=".",
                      location="host", status="exited", exit_code=0, output="",
                      timeout_seconds=60, started_at=at - timedelta(seconds=1), ended_at=at))
        s.commit()
        assert proof.fresh(s, "r", "lead", RUN, proof.last_change(s, "r")) is None


def test_unrecorded_names_the_newest_writer_from_the_oldest_ones_start(factory):
    # (Re-check of D: `sed -i` wrote a.py, `python main.py` 30 s later wrote nothing - from the
    # newest's start a.py was left out, and the turn went unchecked.)
    at = now()
    with factory() as s:
        ran(s, "cat a.py", 0, at - timedelta(seconds=40))  # (a read: not where it starts)
        ran(s, "sed -i s/1/2/ a.py", 0, at - timedelta(seconds=30))
        ran(s, "python -m pytest -q", 0, at - timedelta(seconds=20))
        ran(s, "python main.py", 0, at)
        assert proof.unrecorded(s, "r", {"lead"}) == ("python main.py", at - timedelta(seconds=31))


@pytest.mark.skipif(__import__("shutil").which("git") is None, reason="git is not installed")
def test_touched_since_counts_an_earlier_write_and_a_committed_one(tmp_path, monkeypatch):
    import os

    from tests.test_take_in_scenarios import git, repository
    (tmp_path / "gitconfig").write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    folder = tmp_path / "p"
    folder.mkdir()
    for name in ("a.py", "b.py", "c.py", "d.py"):
        (folder / name).write_text("1\n")
    repository(folder)
    head, began = git(folder, "rev-parse", "HEAD"), now() - timedelta(seconds=60)
    (folder / "a.py").write_text("2\n")  # (by the turn's first writing command, 30 s on)
    os.utime(folder / "a.py", (began.timestamp() + 30,) * 2)
    (folder / "b.py").write_text("2\n")  # (written and committed: `black . && git commit`)
    git(folder, "commit", "-qm", "fmt", "b.py")
    (folder / "d.py").write_text("2\n")  # (an hour old: `cp -p` - not seen, a shortcut)
    os.utime(folder / "d.py", (began.timestamp() - 3600,) * 2)
    assert proof.touched_since(folder, began, set()) == ["a.py"]
    assert proof.touched_since(folder, began, set(), head) == ["a.py", "b.py"]
    assert proof.touched_since(folder, began, {"a.py"}, head) == ["b.py"]


def test_exit_0_with_command_not_found_in_its_output_is_passed():
    out = "test_cli.py::test_missing_tool PASSED  (asserts 'bash: foo: command not found')\n3 passed\n"
    assert proof.tests_row(RUN, 0, out, "exited", "")["state"] == "passed"


@pytest.mark.parametrize(("command", "code", "output"), [
    ("python -m unittest", 5, "\n------\nRan 0 tests in 0.000s\n\nNO TESTS RAN\n"),
    ("python -m unittest discover", 0, "Ran 0 tests in 0.000s\n\nOK\n"),
    ("npx jest", 1, "No tests found, exiting with code 1\n"),
    ("npx vitest run", 1, "No test files found, exiting with code 1\n"),
])
def test_a_run_that_ran_no_test_is_said_so_for_unittest_jest_and_vitest(command, code, output):
    made = proof.tests_row(proof.TestRun(command, ".", True), code, output, "exited", "")
    assert (made["state"], made["text"]) == (
        "not_run", f"Tests ran none: {command} collected no test")


def test_only_skipped_is_not_a_pass():
    made = proof.tests_row(RUN, 0, "sss\n3 skipped in 0.01s\n", "exited", "")
    assert (made["state"], made["text"]) == (
        "not_run", "Tests skipped only: pytest -q - 3 skipped in 0.01s")


def test_an_exit_0_with_no_runner_count_passes_by_exit_code_and_says_so():
    made = proof.tests_row(proof.TestRun("npm test", ".", False), 0, "> node t.js\nall good\n",
                           "exited", "")
    assert (made["state"], made["text"]) == (
        "passed", "Tests passed (by exit code, no count): npm test (guessed)")


def test_a_merged_branch_change_counts_from_when_it_was_made(factory):
    # (A branch turn's work, merged at its end: its rows are "merged", decided at the merge.)
    at = now()
    with factory() as s:
        change(s, "a.py", "1\n", "2\n", status="merged", at=at - timedelta(seconds=30))
        s.query(FileChange).update({"decided_at": at})
        s.commit()
        (found,) = proof.changes(s, "r", "lead")
        assert found.in_project and found.path == "a.py"
        assert proof.last_change(s, "r") == at - timedelta(seconds=30)


def test_a_masked_exit_is_no_verdict_unless_it_counts_a_failure():
    # (As S4 reads a run: `| tail -1`, `|| true` - the exit is not the tests'.)
    masked = proof.TestRun("pytest -q | tail -1", ".", True)
    made = proof.tests_row(masked, 0, "3 passed in 0.1s\n", "exited", "")
    assert (made["state"], made["text"]) == (
        "not_run", "Tests gave no verdict: pytest -q | tail -1 masks its exit")
    assert proof.tests_row(masked, 0, "1 failed, 2 passed\n", "exited", "")["state"] == "failed"


def test_a_recipe_agents_run_where_the_lead_works_stands_across_its_take_in(factory):
    # (Plan decision 13: a recipe's Tester ran the same command on what its copy then held - what
    # Take in brought into the project: no second run. The Lead's own run before the Take in did
    # not see it.)
    at = now()
    with factory() as s:
        s.add(Agent(id="tester", run_id="r", role_name="Tester", tools=[], depth=1))
        s.commit()
        change(s, "calc.py", "1\n", "2\n", agent="coder", at=at - timedelta(seconds=30))
        ran(s, "pytest -q", 0, at - timedelta(seconds=10), agent="tester")
        ran(s, "pytest -q", 0, at - timedelta(seconds=10))
        s.query(FileChange).update({"decided_at": at})  # (taken in after both runs)
        s.commit()
        sharing = {"lead", "coder", "tester"}
        found = proof.fresh(s, "r", "lead", RUN, proof.last_change(s, "r"), sharing,
                            proof.last_change(s, "r", sharing))
        assert found is not None and found.agent_id == "tester"
        assert proof.fresh(s, "r", "lead", RUN, proof.last_change(s, "r")) is None


# --- S10: Check after a change for one chat -------------------------------------------------

@pytest.mark.parametrize(("project", "chat", "said"), [
    ("check", None, "check"), ("tests", None, "tests"), ("nothing", None, "nothing"),
    ("check", "off", "off"), ("nothing", "off", "off"),
    ("nothing", "on", "check"), ("tests", "on", "tests"), ("check", "on", "check"),
])
def test_after_change_of_a_chat(factory, project, chat, said):
    with factory() as s:
        s.get_one(Project, "p").after_change = project
        conversation = s.get_one(Conversation, "c")
        conversation.after_change = chat
        assert proof.after_change_of(s, conversation, s.get_one(Run, "r")) == said


def test_a_recipe_turn_follows_the_recipe_not_the_chats_switch(factory):
    # (Today the recipe's is the project's: S5c gives a recipe a Checks step of its own.)
    with factory() as s:
        conversation = s.get_one(Conversation, "c")
        run = s.get_one(Run, "r")
        run.teams = [{"team_id": "t", "name": "Backend / API"}]
        conversation.after_change = "off"
        assert proof.after_change_of(s, conversation, run) == "check"
        s.get_one(Project, "p").after_change = "nothing"
        conversation.after_change = "on"
        assert proof.after_change_of(s, conversation, run) == "nothing"


# --- S3: what is looked over ----------------------------------------------------------------

def _change(path, added, kind=None):
    return proof.Change(path, kind or proof.kind_of(path), added, 0, False, "lead", True)


def test_review_reasons_big_by_lines_and_files_of_code_only():
    assert proof.review_reasons([_change("a.py", 81)], "").big
    assert not proof.review_reasons([_change("a.py", 80)], "").big
    # (Documents are not counted: 4 .md files are not big; 4 .py are.)
    assert not proof.review_reasons([_change(f"d{i}.md", 30) for i in range(4)], "").big
    assert proof.review_reasons([_change(f"m{i}.py", 1) for i in range(4)], "").big
    said = proof.review_reasons([_change("a.py", 3), _change("b.md", 100)], "")
    assert (said.lines, said.files) == (3, 1)


def test_security_by_path_word_and_added_line_only():
    diff = ("--- a/app/utils.py\n+++ b/app/utils.py\n+import subprocess\n"
            "+subprocess.run(x, shell=True)\n-eval(old)\n")
    said = proof.review_reasons([_change("app/utils.py", 2)], diff)
    assert "shell=True (added in app/utils.py)" in said.security
    assert not any(one.startswith("eval(") for one in said.security)  # (a removed line)
    assert proof.review_reasons([_change("app/auth/session.py", 1)], "").security == [
        "app/auth/session.py (path)"]
    assert proof.review_reasons([_change(".env.local", 1)], "").security
    assert not proof.review_reasons([_change("app/main.py", 1)], "+x = 1\n").security


def test_turn_diff_is_cut_names_what_is_left_out_and_shows_no_secret(factory):
    with factory() as s:
        change(s, "a.py", None, "".join(f"a{i} = {i}\n" for i in range(50)))
        change(s, "b.py", None, "".join(f"b{i} = {i}\n" for i in range(50)))
        change(s, ".env", None, "KEY=very-secret\n")
        shown, whole, left = proof.turn_diff(s, "r", "lead", 600)
    assert "+++ b/a.py" in shown and "a49 = 49" in shown and left == ["b.py"]
    assert len(whole) > len(shown) and "b49 = 49" in whole and "very-secret" not in whole
    with factory() as s:
        whole, _total, left = proof.turn_diff(s, "r", "lead", 100_000)
    assert left == [] and ".env: a secret file - changed, not shown" in whole
    assert "very-secret" not in whole



@pytest.mark.parametrize(("path", "touches"), [
    ("app/auth.py", True), ("app/authentication.py", True), ("src/oauth2.py", True),
    ("app/tokens.py", True), ("app/sessions.py", True), ("app/auth/session.py", True),
    ("AUTHORS.md", False), ("docs/authors.md", False), ("src/author.py", False),
    ("styles/tokens.css", True), ("nlp/tokenizer.py", False), ("aclocal.m4", False),
    ("cookiecutter.json", False), ("src/sessionize.py", False),
    # (Words of a name split on "_" and camelCase: a missed look is worse than one too many.)
    ("app/user_auth.py", True), ("app/api_tokens.py", True), ("web/userAuth.ts", True),
    ("app/policy_net.py", True),
])
def test_security_path_words_are_whole_words(path, touches):
    # (Review of S3: "author", "tokenizer", "aclocal" are no sign-in, token or ACL code.)
    assert bool(proof.review_reasons([_change(path, 1)], "").security) is touches



def test_the_projects_page_says_the_reviewers_size_as_the_gate_reads_it():
    from app.schemas import ProjectOut
    fields = ProjectOut.model_fields
    assert (fields["review_lines"].default, fields["review_files"].default) == (
        proof.BIG_LINES, proof.BIG_FILES)



@pytest.mark.parametrize("line", [
    "pytest -q --cov=. --cov-report=json:.koloni/tmp/coverage-x>o.txt;true",
    "pytest -q --cov=. --cov-report=json:.koloni/tmp/coverage-x||true",
    "pytest -q --cov=. --cov-report=json:.koloni/tmp/coverage-x/../../../x;exit",
    "pytest -q --cov=. --cov-report=json:.koloni/tmp/coverage-0123456789ab/coverage.json",
])
def test_an_agents_coverage_look_alike_is_no_pass_of_the_command(factory, line):
    # (S9 review, 22 Nov: an agent's line that looks like KOLONİ's flagged run folded to the
    # user's `pytest -q` - a fake "Tests passed ... run by the Orchestrator", the suite unrun)
    run, at = proof.TestRun("pytest -q", ".", True), now()
    with factory() as s:
        s.add(Command(run_id="r", agent_id="lead", command=line, cwd=".", location="host",
                      status="exited", exit_code=0, output="", timeout_seconds=60,
                      started_at=at, ended_at=at + timedelta(seconds=1)))
        s.commit()
        assert proof.fresh(s, "r", "lead", run, at - timedelta(seconds=30)) is None


KOLONIS = "pytest -q --cov=. --cov-report=json:{out}/.koloni/tmp/coverage-0123456789ab/coverage.json"


@pytest.mark.parametrize(("line", "args", "known"), [
    (KOLONIS.format(out="."), {"known_as": "pytest -q"}, True),
    # (S9 re-check: a part under a Windows profile folder - a space, parentheses - in quotes)
    (KOLONIS.format(out='"C:/Users/John Smith/My Project (copy)/web"').replace(
        'web"/.koloni/tmp/coverage-0123456789ab/coverage.json', 'web/.koloni/tmp/'
        'coverage-0123456789ab/coverage.json"'), {"known_as": "pytest -q"}, True),
    (KOLONIS.format(out="."), {}, False),  # (no word of what it was built from: its own line)
    (KOLONIS.format(out="."), {"known_as": "pytest -q", "command": "pytest -q --other"}, False),
])
def test_kolonis_own_flagged_run_is_known_by_the_command_it_built_it_from(factory, line, args,
                                                                         known):
    run, at = proof.TestRun("pytest -q", ".", True), now()
    with factory() as s:
        said = Message(conversation_id="c", run_id="r", agent_id="lead", role="assistant",
                       content="done")
        s.add(said)
        s.flush()
        call = ToolCall(run_id="r", agent_id="lead", message_id=said.id, seq=0,
                        provider_call_id=f"{proof.PROOF_CALL}x", name="run_command",
                        arguments=json.dumps({"command": line, **args}))
        s.add(call)
        s.flush()
        s.add(Command(run_id="r", agent_id="lead", command=line, cwd=".", location="host",
                      status="exited", exit_code=0, output="", timeout_seconds=60,
                      tool_call_id=call.id, started_at=at, ended_at=at + timedelta(seconds=1)))
        s.commit()
        assert (proof.fresh(s, "r", "lead", run, at - timedelta(seconds=30)) is not None) is known
