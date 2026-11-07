"""The conditional recipe step (the user's, 28 Oct: "koşullu adım ekleyelim"): a step drawn
`"when": "problem"` runs only if the part before it found a problem - a review there left
findings. Else it is passed, no agent opened, and the strip says "skipped: no problem found".
Quality check uses it: the Tester runs the tests; only if they fail, the Debugger fixes and the
Tester runs them again, at most 2 rounds; then the reviews."""

import pytest

from app import recipe_run
from app.schemas import RecipeStep
from tests.test_chat_flow import text
from tests.test_chat_teams_scenarios import OWN, teams_of
from tests.test_claim_scenarios import write
from tests.test_parallel import until
from tests.test_recipe_checks_scenarios import run_of
from tests.test_recipe_run_scenarios import (
    FOUND,
    NONE,
    answer,
    asked,
    by_call,
    recipe_named,
    row,
    strip,
)
from tests.test_recipes_scenarios import graph
from tests.test_recipes_scenarios import step as part
from tests.test_spawn import begin, call, spawn, step

TEST = part("test", "Run the tests", {"role": "Tester"}, done_when="no_findings")
FIX = part("fix", "Fix it", {"role": "Debugger"}, when="problem")
REVIEW = part("code", "Code review", {"role": "Reviewer"}, done_when="no_findings")
WAY = [("start", "test"), ("test", "fix"), ("fix", "code"), ("code", "end")]


def done(state, role, found=False, findings=None, unchecked=False):
    # (`findings`: some to hand on, as `ended` says - by default, as many as found.)
    entry = recipe_run.opened(state, f"a{len(state['agents'])}", role)
    entry.update(ok=True, found=found, findings=found if findings is None else findings,
                 unchecked=unchecked)


def quality(rounds=2):
    return run_of(graph([TEST, FIX, REVIEW], WAY, loops=[{"from": "fix", "to": "test", "rounds": rounds}]))


def test_tests_that_pass_skip_the_fix_and_the_review_runs():
    state = quality()
    done(state, "Tester")
    said = recipe_run.advance(state)
    assert state["at"] == "code" and state["unmet"] == {"fix": "no problem found"} and "fix" in state["done"]
    assert said == "Next: Code review - open Reviewer. Skipped, no problem found: Fix it."
    assert recipe_run.open_to(state) == ["Reviewer"]


def test_a_failing_test_runs_the_fix_then_the_tests_again_then_the_review():
    state = quality()
    done(state, "Tester", found=True)
    said = recipe_run.advance(state)
    assert state["at"] == "fix" and recipe_run.open_to(state) == ["Debugger"]
    assert said == ("Next: Fix it, as Run the tests found a problem. Hand its findings to Debugger "
                    "with findings_from.")
    done(state, "Debugger")
    assert recipe_run.advance(state) == ("Fixed: back to Run the tests, round 1 of 2, to check it "
                                         "again - open Tester.")
    assert state["at"] == "test" and recipe_run.round_at(state, recipe_run.graph_of(state), "test") == 1
    done(state, "Tester")
    assert recipe_run.advance(state) == "Next: Code review - open Reviewer."
    # B-177: the fix ran in a round of this pass - done, not skipped.
    assert state["at"] == "code" and state["unmet"] == {} and "fix" in state["done"]
    assert state["status"] == "running"


@pytest.mark.parametrize(("failing", "status"), [(False, "done"), (True, "ready")])
def test_a_report_end_asks_to_take_in_a_fix_and_only_a_fix(failing, status):
    """B-178: at a "report" end (Quality check's) the Debugger's fix is the user's Take in."""
    state = run_of(graph([TEST, FIX], [("start", "test"), ("test", "fix"), ("fix", "end")],
                         loops=[{"from": "fix", "to": "test", "rounds": 2}],
                         ends=[{"id": "end", "then": "report"}]))
    done(state, "Tester", found=failing)
    recipe_run.advance(state)
    if failing:
        done(state, "Debugger")
        recipe_run.advance(state)
        done(state, "Tester")
        assert recipe_run.advance(state) == ("The recipe is at its end: the user is asked to "
                                             "take the work in.")
    assert state["status"] == status


