"""Tarif maliyeti T0: how many agents each recipe opens, from its drawing - the fewest, where no
review finds a problem (`recipe_run.least`), and the most, every loop's rounds spent
(`recipe_run.cap`) - is on every recipe the list gives (`RecipeOut.agents`). The ready recipes'
numbers and a 2-line fix through the ready Bugfix are pinned: a budget a recipe change meets on
CI. A fake model and a scripted executor."""

import json

import pytest

from app import recipe_run
from app.agent import review_mixin
from app.schemas import RecipeGraph
from tests.fakes import ScriptedExecutor
from tests.test_chat_flow import text
from tests.test_claim_scenarios import write
from tests.test_proof_end_scenarios import guess, texts
from tests.test_recipe_proof_scenarios import (
    PASSED,
    PYTEST,
    REPRO,
    bugfix_run,
    opened,
    ran_tests,
    scripts,
)
from tests.test_recipe_run_scenarios import by_call
from tests.test_recipes_scenarios import SMALL, graph, listed
from tests.test_recipes_scenarios import step as part
from tests.test_spawn import step

# Each ready recipe's (least, most), from the migrated drawings - a team's experts step one.
READY = {
    "Feature": (6, 16),
    "Bugfix": (4, 14),
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


def test_every_ready_recipe_says_the_fewest_and_most_agents_it_opens(make_client):
    client, _model = make_client([])
    ready = {r["name"]: r["agents"] for r in listed(client)["recipes"] if r["ready"]}
    assert ready == {name: {"least": a, "most": b} for name, (a, b) in READY.items()}


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
def test_a_two_line_fix_through_bugfix_opens_four_agents_and_asks_the_lead_five_times(
    make_client, wait_run, project_dir, monkeypatch
):
    # Today's budget (T1 thins Bugfix: 2 agents, 3 calls). KOLONİ's review and its ask for a test
    # are on in this module (conftest): the Tester's run passed after the last change, so KOLONİ
    # runs no test again; the recipe's Reviewer looked, so it opens no review of its own.
    guess(monkeypatch, PYTEST)
    executor = ScriptedExecutor([REPRO, PASSED])  # (a third run would find no script)
    fixed = [step(write("calc.py", "def calc(x):\n    return 1 / x if x else 0\n")), text("fixed")]
    client, model = make_client({**scripts(ran_tests()), "Coder": fixed}, executor=executor)
    cid, run_id = bugfix_run(client, project_dir)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert opened(snap) == ["Debugger", "Coder", "Tester", "Reviewer"], by_call(snap)
    assert len(snap["agents"]) == 5, by_call(snap)  # (the Lead and its four: no helper)
    assert len(model.calls_of["Lead"]) == 5  # (four spawn_agent calls, then the answer)
    rows = texts(snap)
    assert f"Tests passed: {PYTEST} - run by Tester after the last change" in rows, rows
    assert review_mixin.RECIPE_DID in rows, rows
