"""k-bakis-yeri P: KOLONİ's look at a recipe's work (a recipe with no Review step of its own, at
Test and review) reads and runs where that work is - the recipe's copy, where the end gate's own
tests ran - never the project, which does not have it yet. A fake model per agent, a scripted
executor."""

import os

import pytest

from app.agent.stronger_mixin import ON_HOLD
from tests.fakes import ScriptedExecutor
from tests.test_chat_flow import text
from tests.test_chat_teams_scenarios import OWN, teams_of
from tests.test_claim_scenarios import write
from tests.test_parallel import until
from tests.test_proof_end_scenarios import PASS
from tests.test_proof_review_scenarios import BIG, MERGE
from tests.test_recipe_run_scenarios import READY, answer, asked, made
from tests.test_recipes_scenarios import graph
from tests.test_recipes_scenarios import step as part
from tests.test_spawn import begin, call, spawn, step

pytestmark = pytest.mark.no_po

CHECK = "python check.py"
DONE = [text(f"done {i}") for i in range(3)]


def started(make_client, project_dir, mode, reviewer, scripts, **checks):
    """The user's own recipe - one step, Fix it (Coder), no Review step; its Checks step tests and
    reviews (and `checks`) - picked for Web app; its Coder writes a big calc.py; KOLONİ's Reviewer
    as given."""
    executor = ScriptedExecutor(scripts)
    client, model = make_client(
        {
            "Lead": [spawn("Coder", "fix it", "c1"), *DONE],
            "Coder": [step(write("calc.py", BIG)), text("fixed")],
            "Reviewer": reviewer,
        },
        executor=executor,
    )
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    patched = client.patch(f"/api/projects/{pid}", json={"check_command": CHECK}, headers=OWN)
    assert patched.status_code == 200, patched.text
    recipe = made(
        client,
        "Just fix it",
        {
            **graph([part("fix", "Fix it", {"role": "Coder"})], [("start", "fix"), ("fix", "end")]),
            "checks": {"tests": True, "review": True, **checks},
        },
    )
    web = teams_of(client)["Web app"]
    cid, run_id = begin(
        client,
        project_dir,
        mode=mode,
        spawn_approval="never",
        teams_mode="manual",
        teams=[{"team_id": web["id"], "recipe_id": recipe["id"]}],
    )
    return client, executor, cid, run_id


def calls_of(snap, name):
    (agent,) = [a for a in snap["agents"] if a["name"] == name]
    return {t["provider_call_id"]: t for t in snap["tool_calls"] if t["agent_id"] == agent["id"]}


def test_the_look_reads_and_runs_in_the_recipes_copy(make_client, project_dir):
    reads = step(
        call("read_file", {"path": "calc.py"}, "r1"),
        call("run_command", {"command": CHECK}, "r2"),
    )
    client, executor, cid, _run_id = started(
        make_client, project_dir, "auto_edit", [reads, MERGE], [PASS, PASS, PASS]
    )
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"], timeout=20)
    looked = calls_of(snap, "Reviewer")
    # (the file only the copy has: found, not "does not exist")
    assert looked["r1"]["status"] == "succeeded" and "x89 = 89" in looked["r1"]["result"], looked
    assert looked["r2"]["status"] == "succeeded", looked["r2"]
    # (every run - the gate's and the look's own - in the copy; the project untouched)
    here = os.path.realpath(project_dir)
    assert [cmd for cmd, _cwd in executor.started] == [CHECK, CHECK], executor.started
    assert all(os.path.realpath(cwd) != here for _c, cwd in executor.started), executor.started
    assert not (project_dir / "calc.py").exists()
    answer(client, asked(snap), "Take in")
    assert until(client, cid, lambda _s: (project_dir / "calc.py").exists(), timeout=20)


def test_what_the_looks_run_writes_in_the_copy_is_not_taken_in(make_client, project_dir):
    from tests.fakes import Script

    runs = step(call("run_command", {"command": CHECK}, "r2"))
    wrote = Script(PASS.chunks, writes={"htmlcov/index.html": "<html></html>\n"})
    client, executor, cid, _run_id = started(
        make_client, project_dir, "auto_edit", [runs, MERGE], [PASS, wrote, PASS]
    )
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"], timeout=20)
    assert calls_of(snap, "Reviewer")["r2"]["status"] == "succeeded", calls_of(snap, "Reviewer")
    answer(client, asked(snap), "Take in")
    assert until(client, cid, lambda _s: (project_dir / "calc.py").exists(), timeout=20)
    assert not (project_dir / "htmlcov").exists()


def held_rows(snap, run_id):
    return [
        r
        for m in snap["messages"]
        if m["role"] == "checked" and m["run_id"] == run_id
        for r in m["checked"]
    ]


@pytest.mark.parametrize("mode", ["full_auto", "auto_edit"])
def test_work_a_look_still_holds_is_not_taken_in_at_any_level(
    make_client, wait_run, project_dir, mode
):
    from tests.test_proof_review_scenarios import hold

    client, executor, cid, run_id = started(
        make_client,
        project_dir,
        mode,
        [hold("calc.py: the names are wrong")],
        [PASS, PASS, PASS],
        fix_rounds=0,
    )
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    rows = held_rows(snap, run_id)
    (kept,) = [r for r in rows if r["kind"] == "not_taken"]
    assert kept["text"] == f"Not taken in: {ON_HOLD}", rows
    assert kept["reason"] == "on_hold" and kept["merge_id"], kept
    assert not any(READY in q["question"] for q in snap["questions"]), snap["questions"]
    assert not (project_dir / "calc.py").exists()
    # (Fix it says why in KOLONİ's words, by the row's code)
    fixed = client.post(
        f"/api/runs/{run_id}/held/fix",
        json={"merge_id": kept["merge_id"], "reply": "rename them"},
        headers=OWN,
    )
    assert fixed.status_code == 202, fixed.text
    snap = until(client, cid, lambda s: len([m for m in s["messages"] if m["role"] == "user"]) > 1)
    said = [m["content"] for m in snap["messages"] if m["role"] == "user"][-1]
    assert "a look of KOLONİ's still held it" in said and "rename them" in said, said
