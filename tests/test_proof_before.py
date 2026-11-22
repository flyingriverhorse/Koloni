"""Kanıtlı bitiş S7, what needs no model: the tests a failing run names, the line that runs them
alone, a bug-fix turn's words, new test files, and the last green state's words."""

import sys

import pytest

from app import proof_before


def test_failed_ids_pytest_vitest_jest():
    out = ("FAILED tests/test_a.py::test_x - assert 1 == 2\nERROR tests/test_b.py::test_y\n"
           "FAILED tests/test_a.py::test_x - again\n=== 2 failed in 0.1s ===\n")
    assert proof_before.failed_ids("python -m pytest -q", out) == [
        "tests/test_a.py::test_x", "tests/test_b.py::test_y"]
    assert proof_before.failed_ids("npx vitest run", " FAIL  src/a.test.ts > adds\n") == [
        "src/a.test.ts"]
    assert proof_before.failed_ids("npx jest", "FAIL src/b.test.js\n") == ["src/b.test.js"]
    assert proof_before.failed_ids("make test", "FAILED x\n") == []
    # (coloured output is read as plain)
    assert proof_before.failed_ids("pytest", "\x1b[31mFAILED t.py::a\x1b[0m - x\n") == ["t.py::a"]


def test_alone_builds_a_rerun_or_none():
    quoted = '"t.py::a"' if sys.platform == "win32" else "t.py::a"
    assert proof_before.alone("python -m pytest -q", ["t.py::a"]) == f"python -m pytest -q {quoted}"
    files = '"a.test.ts"' if sys.platform == "win32" else "a.test.ts"
    assert proof_before.alone("npm test", ["a.test.ts"]) == f"npm test -- {files}"
    assert proof_before.alone("npx vitest run", ["a.test.ts"]) == f"npx vitest run {files}"
    assert proof_before.alone("pytest -q | tail -1", ["t.py::a"]) is None  # (its exit masked)
    assert proof_before.alone("pytest", ["t.py::a'b"]) is None
    assert proof_before.alone("make test", ["t"]) is None
    assert proof_before.alone("pytest", []) is None


@pytest.mark.parametrize(("words", "fix"), [
    ("fix the crash in calc", True), ("bu hatayı düzelt", True), ("add a page", False)])
def test_a_bug_fix_by_its_words(words, fix):
    assert bool(proof_before.BUGFIX.search(words)) is fix


def test_new_tests_and_the_green_words():
    assert proof_before.new_tests(["tests/test_a.py", "a.py", "web/x.test.ts", "b_test.go"]) == [
        "tests/test_a.py", "web/x.test.ts", "b_test.go"]
    assert proof_before.green_said(None, 3, 0) == []
    assert proof_before.green_said({"ran": 214, "skipped": 3}, 210, 9) == [
        "Tests went from 214 to 210 (4 removed)", "Skipped rose from 3 to 9"]
    assert proof_before.green_said({"ran": 4, "skipped": 0}, 5, 0) == []



def test_passed_ids_as_the_run_lists_them_or_none():
    out = "tests/test_a.py::test_x PASSED\ntests/test_a.py::test_y PASSED\n=== 2 passed ===\n"
    assert proof_before.passed_ids("python -m pytest -v", out) == [
        "tests/test_a.py::test_x", "tests/test_a.py::test_y"]
    assert proof_before.passed_ids("python -m pytest -q", "..\n2 passed in 0.1s\n") is None
    assert proof_before.passed_ids("npx jest", "PASS src/a.test.js\nPASS src/b.test.js\n") == [
        "src/a.test.js", "src/b.test.js"]
    assert proof_before.passed_ids("npx vitest run", " ✓ src/a.test.ts (3)\n") == ["src/a.test.ts"]
    many = "".join(f"t.py::test_{i} PASSED\n" for i in range(proof_before.MOST_IDS + 10))
    assert len(proof_before.passed_ids("pytest -v", many)) == proof_before.MOST_IDS


def test_a_regression_is_a_test_that_passed_then():
    green = {"ran": 2, "skipped": 0, "ids": ["tests/test_a.py::test_x", "tests/test_a.py::test_y"]}
    # (test_z was added after the green run: never a regression)
    assert proof_before.regressions(["tests/test_a.py::test_x", "tests/test_a.py::test_z"],
                                    green, set()) == [("tests/test_a.py::test_x", False)]
    # (no ids kept: by file - not a file this turn added)
    assert proof_before.regressions(["tests/test_a.py::test_x", "tests/test_n.py::test_m"],
                                    {"ran": 2, "skipped": 0, "ids": None},
                                    {"tests/test_n.py"}) == [("tests/test_a.py::test_x", True)]
