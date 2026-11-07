"""B-375: a part with more than one arrow on forks - its ways run at once, as one part, and where
they meet again waits for all of them. A way is one group (which keeps its own wait) or steps one
after another; what cannot run so is refused as it is saved."""

from app import recipe_run
from app.agent import AgentRunner
from app.schemas import RecipeGraph, WhoLead
from tests.test_chat_flow import text
from tests.test_chat_teams_scenarios import teams_of
from tests.test_claim_scenarios import write
from tests.test_parallel import until
from tests.test_recipe_branches import said, spawns, strip_of
from tests.test_recipe_run_scenarios import READY, answer, asked, made, manual, row
from tests.test_recipes_scenarios import SMALL, graph
from tests.test_recipes_scenarios import step as part
from tests.test_spawn import call, step

# R172: "Your message" to two groups - Checks (first done) and All at once - both to the end.
TWO_GROUPS = graph(
    [part("build", "Build it", {"role": "Coder"}, group="g"),
     part("test", "Test it", {"role": "Tester"}, group="g"),
     part("docs", "Write docs", {"role": "Docs writer"}, group="g"),
     part("f1", "First at once", {"role": "Reviewer"}, group="g1"),
     part("f2", "Second at once", {"role": "UI designer"}, group="g1")],
    [("start", "g"), ("start", "g1"), ("build", "test"), ("g", "end"), ("g1", "end")],
    groups=[{"id": "g", "name": "Checks", "wait": "first"}, {"id": "g1", "name": "All at once"}])

# Build it, then Test it ∥ Write docs, then Review once both are done.
DIAMOND = graph(
    [part("a", "Build it", {"role": "Coder"}), part("b", "Test it", {"role": "Tester"}),
     part("c", "Write docs", {"role": "Docs writer"}), part("d", "Review", {"role": "Reviewer"})],
    [("start", "a"), ("a", "b"), ("a", "c"), ("b", "d"), ("c", "d"), ("d", "end")])


def roles(s):
    return [(s.who.role,)]


# --- as drawn ------------------------------------------------------------------------------------

def test_a_fork_runs_as_one_part_and_a_linear_recipe_is_as_before(make_client):
    client, _ = make_client({})
    assert said(client, TWO_GROUPS) == [] and said(client, DIAMOND) == []
    drawn = RecipeGraph.model_validate(TWO_GROUPS)
    assert recipe_run.strip(drawn) == ["start+", "end"]
    assert recipe_run.name_of(drawn, "start+") == "Checks + All at once"
    assert recipe_run.branches(drawn, "start+") == [["build", "test"], ["docs"], ["f1"], ["f2"]]
    assert recipe_run.is_group(drawn, "start+") and recipe_run.races(drawn, "start+") == ["g"]
    diamond = RecipeGraph.model_validate(DIAMOND)
    assert recipe_run.strip(diamond) == ["a", "a+", "d", "end"]
    assert recipe_run.name_of(diamond, "a+") == "Test it + Write docs"
    # Where two ways meet may fork again: two forks one after the other.
    twice = graph([*DIAMOND["steps"], part("e", "Ship", {"role": "Coder"})],
                  [("start", "b"), ("start", "c"), ("b", "a"), ("c", "a"), ("a", "d"), ("a", "e"),
                   ("d", "end"), ("e", "end")])
    assert said(client, twice) == []
    assert recipe_run.strip(RecipeGraph.model_validate(twice)) == ["start+", "a", "a+", "end"]
    small = RecipeGraph.model_validate(SMALL)
    assert recipe_run.forks(small) == {} and recipe_run.strip(small) == ["a", "b", "end"]


def test_what_a_fork_cannot_run_is_refused(make_client):
    client, _ = make_client({})
    ends = [{"id": "end", "then": "in"}, {"id": "end2", "then": "report"}]
    apart = graph(DIAMOND["steps"], [("start", "a"), ("a", "b"), ("a", "c"), ("b", "end"),
                                     ("c", "end2")], ends=ends)
    del apart["steps"][3]
    assert said(client, apart) == [("a", "Build it: its ways run at once and meet again at one "
                                         "part, which waits for all of them (an end may be it)")]
    # Where they meet, reached by an arrow from beside the ways too.
    beside = graph([*DIAMOND["steps"], part("e", "Extra", {"role": "Coder"})],
                   [("start", "e"), ("e", "a"), ("e", "d"), ("a", "b"), ("a", "c"), ("b", "d"),
                    ("c", "d"), ("d", "end")])
    assert ("d", "Review waits for the ways from Build it, and an arrow from beside them comes to "
                 "it too") in said(client, beside)
    again = graph([*DIAMOND["steps"], part("e", "Extra", {"role": "Coder"})],
                  [("start", "a"), ("a", "b"), ("a", "c"), ("b", "d"), ("b", "e"), ("c", "d"),
                   ("e", "d"), ("d", "end")])
    assert ("b", "Test it forks again on a way from Build it: each way goes on in one line to "
                 "where they meet") in said(client, again)
    straight = graph(DIAMOND["steps"], [*[(a["from"], a["to"]) for a in DIAMOND["arrows"]],
                                        ("a", "d")])
    assert said(client, straight) == [
        ("a", "Build it: its arrow to Review runs nothing beside its other ways")]
    mixed = graph([*TWO_GROUPS["steps"], part("x", "After", {"role": "Coder"})],
                  [("start", "g"), ("start", "g1"), ("build", "test"), ("g", "x"), ("x", "end"),
                   ("g1", "end")], groups=TWO_GROUPS["groups"])
    assert said(client, mixed) == [
        ("g", "Checks: a way from Your message is one group or steps one after another, not both")]
    # Arrows that go round across the ways.
    round_ = graph(DIAMOND["steps"], [*[(a["from"], a["to"]) for a in DIAMOND["arrows"]],
                                      ("d", "a")])
    assert ("d", "Review: its arrow back to Build it makes a loop with no round limit; use Loop "
                 "back") in said(client, round_)