def test_a_problem_with_no_findings_to_hand_on_is_given_in_the_task():
    # (No Findings section: a problem, but nothing for findings_from.)
    state = quality()
    done(state, "Tester", found=True, findings=False)
    assert recipe_run.advance(state) == (
        "Next: Fix it, as Run the tests found a problem. Its report has no findings to hand on: "
        "give Debugger what it said in its task.")


def test_a_check_the_user_skipped_skips_the_fix_saying_nothing_was_checked():
    state = quality()
    done(state, "Tester", unchecked=True)
    assert recipe_run.advance(state) == "Next: Code review - open Reviewer. Skipped, nothing was checked: Fix it."
    assert state["unmet"] == {"fix": "nothing was checked"}


def test_a_conditional_review_that_found_nothing_goes_on_and_does_not_loop_back():
    recheck = part("fix", "Check again", {"role": "Reviewer"}, done_when="no_findings", when="problem")
    state = run_of(graph([TEST, recheck, REVIEW], WAY, loops=[{"from": "fix", "to": "test", "rounds": 2}]))
    done(state, "Tester", found=True)
    recipe_run.advance(state)
    done(state, "Reviewer")
    assert recipe_run.advance(state) == "Next: Code review - open Reviewer."


def test_tests_that_keep_failing_stop_at_the_loops_round_limit():
    state = quality(rounds=2)
    for _round in range(2):
        done(state, "Tester", found=True)
        recipe_run.advance(state)
        done(state, "Debugger")
        recipe_run.advance(state)
    done(state, "Tester", found=True)
    said = recipe_run.advance(state)
    # G1.2's end: the user's - the last fix was tested, no third Debugger opened.
    assert (state["status"], state["at"]) == ("ready", "test")
    assert state["why"] == "findings are left after 2 rounds of Fix it"
    assert said.startswith("The recipe stops here: findings are left after 2 rounds of Fix it.")
    assert len(state["agents"]) == 5  # (Tester, Debugger, Tester, Debugger, Tester)


def test_a_fix_with_no_loop_runs_once_and_two_conditional_steps_in_a_row_skip_together():
    note = part("note", "Note it", {"role": "Docs writer"}, when="problem")
    state = run_of(graph([TEST, FIX, note, REVIEW], [("start", "test"), ("test", "fix"), ("fix", "note"),
                                                     ("note", "code"), ("code", "end")]))
    done(state, "Tester")
    assert recipe_run.advance(state).endswith("Skipped, no problem found: Fix it, Note it.")
    assert state["unmet"] == {"fix": "no problem found", "note": "no problem found"}
    # Found: the fix runs - the note after it does not: the fix is no review, found nothing.
    state = run_of(graph([TEST, FIX, note, REVIEW], [("start", "test"), ("test", "fix"), ("fix", "note"),
                                                     ("note", "code"), ("code", "end")]))
    done(state, "Tester", found=True)
    recipe_run.advance(state)
    done(state, "Debugger")
    recipe_run.advance(state)
    assert (state["at"], state["unmet"]) == ("code", {"note": "no problem found"})


def test_an_old_step_writes_no_when():
    old = RecipeStep.model_validate(part("a", "Build it", {"role": "Coder"}))
    assert "when" not in old.model_dump(mode="json", by_alias=True)
    assert RecipeStep.model_validate(FIX).model_dump(mode="json", by_alias=True)["when"] == "problem"


