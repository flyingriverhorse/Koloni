"""0.1.7 (the user, 23 Nov): Take in's check runs only the test files a sub-agent wrote or changed,
each with its part's test command narrowed to them (`proof_related.own_tests`) - never the whole
suite; Test before adding is gone (migration 0175), and the root is a part the user may set a test
command for, project file or not."""

import sqlite3
from pathlib import Path

import pytest
from alembic import command as alembic

from app.agent import CHECK_PRESS_RUN
from app.proof import TestRun as Run  # (not Test*: pytest would collect it)
from app.proof_related import NO_OWN_TESTS, own_tests
from tests.keyed import OWN
from tests.test_chat_flow import text
from tests.test_claim_scenarios import write
from tests.test_migration_0002 import _config
from tests.test_parallel import until
from tests.test_spawn import call, step
from tests.test_take_in_scenarios import LONG

PYTEST = Run("python -m pytest -q", ".", True)


def test_only_the_tests_it_wrote_each_with_its_parts_runner_narrowed(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_new.py").write_text("def test_a(): pass\n", encoding="utf-8")
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "x.test.ts").write_text("", encoding="utf-8")
    web = Run("npx vitest run", "web", True)
    owns, said = own_tests(
        [PYTEST, web], ["tests/test_new.py", "app.py", "web/x.test.ts"], tmp_path
    )
    runs = [one.run for one in owns]
    assert runs[0] == PYTEST._replace(command="python -m pytest -q tests/test_new.py")
    assert runs[1].cwd == "web" and runs[1].command.endswith("x.test.ts") and said == []
    assert [one.part for one in owns] == [PYTEST, web]  # (beside it: the part's own line)


def test_none_written_none_run_and_a_runner_it_cannot_narrow_is_said(tmp_path):
    assert own_tests([PYTEST], ["app.py", "README.md"], tmp_path) == ([], [NO_OWN_TESTS])
    (tmp_path / "test_new.py").write_text("def test_a(): pass\n", encoding="utf-8")
    runs, said = own_tests([Run("python check.py", ".", True)], ["test_new.py"], tmp_path)
    assert runs == [] and said == [
        ".: its test command (python check.py) cannot run just these files (its runner is not "
        "one KOLONİ narrows) - not run"
    ]
    # (a test in no part that has a runner: said, never the whole suite)
    runs, said = own_tests([Run("npm test", "web", True)], ["test_new.py"], tmp_path)
    assert runs == [] and said == ["test_new.py: no test command of its part - not run"]


def test_the_root_is_a_part_its_test_command_may_be_set_for_with_no_project_file(
    make_client, project_dir
):
    client, _model = make_client([])
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    assert client.get(f"/api/projects/{pid}/map").json()["parts"] == []
    put = client.put(
        f"/api/projects/{pid}/map/test", json={"path": "./", "command": "pytest -q"}, headers=OWN
    )
    assert put.status_code == 200, put.text
    (root,) = put.json()["parts"]
    assert (root["path"], root["language"], root["test"], root["edited"]) == (
        "./",
        "none",
        "pytest -q",
        True,
    )
    # (the old field is no field of the API's any more: a body naming it changes nothing)
    assert "check_command" not in client.get(f"/api/projects/{pid}").json()


def test_the_migration_drops_test_before_adding_and_going_back_adds_it_empty(tmp_path):
    db = tmp_path / "m.db"
    cfg = _config(db)
    alembic.upgrade(cfg, "0174")
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO projects (id, name, root_path, created_at, check_command) "
            "VALUES ('p', 'p', 'C:/p', '2026-11-23', 'pytest -q')"
        )
    alembic.upgrade(cfg, "0175")

    def columns():
        with sqlite3.connect(db) as conn:
            return [row[1] for row in conn.execute("PRAGMA table_info(projects)")]

    assert "check_command" not in columns()
    alembic.downgrade(cfg, "0174")
    assert "check_command" in columns()
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT check_command FROM projects").fetchall() == [(None,)]


# --- round 2 (the review's HOLD): whose command runs a sub-agent's own tests, and what is said --


def evil(marker: Path) -> str:
    """A sub-agent's test that does something the moment pytest imports it."""
    return f"open({str(marker)!r}, 'w').write('x')\n\n\ndef test_a():\n    pass\n"


