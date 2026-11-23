"""Tarif maliyeti T0: how many agents each recipe opens, from its drawing - the fewest, where no
review finds a problem (`recipe_run.least`), and the most, every loop's rounds spent
(`recipe_run.cap`) - is on every recipe the list gives (`RecipeOut.agents`). The ready recipes'
numbers and a 2-line fix through the ready Bugfix are pinned: a budget a recipe change meets on
CI. T1 thinned Bugfix to Reproduce it -> Fix it -> Checks: KOLONİ's fix round and the user's Ask
for changes go back to Fix it, past the failing test Reproduce it showed (`recipe_run.back_to`).
A fake model and a scripted executor."""

import json

import pytest

from app import recipe_run
from app.agent import review_mixin
from app.schemas import RecipeGraph
from tests.fakes import Script, ScriptedExecutor
from tests.test_chat_flow import text
from tests.test_chat_teams_scenarios import OWN
from tests.test_claim_scenarios import write
from tests.test_parallel import until
from tests.test_proof_end_scenarios import guess, texts
from tests.test_recipe_proof_scenarios import (
    FAILED,
    PASSED,
    PYTEST,
    REPRO,
    REPRODUCES,
    bugfix_run,
    opened,
    ran_tests,
    scripts,
)
from tests.test_recipe_run_scenarios import READY, answer, asked, by_call, own_test, row
from tests.test_recipes_scenarios import SMALL, graph, listed
from tests.test_recipes_scenarios import step as part
from tests.test_spawn import spawn, step

# Each ready recipe's (least, most), from the migrated drawings - a team's experts step one.
COUNTS = {
    "Feature": (6, 16),
    "Bugfix": (2, 2),
    "Review only": (3, 3),
    "Integration": (5, 9),
    "Quality check": (3, 8),
    "Model change": (6, 14),
    "Pipeline change": (4, 10),
    "Infra change": (4, 10),
    "Docs": (2, 6),
    "Research": (2, 2),
    "Spec": (2, 2),
    "Analysis": (2, 2),
    "Upkeep": (2, 7),
    "Evolve": (3, 12),
}


# The Orchestrator's way through the thin Bugfix: Reproduce it, Fix it, then its answer.
THIN = [
    spawn("Debugger", "reproduce the crash", "d1"),
    spawn("Coder", "fix it", "c0"),
    text("done"),
]


def fixed(body="def calc(x):\n    return 1 / x if x else 0\n"):
    return [step(write("calc.py", body)), text("fixed")]


def test_every_ready_recipe_says_the_fewest_and_most_agents_it_opens(make_client):
    client, _model = make_client([])
    ready = {r["name"]: r["agents"] for r in listed(client)["recipes"] if r["ready"]}
    assert ready == {name: {"least": a, "most": b} for name, (a, b) in COUNTS.items()}


def test_least_counts_a_role_step_once_and_leaves_out_empty_slots_and_problem_steps():
    drawn = RecipeGraph.model_validate(
        graph(
            [
                part("build", "Build it", {"role": "Coder", "most": 3}),
                part("check", "Check it", {"role": "Tester"}, done_when="no_findings"),
                part("fix", "Fix it", {"role": "Debugger"}, when="problem"),
                part("look", "Look", {"role": "Reviewer"}),
                part("talk", "Talk", {"room": ["Coder", "Reviewer"]}),
            ],
            [
                ("start", "build"),
                ("build", "check"),
                ("check", "fix"),
                ("fix", "look"),
                ("look", "talk"),
                ("talk", "end"),
            ],
        )
    )
    slots = recipe_run.slot_map(drawn, recipe_run.drawn)
    # (Build it may split its work in three, or not; Fix it runs only on a problem.)
    assert (recipe_run.least(drawn, slots), recipe_run.cap(drawn, slots)) == (5, 8)
    # The Reviewer switched off (an empty slot) and nobody to fill Talk (no slot): none of theirs.
    off = {**slots, "look": [["look", []]], "talk": []}
    assert (recipe_run.least(drawn, off), recipe_run.cap(drawn, off)) == (2, 5)


def test_a_folder_recipe_that_leads_nowhere_has_no_count(make_client, project_dir):
    client, _model = make_client([])
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    folder = project_dir / ".koloni" / "recipes"
    folder.mkdir(parents=True)
    nowhere = {**SMALL, "arrows": [{"from": "start", "to": "a"}]}  # (read, never checked to run)
    for name, drawn in (("small", SMALL), ("nowhere", nowhere)):
        (folder / f"{name}.json").write_text(
            json.dumps({"name": name, "graph": drawn}), encoding="utf-8"
        )
    mine = {r["id"]: r["agents"] for r in listed(client, project_id=pid)["recipes"] if r["file"]}
    assert mine == {"small": {"least": 2, "most": 6}, "nowhere": None}


