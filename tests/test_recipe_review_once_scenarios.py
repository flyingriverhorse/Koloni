"""k-dongu-016: a recipe with no Review step of its own, at Test and review, gets KOLONİ's look at
its end on a big or security-touching change once - its Reviewer (and the Security reviewer), not
one more at each look's end (0.1.6 opened ~80); a HOLD goes back into the recipe and its fix is
looked at once more. A fake model per agent, a scripted executor."""

import pytest

from tests.conftest import TERMINAL
from tests.fakes import ScriptedExecutor
from tests.test_chat_flow import text
from tests.test_chat_teams_scenarios import OWN, teams_of
from tests.test_claim_scenarios import write
from tests.test_parallel import until
from tests.test_proof_end_scenarios import PASS, texts
from tests.test_proof_review_scenarios import BIG, MERGE, SIGN, hold, reviewers
from tests.test_recipe_run_scenarios import READY, answer, asked, by_call, made, row
from tests.test_recipes_scenarios import graph
from tests.test_recipes_scenarios import step as part
from tests.test_spawn import begin, spawn, step

pytestmark = pytest.mark.no_po

BIG2 = "".join(f"y{i} = {i}\n" for i in range(90))
SHELL = "import subprocess\nsubprocess.run(x, shell=True)\n"
# (every look that could open says MERGE: a look more is counted, not failed)
LOOKS = {
    name: [MERGE]
    for name in ("Reviewer", "Reviewer 2", "Reviewer 3", "Security reviewer", "Security reviewer 2")
}
DONE = [text(f"done {i}") for i in range(3)]


def started(make_client, project_dir, mode, scripts):
    """The user's own recipe - one step, Fix it (Coder), no Review step; its Checks step tests and
    reviews - picked for Web app, the project's tests passing."""
    client, _model = make_client(
        {**LOOKS, **scripts}, executor=ScriptedExecutor([PASS for _ in range(8)])
    )
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    assert (
        client.patch(
            f"/api/projects/{pid}", json={"check_command": "python check.py"}, headers=OWN
        ).status_code
        == 200
    )
    recipe = made(
        client,
        "Just fix it",
        {
            **graph([part("fix", "Fix it", {"role": "Coder"})], [("start", "fix"), ("fix", "end")]),
            "checks": {"tests": True, "review": True},
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
    return client, cid, run_id


def looked(snap):
    return sorted(a["name"] for a in reviewers(snap))


def ended(client, cid, run_id, most):
    """The snapshot once the run has ended - or once a look more than `most` has opened (each
    look's end opened the next one, without end: no wait on that)."""
    return until(
        client,
        cid,
        lambda s: (
            len(reviewers(s)) > most
            or next(r for r in s["runs"] if r["id"] == run_id)["status"] in TERMINAL
        ),
        timeout=20,
    )


@pytest.mark.parametrize(
    ("changed", "looks"),
    [(BIG, ["Reviewer"]), (SHELL, ["Reviewer", "Security reviewer"])],
    ids=["big", "security"],
)
def test_at_full_auto_one_look_and_the_work_is_taken_in(make_client, project_dir, changed, looks):
    client, cid, run_id = started(
        make_client,
        project_dir,
        "full_auto",
        {
            "Lead": [spawn("Coder", "fix it", "c1"), *DONE],
            "Coder": [step(write("calc.py", changed)), text("fixed")],
        },
    )
    snap = ended(client, cid, run_id, len(looks))
    assert looked(snap) == looks, (looked(snap), texts(snap))
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert row(snap)["status"] == "in", row(snap)
    assert (project_dir / "calc.py").read_bytes() == changed.encode()


def test_a_hold_goes_back_into_the_recipe_and_its_fix_is_looked_at_once(make_client, project_dir):
    client, cid, run_id = started(
        make_client,
        project_dir,
        "full_auto",
        {
            "Lead": [
                spawn("Coder", "fix it", "c1"),
                spawn("Coder", "fix the findings", "c2"),
                *DONE,
            ],
            "Coder": [step(write("calc.py", BIG)), text("fixed")],
            "Coder 2": [step(write("calc.py", BIG2, "w2")), text("fixed again")],
            "Reviewer": [hold("calc.py: the names are wrong")],
        },
    )
    snap = ended(client, cid, run_id, 2)
    assert looked(snap) == ["Reviewer", "Reviewer 2"], (looked(snap), texts(snap))
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert "goes on from Fix it" in by_call(snap)[0][1], by_call(snap)
    assert row(snap)["status"] == "in", row(snap)
    assert (project_dir / "calc.py").read_bytes() == BIG2.encode()


def test_at_auto_edit_the_card_comes_after_the_one_look(make_client, project_dir):
    client, cid, run_id = started(
        make_client,
        project_dir,
        "auto_edit",
        {
            "Lead": [spawn("Coder", "fix it", "c1"), *DONE],
            "Coder": [step(write("calc.py", BIG)), text("fixed")],
        },
    )
    snap = until(
        client,
        cid,
        lambda s: len(reviewers(s)) > 1 or (asked(s) and READY in asked(s)["question"]),
        timeout=20,
    )
    assert looked(snap) == ["Reviewer"], (looked(snap), texts(snap))
    assert f"Review: Reviewer ({SIGN}) - MERGE, no findings" in texts(snap), texts(snap)
    assert not (project_dir / "calc.py").exists()
    answer(client, asked(snap), "Take in")
    snap = ended(client, cid, run_id, 1)
    assert looked(snap) == ["Reviewer"], (looked(snap), texts(snap))
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert (project_dir / "calc.py").read_bytes() == BIG.encode()
