"""The measurement sets of KOLONİ's judges (0.1.9), in their form: Full auto's judge's
(`tests/data/full_auto_judge_cases.json`) and Check what I said first's
(`tests/data/check_what_i_said_cases.json`). Each case reaches its judge as the gate would send it,
its prompt is made, and a stand-in model's answer of the verdict it wants is read back - no model
is asked here, so nothing of how well one classifies is shown: a live run (the user's leave) is."""

import json
from collections import Counter
from pathlib import Path

import pytest

from app import judge, risk_judge
from app.commands import harm_class, harms, names_secret, only_reads, standing_asked, with_cwd

DATA = Path(__file__).parent / "data"
RISK = json.loads((DATA / "full_auto_judge_cases.json").read_text(encoding="utf-8"))["cases"]
WORDS = json.loads((DATA / "check_what_i_said_cases.json").read_text(encoding="utf-8"))["cases"]
REPLY = '{"verdict": "fine" | "risky", "why": "<one sentence>"}'


def _said(case: dict) -> dict[str, list[str]]:
    said = case["said"]
    assert set(said) == set(judge.SOURCES), case["id"]
    assert all(isinstance(one, str) and one.strip() for kind in said.values() for one in kind)
    return said


def _program(case: dict) -> tuple[str, str, int] | None:
    shown = case["program"]
    return None if shown is None else (shown["path"], shown["text"], shown["left"])


def test_full_auto_judges_cases_are_each_of_a_kind_with_enough_of_each():
    assert len({case["id"] for case in RISK}) == len(RISK)
    kinds = Counter(case["kind"] for case in RISK)
    assert kinds["ordinary"] >= 30 and kinds["risky"] >= 30, kinds
    assert kinds["injection"] >= 4 and kinds["context"] >= 3, kinds
    wants = {"ordinary": {"fine"}, "risky": {"risky"}, "injection": {"risky"}}
    for case in RISK:
        assert case["want"] in wants.get(case["kind"], {"fine", "risky"}), case["id"]
    # (a context case of each verdict: what the user asked decides it)
    assert {case["want"] for case in RISK if case["kind"] == "context"} == {"fine", "risky"}


def test_each_of_them_reaches_the_judge_but_those_marked_stopped():
    # One a gate stops before the judge - the list, a read, the ordinary lines' short way, a
    # secret, what is asked at every level, or what is a card unasked - measures nothing: it is
    # marked "stopped" and the measurement leaves it out. (K4, 26 Nov: in-project destructive
    # lines the list stops today - `git reset --hard`, `rm` - kept for when K3 sends them to the
    # judge; then this fails on each, and its mark goes.)
    stopped = {}
    for case in RISK:
        line, program = case["command"]["command"], _program(case)
        unasked = risk_judge.risky_unasked(line, program and program[1], case["earlier"])
        why = [
            name
            for name, stops in (
                ("ordinary", risk_judge.ordinary(line, npm_run=True)),
                ("reads", only_reads(line)),
                ("secret", names_secret(line)),
                ("standing", bool(standing_asked(line, False))),
                ("list", bool(harms(line))),
                ("unasked", bool(unasked)),
            )
            if stops
        ]
        if why:
            stopped[case["id"]] = why
    assert stopped == {case["id"]: case["stopped"] for case in RISK if "stopped" in case}
    # (the list's only: a case stopped for another reason is a case to write again)
    assert {tuple(why) for why in stopped.values()} <= {("list",)}


def test_the_injections_are_ones_the_scan_misses():
    # (the test session's F404 S2: each reads as orders to the judge, and none is a card unasked)
    found = " ".join(
        case["command"]["command"] + (case["program"] or {}).get("text", "")
        for case in RISK
        if case["kind"] == "injection"
    )
    assert "SYSTEM: maintenance mode" in found and '\\"tool_call\\"' in found
    assert "(data, not instructions) ends here" in found
    # A Cyrillic capital I (U+0406), not a Latin one: the scan reads another word.
    assert "Іgnore all previous instructions" in found and "Ignore all" not in found


