"""k-sira-016: KOLONİ's end checks run before Ready for you, on the work in the recipe's copy - the
card (or Full auto's own Take in) comes after the Checked section; work the checks leave failing
is never offered nor taken in (S11's "Not taken in")."""

import os

from tests.fakes import ScriptedExecutor
from tests.test_chat_flow import text
from tests.test_chat_teams_scenarios import OWN, teams_of
from tests.test_claim_scenarios import write
from tests.test_parallel import until
from tests.test_proof_end_scenarios import PASS, failing
from tests.test_recipe_run_scenarios import READY, answer, asked, one_step
from tests.test_spawn import begin, spawn, step

LEAD = [spawn("Coder", "build greet.py", "c1"), *(text(f"done {i}") for i in range(4))]
CODER = [step(write("greet.py", "print('Hello')\n")), text("built")]


def started(make_client, project_dir, mode, scripts):
    executor = ScriptedExecutor(scripts)
    client, _model = make_client({"Lead": list(LEAD), "Coder": list(CODER)}, executor=executor)
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    assert client.patch(f"/api/projects/{pid}", json={
        "check_command": "python check.py", "fix_rounds": 1}, headers=OWN).status_code == 200
    web, recipe = teams_of(client)["Web app"], one_step(client, "Build", "Coder")
    cid, run_id = begin(client, project_dir, mode=mode, spawn_approval="never",
                        teams_mode="manual", teams=[{"team_id": web["id"], "recipe_id": recipe["id"]}])
    return client, executor, cid, run_id


def rows(snap, run_id):
    return [(r["kind"], r["state"]) for m in snap["messages"]
            if m["role"] == "checked" and m["run_id"] == run_id for r in m["checked"]]


def in_copy(executor, project_dir):
    """Every test run was in the recipe's copy, never in the project."""
    here = os.path.realpath(project_dir)
    return executor.started and all(os.path.realpath(cwd) != here for _c, cwd in executor.started)


def test_asked_the_card_comes_after_the_checked_section(make_client, wait_run, project_dir):
    client, executor, cid, run_id = started(make_client, project_dir, "auto_edit", [PASS, PASS])
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"])
    # (the checks ran first, in the copy - the work not in the project yet)
    assert ("tests", "passed") in rows(snap, run_id), rows(snap, run_id)
    assert in_copy(executor, project_dir), executor.started
    assert not (project_dir / "greet.py").exists()
    answer(client, asked(snap), "Take in")
    wait_run(client, cid, run_id)
    assert (project_dir / "greet.py").read_bytes() == b"print('Hello')\n"


def test_at_full_auto_passing_work_is_taken_in_after_its_checks(make_client, wait_run, project_dir):
    client, executor, cid, run_id = started(make_client, project_dir, "full_auto", [PASS, PASS])
    snap = wait_run(client, cid, run_id)
    assert ("tests", "passed") in rows(snap, run_id), rows(snap, run_id)
    first, cwd = executor.started[0]
    assert first == "python check.py" and os.path.realpath(cwd) != os.path.realpath(project_dir)
    assert (project_dir / "greet.py").read_bytes() == b"print('Hello')\n"


def test_at_full_auto_failing_work_is_never_taken_in_nor_carded(make_client, wait_run, project_dir):
    client, executor, cid, run_id = started(make_client, project_dir, "full_auto",
                                            [failing() for _ in range(4)])
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert any(kind == "not_taken" for kind, _state in rows(snap, run_id)), rows(snap, run_id)
    assert not any(READY in q["question"] for q in snap["questions"]), snap["questions"]
    assert in_copy(executor, project_dir), executor.started
    assert not (project_dir / "greet.py").exists()
