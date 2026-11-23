"""Kanıtlı bitiş S5c (plan decision 16): a recipe's own Checks step - what KOLONİ checks at its
end, set for the recipe - is what its turn's end gate checks: a report-like recipe with Tests off
and Docs on runs no test and checks its documents; Fix rounds 0 checks only, sending nothing back.
A fake model and a scripted executor (none of its runs may start)."""

import pytest

from app import proof
from app.agent import review_mixin
from tests.fakes import ScriptedExecutor
from tests.test_chat_flow import text
from tests.test_chat_teams_scenarios import teams_of
from tests.test_claim_scenarios import write
from tests.test_proof_end_scenarios import texts
from tests.test_recipe_run_scenarios import made, recipe_named, row
from tests.test_recipes_scenarios import graph
from tests.test_recipes_scenarios import step as part
from tests.test_spawn import begin, spawn, step

pytestmark = pytest.mark.no_po

BROKEN = "README.md: link to gone.md not found"


def docs_recipe(client, **checks):
    """One step, the Docs writer's - its Checks step set for the recipe: documents and nothing
    else, unless `checks` says otherwise."""
    return made(client, "Write the docs", {**graph(
        [part("write", "Write the docs", {"role": "Docs writer"})],
        [("start", "write"), ("write", "end")]),
        "checks": {"tests": False, "review": False, "docs": True, **checks}})


def run_it(client, project_dir, recipe):
    web = teams_of(client)["Web app"]
    return begin(client, project_dir, mode="full_auto", spawn_approval="never",
                 teams_mode="manual", teams=[{"team_id": web["id"], "recipe_id": recipe["id"]}])


def writer():
    return [step(write("README.md", "# Guide\n\n[more](gone.md)\n")), text("written")]


def test_a_recipe_with_tests_off_and_docs_on_runs_no_test_and_checks_its_docs(
        make_client, wait_run, project_dir):
    executor = ScriptedExecutor([])  # (a test run would start one: none may)
    client, model = make_client({
        "Lead": [spawn("Docs writer", "write the guide", "d1"), text("done"),
                 text("left it")],
        "Docs writer": writer(),
    }, executor=executor)
    recipe = docs_recipe(client, fix_rounds=1)
    assert recipe["graph"]["checks"]["docs"] is True  # (kept with the recipe)
    cid, run_id = run_it(client, project_dir, recipe)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert row(snap)["status"] == "in" and executor.started == []
    rows = texts(snap)
    assert proof.TESTS_OFF in rows and BROKEN in rows, rows
    assert "Sent back to fix: 1 of 1 rounds (1 problem in what it wrote)" in rows, rows
    assert "gone.md" in str(model.calls[-1])  # (the fix round told the Orchestrator)


def test_fix_rounds_0_checks_only_and_sends_nothing_back(make_client, wait_run, project_dir):
    executor = ScriptedExecutor([])
    client, model = make_client({
        "Lead": [spawn("Docs writer", "write the guide", "d1"), text("done")],
        "Docs writer": writer(),
    }, executor=executor)
    cid, run_id = run_it(client, project_dir, docs_recipe(client, fix_rounds=0))
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    rows = texts(snap)
    assert BROKEN in rows and not any(one.startswith("Sent back") for one in rows), rows
    assert review_mixin.REVIEW_OFF in rows, rows  # (the pass went on past the documents)
    assert "gone.md" not in str(model.calls[-1])  # (nothing sent back)


def test_a_recipe_whose_checks_step_checks_nothing_says_so(make_client, wait_run, project_dir):
    executor = ScriptedExecutor([])
    client, _model = make_client({
        "Lead": [spawn("Docs writer", "write the guide", "d1"), text("done")],
        "Docs writer": writer(),
    }, executor=executor)
    cid, run_id = run_it(client, project_dir, docs_recipe(client, docs=False))
    snap = wait_run(client, cid, run_id)
    assert texts(snap)[0] == proof.RECIPE_OFF and executor.started == [], texts(snap)