@pytest.mark.no_po  # (the Assistant PO's request would be one more call)
def test_a_two_line_fix_through_bugfix_opens_two_agents_and_asks_the_lead_three_times(
    make_client, wait_run, project_dir, monkeypatch
):
    # The budget (T1: before, 4 agents and 5 calls). KOLONİ's review and its ask for a test are on
    # in this module (conftest): with no Tester, KOLONİ runs the tests; a small change gets no
    # review, the recipe's or KOLONİ's.
    guess(monkeypatch, PYTEST)
    executor = ScriptedExecutor([REPRO, PASSED])  # (a third run would find no script)
    client, model = make_client(
        {"Lead": THIN, "Debugger": list(REPRODUCES), "Coder": fixed()}, executor=executor
    )
    cid, run_id = bugfix_run(client, project_dir, ready=True)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert opened(snap) == ["Debugger", "Coder"], by_call(snap)
    assert len(snap["agents"]) == 3, by_call(snap)  # (the Lead and its two: no helper)
    assert len(model.calls_of["Lead"]) == 3  # (two spawn_agent calls, then the answer)
    rows = texts(snap)
    assert rows[0] == f"Tests passed: {PYTEST} (guessed) - 4 passed", rows
    assert review_mixin.SMALL.format(lines=3, files=2) in rows, rows
    assert row(snap)["status"] == "in"


@pytest.mark.no_po
def test_koloni_s_fix_round_goes_back_to_fix_it_not_to_reproduce_it(
    make_client, wait_run, project_dir, monkeypatch
):
    # (Before T1's engine change it went back to Reproduce it - whose Debugger would find no new
    # failing test to show, and the work stopped Not checked.)
    guess(monkeypatch, PYTEST)
    executor = ScriptedExecutor([REPRO, FAILED, PASSED])
    lead = [*THIN[:2], spawn("Coder", "fix the failing test", "c1"), text("done")]
    client, model = make_client(
        {
            "Lead": lead,
            "Debugger": list(REPRODUCES),
            "Coder": fixed("def calc(x):\n    return 1 / x\n"),
            "Coder 2": fixed(),
        },
        executor=executor,
    )
    cid, run_id = bugfix_run(client, project_dir, ready=True)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert opened(snap) == ["Debugger", "Coder", "Coder"], by_call(snap)
    sent = by_call(snap)[1][1]
    assert "KOLONİ's checks send the recipe back" in sent and "goes on from Fix it" in sent, sent
    assert len(model.calls_of["Lead"]) == 4  # (one more spawn_agent for the round)
    # (Coder and Coder 2 at Fix it: Reproduce it ran once.)
    assert [(p["part"], len(p["agents"])) for p in row(snap)["passes"]] == [
        ("reproduce", 1),
        ("fix", 2),
    ], row(snap)
    assert row(snap)["status"] == "in"
    rows = texts(snap)
    assert f"Tests passed: {PYTEST} - 4 passed" in rows, rows
    assert "Sent back to fix: round 1 (until it passes, 1 failing → 0)" in rows, rows


def _at_its_end(drawn: dict) -> dict:
    """A run of `drawn` with every step done, at its end - where Ask for changes is answered."""
    graph_ = RecipeGraph.model_validate(drawn)
    state = recipe_run.begin(graph_, "r", "x", recipe_run.drawn)
    state.update(done=[s.id for s in graph_.steps], at="end", status=recipe_run.READY)
    return state


def test_ask_for_changes_skips_a_done_reproduce_step_only(make_client):
    client, _model = make_client([])
    ready = {r["name"]: r["graph"] for r in listed(client)["recipes"] if r["ready"]}
    # The thin Bugfix: back to Fix it, its failing test kept; again, the same.
    state = _at_its_end(ready["Bugfix"])
    assert recipe_run.back_to(state) == "Fix it" and state["done"] == ["reproduce"]
    state.update(done=["reproduce", "fix"], at="end", status=recipe_run.READY)
    assert recipe_run.back_to(state) == "Fix it"
    # Another recipe with no loop goes back to its first step, as before.
    assert recipe_run.back_to(_at_its_end(ready["Spec"])) == "Break it into tasks"
    # A reproduce step held before it was done (R4: no failing test shown) is where it goes back.
    held = _at_its_end(ready["Bugfix"])
    held.update(done=[], at="reproduce")
    assert recipe_run.back_to(held) == "Reproduce it with a failing test"
    # One with nothing but its end after it goes back to it.
    alone = graph([part("reproduce", "Show it", {"role": "Debugger"})], [("start", "reproduce")])
    alone["arrows"].append({"from": "reproduce", "to": "end"})
    assert recipe_run.back_to(_at_its_end(alone)) == "Show it"


@pytest.mark.no_po
def test_a_bugfix_with_its_own_test_and_review_steps_gets_no_review_of_kolonis(
    make_client, wait_run, project_dir, monkeypatch
):
    # (The ready Bugfix before T1, a copy of the user's now: 4 agents, the Lead asked 5 times;
    # the Tester's run passed after the last change and the recipe's Reviewer looked.)
    guess(monkeypatch, PYTEST)
    executor = ScriptedExecutor([REPRO, PASSED])
    client, model = make_client({**scripts(ran_tests()), "Coder": fixed()}, executor=executor)
    cid, run_id = bugfix_run(client, project_dir)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert opened(snap) == ["Debugger", "Coder", "Tester", "Reviewer"], by_call(snap)
    assert len(model.calls_of["Lead"]) == 5
    rows = texts(snap)
    assert f"Tests passed: {PYTEST} - run by Tester after the last change" in rows, rows
    assert review_mixin.RECIPE_DID in rows, rows