def test_a_loop_a_room_or_a_condition_on_a_way_and_two_candidates_are_refused(make_client):
    client, _ = make_client({})
    on_way = {**DIAMOND, "loops": [{"from": "b", "to": "a", "rounds": 2}]}
    assert said(client, on_way) == [
        ("b", "Test it: its loop is on a way beside others; loop back from where they meet")]
    # From where they meet, back over the fork: a loop as any.
    over = {**DIAMOND, "loops": [{"from": "d", "to": "a", "rounds": 2}]}
    over["steps"] = [*DIAMOND["steps"][:3], {**DIAMOND["steps"][3], "done_when": "no_findings"}]
    assert said(client, over) == []
    room = {**DIAMOND, "steps": [*DIAMOND["steps"][:2], part("c", "Talk", {
        "room": ["Coder", "Tester"]}), DIAMOND["steps"][3]]}
    assert said(client, room) == [("c", "Talk: a room meets on its own, not at once with other "
                                        "steps")]
    when = {**DIAMOND, "steps": [*DIAMOND["steps"][:2], {**DIAMOND["steps"][2], "when": "problem"},
                                 DIAMOND["steps"][3]]}
    assert said(client, when) == [("c", "Write docs: a step that runs only if a problem was found "
                                        "is on its own, not at once with other steps")]
    two = {**DIAMOND, "steps": [DIAMOND["steps"][0],
                                part("b", "Try B", {"candidates": "Coder", "most": 2}),
                                part("c", "Try C", {"candidates": "Coder", "most": 2}),
                                DIAMOND["steps"][3]]}
    assert said(client, two) == [("a", "Build it: its ways have one step of candidates at most")]


# --- at work -------------------------------------------------------------------------------------

def test_two_groups_from_the_start_both_run_and_the_end_waits_for_both():
    state = recipe_run.begin(RecipeGraph.model_validate(TWO_GROUPS), "r", "R", roles)
    assert state["at"] == "start+"
    assert recipe_run.open_to(state) == ["Coder", "Docs writer", "Reviewer", "UI designer"]
    for agent, role in [("A", "Coder"), ("B", "Docs writer"), ("C", "Reviewer"),
                        ("D", "UI designer")]:
        recipe_run.opened(state, agent, role)
    recipe_run.entry_of(state, "B")["ok"] = True
    # Checks' branch done first stops its other branch - not All at once's steps.
    assert recipe_run.lost(state) == {"build", "test"} and recipe_run.outrun(state) == ["A"]
    recipe_run.entry_of(state, "A")["ok"] = False
    recipe_run.entry_of(state, "C")["ok"] = True
    assert not recipe_run.complete(state)  # (Second at once still works)
    recipe_run.entry_of(state, "D")["ok"] = True
    assert recipe_run.complete(state)
    recipe_run.advance(state)
    assert (state["at"], state["status"], state["done"]) == ("end", "ready", ["start+"])
    assert state["outrun"] == {"start+": ["build", "test"]}


def test_r179_the_steps_the_lead_picks_are_asked_for_at_once_while_the_first_group_runs():
    # B-375: All at once's "Lead picks" steps were opened only once Checks was done.
    drawn = {**TWO_GROUPS, "steps": [*TWO_GROUPS["steps"][:3], part("f1", "Plan", group="g1"),
                                     part("f2", "Sketch", group="g1")]}
    state = recipe_run.begin(RecipeGraph.model_validate(drawn), "r", "R", lambda s: [
        ("Reviewer", "UI designer")] if isinstance(s.who, WhoLead) else roles(s))
    recipe_run.opened(state, "A", "Coder")
    recipe_run.opened(state, "B", "Docs writer")  # (Checks at work)
    assert ("Open these now, beside the rest - not after them: All at once: Plan; All at once: "
            "Sketch - each one agent of a role you pick") in AgentRunner._where("Web app", state)
    recipe_run.opened(state, "C", "Reviewer")
    assert recipe_run.lead_picks(state) == ["All at once: Sketch"]
    recipe_run.opened(state, "D", "UI designer")
    assert "Open these now" not in AgentRunner._where("Web app", state)


