"""Kanıtlı bitiş S4 - the recipes' own proof (R1-R4), with the fake model and the ready Bugfix:
a failing test goes back to Fix it (R1); a check that reports nothing wrong while a test run on
record failed is blocked (R2) - a later help, list or narrower run of the tool hides none; a
Tester that ran no command but reads or ones that check nothing (`python -c "pass"`) does not pass
(R3); Reproduce it writes a failing test and fixes nothing (R4)."""

from app.agent.words import RAN_NOTHING, REPRODUCE_FIRST, RUN_TO_PASS
from tests.fakes import Script, ScriptedExecutor
from tests.test_agent_commands import cmd
from tests.test_chat_flow import text
from tests.test_chat_teams_scenarios import OWN, teams_of
from tests.test_claim_scenarios import write
from tests.test_parallel import until
from tests.test_recipe_conditions import FAILING
from tests.test_recipe_run_scenarios import NONE, READY, asked, by_call, made, recipe_named, row
from tests.test_recipes_scenarios import graph
from tests.test_recipes_scenarios import step as part
from tests.test_spawn import begin, call, spawn, step

PYTEST = "python -m pytest -q"
FAILED = Script(["1 failed, 3 passed\n"], exit_code=1)
PASSED = Script(["4 passed\n"], exit_code=0)


def bugfix_run(client, project_dir, mode="full_auto"):
    """The Backend / API team by its ready recipe, Bugfix; at Full auto its commands run unasked."""
    backend = teams_of(client)["Backend / API"]
    assert backend["default_recipe_id"] == recipe_named(client, "Bugfix")["id"]
    return begin(client, project_dir, mode=mode, spawn_approval="never", teams_mode="manual",
                 teams=[{"team_id": backend["id"], "recipe_id": None}])


def fix(id):
    return step(call("spawn_agent", {"role": "Coder", "task": "fix it", "findings_from": "Tester"}, id))


def lead(tests, review=True):
    """The Lead's way through Bugfix: Reproduce it, Fix it, then each round's Test it (and the Fix
    it before the next one), then Review it - where the recipe gets there."""
    rounds = [spawn("Tester", "test it", f"t{i}") for i in range(len(tests))]
    way = [spawn("Debugger", "reproduce the crash", "d1"), spawn("Coder", "fix it", "c0"), rounds[0]]
    for i, one in enumerate(rounds[1:], 1):
        way += [fix(f"c{i}"), one]
    return [*way, *([spawn("Reviewer", "review it", "r1")] if review else []), text("done")]


def scripts(*testers, review=True):
    """Each Tester's script by its agent's name ("Tester", "Tester 2", ...), and a Coder for each."""
    named = [("Tester" if i == 0 else f"Tester {i + 1}") for i in range(len(testers))]
    coders = [("Coder" if i == 0 else f"Coder {i + 1}") for i in range(len(testers))]
    return {
        "Lead": lead(testers, review),
        "Debugger": [text("Reproduced: calc(2) crashes.")],
        **{name: [step(write("calc.py", f"x = {i}\n")), text("fixed")] for i, name in enumerate(coders)},
        **dict(zip(named, testers, strict=True)),
        "Reviewer": [text(NONE)],
    }


def ran_tests(report=NONE, id="k1"):
    return [cmd(PYTEST, id), text(report)]


def agent(snap, name):
    return next(a for a in snap["agents"] if a["name"] == name)


def opened(snap):
    return [a["role_name"] for a in snap["agents"] if a["depth"] == 1]


