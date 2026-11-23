"""Kanıtlı bitiş S7, what needs no model: the tests a failing run names, the line that runs them
alone, a bug-fix turn's words, new test files, and the last green state's words."""

from collections import Counter

import pytest

from app import proof_before


def test_failed_ids_pytest_vitest_jest():
    out = (
        "FAILED tests/test_a.py::test_x - assert 1 == 2\nERROR tests/test_b.py::test_y\n"
        "FAILED tests/test_a.py::test_x - again\n=== 2 failed in 0.1s ===\n"
    )
    assert proof_before.failed_ids("python -m pytest -q", out) == [
        "tests/test_a.py::test_x",
        "tests/test_b.py::test_y",
    ]
    assert proof_before.failed_ids("npx vitest run", " FAIL  src/a.test.ts > adds\n") == [
        "src/a.test.ts"
    ]
    assert proof_before.failed_ids("npx jest", "FAIL src/b.test.js\n") == ["src/b.test.js"]
    assert proof_before.failed_ids("make test", "FAILED x\n") == []
    # (coloured output is read as plain)
    assert proof_before.failed_ids("pytest", "\x1b[31mFAILED t.py::a\x1b[0m - x\n") == ["t.py::a"]


def test_alone_builds_a_rerun_or_none():
    # (single quotes on both platforms: literal to sh and to PowerShell alike - review of S7)
    assert proof_before.alone("python -m pytest -q", ["t.py::a[1-2]"]) == (
        "python -m pytest -q 't.py::a[1-2]'"
    )
    assert proof_before.alone("npm test", ["a.test.ts"]) == "npm test -- 'a.test.ts'"
    assert proof_before.alone("npx vitest run", ["a.test.ts"]) == "npx vitest run 'a.test.ts'"
    assert proof_before.alone("pytest -q | tail -1", ["t.py::a"]) is None  # (its exit masked)
    assert proof_before.alone("pytest", ["t.py::a'b"]) is None
    assert proof_before.alone("pytest", ["t.py::a", "t.py::t$(whoami)"]) is None
    assert proof_before.alone("make test", ["t"]) is None
    assert proof_before.alone("pytest", []) is None


@pytest.mark.parametrize(
    ("one", "plain"),
    [
        ("tests/test_a.py::TestK::test_x[1-2]", True),
        ("tests\\test_a.py::t", True),
        ("src/a.test.ts", True),
        ("x.py::t", True),
        ("tests/test_düzelt.py::test_ğ", True),
        # (PowerShell reads its curly quotes and dashes as ' " -)
        ("t.py::a‘b", False),
        ("t.py::a“b", False),
        ("t.py::a–b", False),
        # (what a run PRINTED, put on a line KOLONİ runs unasked: nothing a shell reads, no option,
        # nothing outside the folder)
        ("tests/test_a.py::t$(whoami)", False),
        ("tests/test_a.py::t`$env:USERNAME`x", False),
        ("tests/test_a.py::t;Write-Output;INJECTED", False),
        ("tests/test_a.py::t%PATH%^x", False),
        ("tests/test_a.py::t&x", False),
        ("tests/test_a.py::t|x", False),
        ("t.py::a b", False),
        ("t.py::a'b", False),
        ('t.py::a"b', False),
        ("t.py::a\nb", False),
        ("--co", False),
        ("-p", False),
        ("--rootdir=C:/elsewhere", False),
        ("C:/x/test_a.py::t", False),
        ("/abs/test_a.py::t", False),
        ("\\\\host\\t.py::t", False),
        ("..\\..\\outside\\test_x.py::t", False),
        ("tests/../../x.py::t", False),
        ("", False),
    ],
)
def test_only_a_plain_test_name_is_run_again(one, plain):
    assert proof_before.plain_id(one) is plain


