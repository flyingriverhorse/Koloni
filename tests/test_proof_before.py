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