def test_a_tester_that_says_none_with_a_failing_run_blocks(make_client, wait_run, project_dir):
    # R2: "Findings: none" with a failing run on record - Bugfix's Test it goes back to Fix it.
    executor = ScriptedExecutor([FAILED, PASSED])
    client, _model = make_client(scripts(ran_tests(), ran_tests(id="k2")), executor=executor)
    cid, run_id = bugfix_run(client, project_dir)
    snap = wait_run(client, cid, run_id)
    assert opened(snap) == ["Debugger", "Coder", "Tester", "Coder", "Tester", "Reviewer"], by_call(snap)
    held = agent(snap, "Tester")["findings"]
    assert [(f["what"], f["blocking"]) for f in held] == [
        (f"last test run failed (exit 1): {PYTEST}", True)], held
    assert "Findings are left: back to Fix it, round 1 of 2" in by_call(snap)[2][1]
    # (The second run passed: nothing held against it.)
    assert agent(snap, "Tester 2")["findings"] == []


def test_already_failing_before_is_not_blocked_by_r2(make_client, wait_run, project_dir):
    # (Review of S4: only where it names every test the run says failed - FAILING names test_x.)
    executor = ScriptedExecutor([Script(["FAILED tests/test_x.py::test_x - assert 0\n1 failed, 3 passed\n"],
                                        exit_code=1)])
    client, _model = make_client(scripts(ran_tests(FAILING)), executor=executor)
    cid, run_id = bugfix_run(client, project_dir)
    snap = wait_run(client, cid, run_id)
    assert opened(snap) == ["Debugger", "Coder", "Tester", "Reviewer"], by_call(snap)
    assert agent(snap, "Tester")["findings"] == []


# Review of S4 (HIGH): a line about another test does not hide this one's failure.
OTHER_BEFORE = ("Ran pytest.\n\nAlready failing before: test_old_flaky in tests/test_legacy.py\n\n"
                "Checked: ran pytest\n\nFindings: none")


def test_an_already_failing_line_about_another_test_does_not_turn_r2_off(make_client, wait_run, project_dir):
    failed = Script(["FAILED tests/test_repro.py::test_calc_2 - ZeroDivisionError\n1 failed, 3 passed\n"],
                    exit_code=1)
    executor = ScriptedExecutor([failed, PASSED])
    client, _model = make_client(scripts(ran_tests(OTHER_BEFORE), ran_tests(id="k2")), executor=executor)
    cid, run_id = bugfix_run(client, project_dir)
    snap = wait_run(client, cid, run_id)
    assert opened(snap) == ["Debugger", "Coder", "Tester", "Coder", "Tester", "Reviewer"], by_call(snap)
    held = agent(snap, "Tester")["findings"]
    assert [(f["what"], f["blocking"]) for f in held] == [
        (f"last test run failed (exit 1): {PYTEST}", True)], held


def test_the_reproduction_test_is_never_already_failing_before(make_client, wait_run, project_dir):
    # Review of S4 (re-review): what Reproduce it showed failing is the bug, not an old failure - a
    # Tester's honest line about it does not let it be taken in still failing.
    repro = Script(["FAILED tests/test_repro.py::test_calc_2 - ZeroDivisionError\n1 failed\n"], exit_code=1)
    honest = ("Ran pytest.\n\nAlready failing before: the reproduction test_calc_2 was failing before the fix"
              "\n\nChecked: ran pytest\n\nFindings: none")
    executor = ScriptedExecutor([repro, repro, PASSED])
    client, _model = make_client({
        **scripts(ran_tests(honest), ran_tests(id="k2")),
        "Debugger": [step(write("tests/test_repro.py", "def test_calc_2(): 1 / 0\n")),
                     cmd(f"{PYTEST} tests/test_repro.py", "kd"), text("Reproduced: test_calc_2 fails.")]},
        executor=executor)
    cid, run_id = bugfix_run(client, project_dir)
    snap = wait_run(client, cid, run_id)
    assert opened(snap) == ["Debugger", "Coder", "Tester", "Coder", "Tester", "Reviewer"], by_call(snap)
    held = agent(snap, "Tester")["findings"]
    assert [(f["what"], f["blocking"]) for f in held] == [
        (f"last test run failed (exit 1): {PYTEST}", True)], held
    assert "Findings are left: back to Fix it, round 1 of 2" in by_call(snap)[2][1]


