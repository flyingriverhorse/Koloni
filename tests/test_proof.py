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
from app.db.session import make_engine, make_session_factory
from tests.conftest import migrated_copy


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
    migrated_copy(db)  # (one migration a run: 30 s a test on Windows CI)
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


def test_a_copy_waiting_over_a_change_in_the_project_is_still_said_waiting(factory):
    # (k-onceki-1: the path the project holds the Lead's change of is in the project - and the
    # Coder's newer change of it, waiting in its copy, is still said)
    from app.agent.proof_mixin import ProofMixin
    with factory() as s:
        change(s, "a.py", "1\n", "2\n", at=now() - timedelta(seconds=2))
        change(s, "a.py", "2\n", "3\n", agent="coder", status="in_copy", at=now())
        (found,) = proof.changes(s, "r", "lead")
        assert (found.in_project, found.agent_id, found.waiting) == (True, "lead", "coder")
        assert [r["text"] for r in ProofMixin._waiting_rows(s, [found])] == [
            proof.WAITING.format(name="Coder")]


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


def agent_ran(s, command, at, seq, cwd="."):
    """A command an agent ran by its tool call (KOLONİ's own runs have none)."""
    call = ToolCall(run_id="r", agent_id="lead", message_id="m", seq=seq,
                    provider_call_id=f"call_{seq}", name="run_command",
                    arguments=json.dumps({"command": command}))
    s.add(call)
    s.flush()
    s.add(Command(run_id="r", agent_id="lead", tool_call_id=call.id, command=command, cwd=cwd,
                  location="host", status="exited", exit_code=0, output="", timeout_seconds=60,
                  started_at=at - timedelta(seconds=1), ended_at=at))
    s.commit()


def test_unrecorded_names_the_newest_writer_from_the_oldest_ones_start(factory, tmp_path):
    # (Re-check of D: `sed -i` wrote a.py, `python main.py` 30 s later wrote nothing - from the
    # newest's start a.py was left out, and the turn went unchecked.)
    at, project = now(), tmp_path / "project"
    with factory() as s:
        agent_ran(s, "cat a.py", at - timedelta(seconds=50), 0)  # (a read: not where it starts)
        agent_ran(s, "rg KEY .", at - timedelta(seconds=45), 1)  # (a lone search reads too)
        agent_ran(s, "sed -i s/1/2/ a.py", at - timedelta(seconds=30), 2)
        agent_ran(s, "python -m pytest -q", at - timedelta(seconds=20), 3)
        agent_ran(s, "python main.py", at - timedelta(seconds=10), 4, str(project))
        # (CI on b16805f: KOLONİ's own check in a room's copy - no tool call - opened the gate.)
        ran(s, "python check.py --merge", 0, at - timedelta(seconds=5))
        agent_ran(s, "python gen.py", at, 5, str(tmp_path / "copies" / "web"))  # (a working copy's)
        assert proof.unrecorded(s, "r", {"lead"}, str(project)) == (
            "python main.py", at - timedelta(seconds=31))


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


@pytest.mark.parametrize("line", [
    "cat gen.py > calc.py", "> f", "git show HEAD:f > f", "grep -v x a > b", "rg x > f",
    "head -3 a > f", "type a > b", "Get-Content a > b", "npm test -- -u", "npx jest -u",
    "npx vitest run -u", "pytest --snapshot-update", "python -m pytest -q --junitxml=calc.py",
    "pytest -q $(sed -i s/a/b/ a.py)", 'bash -c "pytest -q > a.py"',
    # (CL-336: go's golden files, inline-snapshot's that write, an update asked in the
    # environment, go's test binary at a path, options carried in PYTEST_ADDOPTS)
    "go test ./... -update", "pytest --inline-snapshot=fix", "pytest --inline-snapshot=create",
    "pytest --inline-snapshot=review,update", "INSTA_UPDATE=always cargo test",
    "UPDATE_SNAPSHOTS=1 npx playwright test", "SNAPSHOT_UPDATE=true pytest -q",
    "go test -o x ./...", "PYTEST_ADDOPTS=--junitxml=a.py pytest -q",
    'PYTEST_ADDOPTS="-q --junitxml=a.py" python -m pytest'])
def test_a_redirect_or_a_test_runs_writing_option_may_write(line):
    # (CL-329 G: the end check opened for none of these - `ledger._split` drops a redirection,
    # and a test run was taken as reading only)
    assert proof.may_write(line)


@pytest.mark.parametrize("line", [
    "pytest -q", "pytest -q 2>&1 | tail -1", "git status > /dev/null", "python -m pytest -q > NUL",
    'bash -c "pytest -q"', "rg KEY .", "python -u -m pytest -q", "pytest --cov-report=term",
    "CI=1 pytest -q", "PYTHONPATH=. pytest", "PYTEST_ADDOPTS=-q pytest", "go test -run x ./...",
    "INSTA_UPDATE=no cargo test", "pytest --inline-snapshot=disable", "pytest -o x=1 -q"])
def test_a_stream_nowhere_or_a_plain_test_run_writes_nothing(line):
    assert not proof.may_write(line)