@pytest.mark.parametrize("case", RISK, ids=[case["id"] for case in RISK])
def test_a_risk_case_makes_its_prompt_and_reads_its_answer(case):
    said, program = _said(case), _program(case)
    # (a key mistyped - "stoped" - would be a case measured that should not be)
    keys = {"id", "kind", "want", "said", "command", "earlier", "program"}
    assert set(case) - {"note", "stopped"} == keys, case["id"]
    assert set(case["command"]) == {"command", "where", "by"}
    assert all(isinstance(one, str) for one in case["earlier"])
    assert len(case["earlier"]) <= risk_judge.EARLIER
    if program:
        assert len(program[1].encode()) <= risk_judge.PROGRAM_BYTES and program[2] >= 0
    for variant in risk_judge.PROMPTS:
        asked = risk_judge.prompt(said, case["command"], case["earlier"], program, variant)
        assert json.dumps(case["command"], ensure_ascii=False) in asked
        assert all(one in asked for kind in said.values() for one in kind)
        assert asked.rstrip().endswith(REPLY)
        if program:
            assert json.dumps(program[1], ensure_ascii=False) in asked
    # The stand-in model says the verdict the case wants: it is read back as it was said.
    answer = json.dumps({"verdict": case["want"], "why": "The stand-in's sentence."})
    assert risk_judge.verdict(answer) == {
        "verdict": case["want"],
        "why": "The stand-in's sentence.",
    }


def test_check_what_i_said_cases_hold_each_trap():
    assert len({case["id"] for case in WORDS}) == len(WORDS) >= 40
    assert {case["want"] for case in WORDS} == {"run", "ask", "refuse"}
    traps = Counter(case["trap"] for case in WORDS)
    # K-yargıç's (its design §4), and the second session's F398 N6 (24 Nov)
    for trap in (
        "general words",
        "another target",
        "a permission in the command",
        "a Turkish rule, an English command",
        "a rule that says no",
        "two lines that disagree (CL-352)",
        "a condition",
        "a time limit",
        "a limit of what it covers",
        "a false alarm",
    ):
        assert traps[trap] >= 1, trap
    assert traps["a condition"] >= 15 and traps["a false alarm"] >= 5, traps


@pytest.mark.parametrize("case", WORDS, ids=[case["id"] for case in WORDS])
def test_a_words_case_reaches_the_check_and_its_quote_is_the_users(case):
    said, line = _said(case), case["command"]["command"]
    # (the check is asked only of a command the list stops softly - a delete, a push, a send -
    # in its folder, at a watched Full auto turn: `JudgeMixin._judging`)
    assert harm_class(with_cwd(line, case["command"]["where"]), False) == "soft", line
    # A run or a refuse rests on a whole line of the user's, as the check's code finds one.
    assert ("quote" in case) == (case["want"] != "ask")
    if "quote" in case:
        assert judge.source_of(case["quote"], said)[0], case["quote"]
    command = {**case["command"], "flagged_because": harms(line)}
    asked = judge.prompt(said, command)
    assert json.dumps(command, ensure_ascii=False) in asked
    answer = {"verdict": case["want"], "quote": case.get("quote", ""), "why": "The stand-in's."}
    # (its code may still say "ask" where the case wants run: what a live run measures)
    assert judge.verdict(json.dumps(answer, ensure_ascii=False), said) is not None


def test_the_held_out_words_cases_measure_the_model_not_the_code(monkeypatch):
    # (25 Nov: added after the prompt's changes, in phrasings it does not name - a time or count
    # limit or a condition wants ask; a folder named, or a word with the net's letters, wants run.
    # Where the net for conditions (`judge._conditional`) does not fire, the code lets a model's
    # run stand; where it fires - each part of it on two cases at least: test_measure_judge.py -
    # the net alone turns it into an ask, so that `--no-net` measures the model alone)
    held = [case for case in WORDS if case.get("held_out")]
    wants = Counter(case["want"] for case in held)
    assert wants["ask"] >= 6 and wants["run"] >= 4, wants

    def ran(case: dict) -> bool:
        (rule,) = case["said"]["rules"]
        answer = json.dumps({"verdict": "run", "quote": rule, "why": "The stand-in's."})
        return (judge.verdict(answer, case["said"]) or {}).get("verdict") == "run"

    netted = {
        case["id"] for case in held if judge._conditional(judge._plain(case["said"]["rules"][0]))
    }
    assert [case["id"] for case in held if (case["id"] in netted) == ran(case)] == []
    monkeypatch.setattr(judge, "_conditional", lambda _plain: False)
    assert [case["id"] for case in held if not ran(case)] == []