def test_the_ready_bugfix_checks_its_tests_and_a_review(make_client):
    client, _model = make_client([])
    checks = recipe_named(client, "Bugfix")["graph"]["checks"]
    assert {part for part, on in checks.items() if on is True} == {"tests", "review"}
    assert "checks" not in recipe_named(client, "Research")["graph"]  # (it follows the project)


def test_a_folder_recipe_carries_its_checks_step_and_a_wrong_one_is_not_read(make_client,
                                                                            project_dir):
    import json

    from tests.test_recipes_scenarios import OWN, SMALL, listed
    client, _model = make_client([])
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    folder = project_dir / ".koloni" / "recipes"
    folder.mkdir(parents=True)
    checks = {"tests": False, "review": True, "docs": True, "diagram": False, "data": False,
              "slides": False, "ui": False, "fix_rounds": 0}
    (folder / "report.json").write_text(json.dumps(
        {"name": "Report", "graph": {**SMALL, "checks": checks}}), encoding="utf-8")
    for name, wrong in (("rounds", {**checks, "fix_rounds": 9}), ("pages", {"pages": True})):
        (folder / f"{name}.json").write_text(json.dumps(
            {"name": name, "graph": {**SMALL, "checks": wrong}}), encoding="utf-8")
    read = listed(client, project_id=pid)
    (mine,) = [r for r in read["recipes"] if r["project_id"]]
    assert mine["graph"]["checks"] == checks and len(read["broken"]) == 2, read["broken"]
    # (Written back by the page as it reads: the step's choice kept in the file.)
    saved = client.put(f"/api/projects/{pid}/recipes/report",
                       json={"name": "Report", "graph": mine["graph"]}, headers=OWN)
    assert saved.status_code == 200, saved.text
    assert json.loads((folder / "report.json").read_text(encoding="utf-8"))["graph"][
        "checks"] == checks


def begin_at(client, project_dir, project, chat, content="fix it"):
    """A chat in a project set as `project` says, at the chat's `chat` settings, its message sent."""
    from tests.test_recipes_scenarios import OWN
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    assert client.patch(f"/api/projects/{pid}", json=project, headers=OWN).status_code == 200
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    assert client.patch(f"/api/conversations/{cid}", json=chat, headers=OWN).status_code == 200
    posted = client.post(f"/api/conversations/{cid}/messages", json={"content": content},
                         headers=OWN).json()
    return cid, posted["run"]["id"]


def test_a_ready_bugfix_checks_its_tests_in_a_project_at_nothing(make_client, wait_run,
                                                                  project_dir, monkeypatch):
    # (Its own Checks step, not the project's After a change - as the chat's switch never did.)
    from tests.test_proof_end_scenarios import guess
    from tests.test_recipe_proof_scenarios import PASSED, PYTEST, REPRO, ran_tests, scripts
    guess(monkeypatch, PYTEST)
    executor = ScriptedExecutor([REPRO, PASSED])
    client, _model = make_client(scripts(ran_tests()), executor=executor)
    backend = teams_of(client)["Backend / API"]
    cid, run_id = begin_at(client, project_dir, {"after_change": "nothing"}, {
        "permission_mode": "full_auto", "spawn_approval": "never", "teams_mode": "manual",
        "teams": [{"team_id": backend["id"], "recipe_id": None}]})
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    rows = texts(snap)
    assert f"Tests passed: {PYTEST} - run by Tester after the last change" in rows, rows
    assert proof.NOT_CHECKED not in rows