UNITTEST = "python -m unittest -q test_bf037"


def test_a_tester_whose_failing_run_is_followed_by_a_help_blocks(make_client, wait_run, project_dir):
    # CL-305 B (in the browser): `unittest` failed, then `unittest -h` exited 0 and was taken for a
    # pass of the same tool - the work went in with a failing test on record.
    failed = Script(["F\nRan 1 test in 0.001s\n\nFAILED (failures=1)\n"], exit_code=1)
    usage = Script(["usage: python -m unittest [-h] [-v] [-q]\n"], exit_code=0)
    tester = [cmd(UNITTEST, "k0"), cmd("python -m unittest -h", "k1"), text(NONE)]
    executor = ScriptedExecutor([failed, usage, PASSED])
    client, _model = make_client(scripts(tester, ran_tests(id="k2")), executor=executor)
    cid, run_id = bugfix_run(client, project_dir)
    snap = wait_run(client, cid, run_id)
    assert opened(snap) == ["Debugger", "Coder", "Tester", "Coder", "Tester", "Reviewer"], by_call(snap)
    held = agent(snap, "Tester")["findings"]
    assert [(f["what"], f["blocking"]) for f in held] == [
        (f"last test run failed (exit 1): {UNITTEST}", True)], held
    assert "Findings are left: back to Fix it, round 1 of 2" in by_call(snap)[2][1]


def test_a_narrower_pass_does_not_hide_a_whole_runs_failure(make_client, wait_run, project_dir):
    tester = [cmd(PYTEST, "k0"), cmd(f"{PYTEST} tests/test_ok.py", "k1"), text(NONE)]
    executor = ScriptedExecutor([FAILED, Script(["2 passed\n"]), PASSED])
    client, _model = make_client(scripts(tester, ran_tests(id="k2")), executor=executor)
    cid, run_id = bugfix_run(client, project_dir)
    snap = wait_run(client, cid, run_id)
    assert opened(snap) == ["Debugger", "Coder", "Tester", "Coder", "Tester", "Reviewer"], by_call(snap)
    assert [f["what"] for f in agent(snap, "Tester")["findings"]] == [
        f"last test run failed (exit 1): {PYTEST}"]
    assert agent(snap, "Tester 2")["findings"] == []


def test_a_tester_that_ran_only_python_pass_does_not_pass(make_client, wait_run, project_dir):
    # CL-305 (noop): `python -c "pass"` started and is no read - and checks nothing.
    executor = ScriptedExecutor([Script([]), PASSED])
    client, _model = make_client(scripts([cmd('python -c "pass"', "k0"), text(NONE)], ran_tests()),
                                 executor=executor)
    cid, run_id = bugfix_run(client, project_dir)
    snap = wait_run(client, cid, run_id)
    assert opened(snap) == ["Debugger", "Coder", "Tester", "Coder", "Tester", "Reviewer"], by_call(snap)
    assert agent(snap, "Tester")["findings"] == [RAN_NOTHING]
    assert "ran no test" in RAN_NOTHING["what"]
    assert agent(snap, "Tester 2")["findings"] == []


def test_a_tester_that_retried_with_another_spelling_passes(make_client, wait_run, project_dir):
    # Review of S4: `pytest` not on PATH, then `python -m pytest` passed - the same tool, passing.
    missing = Script(["'pytest' is not recognized as an internal or external command\n"], exit_code=1)
    executor = ScriptedExecutor([missing, PASSED])
    tester = [cmd("pytest -q", "k0"), cmd(PYTEST, "k1"), text(NONE)]
    client, _model = make_client(scripts(tester), executor=executor)
    cid, run_id = bugfix_run(client, project_dir)
    snap = wait_run(client, cid, run_id)
    assert opened(snap) == ["Debugger", "Coder", "Tester", "Reviewer"], by_call(snap)
    assert agent(snap, "Tester")["findings"] == []


