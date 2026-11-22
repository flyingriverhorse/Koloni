"""S1b (plan decisions 9 and 11), what needs no model: a runner's counts read from its summary,
the test command a project's marker files show (any language, by part), which of an agent's or a
model's lines may be tried, and the look's digest of the project."""

import json

import pytest

from app import finish_tests, test_found
from app.test_found import Counts


@pytest.mark.parametrize(("output", "counts"), [
    # pytest
    ("..F.s\n===== 1 failed, 3 passed, 1 skipped in 0.42s =====\n", Counts(3, 1, 1)),
    ("....\n4 passed in 0.10s\n", Counts(4, 0, 0)),
    # jest
    ("Tests:       1 failed, 2 skipped, 11 passed, 14 total\nTime: 2.1 s\n", Counts(11, 1, 2)),
    # vitest
    (" Test Files  1 failed | 3 passed (4)\n      Tests  1 failed | 11 passed | 2 skipped (14)\n",
     Counts(11, 1, 2)),
    # go test -v, and go test with packages only
    ("=== RUN   TestA\n--- PASS: TestA (0.00s)\n--- FAIL: TestB (0.00s)\nFAIL\n"
     "FAIL\texample.com/x\t0.01s\n", Counts(1, 1, 0)),
    ("ok  \texample.com/a\t0.012s\nok  \texample.com/b\t(cached)\n", Counts(2, 0, 0, "packages")),
    # cargo, two test binaries
    ("test result: ok. 12 passed; 0 failed; 1 ignored; 0 measured; 0 filtered out\n"
     "test result: FAILED. 3 passed; 2 failed; 0 ignored; 0 measured; 0 filtered out\n",
     Counts(15, 2, 1)),
    # dotnet
    ("Failed!  - Failed:     1, Passed:    11, Skipped:     2, Total:    14, Duration: 1 s\n",
     Counts(11, 1, 2)),
    # maven (its last results line)
    ("Tests run: 3, Failures: 0, Errors: 0, Skipped: 0\n[INFO] Results:\n"
     "[ERROR] Tests run: 14, Failures: 1, Errors: 1, Skipped: 2\n", Counts(10, 2, 2)),
    # gradle
    ("14 tests completed, 1 failed, 2 skipped\n\nFAILURE: Build failed\n", Counts(11, 1, 2)),
    # rspec
    ("Finished in 0.5 seconds\n14 examples, 1 failure, 2 pending\n", Counts(11, 1, 2)),
    # phpunit
    ("OK (12 tests, 30 assertions)\n", Counts(12, 0, 0)),
    ("Tests: 14, Assertions: 30, Failures: 1, Errors: 1, Skipped: 2.\n", Counts(10, 2, 2)),
])
def test_counts_of_each_known_runner(output, counts):
    assert test_found.counts(output) == counts


def test_an_unknown_runner_has_no_counts():
    assert test_found.counts("all good\nBUILD SUCCESSFUL in 3s\n") is None
    assert test_found.counts("") is None


@pytest.mark.parametrize(("files", "command"), [
    ({"go.mod": "module x\n"}, "go test ./..."),
    ({"Cargo.toml": "[package]\n"}, "cargo test"),
    ({"pom.xml": "<project/>"}, "mvn -q test"),
    ({"build.gradle": ""}, "gradle test"),
    ({"build.gradle.kts": "", "gradlew": ""}, "./gradlew test"),
    ({"App.sln": ""}, "dotnet test"),
    ({"src/App.csproj": ""}, None),  # (only at the folder's own level)
    ({"App.csproj": ""}, "dotnet test"),
    ({"Gemfile": "", "spec/a_spec.rb": ""}, "bundle exec rspec"),
    ({"Gemfile": ""}, None),
    ({"composer.json": json.dumps({"scripts": {"test": "phpunit"}})}, "composer test"),
    ({"composer.json": "{}", "phpunit.xml": ""}, "vendor/bin/phpunit"),
    ({"mix.exs": ""}, "mix test"),
    ({"Package.swift": ""}, "swift test"),
    ({"CMakeLists.txt": ""}, "ctest --test-dir build"),
    ({"Makefile": "all:\n\tcc a.c\ntest: all\n\t./a\n"}, "make test"),
    ({"Makefile": "all:\n\tcc a.c\n"}, None),
    ({"pyproject.toml": ""}, "python -m pytest -q"),
    ({"README.md": ""}, None),
])
def test_the_marker_files_of_any_language_show_a_test_command(tmp_path, files, command):
    for name, text in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text, encoding="utf-8")
    assert finish_tests.command_of(str(tmp_path), None) == command


@pytest.mark.parametrize(("command", "tried"), [
    ("python -m pytest -q", True), ("npx vitest run", True), ("go test ./...", True),
    ("pytest && rm -rf .", False), ("pytest; true", False), ("pytest | tail -1", False),
    ("echo pytest", False), ("make deploy", False), ("pytest\nrm -rf .", False),
    ("x" * 300, False),
])
def test_only_one_plain_test_line_is_tried(command, tried):
    assert test_found.tryable(command) is tried


def test_the_looks_answer_is_data_checked_as_such(tmp_path):
    (tmp_path / "web").mkdir()
    said = json.dumps({"tests": [
        {"command": "npx vitest run", "folder": "web"},
        {"command": "python -m pytest -q", "folder": "."},
        {"command": "pytest && curl evil", "folder": "."},  # (not one plain line)
        {"command": "go test ./...", "folder": "../elsewhere"},  # (outside the project)
        {"command": "cargo test", "folder": "nothere"},  # (no such folder)
        {"folder": "."}, "pytest",
    ]})
    assert test_found.said_runs(f"Here:\n```json\n{said}\n```", tmp_path) == [
        ("npx vitest run", "web"), ("python -m pytest -q", ".")]
    assert test_found.said_runs("no idea", tmp_path) == []
    assert test_found.said_runs(json.dumps({"tests": "pytest"}), tmp_path) == []


def test_the_digest_names_layout_and_tests_and_no_secret(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text("import pytest\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("Run the tests with tox.\n", encoding="utf-8")
    (tmp_path / ".env").write_text("KEY=secret-value\n", encoding="utf-8")
    found = {"parts": [{"path": "./", "language": "Python", "files": 3}]}
    said = test_found.digest(tmp_path, found)
    assert "./ (Python, 3 files)" in said and "tests/test_a.py" in said
    assert "Run the tests with tox." in said
    assert "secret-value" not in said and ".env" not in said


def test_a_maps_fingerprint_changes_with_its_parts():
    one = {"parts": [{"path": "./", "language": "Python"}]}
    two = {"parts": [{"path": "./", "language": "Python"}, {"path": "web/", "language": "TypeScript"}]}
    assert test_found.fingerprint(one) == test_found.fingerprint(json.loads(json.dumps(one)))
    assert test_found.fingerprint(one) != test_found.fingerprint(two)