def test_fix_rounds_0_with_failing_tests_says_check_only(make_client, wait_run, project_dir,
                                                         monkeypatch):
    # (A test command found, not the user's check command: that one would hold Take in first.)
    from tests.fakes import Script
    from tests.test_proof_end_scenarios import guess
    pytest_q = "python -m pytest -q"
    guess(monkeypatch, pytest_q)
    executor = ScriptedExecutor([Script(["1 failed, 3 passed\n"], exit_code=1)])
    client, model = make_client({
        "Lead": [spawn("Coder", "build it", "c1"), text("done")],
        "Coder": [step(write("a.py", "x = 1\n")), text("built")],
    }, executor=executor)
    recipe = made(client, "Build, check only", {**graph(
        [part("build", "Build it", {"role": "Coder"})], [("start", "build"), ("build", "end")]),
        "checks": {"tests": True, "review": False, "fix_rounds": 0}})
    web = teams_of(client)["Web app"]
    cid, run_id = begin_at(client, project_dir, {}, {
        "permission_mode": "full_auto", "spawn_approval": "never", "teams_mode": "manual",
        "teams": [{"team_id": web["id"], "recipe_id": recipe["id"]}]})
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    rows = texts(snap)
    assert proof.CHECK_ONLY in rows and not any(one.startswith("Sent back") for one in rows), rows
    assert [one for one, _cwd in executor.started] == [pytest_q]  # (once: nothing went back)
    assert "1 failed" not in str(model.calls[-1])


def test_a_recipe_the_orchestrator_picks_never_turns_the_projects_checks_off(make_client,
                                                                              wait_run,
                                                                              project_dir):
    # (Review of S5c: picked by the Orchestrator, a recipe with tests off left its own code
    # untested. Its Checks step only adds to the project's then; only your own pick lowers them.)
    from tests.test_chat_teams_scenarios import pick
    from tests.test_proof_end_scenarios import PASS
    executor = ScriptedExecutor([PASS, PASS])
    client, _model = make_client({
        "Lead": [pick({"team": "Web app", "recipe": "Write the docs", "why": "a quick change"}),
                 spawn("Docs writer", "change the code", "d1"), text("done")],
        "Docs writer": [step(write("app.py", "def f():\n    return 2\n")), text("changed")],
    }, executor=executor)
    docs_recipe(client, fix_rounds=0)
    cid, run_id = begin_at(client, project_dir, {"check_command": "python check.py"}, {
        "permission_mode": "full_auto", "spawn_approval": "never", "teams_mode": "lead"})
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    rows = texts(snap)
    # (Its tests ran at the end - besides Test before adding's run before Take in.)
    assert "Tests passed: python check.py - 4 passed in 0.1s" in rows, (executor.started, rows)
    assert proof.TESTS_OFF not in rows and review_mixin.REVIEW_OFF not in rows, rows


def test_the_orchestrators_pick_adds_and_the_users_lowers(make_client, wait_run, project_dir):
    # (The rule, by the turn's rows: a Lead's pick of a recipe with tests off and docs on checks
    # the project's parts and docs too, the more rounds; the user's own pick checks what it says.)
    from app.db.models import Conversation, ConversationTeam, Run
    client, _model = make_client([text("hi")])
    cid, run_id = begin_at(client, project_dir, {"fix_rounds": 3}, {})
    wait_run(client, cid, run_id)
    own = {"tests": False, "review": False, "docs": True, "diagram": False, "data": False,
           "slides": False, "fix_rounds": 0}
    with client.app.state.session_factory() as session:
        run = session.get_one(Run, run_id)
        team = session.scalars(select_team()).first()
        run.teams = [{"team_id": team}]
        row = ConversationTeam(conversation_id=cid, team_id=team, picked_by="lead", position=0,
                               state={"run_id": run_id, "graph": {"checks": own}})
        session.add(row)
        session.commit()
        conversation = session.get_one(Conversation, cid)
        by_lead = proof.checks_of(session, conversation, run)
        row.picked_by = "user"
        session.commit()
        by_user = proof.checks_of(session, conversation, run)
    assert by_lead.on >= {"tests", "review", "docs"} and by_lead.rounds == 3, by_lead
    assert by_user.on == {"docs"} and by_user.rounds == 0, by_user


def select_team():
    from sqlalchemy import select

    from app.db.models import Team
    return select(Team.id)