def test_a_conditional_step_saves_and_one_that_could_never_tell_is_refused(make_client):
    client, _model = make_client({})

    def saved(name, steps, arrows, **more):
        return client.post("/api/recipes", headers=OWN, json={"name": name, "graph": graph(steps, arrows, **more)})

    ok = saved("Fix on failure", [TEST, FIX, REVIEW], WAY, loops=[{"from": "fix", "to": "test", "rounds": 2}])
    assert ok.status_code == 201, ok.text
    assert ok.json()["graph"]["steps"][1]["when"] == "problem"

    def refused(response):
        assert response.status_code == 422, response.text
        return [(one["at"], one["msg"]) for one in response.json()["detail"]]

    first = part("fix", "Fix it", {"role": "Debugger"}, when="problem")
    assert refused(saved("First", [first, REVIEW], [("start", "fix"), ("fix", "code"), ("code", "end")])) == [
        ("fix", "Fix it runs only if the step before found a problem, but that is no review (Done when: no finding is left)")]
    build = part("build", "Build it", {"role": "Coder"})
    assert refused(saved("After a build", [build, FIX], [("start", "build"), ("build", "fix"), ("fix", "end")])) == [
        ("fix", "Fix it runs only if the step before found a problem, but that is no review (Done when: no finding is left)")]
    grouped = part("fix", "Fix it", {"role": "Debugger"}, when="problem", group="g")
    assert refused(saved("Grouped", [TEST, grouped, part("x", "Other", {"role": "Coder"}, group="g")],
                         [("start", "test"), ("test", "g"), ("g", "end")], groups=[{"id": "g", "name": "At once"}])) == [
        ("fix", "Fix it: a step that runs only if a problem was found is on its own, not at once with other steps")]
    build_first = [build, TEST, FIX, REVIEW]
    assert refused(saved("Looped", build_first, [("start", "build"), ("build", "test"), *WAY[1:]],
                         loops=[{"from": "test", "to": "build", "rounds": 1}])) == [
        ("fix", "Fix it runs only if the step before found a problem, but Run the tests loops back with what it "
                "finds; keep the loop or the condition")]
    # Still refused as before: a step not reached.
    assert ("code", "Code review is not reached from Your message") in refused(
        saved("Broken", [TEST, FIX, REVIEW], [("start", "test"), ("test", "fix"), ("fix", "end")]))


# --- the ready Quality check, with the fake model -------------------------------------------------


def quality_run(client, project_dir):
    quality = teams_of(client)["Quality"]
    assert quality["default_recipe_id"] == recipe_named(client, "Quality check")["id"]
    return begin(client, project_dir, mode="auto_edit", spawn_approval="never", teams_mode="manual",
                 teams=[{"team_id": quality["id"], "recipe_id": None}])


REVIEWERS = ("Reviewer", "Security reviewer")


def reviews(at):
    return step(*(call("spawn_agent", {"role": role, "task": "review"}, f"r{at}{i}") for i, role in enumerate(REVIEWERS)))


def opened(snap):
    """The Lead's agents in the order they were opened - the reviewers, opened at once, in
    either order (under load the second one was at times on record first)."""
    roles = [a["role_name"] for a in snap["agents"] if a["depth"] == 1]
    return roles[:-len(REVIEWERS)] + sorted(roles[-len(REVIEWERS):])


# (Its tests passing, the Debugger skipped: `test_the_ready_quality_check_recipe_runs_the_tests...`.)


def test_quality_check_whose_tester_finds_a_problem_debugs_and_tests_again(make_client, wait_run, project_dir):
    client, model = make_client({
        "Lead": [spawn("Tester", "run the tests", "t1"),
                 step(call("spawn_agent", {"role": "Debugger", "task": "fix it", "findings_from": "Tester"}, "d1")),
                 spawn("Tester", "run the tests again", "t2"), reviews(1), text("all checked")],
        "Tester": [text(FOUND)], "Debugger": [step(write("calc.py", "x = 1\n")), text("fixed")],
        "Tester 2": [text(NONE)], **{role: [text(NONE)] for role in REVIEWERS}})
    cid, run_id = quality_run(client, project_dir)
    # B-178: the fix is the user's Take in, at Ready for you - not a kept copy's card.
    snap = until(client, cid, lambda s: asked(s) and "Ready for you" in asked(s)["question"])
    assert not (project_dir / "calc.py").exists()
    answer(client, asked(snap), "Take in")
    snap = wait_run(client, cid, run_id)
    assert (project_dir / "calc.py").read_text() == "x = 1\n"
    assert not [c for c in by_call(snap) if c[0] == "failed"], by_call(snap)
    assert opened(snap) == ["Tester", "Debugger", "Tester", *REVIEWERS]
    # B-177: the fix ran in round 1, then the tests passed: it shows done, not skipped.
    assert strip(row(snap)) == [("test", "done", 1), ("fix", "done", 1), ("reviews", "done", 0), ("end", "done", 0)]
    told = [said for _, said in by_call(snap)]
    assert "Next: Find and fix the cause, as Run the tests found a problem. Hand its findings" in told[0]
    assert "Fixed: back to Run the tests, round 1 of 2" in told[1]
    assert row(snap)["status"] == "in"
    # Before a fix, the Tester is told a failing test is a finding, failing before or not.
    assert "Here every test or command that fails is a finding" in model.calls_of["Tester"][0][0]["content"]