def test_a_tester_is_told_a_pass_needs_a_command_on_record(make_client, wait_run, project_dir):
    client, _model = make_client(scripts(ran_tests()), executor=ScriptedExecutor([PASSED]))
    cid, run_id = bugfix_run(client, project_dir)
    snap = wait_run(client, cid, run_id)
    assert RUN_TO_PASS in agent(snap, "Tester")["task"]
    assert all(RUN_TO_PASS not in agent(snap, name)["task"] for name in ("Debugger", "Coder", "Reviewer"))


def test_a_tester_that_only_read_does_not_pass(make_client, wait_run, project_dir):
    # Review of S4: `ls` checks nothing - R3 counts a command that started and is no mere read.
    executor = ScriptedExecutor([Script(["calc.py\n"]), PASSED])
    client, _model = make_client(scripts([cmd("ls", "k0"), text(NONE)], ran_tests()), executor=executor)
    cid, run_id = bugfix_run(client, project_dir)
    snap = wait_run(client, cid, run_id)
    assert opened(snap) == ["Debugger", "Coder", "Tester", "Coder", "Tester", "Reviewer"], by_call(snap)
    assert agent(snap, "Tester")["findings"] == [RAN_NOTHING]


def test_a_check_whose_command_the_user_declined_stops_at_ready_for_you(make_client, wait_run, project_dir):
    # Review of S4: no loop back to a Coder who could not act on it - the user's, not checked.
    client, _model = make_client(scripts(ran_tests(), review=False), executor=ScriptedExecutor([]))
    cid, run_id = bugfix_run(client, project_dir, mode="auto_edit")
    snap = until(client, cid, lambda s: [c for c in s["commands"] if c["status"] == "proposed"])
    (proposed,) = [c for c in snap["commands"] if c["status"] == "proposed"]
    assert client.post(f"/api/commands/{proposed['id']}/reject", headers=OWN).status_code == 200
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"])
    assert (row(snap)["status"], row(snap)["why"]) == ("ready", f"Not checked: you declined {PYTEST}"), row(snap)
    assert opened(snap) == ["Debugger", "Coder", "Tester"], by_call(snap)
    assert [f["what"] for f in agent(snap, "Tester")["findings"]] == [f"not checked: you declined {PYTEST}"]


def test_a_tester_at_the_reproduce_step_may_see_the_test_fail(make_client, wait_run, project_dir):
    # Review of S4: there the failing test is the work - said so, and nothing is held against it.
    # (In the ready Bugfix a Debugger reproduces and may open no Tester there - the step's door: a
    # recipe of the user's whose reproduce step is a Tester's.)
    fails = Script(["FAILED tests/test_repro.py::test_calc_2 - ZeroDivisionError\n1 failed\n"], exit_code=1)
    client, _model = make_client({
        "Lead": [spawn("Tester", "show the bug with a failing test", "t1"), spawn("Coder", "fix it", "c1"),
                 text("done")],
        "Tester": ran_tests(), "Coder": [step(write("calc.py", "x = 1\n")), text("fixed")]},
        executor=ScriptedExecutor([fails]))
    drawn = made(client, "Show then fix", graph(
        [part("reproduce", "Reproduce it", {"role": "Tester"}), part("fix", "Fix it", {"role": "Coder"})],
        [("start", "reproduce"), ("reproduce", "fix"), ("fix", "end")]))
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never", teams_mode="manual",
                        teams=[{"team_id": teams_of(client)["Web app"]["id"], "recipe_id": drawn["id"]}])
    snap = wait_run(client, cid, run_id)
    assert opened(snap) == ["Tester", "Coder"], by_call(snap)
    assert REPRODUCE_FIRST in agent(snap, "Tester")["task"]
    assert [(f["what"], f["blocking"]) for f in agent(snap, "Tester")["findings"]] == [
        ("fails as it should: tests/test_repro.py::test_calc_2", False)]