@pytest.mark.no_po
def test_the_users_ask_for_changes_goes_back_to_fix_it(make_client, wait_run, project_dir):
    # (At Auto-edit: the Debugger's run is asked first, R4; the project's own test command runs
    # unasked at every level.)
    git = Script(["git version 2.47\n"])
    executor = ScriptedExecutor([REPRO, git, git, git])
    lead = [*THIN[:2], spawn("Coder", "handle zero", "c1"), text("done")]
    client, model = make_client(
        {"Lead": lead, "Debugger": list(REPRODUCES), "Coder": fixed(), "Coder 2": fixed("x = 0\n")},
        executor=executor,
    )
    own_test(client, project_dir)
    cid, run_id = bugfix_run(client, project_dir, mode="auto_edit", ready=True)
    snap = until(client, cid, lambda s: [c for c in s["commands"] if c["status"] == "proposed"])
    (repro,) = [c for c in snap["commands"] if c["status"] == "proposed"]
    approved = client.post(
        f"/api/commands/{repro['id']}/approve", json={"remember": False}, headers=OWN
    )
    assert approved.status_code == 200
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"])
    answer(client, asked(snap), "Ask for changes: handle zero")
    snap = until(
        client,
        cid,
        lambda s: len([q for q in s["questions"] if READY in q["question"]]) == 2 and asked(s),
    )
    answer(client, asked(snap), "Take in")
    snap = wait_run(client, cid, run_id)
    assert opened(snap) == ["Debugger", "Coder", "Coder"], by_call(snap)
    assert "Backend / API goes on from Fix it" in by_call(snap)[1][1], by_call(snap)
    assert (project_dir / "calc.py").read_text() == "x = 0\n" and row(snap)["status"] == "in"


# --- KOLONİ's own look at the thin Bugfix's end (review of T1: once, as PR #24 has it) ---------

BIG = "".join(f"x{i} = {i}\n" for i in range(90))
BIG2 = "".join(f"y{i} = {i}\n" for i in range(90))


@pytest.mark.no_po
def test_a_big_fix_through_bugfix_gets_one_kolonis_reviewer_and_goes_in(
    make_client, project_dir, monkeypatch
):
    from tests.test_proof_review_scenarios import MERGE, reviewers
    from tests.test_recipe_review_once_scenarios import ended

    guess(monkeypatch, PYTEST)
    client, model = make_client(
        {
            "Lead": [*THIN, text("done again")],
            "Debugger": list(REPRODUCES),
            "Coder": fixed(BIG),
            "Reviewer": [MERGE],
            "Reviewer 2": [MERGE],  # (one more would be counted, not failed)
        },
        executor=ScriptedExecutor([REPRO, *[PASSED] * 6]),
    )
    cid, run_id = bugfix_run(client, project_dir, ready=True)
    snap = ended(client, cid, run_id, 1)
    assert [a["name"] for a in reviewers(snap)] == ["Reviewer"], texts(snap)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert row(snap)["status"] == "in", row(snap)
    assert (project_dir / "calc.py").read_text(encoding="utf-8") == BIG


@pytest.mark.no_po
def test_a_hold_on_the_bugfix_goes_back_to_fix_it_and_its_fix_is_looked_at_once(
    make_client, project_dir, monkeypatch
):
    from tests.test_proof_review_scenarios import MERGE, hold, reviewers
    from tests.test_recipe_review_once_scenarios import ended

    guess(monkeypatch, PYTEST)
    client, model = make_client(
        {
            "Lead": [*THIN[:2], spawn("Coder", "fix the findings", "c1"), text("done")],
            "Debugger": list(REPRODUCES),
            "Coder": fixed(BIG),
            "Coder 2": fixed(BIG2),
            "Reviewer": [hold("calc.py: the names are wrong")],
            "Reviewer 2": [MERGE],
            "Reviewer 3": [MERGE],  # (one more would be counted, not failed)
        },
        executor=ScriptedExecutor([REPRO, *[PASSED] * 8]),
    )
    cid, run_id = bugfix_run(client, project_dir, ready=True)
    snap = ended(client, cid, run_id, 2)
    assert [a["name"] for a in reviewers(snap)] == ["Reviewer", "Reviewer 2"], texts(snap)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert "goes on from Fix it" in by_call(snap)[1][1], by_call(snap)
    # (Coder 2 at Fix it: Reproduce it ran once.)
    assert [(p["part"], len(p["agents"])) for p in row(snap)["passes"]] == [
        ("reproduce", 1),
        ("fix", 2),
    ], row(snap)
    assert row(snap)["status"] == "in", row(snap)
    assert (project_dir / "calc.py").read_text(encoding="utf-8") == BIG2