# A Tester's report as real ones come: each a problem, so the Debugger runs.
CHECKED_NOTHING = "All good.\n\nFindings: none"
NO_SECTION = "Ran the tests: 2 failed."
FAILING = "Ran pytest.\n\nAlready failing before: test_x\n\nChecked: ran pytest - test_x fails\n\nFindings: none"
# B-192: a failing test marked a suggestion is blocking all the same.
FAILS_MARKED = "Checked: ran pytest\n\n## Findings\n- test_x fails | kind: test | role: Debugger | suggestion"
# ...and suggestions alone are no problem: the Debugger is skipped.
SUGGESTS = "Checked: ran pytest, 3 passed\n\n## Findings\n- name the test better | kind: test | role: Tester | suggestion"
# (Suggestions alone with nothing checked are no pass, as nothing found is not: G1.5.)
SUGGESTS_UNCHECKED = SUGGESTS.split("\n\n", 1)[1]


@pytest.mark.parametrize(("report", "hand"), [(CHECKED_NOTHING, True), (NO_SECTION, False), (FAILING, True),
                                              (FAILS_MARKED, True), (SUGGESTS_UNCHECKED, True)])
def test_a_tester_report_that_is_no_pass_runs_the_debugger(make_client, wait_run, project_dir, report, hand):
    fix = {"role": "Debugger", "task": "fix it", **({"findings_from": "Tester"} if hand else {})}
    client, _model = make_client({
        "Lead": [spawn("Tester", "run the tests", "t1"), step(call("spawn_agent", fix, "d1")),
                 spawn("Tester", "run the tests again", "t2"), reviews(1), text("all checked")],
        "Tester": [text(report)], "Debugger": [step(write("fix.txt", "f\n")), text("fixed")],
        "Tester 2": [text(NONE)], **{role: [text(NONE)] for role in REVIEWERS}})
    cid, run_id = quality_run(client, project_dir)
    answer(client, asked(until(client, cid, asked)), "Take in")  # (B-178: the fix's)
    snap = wait_run(client, cid, run_id)
    assert not [c for c in by_call(snap) if c[0] == "failed"], by_call(snap)
    assert opened(snap) == ["Tester", "Debugger", "Tester", *REVIEWERS]
    told = by_call(snap)[0][1]
    assert ("Hand its findings to Debugger with findings_from" in told) is hand
    assert ("Its report has no findings to hand on" in told) is not hand
    if report == FAILING:  # (handed on as a finding: the Debugger's to fix)
        debugger = next(a for a in snap["agents"] if a["role_name"] == "Debugger")
        assert "already failing before: test_x" in debugger["task"]


def test_suggestions_alone_send_no_work_back_and_the_card_says_them(make_client, wait_run, project_dir):
    # B-192 (live): every small note looped the recipe; a suggestion is the user's, on the card.
    client, _model = make_client({
        "Lead": [spawn("Tester", "run the tests", "t1"), reviews(1), text("all checked")],
        "Tester": [text(SUGGESTS)], **{role: [text(NONE)] for role in REVIEWERS}})
    cid, run_id = quality_run(client, project_dir)
    snap = wait_run(client, cid, run_id)
    assert not [c for c in by_call(snap) if c[0] == "failed"], by_call(snap)
    assert opened(snap) == ["Tester", *REVIEWERS]
    assert strip(row(snap)) == [("test", "done", 0), ("fix", "skipped", 0), ("reviews", "done", 0), ("end", "done", 0)]
    assert row(snap)["status"] == "done"
    tester = next(a for a in snap["agents"] if a["role_name"] == "Tester")
    assert [(f["what"], f["blocking"]) for f in tester["findings"]] == [("name the test better", False)]


def test_next_names_each_role_of_an_all_at_once_group():
    # B-191 (review): "open Reviewer or Security reviewer" read as one of them.
    build = part("build", "Build it", {"role": "Coder"})
    reviews = [part("r1", "Code review", {"role": "Reviewer"}, done_when="no_findings", group="g"),
               part("r2", "Security review", {"role": "Security reviewer"}, done_when="no_findings", group="g")]
    state = run_of(graph([build, *reviews], [("start", "build"), ("build", "g"), ("g", "end")],
                         groups=[{"id": "g", "name": "All at once, wait for all"}]))
    done(state, "Coder")
    assert recipe_run.advance(state) == "Next: All at once, wait for all - open Reviewer and Security reviewer."