@pytest.mark.parametrize(
    ("answer", "drop", "skip"),
    [
        ("Removed a stray debug print.", None, None),  # (the probe: excuses nothing)
        (
            "I removed the obsolete test of the old parser",
            "I removed the obsolete test of the old parser",
            None,
        ),
        (
            "Done. Removed test_old.py: it tested the old parser.\nAll green.",
            "Removed test_old.py: it tested the old parser.",
            None,
        ),
        (
            "I marked two tests skip on Windows.",
            "I marked two tests skip on Windows.",
            "I marked two tests skip on Windows.",
        ),
        ("I removed the old parser. The tests pass.", None, None),  # (not in one sentence)
        ("Removed a specific print.", None, None),
    ],
)
def test_an_excuse_names_tests_in_the_sentence_that_says_why(answer, drop, skip):
    assert proof_before.excuse(answer, "Tests went from 4 to 3 (1 removed)") == drop
    assert proof_before.excuse(answer, "Skipped rose from 0 to 2") == skip
    long = "Removed the tests of " + "x" * 300
    assert len(proof_before.excuse(long, "Tests went from 4 to 3 (1 removed)")) == (
        proof_before.MOST_SAID
    )


def test_a_reproduction_is_a_failing_test_of_a_file_it_wrote():
    wrote = {"tests/test_bug.py": "def test_calc():\n    assert calc() == 2\n"}
    failed = "FAILED tests/test_bug.py::test_calc - assert 1 == 2\n=== 1 failed in 0.1s ===\n"
    assert proof_before.reproduces(failed, wrote)
    # (a collection or syntax error names no failing test: no reproduction - review of S7)
    broken = (
        "ERROR collecting tests/test_bug.py\nE   SyntaxError: invalid syntax\n"
        "ERROR tests/test_bug.py\n!!! Interrupted: 1 error during collection !!!\n"
    )
    assert not proof_before.reproduces(broken, wrote)
    assert not proof_before.reproduces(failed.replace("test_bug", "test_other"), wrote)
    # (run from a sub-folder: its ids are from there)
    assert proof_before.reproduces(failed, {"backend/tests/test_bug.py": ""})
    assert proof_before.reproduces(
        " FAIL  src/bug.test.ts > calc > adds\n", {"src/bug.test.ts": ""}
    )
    # (jest and go name no file: by the test's name in the file it wrote)
    jest = "  \u25cf calc \u203a adds two\n"
    assert proof_before.reproduces(jest, {"src/bug.test.js": "it('adds two', () => {})"})
    assert not proof_before.reproduces(jest, {"src/bug.test.js": "it('subtracts', () => {})"})
    assert proof_before.reproduces(
        "--- FAIL: TestAdd (0.00s)\n", {"add_test.go": "func TestAdd(t *testing.T) {}"}
    )
    # (shortcut, said in `reproduces`: a jest test outside a describe is a name not read - none)
    assert not proof_before.reproduces(
        "  ● adds two\n", {"src/bug.test.js": "it('adds two', () => {})"}
    )


@pytest.mark.parametrize(
    ("words", "fix"),
    [("fix the crash in calc", True), ("bu hatayı düzelt", True), ("add a page", False)],
)
def test_a_bug_fix_by_its_words(words, fix):
    assert bool(proof_before.BUGFIX.search(words)) is fix


def test_new_tests_and_the_green_words():
    assert proof_before.new_tests(["tests/test_a.py", "a.py", "web/x.test.ts", "b_test.go"]) == [
        "tests/test_a.py",
        "web/x.test.ts",
        "b_test.go",
    ]
    assert proof_before.green_said(None, 3, 0) == []
    assert proof_before.green_said({"ran": 214, "skipped": 3}, 210, 9) == [
        "Tests went from 214 to 210 (4 removed)",
        "Skipped rose from 3 to 9",
    ]
    assert proof_before.green_said({"ran": 4, "skipped": 0}, 5, 0) == []


def test_passed_ids_as_the_run_lists_them_or_none():
    out = "tests/test_a.py::test_x PASSED\ntests/test_a.py::test_y PASSED\n=== 2 passed ===\n"
    assert proof_before.passed_ids("python -m pytest -v", out) == [
        "tests/test_a.py::test_x",
        "tests/test_a.py::test_y",
    ]
    assert proof_before.passed_ids("python -m pytest -q", "..\n2 passed in 0.1s\n") is None
    assert proof_before.passed_ids("npx jest", "PASS src/a.test.js\nPASS src/b.test.js\n") == [
        "src/a.test.js",
        "src/b.test.js",
    ]
    assert proof_before.passed_ids("npx vitest run", " ✓ src/a.test.ts (3)\n") == ["src/a.test.ts"]
    many = "".join(f"t.py::test_{i} PASSED\n" for i in range(proof_before.MOST_IDS + 10))
    assert len(proof_before.passed_ids("pytest -v", many)) == proof_before.MOST_IDS


