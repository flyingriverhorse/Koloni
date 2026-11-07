"""K-evrim slice 1: a measure command's score, and which candidate is best."""

import pytest

from app.evolve import best, score_of, table


@pytest.mark.parametrize(("output", "score"), [
    ("85", 85.0),
    ("compiling\nlength 12\n72.5\n", 72.5),
    ("0", 0.0),
    ("100", 100.0),
    ("  42  \n\n  \n", 42.0),  # trailing blank lines: the last line with something on it
    ("50\r\n", 50.0),
])
def test_the_last_non_empty_line_is_the_score(output, score):
    assert score_of(output) == score


@pytest.mark.parametrize("output", [
    "", "\n\n", "oops", "score: 85", "85%", "-5", "100.5", "101", "1e2", "nan", "inf",
    "85 90", "85\ndone",  # the number must be the last line
])
def test_anything_else_is_no_score(output):
    assert score_of(output) is None


def test_the_best_is_first_and_ties_go_to_the_first_opened():
    assert best({"Coder": 70.0, "Coder 2": 85.0, "Coder 3": 85.0}) == [
        "Coder 2", "Coder 3", "Coder"]


def test_a_candidate_with_no_score_is_last_even_after_a_zero():
    assert best({"Coder": None, "Coder 2": 0.0, "Coder 3": None, "Coder 4": 3.0}) == [
        "Coder 4", "Coder 2", "Coder", "Coder 3"]
    assert best({}) == []


def test_the_table_says_them_best_first_and_why_one_has_none():
    assert table({"Coder": 1.0, "Coder 2": None, "Coder 3": 72.5},
                 {"Coder 2": "no number"}) == "Coder 3: 72.5 · Coder: 1 · Coder 2: no score (no number)"