def test_a_tester_that_ran_nothing_does_not_pass(make_client, wait_run, project_dir):
    # R3: it could run commands, and ran none - what it says of the tests is not on record.
    executor = ScriptedExecutor([PASSED])
    client, _model = make_client(scripts([text(NONE)], ran_tests()), executor=executor)
    cid, run_id = bugfix_run(client, project_dir)
    snap = wait_run(client, cid, run_id)
    assert opened(snap) == ["Debugger", "Coder", "Tester", "Coder", "Tester", "Reviewer"], by_call(snap)
    assert agent(snap, "Tester")["findings"] == [RAN_NOTHING]
    assert "Findings are left: back to Fix it, round 1 of 2" in by_call(snap)[2][1]
    assert agent(snap, "Tester 2")["findings"] == []


def test_a_reviewer_without_run_command_is_not_held_to_r3(make_client, wait_run, project_dir):
    executor = ScriptedExecutor([PASSED])
    client, _model = make_client(scripts(ran_tests()), executor=executor)
    cid, run_id = bugfix_run(client, project_dir)
    snap = wait_run(client, cid, run_id)
    assert opened(snap) == ["Debugger", "Coder", "Tester", "Reviewer"], by_call(snap)
    # (It ran no command - it has none to run: its "none" stands.)
    assert not [c for c in snap["commands"] if c["agent_id"] == agent(snap, "Reviewer")["id"]]
    assert agent(snap, "Reviewer")["findings"] == []
    assert row(snap)["status"] == "in"  # (Full auto takes it in)


def test_a_cli_tester_whose_commands_are_not_seen_is_not_held_to_r3(
        make_client, wait_run, project_dir, monkeypatch):
    # (A CLI whose own work KOLONİ does not record - Codex's, say: its commands may have run.)
    monkeypatch.setattr("app.handoff.counted_on", lambda model: False)
    client, _model = make_client(scripts([text(NONE)]))
    cid, run_id = bugfix_run(client, project_dir)
    snap = wait_run(client, cid, run_id)
    assert opened(snap) == ["Debugger", "Coder", "Tester", "Reviewer"], by_call(snap)
    assert agent(snap, "Tester")["findings"] == []


def test_bugfix_failing_test_goes_back_to_fix_twice_then_stops(make_client, wait_run, project_dir):
    # R1: Test it loops back to Fix it, at most 2 rounds, as Review it does - then the user's.
    executor = ScriptedExecutor([FAILED, FAILED, FAILED])
    client, _model = make_client(
        scripts(ran_tests(), ran_tests(id="k2"), ran_tests(id="k3"), review=False), executor=executor)
    cid, run_id = bugfix_run(client, project_dir)
    snap = wait_run(client, cid, run_id)
    assert opened(snap) == ["Debugger", "Coder", "Tester", "Coder", "Tester", "Coder", "Tester"], by_call(snap)
    state = row(snap)
    # (At Ready for you: at Full auto nobody is asked - it is taken in with the findings said.)
    assert (state["status"], state["why"]) == ("in", "findings are left after 2 rounds of Test it"), state
    told = [said for _status, said in by_call(snap)]
    assert "round 1 of 2" in told[2] and "round 2 of 2" in told[4]
    assert "The recipe stops here: findings are left after 2 rounds of Test it" in told[6]


def test_the_reproduce_step_is_told_to_write_a_failing_test_only(make_client, wait_run, project_dir):
    # R4: Reproduce it writes the failing test; Fix it makes it pass.
    executor = ScriptedExecutor([PASSED])
    client, _model = make_client(scripts(ran_tests()), executor=executor)
    cid, run_id = bugfix_run(client, project_dir)
    snap = wait_run(client, cid, run_id)
    assert REPRODUCE_FIRST in agent(snap, "Debugger")["task"]
    assert all(REPRODUCE_FIRST not in agent(snap, name)["task"] for name in ("Coder", "Tester", "Reviewer"))
    assert [s["name"] for s in row(snap)["steps"]][0] == "Reproduce it with a failing test"
