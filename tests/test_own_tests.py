"""0.1.7 (the user, 23 Nov): Take in's check runs only the test files a sub-agent wrote or changed,
each with its part's test command narrowed to them (`proof_related.own_tests`) - never the whole
suite; Test before adding is gone (migration 0174), and the root is a part the user may set a test
command for, project file or not."""

import sqlite3

from alembic import command as alembic

from app.proof import TestRun
from app.proof_related import NO_OWN_TESTS, own_tests
from tests.keyed import OWN
from tests.test_migration_0002 import _config

PYTEST = TestRun("python -m pytest -q", ".", True)


def test_only_the_tests_it_wrote_each_with_its_parts_runner_narrowed(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_new.py").write_text("def test_a(): pass\n", encoding="utf-8")
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "x.test.ts").write_text("", encoding="utf-8")
    web = TestRun("npx vitest run", "web", True)
    runs, said = own_tests(
        [PYTEST, web], ["tests/test_new.py", "app.py", "web/x.test.ts"], tmp_path
    )
    assert runs[0] == PYTEST._replace(command="python -m pytest -q tests/test_new.py")
    assert runs[1].cwd == "web" and runs[1].command.endswith("x.test.ts") and said == []


def test_none_written_none_run_and_a_runner_it_cannot_narrow_is_said(tmp_path):
    assert own_tests([PYTEST], ["app.py", "README.md"], tmp_path) == ([], [NO_OWN_TESTS])
    (tmp_path / "test_new.py").write_text("def test_a(): pass\n", encoding="utf-8")
    runs, said = own_tests([TestRun("python check.py", ".", True)], ["test_new.py"], tmp_path)
    assert runs == [] and said == [
        ".: its test command (python check.py) cannot run just these files - not run"
    ]
    # (a test in no part that has a runner: said, never the whole suite)
    runs, said = own_tests([TestRun("npm test", "web", True)], ["test_new.py"], tmp_path)
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
    alembic.upgrade(cfg, "0173")
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO projects (id, name, root_path, created_at, check_command) "
            "VALUES ('p', 'p', 'C:/p', '2026-11-23', 'pytest -q')"
        )
    alembic.upgrade(cfg, "0174")

    def columns():
        with sqlite3.connect(db) as conn:
            return [row[1] for row in conn.execute("PRAGMA table_info(projects)")]

    assert "check_command" not in columns()
    alembic.downgrade(cfg, "0173")
    assert "check_command" in columns()
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT check_command FROM projects").fetchall() == [(None,)]
