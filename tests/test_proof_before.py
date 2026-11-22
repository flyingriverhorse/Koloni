"""Kanıtlı bitiş S7, what needs no model: the tests a failing run names, the line that runs them
alone, a bug-fix turn's words, new test files, and the last green state's words."""

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
    # (single quotes on both platforms: literal to sh and to PowerShell alike - review of S7)
    assert proof_before.alone("python -m pytest -q", ["t.py::a[1-2]"]) == (
        "python -m pytest -q 't.py::a[1-2]'")
    assert proof_before.alone("npm test", ["a.test.ts"]) == "npm test -- 'a.test.ts'"
    assert proof_before.alone("npx vitest run", ["a.test.ts"]) == "npx vitest run 'a.test.ts'"
    assert proof_before.alone("pytest -q | tail -1", ["t.py::a"]) is None  # (its exit masked)
    assert proof_before.alone("pytest", ["t.py::a'b"]) is None
    assert proof_before.alone("pytest", ["t.py::a", "t.py::t$(whoami)"]) is None
    assert proof_before.alone("make test", ["t"]) is None
    assert proof_before.alone("pytest", []) is None


@pytest.mark.parametrize(("one", "plain"), [
    ("tests/test_a.py::TestK::test_x[1-2]", True), ("tests\\test_a.py::t", True),
    ("src/a.test.ts", True), ("x.py::t", True), ("tests/test_düzelt.py::test_ğ", True),
    # (PowerShell reads its curly quotes and dashes as ' " -)
    ("t.py::a‘b", False), ("t.py::a“b", False), ("t.py::a–b", False),
    # (what a run PRINTED, put on a line KOLONİ runs unasked: nothing a shell reads, no option,
    # nothing outside the folder)
    ("tests/test_a.py::t$(whoami)", False), ("tests/test_a.py::t`$env:USERNAME`x", False),
    ("tests/test_a.py::t;Write-Output;INJECTED", False), ("tests/test_a.py::t%PATH%^x", False),
    ("tests/test_a.py::t&x", False), ("tests/test_a.py::t|x", False), ("t.py::a b", False),
    ("t.py::a'b", False), ('t.py::a"b', False), ("t.py::a\nb", False), ("--co", False),
    ("-p", False), ("--rootdir=C:/elsewhere", False), ("C:/x/test_a.py::t", False),
    ("/abs/test_a.py::t", False), ("\\\\host\\t.py::t", False),
    ("..\\..\\outside\\test_x.py::t", False), ("tests/../../x.py::t", False), ("", False)])
def test_only_a_plain_test_name_is_run_again(one, plain):
    assert proof_before.plain_id(one) is plain


@pytest.mark.parametrize(("answer", "drop", "skip"), [
    ("Removed a stray debug print.", None, None),  # (the probe: excuses nothing)
    ("I removed the obsolete test of the old parser", "I removed the obsolete test of the old "
     "parser", None),
    ("Done. Removed test_old.py: it tested the old parser.\nAll green.",
     "Removed test_old.py: it tested the old parser.", None),
    ("I marked two tests skip on Windows.", "I marked two tests skip on Windows.",
     "I marked two tests skip on Windows."),
    ("I removed the old parser. The tests pass.", None, None),  # (not in one sentence)
    ("Removed a specific print.", None, None)])
def test_an_excuse_names_tests_in_the_sentence_that_says_why(answer, drop, skip):
    assert proof_before.excuse(answer, "Tests went from 4 to 3 (1 removed)") == drop
    assert proof_before.excuse(answer, "Skipped rose from 0 to 2") == skip
    long = "Removed the tests of " + "x" * 300
    assert len(proof_before.excuse(long, "Tests went from 4 to 3 (1 removed)")) == (
        proof_before.MOST_SAID)


def test_a_reproduction_is_a_failing_test_of_a_file_it_wrote():
    wrote = {"tests/test_bug.py": "def test_calc():\n    assert calc() == 2\n"}
    failed = "FAILED tests/test_bug.py::test_calc - assert 1 == 2\n=== 1 failed in 0.1s ===\n"
    assert proof_before.reproduces(failed, wrote)
    # (a collection or syntax error names no failing test: no reproduction - review of S7)
    broken = ("ERROR collecting tests/test_bug.py\nE   SyntaxError: invalid syntax\n"
              "ERROR tests/test_bug.py\n!!! Interrupted: 1 error during collection !!!\n")
    assert not proof_before.reproduces(broken, wrote)
    assert not proof_before.reproduces(failed.replace("test_bug", "test_other"), wrote)
    # (run from a sub-folder: its ids are from there)
    assert proof_before.reproduces(failed, {"backend/tests/test_bug.py": ""})
    assert proof_before.reproduces(" FAIL  src/bug.test.ts > calc > adds\n",
                                   {"src/bug.test.ts": ""})
    # (jest and go name no file: by the test's name in the file it wrote)
    jest = "  \u25cf calc \u203a adds two\n"
    assert proof_before.reproduces(jest, {"src/bug.test.js": "it('adds two', () => {})"})
    assert not proof_before.reproduces(jest, {"src/bug.test.js": "it('subtracts', () => {})"})
    assert proof_before.reproduces("--- FAIL: TestAdd (0.00s)\n",
                                   {"add_test.go": "func TestAdd(t *testing.T) {}"})


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