def test_a_step_forking_into_two_both_run_and_the_one_they_meet_at_waits_for_both():
    state = recipe_run.begin(RecipeGraph.model_validate(DIAMOND), "r", "R", roles)
    recipe_run.opened(state, "A", "Coder")["ok"] = True
    assert "Next: Test it + Write docs - open Docs writer and Tester" in recipe_run.advance(state)
    assert state["at"] == "a+" and recipe_run.allowed(state) == {"tester", "docs writer"}
    recipe_run.opened(state, "B", "Tester")["ok"] = True
    recipe_run.opened(state, "C", "Docs writer")
    assert not recipe_run.complete(state) and "reviewer" not in recipe_run.allowed(state)
    recipe_run.entry_of(state, "C")["ok"] = True
    assert recipe_run.complete(state)
    assert recipe_run.advance(state) == "Next: Review - open Reviewer."
    assert state["done"] == ["a", "a+"]


def test_a_loop_from_where_the_ways_meet_goes_back_over_the_fork_and_it_runs_again():
    drawn = {**DIAMOND, "loops": [{"from": "d", "to": "a", "rounds": 1}]}
    drawn["steps"] = [*DIAMOND["steps"][:3], {**DIAMOND["steps"][3], "done_when": "no_findings"}]
    state = recipe_run.begin(RecipeGraph.model_validate(drawn), "r", "R", roles)
    recipe_run.opened(state, "A", "Coder")["ok"] = True
    recipe_run.advance(state)
    recipe_run.opened(state, "B", "Tester")["ok"] = True
    recipe_run.opened(state, "C", "Docs writer")["ok"] = True
    recipe_run.advance(state)
    recipe_run.opened(state, "D", "Reviewer").update(ok=True, found=True)
    assert "back to Build it, round 1 of 1" in recipe_run.advance(state)
    assert (state["at"], state["done"]) == ("a", [])
    recipe_run.opened(state, "A2", "Coder")["ok"] = True
    recipe_run.advance(state)
    assert state["at"] == "a+" and recipe_run.open_to(state) == ["Docs writer", "Tester"]


# --- live ----------------------------------------------------------------------------------------

def test_r172_the_second_group_runs_beside_the_first_and_both_go_to_the_end(
        make_client, wait_run, project_dir, gate):
    client, _model = make_client({
        "Lead": [spawns("Coder", "Docs writer", "Reviewer", "UI designer"), text("done")],
        # (Held: Write docs is done first, so Checks stops it.)
        "Coder": [step(write("a.py", "a\n")), gate.step(step(call("read_file", {"path": "a.py"},
                                                                   "rc"))),
                  step(write("more.py", "m\n", id="wm")), text("never said")],
        "Docs writer": [step(write("docs.md", "d\n", id="wd")), text("written")],
        "Reviewer": [step(call("read_file", {"path": "docs.md"}, "r1")), text("first")],
        "UI designer": [step(write("ui.md", "u\n", id="wu")), text("second")],
    })
    cid, run_id = manual(client, project_dir,
                         (teams_of(client)["Web app"], made(client, "Kol first", TWO_GROUPS)))
    gate.wait_partial()
    until(client, cid, lambda s: sum(a["status"] == "completed" for a in s["agents"]) == 3)
    gate.release()
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"])
    steps = row(snap)["steps"]
    assert [(one["name"], one["state"], one["group"]) for one in steps] == [
        ("Checks + All at once", "done", True), ("You", "now", False)]
    assert strip_of(snap) == [[("Build it", "stopped"), ("Test it", "stopped")],
                              [("Write docs", "done")], [("First at once", "done")],
                              [("Second at once", "done")]]
    assert not any(a["role_name"] == "Tester" for a in snap["agents"])
    answer(client, asked(snap), "Take in")
    wait_run(client, cid, run_id)
    assert (project_dir / "docs.md").exists() and (project_dir / "ui.md").exists()
    assert not (project_dir / "more.py").exists()


def test_a_step_forking_into_two_runs_both_then_the_third(make_client, wait_run, project_dir):
    client, _model = make_client({
        "Lead": [spawns("Coder"), spawns("Tester", "Docs writer"), spawns("Reviewer"),
                 text("done")],
        "Coder": [step(write("a.py", "a\n")), text("built")],
        "Tester": [step(call("read_file", {"path": "a.py"}, "rt")), text("tested")],
        "Docs writer": [step(write("docs.md", "d\n", id="wd")), text("written")],
        "Reviewer": [step(call("read_file", {"path": "docs.md"}, "rv")), text("reviewed")],
    })
    cid, run_id = manual(client, project_dir,
                         (teams_of(client)["Web app"], made(client, "Diamond", DIAMOND)))
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"])
    names = {a["id"]: a["role_name"] for a in snap["agents"]}
    assert [(p["part"], sorted(names[a] for a in p["agents"])) for p in row(snap)["passes"]] == [
        ("a", ["Coder"]), ("a+", ["Docs writer", "Tester"]), ("d", ["Reviewer"])]
    answer(client, asked(snap), "Take in")
    wait_run(client, cid, run_id)
    assert (project_dir / "docs.md").exists()
