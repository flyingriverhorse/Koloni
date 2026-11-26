"""Tarif maliyeti T0: how many agents each recipe opens, from its drawing - the fewest, where no
review finds a problem (`recipe_run.least`), and the most, every loop's rounds spent
(`recipe_run.cap`) - is on every recipe the list gives (`RecipeOut.agents`). The ready recipes'
numbers and a 2-line fix through the ready Bugfix are pinned: a budget a recipe change meets on
CI. T1 thinned Bugfix to Reproduce it -> Fix it -> Checks: KOLONİ's fix round and the user's Ask
for changes go back to Fix it, past the failing test Reproduce it showed (`recipe_run.back_to`).
T3 (0195) thinned Feature to Write the spec -> Build it -> UI review, Model change and Pipeline
change to their own checks, and KOLONİ's fix round gives a recipe's loops no rounds again (the
user's Ask for changes does). A fake model and a scripted executor."""

import json

import pytest

from app import recipe_run
from app.agent import review_mixin
from app.schemas import RecipeGraph
from tests.fakes import Script, ScriptedExecutor
from tests.test_chat_flow import text
from tests.test_chat_teams_scenarios import OWN, former, teams_of
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
from tests.test_spawn import begin, call, spawn, step

# Each ready recipe's (least, most), from the migrated drawings - a team's experts step one.
COUNTS = {
    "Feature": (3, 7),
    "Bugfix": (2, 2),
    "Review only": (3, 3),
    "Integration": (5, 9),
    "Quality check": (3, 8),
    "Model change": (4, 10),
    "Pipeline change": (2, 6),
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


@pytest.mark.no_po  # (the Scout's request would be one more call)
def test_a_two_line_fix_through_bugfix_opens_two_agents_and_asks_the_lead_three_times(
    make_client, wait_run, project_dir, monkeypatch
):
    # The budget (T1: before, 4 agents and 5 calls). KOLONİ's review and its ask for a test are on
    # in this module (conftest): with no Tester, KOLONİ runs the tests; a small change gets no
    # review, the recipe's or KOLONİ's.
    guess(monkeypatch, PYTEST)
    # (and Take in's check of the Debugger's own test, tests/test_repro.py - 0.1.7; a fourth run
    # would find no script)
    executor = ScriptedExecutor([REPRO, PASSED, PASSED])
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
    # (and Take in's check of the Debugger's own test - 0.1.7)
    executor = ScriptedExecutor([REPRO, FAILED, PASSED, PASSED])
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


@pytest.mark.parametrize(
    ("name", "back", "kept", "review"),
    [
        ("Feature", "Build it", ["spec"], "ui"),
        ("Model change", "Build it", ["plan", "experts"], "metrics"),
        ("Pipeline change", "Change the pipeline", [], "quality"),
    ],
)
def test_a_thin_recipe_goes_back_to_its_build_and_koloni_s_round_keeps_its_rounds(
    make_client, name, back, kept, review
):
    # T3: the user's Ask for changes gives the loops their rounds again; KOLONİ's fix round, the
    # same way back, does not - its review runs again, and findings once its loop ran out are the
    # user's (before 0195 each fix round gave the review group 2 rounds more).
    client, _model = make_client([])
    ready = {r["name"]: r["graph"] for r in listed(client)["recipes"] if r["ready"]}
    # (Its review is none of KOLONİ's: a big or security-touching change still gets KOLONİ's look.)
    assert {s["who"].get("role") for s in ready[name]["steps"]}.isdisjoint(review_mixin.REVIEWERS)
    for anew in (True, False):
        state = _at_its_end(ready[name])
        state.update(rounds={review: 2}, sent_back=review)
        assert recipe_run.back_to(state, anew) == back and state["done"] == kept
        assert state["rounds"] == ({} if anew else {review: 2})
        assert recipe_run.ahead(state)["at"] == review  # (its review in the way again)
        assert recipe_run.found_left(state) is None  # (sent back by a word, not by its loop)


def test_integration_s_fix_round_goes_back_to_its_plan(make_client):
    # (Pinned, not changed - tarifler §3: its one loop goes to Plan, so a fix round of KOLONİ's
    # opens the Planner, the experts' check, the Coder and the Tester again.)
    client, _model = make_client([])
    ready = {r["name"]: r["graph"] for r in listed(client)["recipes"] if r["ready"]}
    state = _at_its_end(ready["Integration"])
    assert recipe_run.back_to(state, anew=False) == "Plan" and state["done"] == ["learn"]


@pytest.mark.no_po
def test_a_bugfix_with_its_own_test_and_review_steps_gets_no_review_of_kolonis(
    make_client, wait_run, project_dir, monkeypatch
):
    # (The ready Bugfix before T1, a copy of the user's now: 4 agents, the Lead asked 5 times;
    # the Tester's run passed after the last change and the recipe's Reviewer looked.)
    guess(monkeypatch, PYTEST)
    # (and Take in's check of the Debugger's own test - 0.1.7)
    executor = ScriptedExecutor([REPRO, PASSED, PASSED])
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


@pytest.mark.no_po
def test_a_steps_suggestions_reach_the_next_step_by_findings_from(
    make_client, wait_run, project_dir, monkeypatch
):
    # (CL-345: the thin Bugfix's Lead handing the Debugger's findings to Fix it was refused -
    # "left suggestions only - they are the user's": no step's brief carries a step's report on,
    # so a recipe step's findings, suggestions too, are its handoff to the next - those for the
    # next step's role or for none, never another role's)
    from tests.test_spawn import call

    guess(monkeypatch, PYTEST)
    said = (
        "Reproduced: calc(2) crashes.\n\n## Findings\n"
        "- calc.py:2 divides by x with no check for 0 | kind: code | role: Coder | suggestion\n"
        "- the crash shows only with 0 | kind: code | role: none | suggestion\n"
        "- the README's example is wrong | kind: docs | role: Tester | suggestion"
    )
    lead = [
        spawn("Debugger", "reproduce the crash", "d1"),
        step(
            call(
                "spawn_agent",
                {"role": "Coder", "task": "fix it", "findings_from": "Debugger"},
                "c0",
            )
        ),
        text("done"),
    ]
    client, model = make_client(
        {"Lead": lead, "Debugger": [*REPRODUCES[:2], text(said)], "Coder": fixed()},
        # (and Take in's check of the Debugger's own test, tests/test_repro.py - 0.1.7)
        executor=ScriptedExecutor([REPRO, PASSED, PASSED]),
    )
    cid, run_id = bugfix_run(client, project_dir, ready=True)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert opened(snap) == ["Debugger", "Coder"], by_call(snap)
    first = model.calls_of["Coder"][0][1]["content"]
    assert "divides by x with no check for 0" in first, first[-600:]
    assert "the crash shows only with 0" in first and "README" not in first, first[-600:]


@pytest.mark.no_po
def test_a_steps_suggestions_reach_no_step_its_arrow_does_not_go_to(
    make_client, wait_run, project_dir
):
    # (B-192 outside the handoff: a Reviewer's step before the Debugger's - its suggestions are
    # the user's, never Fix it's, the step after the next)
    from tests.test_recipe_run_scenarios import made
    from tests.test_spawn import begin, call

    said = (
        "Looked.\n\n## Findings\n"
        "- rename calc to divide | kind: code | role: Coder | suggestion\n\nVerdict: MERGE"
    )
    lead = [
        spawn("Reviewer", "look first", "r1"),
        spawn("Debugger", "trace it", "d1"),
        step(
            call(
                "spawn_agent",
                {"role": "Coder", "task": "fix it", "findings_from": "Reviewer"},
                "c0",
            )
        ),
        spawn("Coder", "fix it", "c1"),
        text("done"),
    ]
    client, model = make_client(
        {
            "Lead": lead,
            "Reviewer": [text(said)],
            "Debugger": [text("reproduced")],
            "Coder": [text("fixed")],
        }
    )
    recipe = made(
        client,
        "Look, reproduce, fix",
        {
            **graph(
                [
                    part("look", "Look first", {"role": "Reviewer"}),
                    part("trace", "Trace it", {"role": "Debugger"}),
                    part("fix", "Fix it", {"role": "Coder"}),
                ],
                [("start", "look"), ("look", "trace"), ("trace", "fix"), ("fix", "end")],
            ),
            "checks": {"tests": False, "review": False},
        },
    )
    backend = former(client, "Backend / API")["Backend / API"]  # (a ready team until 0.1.10)
    cid, run_id = begin(
        client,
        project_dir,
        mode="full_auto",
        spawn_approval="never",
        teams_mode="manual",
        teams=[{"team_id": backend["id"], "recipe_id": recipe["id"]}],
    )
    snap = wait_run(client, cid, run_id)
    refused = [result for status, result in by_call(snap) if "findings_from" in (result or "")]
    assert refused and "left suggestions only" in refused[0], by_call(snap)
    assert all("rename calc" not in call[1]["content"] for call in model.calls_of["Coder"])


# --- the thin Feature (T3, 0195): Write the spec -> Build it -> UI review -> Checks -----------------

LOOKED = "Looked at its screens.\n\nChecked: read calc.py\n\nFindings: none"


def built(body="def calc(x):\n    return 1 / x if x else 0\n"):
    """The Coder's change with a test of it (KOLONİ asks for none - it is on in this module)."""
    test = "from calc import calc\n\n\ndef test_zero():\n    assert calc(0) == 0\n"
    return [step(write("calc.py", body), write("tests/test_calc.py", test, "w2")), text("built")]


def feature_lead(*more):
    """The Orchestrator's way through the thin Feature at Full auto - it answers Ask me for the
    user - then `more`, then its answer."""
    from tests.test_lead_decides import says

    return [
        spawn("Spec writer", "write the spec", "s1"),
        says("Go on", "The spec covers it."),
        spawn("Coder", "build it", "c0"),
        spawn("UI designer", "look at its screens", "u0"),
        *more,
        text("done"),
    ]


def feature_run(client, project_dir):
    """The Web app team by its default, the ready Feature, at Full auto."""
    web = teams_of(client)["Web app"]
    return begin(
        client,
        project_dir,
        mode="full_auto",
        spawn_approval="never",
        teams_mode="manual",
        teams=[{"team_id": web["id"], "recipe_id": None}],
    )


@pytest.mark.no_po
def test_a_small_feature_opens_three_agents_and_asks_the_lead_five_times(
    make_client, wait_run, project_dir, monkeypatch
):
    # (Before T3 the same work opened six: its four reviews at once.) KOLONİ runs the tests; a small
    # change gets no review of KOLONİ's.
    guess(monkeypatch, PYTEST)
    client, model = make_client(
        {
            "Lead": feature_lead(),
            "Spec writer": [text("the spec")],
            "Coder": built(),
            "UI designer": [text(LOOKED)],
        },
        executor=ScriptedExecutor([PASSED] * 2),
    )
    cid, run_id = feature_run(client, project_dir)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert row(snap)["recipe"] == "Feature"
    assert opened(snap) == ["Spec writer", "Coder", "UI designer"], by_call(snap)
    assert len(snap["agents"]) == 4, by_call(snap)  # (the Lead and its three: no helper)
    assert len(model.calls_of["Lead"]) == 5  # (three spawn_agent calls, Ask me, the answer)
    rows = texts(snap)
    assert rows[0] == f"Tests passed: {PYTEST} (guessed) - 4 passed", rows
    assert review_mixin.SMALL.format(lines=7, files=2) in rows, rows
    assert row(snap)["status"] == "in"


@pytest.mark.no_po
def test_a_big_feature_still_gets_one_kolonis_reviewer(make_client, project_dir, monkeypatch):
    # (The UI designer is none of KOLONİ's reviewers: its look keeps KOLONİ's from no change.)
    from tests.test_proof_review_scenarios import MERGE, reviewers
    from tests.test_recipe_review_once_scenarios import ended

    guess(monkeypatch, PYTEST)
    client, _model = make_client(
        {
            "Lead": [*feature_lead(), text("done again")],
            "Spec writer": [text("the spec")],
            "Coder": built(BIG),
            "UI designer": [text(LOOKED)],
            "Reviewer": [MERGE],
            "Reviewer 2": [MERGE],  # (one more would be counted, not failed)
        },
        executor=ScriptedExecutor([PASSED] * 6),
    )
    cid, run_id = feature_run(client, project_dir)
    snap = ended(client, cid, run_id, 1)
    assert [a["name"] for a in reviewers(snap)] == ["Reviewer"], texts(snap)
    assert opened(snap)[:3] == ["Spec writer", "Coder", "UI designer"], by_call(snap)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert row(snap)["status"] == "in", row(snap)


@pytest.mark.no_po
def test_koloni_s_fix_round_sends_the_feature_back_to_build_it_and_its_ui_review_runs_again(
    make_client, wait_run, project_dir, monkeypatch
):
    guess(monkeypatch, PYTEST)
    client, model = make_client(
        {
            "Lead": feature_lead(
                spawn("Coder", "fix the failing test", "c1"),
                spawn("UI designer", "look again", "u1"),
            ),
            "Spec writer": [text("the spec")],
            "Coder": built("def calc(x):\n    return 1 / x\n"),
            "Coder 2": fixed(),
            "UI designer": [text(LOOKED)],
            "UI designer 2": [text(LOOKED)],
        },
        executor=ScriptedExecutor([FAILED, PASSED, PASSED]),
    )
    cid, run_id = feature_run(client, project_dir)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert opened(snap) == ["Spec writer", "Coder", "UI designer", "Coder", "UI designer"], by_call(
        snap
    )
    assert any(
        "KOLONİ's checks send the recipe back" in said and "goes on from Build it" in said
        for _status, said in by_call(snap)
    ), by_call(snap)
    assert len(model.calls_of["Lead"]) == 7
    # (The spec written once; Build it and UI review twice.)
    assert [(p["part"], len(p["agents"])) for p in row(snap)["passes"]] == [
        ("spec", 1),
        ("build", 1),
        ("ui", 1),
        ("build", 1),
        ("ui", 1),
    ], row(snap)
    assert row(snap)["status"] == "in"
    assert "Sent back to fix: round 1 (until it passes, 1 failing → 0)" in texts(snap), texts(snap)


LABEL = "Looked.\n\n## Findings\n- the button has no label | kind: code | role: Coder\n"


def look_lead(*more):
    """Build it, UI review (it finds), Build it again, UI review (it finds again): its one round
    spent; then `more`, then the Orchestrator's answer."""
    return [
        spawn("Coder", "build it", "c0"),
        spawn("UI designer", "look at it", "u0"),
        step(
            call(
                "spawn_agent",
                {"role": "Coder", "task": "fix it", "findings_from": "UI designer"},
                "c1",
            )
        ),
        spawn("UI designer", "look again", "u1"),
        *more,
        text("done"),
    ]


def look_run(client, project_dir, mode="full_auto"):
    """The Web app team by Build it -> UI review, back once - its Checks the tests and a review."""
    from tests.test_recipe_run_scenarios import made

    drawn = graph(
        [
            part("build", "Build it", {"role": "Coder"}),
            part("ui", "UI review", {"role": "UI designer"}, done_when="no_findings"),
        ],
        [("start", "build"), ("build", "ui"), ("ui", "end")],
        loops=[{"from": "ui", "to": "build", "rounds": 1}],
    )
    recipe = made(client, "Build and look", {**drawn, "checks": {"tests": True, "review": True}})
    return begin(
        client,
        project_dir,
        mode=mode,
        spawn_approval="never",
        teams_mode="manual",
        teams=[{"team_id": teams_of(client)["Web app"]["id"], "recipe_id": recipe["id"]}],
    )


@pytest.mark.no_po
def test_a_loop_run_out_gets_no_round_again_from_koloni_s_fix_round(
    make_client, wait_run, project_dir, monkeypatch
):
    # T3a: the review's loop runs out; KOLONİ's failing tests send the recipe back - Build it and
    # UI review once more, and what UI review finds then is the user's: no round of its loop
    # again (before, the fix round gave it its round back - a third Coder and UI designer here).
    guess(monkeypatch, PYTEST)
    client, model = make_client(
        {
            "Lead": look_lead(
                spawn("Coder", "fix the failing test", "c2"),
                spawn("UI designer", "look once more", "u2"),
            ),
            "Coder": built("def calc(x):\n    return 1 / x\n"),
            "Coder 2": [text("labelled")],
            "Coder 3": fixed(),
            **{f"UI designer{n}": [text(LABEL)] for n in ("", " 2", " 3")},
        },
        executor=ScriptedExecutor([FAILED, PASSED, PASSED]),
    )
    cid, run_id = look_run(client, project_dir)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert opened(snap) == ["Coder", "UI designer"] * 3, by_call(snap)
    last = by_call(snap)[-1][1]
    assert "is at its end" in last and "Findings are left: the user sees them." in last, last
    assert len(model.calls_of["Lead"]) == 7
    # (Full auto takes it in, as at a stop before a next step - its findings said on the row.)
    assert (row(snap)["status"], row(snap)["why"]) == (
        "in",
        "findings are left after 1 round of UI review",
    )


@pytest.mark.no_po
def test_a_last_reviews_findings_left_are_named_on_the_card_with_fix_the_findings(
    make_client, wait_run, project_dir
):
    # (Review: the run reached its end with no why - the card said "ready" with no findings and
    # offered no Fix the findings, where a stop before a next step (G1.2) did.)
    client, _model = make_client(
        {
            "Lead": [*look_lead(), text("taken in")],
            "Coder": built(),
            "Coder 2": [text("labelled")],
            **{f"UI designer{n}": [text(LABEL)] for n in ("", " 2")},
        },
        executor=ScriptedExecutor([PASSED] * 3),
    )
    own_test(client, project_dir)
    cid, run_id = look_run(client, project_dir, mode="auto_edit")
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"], timeout=20)
    card = asked(snap)
    assert "findings are left after 1 round of UI review" in card["question"], card
    assert card["options"] == ["Take in", "Fix the findings", "Ask for changes"], card
    answer(client, card, "Take in")
    snap = wait_run(client, cid, run_id)
    assert row(snap)["status"] == "in", row(snap)


@pytest.mark.no_po
def test_upkeep_whose_fix_loop_ran_out_gets_no_fix_round_that_only_tests_again(
    make_client, wait_run, project_dir, monkeypatch
):
    # (Review of T3a: a fix round keeps the rounds spent, so it would go back to Run the tests and
    # stop before Find and fix the cause - a Tester for nothing. Its fixer's loop back to the tests
    # counts as the recipe's own test-to-fix loop: KOLONİ sends nothing back on top.)
    guess(monkeypatch, PYTEST)
    found = "Ran them.\n\n## Findings\n- test_calc fails | kind: code | role: Debugger\n"
    debugged = [step(write("calc.py", "def calc(x):\n    return 1 / x\n")), text("fixed")]
    client, _model = make_client(
        {
            "Lead": [
                spawn("Dependency keeper", "update them", "k0"),
                spawn("Tester", "run the tests", "t0"),
                *[
                    one
                    for n in (1, 2)
                    for one in (
                        step(
                            call(
                                "spawn_agent",
                                {"role": "Debugger", "task": "fix it", "findings_from": "Tester"},
                                f"d{n}",
                            )
                        ),
                        spawn("Tester", "run them again", f"t{n}"),
                    )
                ],
                spawn("Tester", "run them once more", "t3"),
                text("done"),
                text("done again"),
            ],
            "Dependency keeper": [step(write("deps.txt", "x==2\n")), text("updated")],
            **{f"Debugger{n}": list(debugged) for n in ("", " 2")},
            **{f"Tester{n}": [text(found)] for n in ("", " 2", " 3", " 4")},
        },
        executor=ScriptedExecutor([FAILED] * 6),
    )
    upkeep = next(r for r in listed(client)["recipes"] if r["name"] == "Upkeep")
    cid, run_id = begin(
        client,
        project_dir,
        mode="full_auto",
        spawn_approval="never",
        teams_mode="manual",
        teams=[{"team_id": teams_of(client)["Web app"]["id"], "recipe_id": upkeep["id"]}],
    )
    snap = wait_run(client, cid, run_id)
    assert opened(snap) == [
        "Dependency keeper",
        "Tester",
        "Debugger",
        "Tester",
        "Debugger",
        "Tester",
    ], by_call(snap)
    assert row(snap)["why"] == "findings are left after 2 rounds of Find and fix the cause", row(
        snap
    )
    assert row(snap)["status"] != "in" and not (project_dir / "calc.py").exists(), row(snap)


@pytest.mark.no_po
def test_a_last_reviews_findings_are_no_failing_test_where_the_test_loop_ran_out(
    make_client, wait_run, project_dir
):
    # (Review of T3: its findings are said at the end now - they hold back no work as failing
    # tests do, though the test loop before it ran out and its tests then passed.)
    from tests.test_recipe_run_scenarios import FOUND, checked, made

    client, _model = make_client(
        {
            "Lead": [
                spawn("Coder", "build it", "c0"),
                spawn("Tester", "test it", "t0"),
                step(
                    call(
                        "spawn_agent",
                        {"role": "Coder", "task": "fix it", "findings_from": "Tester"},
                        "c1",
                    )
                ),
                spawn("Tester", "test it again", "t1"),
                spawn("UI designer", "look at it", "u0"),
                text("done"),
            ],
            "Coder": built(),
            "Coder 2": [text("fixed")],
            "Tester": [text(FOUND)],
            "Tester 2": checked(),
            "UI designer": [text(LABEL)],
        },
        executor=ScriptedExecutor([PASSED] * 5),
    )
    own_test(client, project_dir)
    drawn = graph(
        [
            part("build", "Build it", {"role": "Coder"}),
            part("test", "Test it", {"role": "Tester"}, done_when="no_findings"),
            part("ui", "UI review", {"role": "UI designer"}, done_when="no_findings"),
        ],
        [("start", "build"), ("build", "test"), ("test", "ui"), ("ui", "end")],
        loops=[{"from": "test", "to": "build", "rounds": 1}],
    )
    recipe = made(client, "Test then look", {**drawn, "checks": {"tests": True, "review": True}})
    cid, run_id = begin(
        client,
        project_dir,
        mode="full_auto",
        spawn_approval="never",
        teams_mode="manual",
        teams=[{"team_id": teams_of(client)["Web app"]["id"], "recipe_id": recipe["id"]}],
    )
    snap = wait_run(client, cid, run_id)
    assert opened(snap) == ["Coder", "Tester", "Coder", "Tester", "UI designer"], by_call(snap)
    assert (row(snap)["status"], row(snap)["why"]) == (
        "in",
        "findings are left after UI review",
    ), row(snap)
