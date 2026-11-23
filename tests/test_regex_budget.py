"""SonarCloud's regex findings (PR #23), measured: each pattern that tried a run of spaces or a long
word every way is read in time on what a model may write - a command line, a test run's output, a
reviewer's report - and still reads what it read."""

import re
import time

import pytest

from app import commands, ledger, proof_before
from app.agent import review_mixin, stronger_mixin
from app.test_found import counts

BUDGET_MS = 50  # (before: 443 ms for `$(date` and 25 spaces, doubling per 2; the others 0.1-2 s)
LONG = 20_000


def took(run) -> float:
    began = time.perf_counter()
    run()
    return 1000 * (time.perf_counter() - began)


@pytest.mark.parametrize(
    ("name", "run"),
    [
        ("_DATE_NAME", lambda: commands._DATE_NAME.search("$(date" + " " * 40 + "x")),
        ("_CASE_BRANCH", lambda: commands._CASE_BRANCH.search("in " + " " * LONG + "x")),
        ("_TEST_FILE", lambda: ledger._TEST_FILE.findall("a." * LONG)),
        ("_PYTEST_PASSED", lambda: proof_before._PYTEST_PASSED.findall(":" * LONG)),
        ("DIAGNOSIS", lambda: stronger_mixin.DIAGNOSIS.match(" " * LONG + "x")),
        ("QUESTION", lambda: stronger_mixin.QUESTION.match(" " * LONG + "x")),
        ("VERDICT", lambda: review_mixin.VERDICT.match(" " * LONG + "x")),
        ("phpunit", lambda: counts("Tests: 5, Assertions: 7, " + "a" * LONG, "vendor/bin/phpunit")),
    ],
)
def test_each_regex_reads_an_adversarial_input_in_time(name, run):
    assert took(run) < BUDGET_MS, name


def test_the_fixed_regexes_still_read_what_they_read():
    assert commands._DATE_NAME.search("cp a.log $(date +%F).log")
    assert commands._DATE_NAME.search("cp a $(date  +%s  ).bak")
    assert commands._CASE_BRANCH.search("case $x in (a|b) echo y;; esac")
    assert ledger._TEST_FILE.findall("FAILED tests/test_a.py::t - x; see src/b.test.ts") == [
        "tests/test_a.py",
        "src/b.test.ts",
    ]
    assert proof_before.passed_ids(
        "python -m pytest -v", "tests/test_a.py::test_x PASSED\n::odd PASSED\nplain PASSED\n"
    ) == ["tests/test_a.py::test_x"]
    assert stronger_mixin.diagnosis_of("  - **Diagnosis: test-wrong - why")[0] == "test-wrong"
    assert review_mixin.verdict_of("  1. **Final Verdict: MERGE**") == "MERGE"
    assert re.findall(r"\b(\w+): (\d+)", "Tests: 5, Failures: 1") == [
        ("Tests", "5"),
        ("Failures", "1"),
    ]
