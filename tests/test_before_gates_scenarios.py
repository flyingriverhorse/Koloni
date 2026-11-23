"""k-bakis-yeri N: a test run whose failures were all failing before this turn (S7) is said, not
sent back - so it holds back no look either: a big change still gets KOLONİ's review. (A failure
of the turn's own still keeps the look off: test_proof_review_scenarios
`test_failing_tests_are_fixed_before_any_look`.) A fake model per agent, a scripted executor."""

import pytest

from app import proof
from app.agent import before_mixin
from tests.fakes import ScriptedExecutor
from tests.test_chat_flow import text
from tests.test_chat_teams_scenarios import OWN
from tests.test_proof_before_scenarios import ONE, PYTEST, failing
from tests.test_proof_end_scenarios import begin, texts
from tests.test_proof_review_scenarios import BIG, MERGE, SIGN, calls_of, reviewers
from tests.test_spawn import call, step

pytestmark = pytest.mark.no_po


def test_a_change_whose_failing_tests_were_failing_before_is_still_looked_over(
    make_client, wait_run, project_dir
):
    executor = ScriptedExecutor([failing(ONE), failing(ONE), failing(ONE)])
    client, model = make_client(
        {
            "Lead": [step(call("write_file", {"path": "a.py", "content": BIG}, "w")), text("done")],
            "Reviewer": [MERGE],
        },
        executor=executor,
    )
    cid, run_id = begin(client, project_dir, check_command=PYTEST)
    snap = wait_run(client, cid, run_id)
    rows = texts(snap)
    assert before_mixin.BEFORE.format(n=1, m=0) in rows, rows
    assert f"Review: Reviewer ({SIGN}) - MERGE, no findings" in rows, rows
    assert [a["name"] for a in reviewers(snap)] == ["Reviewer"]
    # (and the Reviewer is told so: a red line failing before is no finding of the change's)
    assert before_mixin.BEFORE.format(n=1, m=0) in calls_of(model, "Reviewer")[0]


def test_still_failing_reads_past_rows_failing_before():
    failed = proof.row("tests", "failed", "Tests failed: x", "x")
    assert proof.still_failing([failed])
    assert not proof.still_failing([{**failed, "before": True}])
    assert not proof.still_failing([proof.row("tests", "passed", "Tests passed: x", "x")])


class ByContent(ScriptedExecutor):
    """A test run fails wherever a.py is the held work's (its x89 line), and passes elsewhere -
    in the project, and in an old code without it."""

    async def start(self, command_id, command, cwd, copy=None, links=None, secrets=None, env=None):
        from pathlib import Path

        from tests.fakes import ScriptedCommand
        from tests.test_proof_before_scenarios import passing

        here = Path(cwd) / "a.py"
        held = here.is_file() and "x89 = 89" in here.read_text(encoding="utf-8")
        self.started.append((command, str(cwd)))
        return ScriptedCommand(failing(ONE) if held else passing(), self, command_id)


def test_fix_it_on_work_held_for_its_tests_excuses_none_of_them_as_failing_before(
    make_client, wait_run, project_dir
):
    # (B3: the old code S7 runs a failure on is the project's - not the kept copy, which holds
    # the held work's own failure: that was never "failing before this turn")
    from tests.test_chat_teams_scenarios import teams_of
    from tests.test_claim_scenarios import write
    from tests.test_recipe_run_scenarios import made
    from tests.test_recipes_scenarios import graph
    from tests.test_recipes_scenarios import step as part
    from tests.test_spawn import begin as begin_in
    from tests.test_spawn import spawn

    executor = ByContent([])
    client, model = make_client(
        {
            "Lead": [spawn("Coder", "fix it", "c1"), text("done 0")],
            "Coder": [step(write("a.py", BIG)), text("fixed")],
            "Reviewer": [MERGE, MERGE],
        },
        executor=executor,
    )
    (project_dir / "tests").mkdir(exist_ok=True)
    (project_dir / "tests" / "test_a.py").write_text("def test_x(): pass\n", encoding="utf-8")
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    client.patch(
        f"/api/projects/{pid}", json={"check_command": PYTEST, "fix_rounds": 1}, headers=OWN
    )
    recipe = made(
        client,
        "Just fix it",
        {
            **graph([part("fix", "Fix it", {"role": "Coder"})], [("start", "fix"), ("fix", "end")]),
            "checks": {"tests": True, "review": True, "fix_rounds": 0},
        },
    )
    web = teams_of(client)["Web app"]
    cid, run_id = begin_in(
        client,
        project_dir,
        mode="full_auto",
        spawn_approval="never",
        teams_mode="manual",
        teams=[{"team_id": web["id"], "recipe_id": recipe["id"]}],
    )
    snap = wait_run(client, cid, run_id)
    (kept,) = [r for r in rows_of(snap, run_id) if r["kind"] == "not_taken"]
    assert not (project_dir / "a.py").exists()
    # (Fix it's Lead changes a line that does not fix the failing test)
    model.by_agent["Lead"] += [
        step(write("a.py", BIG.replace("x1 = 1", "y1 = 1"), "w9")),
        text("renamed it"),
        *[text(f"done {i}") for i in range(3)],
    ]
    client.patch(f"/api/conversations/{cid}", json={"lead_hands_code": False}, headers=OWN)
    went = client.post(
        f"/api/runs/{run_id}/held/fix",
        json={"merge_id": kept["merge_id"], "reply": "fix the code"},
        headers=OWN,
    )
    assert went.status_code == 202, went.text
    second = went.json()["run_id"]
    snap = wait_run(client, cid, second)
    said = [r["text"] for r in rows_of(snap, second)]
    assert not any("failing before" in one for one in said), said
    assert not (project_dir / "a.py").exists(), (said, executor.started)


def rows_of(snap, run_id):
    return [
        r
        for m in snap["messages"]
        if m["role"] == "checked" and m["run_id"] == run_id
        for r in m["checked"]
    ]