def test_a_regression_is_a_test_that_passed_then():
    green = {"ran": 2, "skipped": 0, "ids": ["tests/test_a.py::test_x", "tests/test_a.py::test_y"]}
    # (test_z was added after the green run: never a regression)
    assert proof_before.regressions(
        ["tests/test_a.py::test_x", "tests/test_a.py::test_z"], green, set()
    ) == [("tests/test_a.py::test_x", False)]
    # (no ids kept: by file - not a file this turn added)
    assert proof_before.regressions(
        ["tests/test_a.py::test_x", "tests/test_n.py::test_m"],
        {"ran": 2, "skipped": 0, "ids": None},
        {"tests/test_n.py"},
    ) == [("tests/test_a.py::test_x", True)]


def test_lint_findings_name_the_project_files_each_tool_says(tmp_path):
    # (CL-336 M: a lint, format or type check's findings by the file each names)
    for rel in ("old.py", "src/a.ts", "web/b.js"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("x\n", encoding="utf-8")
    ruff = (
        "F401 [*] `os` imported but unused\n --> old.py:1:8\n  |\n1 | import os\n  |\n"
        "Found 1 error.\n"
    )
    assert proof_before.lint_findings(ruff, tmp_path, ".") == (
        frozenset({"old.py"}),
        Counter(
            {
                "F401 [*] `os` imported but unused --> old.py:1:8": 1,
                "F401 [*] `os` imported but unused": 1,
            }
        ),
    )
    said = {
        "Would reformat: old.py\n1 file would be reformatted\n": "old.py",  # (ruff format)
        "would reformat old.py\nOh no!\n": "old.py",  # (black --check)
        "[warn] web/b.js\n[warn] Code style issues found.\n": "web/b.js",  # (prettier)
        'old.py:3: error: Argument 1 to "f" has incompatible type\nFound 1 error\n': "old.py",
        "src/a.ts(3,4): error TS2322: Type 'string' is not assignable\n": "src/a.ts",
        "src/a.ts:3:4 - error TS2322: Type 'string'\n": "src/a.ts",  # (tsc --pretty)
        f"{tmp_path / 'web' / 'b.js'}\n  3:1  error  'x' is not defined  no-undef\n\n"
        "✖ 1 problem\n": "web/b.js",  # (eslint, its absolute path)
    }
    for output, rel in said.items():
        found = proof_before.lint_findings(output, tmp_path, ".")
        assert found is not None and found[0] == {rel}, (output, found)
    eslint = proof_before.lint_findings(
        f"{tmp_path / 'web' / 'b.js'}\n  3:1  error  x\n", tmp_path, "."
    )
    assert eslint is not None and "web/b.js 3:1  error  x" in eslint[1]  # (its lines under it)
    # (from a part's folder: project-relative; none named, or a name that is no project file
    # - gone, outside it - is not to be told apart)
    assert proof_before.lint_findings("a.ts:1:1: x\n", tmp_path, "src")[0] == {"src/a.ts"}
    assert (
        proof_before.lint_findings("error: Failed to parse pyproject.toml\n", tmp_path, ".") is None
    )
    assert proof_before.lint_findings("old.py:1:1: E1\ngone.py:2:1: E2\n", tmp_path, ".") is None
    assert proof_before.lint_findings("../outside.py:1:1: E1\n", tmp_path, ".") is None
    # (coloured output is read as plain)
    assert proof_before.lint_findings("\x1b[1mold.py\x1b[0m:1:1: E1\n", tmp_path, ".")[0] == {
        "old.py"
    }


# ruff 0.x's own words on an old.py of `import os`, `y   =  1`, `x = np.zeros(3,4)` (measured):
# the code it quotes names no file.
RUFF_FORMAT = """unformatted: File would be reformatted
 --> old.py:2:1
  |
1 | import os
  - y   =  1
  - x = np.zeros(3,4)
2 +
3 + y = 1
4 + x = np.zeros(3, 4)
  |

1 file would be reformatted, 1 file already formatted
"""
RUFF_CHECK = """F401 [*] `os` imported but unused
 --> old.py:1:8
  |
1 | import os
  |        ^^
2 | y   =  1
3 | x = np.zeros(3,4)
  |
help: Remove unused import: `os`

F821 Undefined name `np`
 --> old.py:3:5
  |
2 | y   =  1
3 | x = np.zeros(3,4)
  |     ^^
  |

Found 2 errors.
[*] 1 fixable with the `--fix` option.
"""


def test_lint_findings_read_ruffs_own_output(tmp_path):
    (tmp_path / "old.py").write_text("import os\n", encoding="utf-8")
    assert proof_before.lint_findings(RUFF_FORMAT, tmp_path, ".") == (
        frozenset({"old.py"}),
        Counter({"unformatted: File would be reformatted --> old.py:2:1": 1}),
    )
    assert proof_before.lint_findings(RUFF_CHECK, tmp_path, ".") == (
        frozenset({"old.py"}),
        Counter(
            {
                "F401 [*] `os` imported but unused --> old.py:1:8": 1,
                "F401 [*] `os` imported but unused": 1,
                "F821 Undefined name `np` --> old.py:3:5": 1,
                "F821 Undefined name `np`": 1,
            }
        ),
    )


OLD_TS = "old.ts(3,5): error TS2345: Argument of type 'number' is not assignable.\n"


@pytest.mark.parametrize(
    "now, then",
    [
        # (review of CL-336 M: the turn's own failure beside an old one was excused with it - a
        # tsconfig option it broke, a config error of mypy's, ruff's parse error naming a file
        # mid-line; and one old finding that came twice)
        (
            "error TS5023: Unknown compiler option 'strictt'.\n"
            + OLD_TS
            + "Found 2 errors in 1 file.\n",
            OLD_TS + "Found 1 error in 1 file.\n",
        ),
        (
            "mypy.ini: [mypy]: Unrecognized option: strictt = True\n"
            "old.py:3: error: Name 'y' is not defined  [name-defined]\nFound 1 error\n",
            "old.py:3: error: Name 'y' is not defined  [name-defined]\nFound 1 error\n",
        ),
        (
            "error: Failed to parse src/a.py:1:1: Expected an expression\n"
            "old.py:3:1: F821 Undefined name `y`\nFound 1 error.\n",
            "old.py:3:1: F821 Undefined name `y`\nFound 1 error.\n",
        ),
        ("old.py:3: error: X\nold.py:3: error: X\n", "old.py:3: error: X\n"),
    ],
)
def test_a_finding_the_old_code_has_not_is_the_turns(tmp_path, now, then):
    for name in ("old.ts", "tsconfig.json", "old.py", "src/a.py", "mypy.ini"):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text("x\n", encoding="utf-8")
    found, was = (proof_before.lint_findings(one, tmp_path, ".") for one in (now, then))
    assert found is not None and was is not None and not found[1] <= was[1], (found, was)
    # (the same old findings with their summary's counts moved: failing before)
    same = proof_before.lint_findings(OLD_TS + "Found 3 errors in 2 files.\n", tmp_path, ".")
    old = proof_before.lint_findings(OLD_TS + "Found 1 error in 1 file.\n", tmp_path, ".")
    assert same is not None and old is not None and same[1] <= old[1]


def test_a_file_the_turn_changed_anywhere_in_the_output_makes_it_the_turns(tmp_path):
    for name in ("old.py", "src/a.py"):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text("x\n", encoding="utf-8")
    said = (
        "error: Failed to parse src/a.py:1:1: Expected an expression\n"
        "old.py:3:1: F821 Undefined name `y`\n"
    )
    assert proof_before.lint_findings(said, tmp_path, ".", ["src/a.py"]) is None
    assert (
        proof_before.lint_findings(
            said.replace("src/a.py", "src\\a.py"), tmp_path, ".", ["SRC/A.py"]
        )
        is None
    )  # (its slashes, its case)
    assert proof_before.lint_findings("a.py:1:1: E1\n", tmp_path, "src", ["src/a.py"]) is None
    # (not a name that only ends like it)
    assert proof_before.lint_findings("old.py:3:1: F821 `y`\n", tmp_path, ".", ["d.py"]) is not None
