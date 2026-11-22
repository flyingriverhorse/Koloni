"""Kanıtlı bitiş (S1), what needs no model: the kind of each changed file, the tests' command(s), a
test run's row, a turn's changes on record, and whether a test run on record is fresh enough to
stand for this turn's (`app.proof`)."""

import json
from datetime import timedelta
from types import SimpleNamespace

import pytest

from app import proof
from app.db.models import Agent, Command, Conversation, FileChange, Message, Project, Run, now
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