@pytest.mark.parametrize("mode", ["ask", "auto_edit"])
def test_a_guess_never_runs_a_sub_agents_own_tests_before_the_users_click(
    make_client, wait_run, project_dir, tmp_path, monkeypatch, mode
):
    """B1: KOLONİ's guess of the test command, narrowed to the sub-agent's test, ran it - its
    code - before the card at Ask and Auto-edit, unasked. It waits on the card for Run the test,
    and nothing is taken before."""
    from tests.test_take_in_scenarios import card, guessed, start

    guessed(monkeypatch, project_dir)
    marker = tmp_path / "RAN-UNASKED"
    client, _pid, cid, run_id = start(
        make_client,
        project_dir,
        [step(write("test_evil.py", evil(marker))), text("done")],
        project={"after_change": "nothing"},
        permission_mode=mode,
    )
    merge = card(client, cid)
    assert not marker.exists(), merge["check"]
    assert merge["check"]["state"] == "not_run" and CHECK_PRESS_RUN in merge["check"]["note"]
    assert not (project_dir / "test_evil.py").exists()  # (not taken before the check either)
    # (the user's click is its leave: it runs, on the card)
    assert client.post(f"/api/merges/{merge['id']}/check").status_code == 200
    until(client, cid, lambda s: s["merges"][0]["check"]["state"] == "passed", timeout=LONG)
    assert marker.exists()
    assert client.post(f"/api/merges/{merge['id']}/approve").status_code == 200
    wait_run(client, cid, run_id, timeout=LONG)


def test_at_full_auto_a_guess_runs_by_itself_and_the_users_own_command_at_every_level(
    make_client, wait_run, project_dir, tmp_path, monkeypatch
):
    from tests.test_take_in_scenarios import guessed, start

    guessed(monkeypatch, project_dir)
    marker = tmp_path / "RAN"
    client, _pid, cid, run_id = start(
        make_client,
        project_dir,
        [step(write("test_evil.py", evil(marker))), text("done")],
        project={"after_change": "nothing"},
    )
    (merge,) = wait_run(client, cid, run_id, timeout=LONG)["merges"]
    assert merge["check"]["state"] == "passed" and merge["status"] == "applied"
    assert marker.exists()


@pytest.mark.parametrize("ticked", [True, False])
def test_a_ticked_leave_for_a_saved_command_covers_its_narrowed_line(
    make_client, wait_run, project_dir, ticked
):
    """B3: a trigger's turn - a saved command an Always rule covers is the user's own; the
    trigger's tick for it (the line they can know) covers the line narrowed to the Coder's
    test, which only adds the file to it."""
    from app.db.models import Project
    from tests.test_take_in_scenarios import (
        CHECK,
        LINES,
        ORIGIN,
        RUNS,
        own_test,
    )
    from tests.test_trigger_scenarios import allow, run_now, trigger

    (project_dir / "lines.txt").write_bytes(LINES.encode())
    (project_dir / "check.py").write_bytes(CHECK.encode())
    client, _model = make_client(
        {
            "Lead": [
                step(call("spawn_agent", {"role": "Coder", "task": "do it"}, "s")),
                text("done"),
            ],
            "Coder": [step(write("a.txt", "A")), own_test("NEVER-THERE"), text("A done")],
        }
    )
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    patched = client.patch(f"/api/projects/{pid}", json={"after_change": "nothing"})
    assert patched.status_code == 200
    with client.app.state.session_factory() as session:  # (saved by KOLONİ, and Always)
        session.get_one(Project, pid).tests_found = {".": {"command": RUNS, "always": True}}
        session.commit()
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    rules = [allow(client, cid, RUNS)] if ticked else []
    made = trigger(client, pid, cid, permissions={"write": True, "commands": rules, "agents": 1})
    snap = wait_run(client, cid, run_now(client, made["id"]), timeout=LONG)
    (merge,) = snap["merges"]
    if ticked:  # (it ran, failed: nothing taken, the copy kept for the user)
        assert merge["check"]["state"] == "failed" and merge["status"] == "kept", merge["check"]
    else:
        assert merge["check"]["state"] == "not_run" and merge["status"] == "applied"
        assert "does not let this command run" in merge["check"]["note"]


def test_a_command_that_cannot_run_just_its_files_is_said_on_the_card_and_in_checked(
    make_client, wait_run, project_dir
):
    """B2: what `own_tests` says was dropped - the card said "No tests of its own"."""
    import sys

    from tests.test_proof_end_scenarios import texts
    from tests.test_take_in_scenarios import own_test, root_runs, start

    command = f"{sys.executable} check.py one"
    client, _pid, cid, run_id = start(
        make_client,
        project_dir,
        [step(write("a.txt", "A")), own_test("one"), text("A done")],
        project=root_runs(command, after_change="check"),
        permission_mode="auto_edit",
    )
    snap = wait_run(client, cid, run_id, timeout=LONG)
    (merge,) = snap["merges"]
    said = (
        f".: its test command ({command}) cannot run just these files (its runner is not one "
        "KOLONİ narrows) - not run"
    )
    assert merge["check"]["command"] == "" and merge["check"]["note"] == said, merge["check"]
    assert client.post(f"/api/merges/{merge['id']}/check").status_code == 409
    assert f"Take in's check of Coder's work: {said}" in texts(snap), texts(snap)


