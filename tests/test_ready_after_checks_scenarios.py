"""k-sira-016: KOLONİ's end checks run before Ready for you, on the work in the recipe's copy - the
card (or Full auto's own Take in) comes after the Checked section; a fix round sends the recipe
back to work (its roles fix it, in its copy); work the checks leave failing after the rounds is
never offered nor taken in (S11's "Not taken in")."""

import os

from app.agent.stronger_mixin import FIX_IN_RECIPE
from tests.fakes import ScriptedExecutor
from tests.test_chat_flow import text
from tests.test_chat_teams_scenarios import OWN, teams_of
from tests.test_claim_scenarios import write
from tests.test_parallel import until
from tests.test_proof_end_scenarios import PASS, failing
from tests.test_recipe_run_scenarios import READY, answer, asked, one_step
from tests.test_spawn import begin, spawn, step

DONE = [text(f"done {i}") for i in range(4)]
ONCE = [spawn("Coder", "build greet.py", "c1"), *DONE]
# (the round's failure goes back: the recipe's Coder again, in the recipe's copy)
TWICE = [spawn("Coder", "build greet.py", "c1"), spawn("Coder", "fix greet.py", "c2"), *DONE]
CODERS = {"Coder": [step(write("greet.py", "print('Hello')\n")), text("built")],
          "Coder 2": [step(write("greet.py", "print('Hello!')\n", "w2")), text("fixed")]}


def started(make_client, project_dir, mode, scripts, lead=ONCE, rounds=1):
    executor = ScriptedExecutor(scripts)
    client, model = make_client({"Lead": list(lead), **CODERS}, executor=executor)
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    assert client.patch(f"/api/projects/{pid}", json={"check_command": "python check.py", **(
        {"fix_rounds": rounds} if rounds else {})}, headers=OWN).status_code == 200
    web, recipe = teams_of(client)["Web app"], one_step(client, "Build", "Coder")
    cid, run_id = begin(client, project_dir, mode=mode, spawn_approval="never",
                        teams_mode="manual", teams=[{"team_id": web["id"], "recipe_id": recipe["id"]}])
    return client, executor, cid, run_id


def rows(snap, run_id):
    return [(r["kind"], r["state"], r["text"]) for m in snap["messages"]
            if m["role"] == "checked" and m["run_id"] == run_id for r in m["checked"]]


def in_copy(executor, project_dir):
    """Every test run was in the recipe's copy, never in the project."""
    here = os.path.realpath(project_dir)
    return executor.started and all(os.path.realpath(cwd) != here for _c, cwd in executor.started)


def passed(snap, run_id):
    return any(kind == "tests" and state == "passed" for kind, state, _t in rows(snap, run_id))


def test_asked_the_card_comes_after_the_checked_section(make_client, wait_run, project_dir):
    client, executor, cid, run_id = started(make_client, project_dir, "auto_edit", [PASS, PASS])
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"])
    # (the checks ran first, in the copy - the work not in the project yet)
    assert passed(snap, run_id), rows(snap, run_id)
    assert in_copy(executor, project_dir), executor.started
    assert not (project_dir / "greet.py").exists()
    answer(client, asked(snap), "Take in")
    wait_run(client, cid, run_id)
    assert (project_dir / "greet.py").read_bytes() == b"print('Hello')\n"


def test_at_full_auto_passing_work_is_taken_in_after_its_checks(make_client, wait_run, project_dir):
    client, executor, cid, run_id = started(make_client, project_dir, "full_auto", [PASS, PASS])
    snap = wait_run(client, cid, run_id)
    assert passed(snap, run_id), rows(snap, run_id)
    first, cwd = executor.started[0]
    assert first == "python check.py" and os.path.realpath(cwd) != os.path.realpath(project_dir)
    assert (project_dir / "greet.py").read_bytes() == b"print('Hello')\n"


def test_a_fix_round_goes_back_into_the_recipe_and_its_fix_is_taken_in(make_client, wait_run,
                                                                      project_dir):
    client, executor, cid, run_id = started(make_client, project_dir, "full_auto",
                                            [failing(), PASS, PASS], lead=TWICE)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    first = next(c for c in snap["tool_calls"] if c["name"] == "spawn_agent")["result"]
    assert FIX_IN_RECIPE.split("{back}")[0] in first, first  # (no role is refused the fix)
    assert [c["status"] for c in snap["tool_calls"] if c["name"] == "spawn_agent"] == [
        "succeeded", "succeeded"]
    said = [one for _k, _s, one in rows(snap, run_id)]
    assert passed(snap, run_id) and "Sent back to fix: 1 of 1 rounds" in said, said
    assert in_copy(executor, project_dir), executor.started
    assert (project_dir / "greet.py").read_bytes() == b"print('Hello!')\n"


def test_at_full_auto_failing_work_is_never_taken_in_nor_carded(make_client, wait_run, project_dir):
    client, executor, cid, run_id = started(make_client, project_dir, "full_auto",
                                            [failing() for _ in range(4)], lead=TWICE)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert any(kind == "not_taken" for kind, _s, _t in rows(snap, run_id)), rows(snap, run_id)
    assert not any(READY in q["question"] for q in snap["questions"]), snap["questions"]
    assert in_copy(executor, project_dir), executor.started
    assert not (project_dir / "greet.py").exists()


def test_until_it_passes_a_round_that_made_no_progress_stops_the_recipe_short(make_client, wait_run,
                                                                             project_dir):
    # (k-canli-016's default: the send-back is `_round_left`'s - the same failing set again is no
    # progress, `held.halted`, and no round more is sent into the recipe)
    client, executor, cid, run_id = started(make_client, project_dir, "full_auto",
                                            [failing() for _ in range(4)], lead=TWICE, rounds=None)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    spawns = [c["result"] for c in snap["tool_calls"] if c["name"] == "spawn_agent"]
    assert [FIX_IN_RECIPE.split("{back}")[0] in one for one in spawns] == [True, False], spawns
    said = [one for _k, _s, one in rows(snap, run_id)]
    assert "Stopped after round 1: no progress in two rounds - you decide (Fix it)" in said, said
    assert any(kind == "not_taken" for kind, _s, _t in rows(snap, run_id)), said
    assert not (project_dir / "greet.py").exists()