@pytest.mark.skipif(__import__("shutil").which("git") is None, reason="git is not installed")
def test_a_test_file_a_command_deleted_is_counted_and_another_file_is_put_back(tmp_path,
                                                                              monkeypatch):
    from tests.test_take_in_scenarios import repository
    (tmp_path / "gitconfig").write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    folder = tmp_path / "p"
    folder.mkdir()
    for name in ("a.py", "b.py", "test_b.py", "c.py"):
        (folder / name).write_text("1\n")
    repository(folder)
    # (CL-329 G: a tracked test deleted - no time to read - is counted; another file is not)
    (folder / "test_b.py").unlink()
    (folder / "c.py").unlink()
    assert proof.touched_since(folder, now(), set()) == ["test_b.py"]
    assert proof.touched_since(folder, now(), {"test_b.py"}) == []



@pytest.mark.skipif(__import__("shutil").which("git") is None, reason="git is not installed")
def test_what_changed_while_kolonis_run_went_on_is_said_and_put_back_only_by_a_click(
        tmp_path, monkeypatch):
    # (review of k-onceki-2: the run's put-back reverted the user's editor save, newer uncommitted
    # work, another chat's change and an edit after a commit. Nothing is put back by itself now:
    # it is said, and Put back - the user's click - restores one still as the run left it.)
    from tests.test_take_in_scenarios import git, repository
    (tmp_path / "gitconfig").write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    folder = tmp_path / "p"
    folder.mkdir()
    for name in ("a.py", "b.py", "c.py", "d.py", "e.txt", "f.py"):
        (folder / name).write_bytes(b"1\n")
    repository(folder)
    (folder / "c.py").write_bytes(b"C = 2  # the user's uncommitted work\n")
    before = proof.sources_before(folder)
    assert before is not None and before.files == {"c.py": b"C = 2  # the user's uncommitted work\n"}
    # (while the run goes on: the user's editor, newer work, another chat's command, the run's
    # own reformat, a commit then an edit; an agent's write on record; a report it made)
    (folder / "a.py").write_bytes(b"NEW = 'the user saved this'\n")
    (folder / "c.py").write_bytes(b"C = 3  # newer\n")
    (folder / "d.py").write_bytes(b"D = 2  # another chat\n")
    (folder / "b.py").write_bytes(b"B = 1  # reformatted by the run\n")
    (folder / "e.txt").write_bytes(b"committed\n")
    git(folder, "commit", "-qm", "mid-run", "--", "e.txt")
    (folder / "e.txt").write_bytes(b"committed\nstill editing\n")
    (folder / "f.py").write_bytes(b"an agent's\n")
    (folder / "report.xml").write_bytes(b"<r/>")
    changed = proof.changed_during(folder, before, {"f.py"})
    assert sorted(changed) == ["a.py", "b.py", "c.py", "d.py", "e.txt"]
    # (nothing lost without a click)
    assert (folder / "a.py").read_bytes() == b"NEW = 'the user saved this'\n"
    assert (folder / "c.py").read_bytes() == b"C = 3  # newer\n"
    assert (folder / "e.txt").read_bytes() == b"committed\nstill editing\n"
    # (a click: b.py as the run's commit had it, c.py as it was then; one changed again: refused)
    assert proof.put_back(folder, "b.py", before, changed["b.py"]) is None
    assert (folder / "b.py").read_bytes() == b"1\n"
    assert proof.put_back(folder, "c.py", before, changed["c.py"]) is None
    assert (folder / "c.py").read_bytes() == b"C = 2  # the user's uncommitted work\n"
    (folder / "a.py").write_bytes(b"NEW = 'and saved again'\n")
    assert proof.put_back(folder, "a.py", before, changed["a.py"]) == (
        "a.py changed again since KOLONİ's run")
    assert (folder / "a.py").read_bytes() == b"NEW = 'and saved again'\n"
    assert proof.put_back(folder, "../x.py", before, "") == "../x.py is not in the project"


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


def test_a_kolonis_fixers_commands_count_as_a_change_its_reviewers_do_not(factory):
    # (S11 x k-kucuk: `changed_since` leaves out agents KOLONİ opened only where they only read)
    at = now()
    with factory() as s:
        said = Message(conversation_id="c", run_id="r", agent_id="lead", role="assistant",
                       content="done")
        s.add(said)
        s.flush()
        calls = {kind: ToolCall(run_id="r", agent_id="lead", message_id=said.id, seq=n,
                                provider_call_id=f"{proof.PROOF_CALL}{kind}_1",
                                name="spawn_agent", arguments="{}")
                 for n, kind in enumerate(("fix", "review"))}
        s.add_all(calls.values())
        s.flush()
        s.add_all([Agent(id=kind, run_id="r", role_name="Coder", tools=[], depth=1,
                         tool_call_id=call.id) for kind, call in calls.items()])
        ran = Command(run_id="r", agent_id="lead", command="pytest -q", cwd=".",
                      location="host", status="exited", exit_code=0, output="",
                      timeout_seconds=60, started_at=at, ended_at=at + timedelta(seconds=1))
        s.add(ran)
        s.flush()
        s.add(Command(run_id="r", agent_id="review", command="python fix.py", cwd=".",
                      location="host", status="exited", exit_code=0, output="",
                      timeout_seconds=60, started_at=at + timedelta(seconds=2)))
        s.commit()
        assert not proof.changed_since(s, "p", at - timedelta(seconds=5), ran)
        s.add(Command(run_id="r", agent_id="fix", command="python fix.py", cwd=".",
                      location="host", status="exited", exit_code=0, output="",
                      timeout_seconds=60, started_at=at + timedelta(seconds=3)))
        s.commit()
        assert proof.changed_since(s, "p", at - timedelta(seconds=5), ran)