def test_a_part_not_run_is_said_beside_a_pass(make_client, wait_run, project_dir):
    from tests.test_take_in_scenarios import own_test, root_runs, start

    (project_dir / "web").mkdir()
    (project_dir / "web" / "package.json").write_text(
        '{"name": "w", "scripts": {"test": "make test"}}', encoding="utf-8"
    )
    client, _pid, cid, run_id = start(
        make_client,
        project_dir,
        [
            step(write("a.txt", "A")),
            own_test("one"),
            step(write("web/x.test.js", "test('x', () => {})\n", "wx")),
            text("A done"),
        ],
        project=root_runs(),
    )
    (merge,) = wait_run(client, cid, run_id, timeout=LONG)["merges"]
    assert merge["check"]["state"] == "passed", merge["check"]
    assert (
        "web: its test command (npm test) cannot run just these files (its test script is not "
        "vitest or jest alone) - not run"
    ) in merge["check"]["note"]


def test_tests_that_ran_none_are_said_not_failed(make_client, wait_run, project_dir):
    """pytest's exit 5 (none collected): a note - the work goes in as one with no test would."""
    from tests.test_take_in_scenarios import root_runs, start

    client, _pid, cid, run_id = start(
        make_client,
        project_dir,
        [step(write("test_none.py", "x = 1\n")), text("done")],
        project=root_runs(),
    )
    (merge,) = wait_run(client, cid, run_id, timeout=LONG)["merges"]
    assert merge["check"]["state"] == "not_run" and merge["status"] == "applied"
    assert ".: no test of these files was found - nothing ran" in merge["check"]["note"]


def test_nothing_ran_is_read_from_each_runners_words():
    from app.agent import _nothing_ran

    assert _nothing_ran("python -m pytest -q test_none.py", 5, "no tests ran")
    assert not _nothing_ran("python -m pytest -q test_a.py", 1, "1 failed")
    # (vitest 5, measured: its words with --passWithNoTests, exit 0)
    said = "No test files found, exiting with code 0\n"
    assert _nothing_ran("npx --no vitest related --run --passWithNoTests x.ts", 0, said)
    assert not _nothing_ran("npx --no vitest related --run --passWithNoTests x.ts", 0, "1 passed")


def test_a_package_json_the_copy_changed_runs_none_of_its_scripts(tmp_path):
    copy, project = tmp_path / "copy", tmp_path / "project"
    for root, script in ((project, "vitest"), (copy, "vitest --config C:/elsewhere/v.mjs")):
        (root / "web").mkdir(parents=True)
        (root / "web" / "package.json").write_text(
            f'{{"scripts": {{"test": "{script}"}}}}', encoding="utf-8"
        )
        (root / "web" / "x.test.ts").write_text("", encoding="utf-8")
    npm = Run("npm test", "web", True)
    owns, said = own_tests([npm], ["web/package.json", "web/x.test.ts"], copy, project)
    assert owns == [] and said == [
        "web: the sub-agent changed package.json's test scripts - its tests are not run before "
        "it is added"
    ]
    # (`#` in its script: npm's shell would end the line there)
    (project / "web" / "package.json").write_text(
        '{"scripts": {"test": "vitest # x"}}', encoding="utf-8"
    )
    owns, said = own_tests([npm], ["web/x.test.ts"], project, project)
    assert owns == [] and "cannot run just these files" in said[0]


def test_test_files_of_more_languages_are_its_own_tests(tmp_path):
    from app.proof_related import is_test_file

    for one in ("src/FooTest.java", "FooTests.cs", "tests/it.rs", "a_spec.rb", "b_test.rb"):
        assert is_test_file(one), one
    assert not is_test_file("src/Foo.java") and not is_test_file("src/lib.rs")
    owns, said = own_tests([Run("mvn test", ".", True)], ["src/FooTest.java"], tmp_path)
    assert owns == [] and "cannot run just these files" in said[0]  # (never "no tests of its own")


def test_a_test_file_pytest_is_named_runs_whatever_a_parent_testpaths_says(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\ntestpaths = ['tests']\n", encoding="utf-8"
    )
    (tmp_path / "proj" / "tests").mkdir(parents=True)
    (tmp_path / "proj" / "tests" / "test_a.py").write_text("def test_a(): pass\n")
    owns, said = own_tests([PYTEST], ["tests/test_a.py"], tmp_path / "proj")
    assert [one.run.command for one in owns] == ["python -m pytest -q tests/test_a.py"], said


def test_the_whole_projects_no_test_stops_the_guess(monkeypatch):
    from types import SimpleNamespace

    from app import proof

    monkeypatch.setattr(proof.finish_tests, "command_of", lambda _root, _check: "pytest -q")
    project = SimpleNamespace(root_path="x", test_commands={"./": ""}, tests_found={})
    assert proof.test_runs(project, None) == []
    assert proof.test_runs(SimpleNamespace(**{**vars(project), "test_commands": {}}), None)
