"""Kanıtlı bitiş S5c (plan decision 16): a recipe's own Checks step - what KOLONİ checks at its
end, set for the recipe - is what its turn's end gate checks: a report-like recipe with Tests off
and Docs on runs no test and checks its documents; Fix rounds 0 checks only, sending nothing back.
A fake model and a scripted executor (none of its runs may start)."""

import pytest

from app import proof
from app.agent import review_mixin, stronger_mixin
from tests.fakes import ScriptedExecutor
from tests.test_chat_flow import text
from tests.test_chat_teams_scenarios import former, teams_of
from tests.test_claim_scenarios import write
from tests.test_proof_end_scenarios import checked, texts
from tests.test_recipe_run_scenarios import made, recipe_named, row
from tests.test_recipes_scenarios import graph
from tests.test_recipes_scenarios import step as part
from tests.test_spawn import begin, spawn, step

pytestmark = pytest.mark.no_po

BROKEN = "README.md: link to gone.md not found"


def docs_recipe(client, **checks):
    """One step, the Docs writer's - its Checks step set for the recipe: documents and nothing
    else, unless `checks` says otherwise."""
    return made(
        client,
        "Write the docs",
        {
            **graph(
                [part("write", "Write the docs", {"role": "Docs writer"})],
                [("start", "write"), ("write", "end")],
            ),
            "checks": {"tests": False, "review": False, "docs": True, **checks},
        },
    )


def run_it(client, project_dir, recipe):
    web = teams_of(client)["Web app"]
    return begin(
        client,
        project_dir,
        mode="full_auto",
        spawn_approval="never",
        teams_mode="manual",
        teams=[{"team_id": web["id"], "recipe_id": recipe["id"]}],
    )


def writer():
    return [step(write("README.md", "# Guide\n\n[more](gone.md)\n")), text("written")]


def held_docs(make_client, wait_run, project_dir):
    """A docs recipe whose link the fix round left broken: its work kept out, Take in anyway or
    Fix it. The client, model, chat, turn and its "not_taken" row."""
    executor = ScriptedExecutor([])  # (a test run would start one: none may)
    client, model = make_client(
        {
            # (k-sira-016: the round, at Ready for you, sends the recipe back - its Docs writer again)
            "Lead": [
                spawn("Docs writer", "write the guide", "d1"),
                spawn("Docs writer", "fix the link", "d2"),
                text("done"),
                text("left it"),
            ],
            "Docs writer": writer(),
            "Docs writer 2": [text("left the link as it is")],
        },
        executor=executor,
    )
    recipe = docs_recipe(client, fix_rounds=1)
    assert recipe["graph"]["checks"]["docs"] is True  # (kept with the recipe)
    cid, run_id = run_it(client, project_dir, recipe)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert executor.started == []
    rows = texts(snap)
    assert proof.TESTS_OFF in rows and BROKEN in rows, rows
    assert "Sent back to fix: 1 of 1 rounds (1 problem in what it wrote)" in rows, rows
    assert "gone.md" in str(model.calls[-1])  # (the fix round told the Orchestrator)
    # (k-a11y-2: the link the round left broken - ended as failing tests are, and the work kept
    # out, Take in anyway or Fix it: it was taken in by a plain Take in)
    assert "Still failing after 1 fix rounds: you decide (Fix it)" in rows, rows
    (kept,) = [one for one in checked(snap) if one["kind"] == "not_taken"]
    assert kept["text"] == f"Not taken in: {stronger_mixin.KINDS_FAILING}", kept
    assert kept["reason"] == "kinds" and kept["question"] == stronger_mixin.ASK_KINDS, kept
    assert kept.get("merge_id") and row(snap)["status"] != "in", row(snap)
    assert not (project_dir / "README.md").exists()
    return client, model, cid, run_id, kept


def fix_held(client, wait_run, model, cid, run_id, kept, lead):
    """Fix it with an answer on the kept work: a turn in its copy, the Lead's steps `lead`. Its
    snapshot, its turn and its Checked rows' texts."""
    from tests.test_proof_end_scenarios import OWN

    model.by_agent["Lead"] += lead
    client.patch(f"/api/conversations/{cid}", json={"lead_hands_code": False}, headers=OWN)
    went = client.post(
        f"/api/runs/{run_id}/held/fix",
        json={"merge_id": kept["merge_id"], "reply": "fix the link"},
        headers=OWN,
    )
    assert went.status_code == 202, went.text
    second = went.json()["run_id"]
    snap = wait_run(client, cid, second)
    rows = [
        r["text"]
        for m in snap["messages"]
        if m["role"] == "checked" and m["run_id"] == second
        for r in m["checked"]
    ]
    return snap, second, rows


def test_a_recipe_with_tests_off_and_docs_on_runs_no_test_and_checks_its_docs(
    make_client, wait_run, project_dir
):
    client, model, cid, run_id, kept = held_docs(make_client, wait_run, project_dir)
    # (Fix it with an answer: a turn in the kept copy, told why by the row's code)
    snap, second, rows = fix_held(client, wait_run, model, cid, run_id, kept, [text("on it")])
    (asked,) = [
        m["content"] for m in snap["messages"] if m["role"] == "user" and m["run_id"] == second
    ]
    assert asked.startswith(
        "The last turn's work was not taken in: KOLONİ's checks of what it wrote still found "
        "problems."
    ), asked
    # (N2: it changed nothing, and the kept work was checked - none of it "not checked")
    assert BROKEN in rows and not any(one.startswith("Not checked") for one in rows), rows
    # (N3: the held turn's line of where its work is - it went on in this turn, never "Not in the
    # project yet: … wait in Ready for you")
    assert "Not in the project yet" not in landed_of(client, cid, run_id)["content"]


def landed_of(client, cid, run_id):
    snap = client.get(f"/api/conversations/{cid}").json()
    (said,) = [m for m in snap["messages"] if m["role"] == "landed" and m["run_id"] == run_id]
    return said


def test_fix_it_on_kept_work_that_breaks_after_a_round_is_no_check_not_reached(
    make_client, wait_run, project_dir
):
    # (review: no change, sent back a round, and the model breaks - the copy is kept again, with
    # no record of this turn's: the kept work was checked all the same)
    client, model, cid, run_id, kept = held_docs(make_client, wait_run, project_dir)
    snap, second, rows = fix_held(client, wait_run, model, cid, run_id, kept, [RuntimeError("x")])
    assert [r["status"] for r in snap["runs"] if r["id"] == second] == ["failed"], rows
    assert BROKEN in rows and not any(one.startswith("Not checked") for one in rows), rows


def test_fix_it_on_kept_work_that_passes_is_taken_in_as_checked(make_client, wait_run, project_dir):
    # (N2: its Take in at the end, after the check, puts records of its own on the turn - the
    # kept turn's files - which are no later change)
    client, model, cid, run_id, kept = held_docs(make_client, wait_run, project_dir)
    fixed = [step(write("README.md", "# Guide\n")), text("fixed the link")]
    _snap, _second, rows = fix_held(client, wait_run, model, cid, run_id, kept, fixed)
    assert (project_dir / "README.md").read_text(encoding="utf-8") == "# Guide\n", rows
    assert rows and not any("Not checked" in one or "Not taken" in one for one in rows), rows


def test_fix_it_on_kept_work_changed_after_its_check_says_so(make_client, wait_run, project_dir):
    # (the real case: sent back, it writes again - and its model breaks before KOLONİ's check)
    client, model, cid, run_id, kept = held_docs(make_client, wait_run, project_dir)
    again = [
        step(write("README.md", "# Guide\n\n[more](lost.md)\n")),
        text("fixed the link"),
        step(write("README.md", "# Guide\n", "w2")),
        RuntimeError("its model broke"),
    ]
    _snap, _second, rows = fix_held(client, wait_run, model, cid, run_id, kept, again)
    assert "Not checked on the last change: documents" in rows, rows


def test_take_in_anyway_says_anew_where_the_work_is(make_client, wait_run, project_dir):
    # (N3: the turn's line of where its work is, written again once it is taken in - never "Not
    # in the project yet" beside work that is in)
    from tests.test_proof_end_scenarios import OWN

    client, model, cid, run_id, kept = held_docs(make_client, wait_run, project_dir)
    before = landed_of(client, cid, run_id)
    assert before["content"].startswith("Not in the project yet: README.md"), before
    went = client.post(f"/api/merges/{kept['merge_id']}/approve", headers=OWN)
    assert went.status_code == 200, went.text
    after = landed_of(client, cid, run_id)
    assert after["id"] == before["id"] and after["content"].startswith(
        "In the project: README.md"
    ), after
    assert "Not in the project yet" not in after["content"], after
    # (review: the failing work is in the project now - a turn that changes nothing says it
    # still fails, Fix it with it; its kept copy's row is not said again)
    model.by_agent["Lead"] += [text("a guide")]
    asked = client.post(f"/api/conversations/{cid}/messages", json={"content": "what is it?"})
    next_run = asked.json()["run"]["id"]
    wait_run(client, cid, next_run)
    snap = client.get(f"/api/conversations/{cid}").json()
    (rows,) = [m["checked"] for m in snap["messages"] if m["checked"] and m["run_id"] == next_run]
    assert [r["text"] for r in rows][:2] == [proof.UNCHANGED, BROKEN], rows
    assert not any(r["kind"] == "not_taken" for r in rows), rows


def test_fix_rounds_0_checks_only_and_sends_nothing_back(make_client, wait_run, project_dir):
    executor = ScriptedExecutor([])
    client, model = make_client(
        {
            "Lead": [spawn("Docs writer", "write the guide", "d1"), text("done")],
            "Docs writer": writer(),
        },
        executor=executor,
    )
    cid, run_id = run_it(client, project_dir, docs_recipe(client, fix_rounds=0))
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    rows = texts(snap)
    assert BROKEN in rows and not any(one.startswith("Sent back") for one in rows), rows
    assert review_mixin.REVIEW_OFF in rows, rows  # (the pass went on past the documents)
    assert "gone.md" not in str(model.calls[-1])  # (nothing sent back)


def test_a_recipe_whose_checks_step_checks_nothing_says_so(make_client, wait_run, project_dir):
    executor = ScriptedExecutor([])
    client, _model = make_client(
        {
            "Lead": [spawn("Docs writer", "write the guide", "d1"), text("done")],
            "Docs writer": writer(),
        },
        executor=executor,
    )
    cid, run_id = run_it(
        client,
        project_dir,
        docs_recipe(client, docs=False, config=False, scripts=False, style=False),
    )
    snap = wait_run(client, cid, run_id)
    assert texts(snap)[0] == proof.RECIPE_OFF and executor.started == [], texts(snap)


def test_the_ready_bugfix_checks_its_tests_and_a_review(make_client):
    client, _model = make_client([])
    checks = recipe_named(client, "Bugfix")["graph"]["checks"]
    # (and Config and Scripts - model-free and cheap - and Code style and types - which asks
    # before it runs a tool unasked - on unless unticked: a Checks step from before reads so)
    assert {part for part, on in checks.items() if on is True} == {
        "tests",
        "review",
        "config",
        "scripts",
        "style",
    }
    assert "checks" not in recipe_named(client, "Research")["graph"]  # (it follows the project)


def test_a_folder_recipe_carries_its_checks_step_and_a_wrong_one_is_not_read(
    make_client, project_dir
):
    import json

    from tests.test_recipes_scenarios import OWN, SMALL, listed

    client, _model = make_client([])
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    folder = project_dir / ".koloni" / "recipes"
    folder.mkdir(parents=True)
    checks = {
        "tests": False,
        "review": True,
        "docs": True,
        "diagram": False,
        "data": False,
        "slides": False,
        "ui": False,
        "fix_rounds": 0,
    }  # (written before 0.1.7: no Config - it reads as on, and is written back so)
    read_as = {**checks, "config": True, "scripts": True, "style": True}
    (folder / "report.json").write_text(
        json.dumps({"name": "Report", "graph": {**SMALL, "checks": checks}}), encoding="utf-8"
    )
    for name, wrong in (("rounds", {**checks, "fix_rounds": 11}), ("pages", {"pages": True})):
        (folder / f"{name}.json").write_text(
            json.dumps({"name": name, "graph": {**SMALL, "checks": wrong}}), encoding="utf-8"
        )
    read = listed(client, project_id=pid)
    (mine,) = [r for r in read["recipes"] if r["project_id"]]
    assert mine["graph"]["checks"] == read_as and len(read["broken"]) == 2, read["broken"]
    # (Written back by the page as it reads: the step's choice kept in the file.)
    saved = client.put(
        f"/api/projects/{pid}/recipes/report",
        json={"name": "Report", "graph": mine["graph"]},
        headers=OWN,
    )
    assert saved.status_code == 200, saved.text
    assert (
        json.loads((folder / "report.json").read_text(encoding="utf-8"))["graph"]["checks"]
        == read_as
    )


def begin_at(client, project_dir, project, chat, content="fix it"):
    """A chat in a project set as `project` says, at the chat's `chat` settings, its message sent."""
    from tests.test_recipes_scenarios import OWN

    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    assert client.patch(f"/api/projects/{pid}", json=project, headers=OWN).status_code == 200
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    assert client.patch(f"/api/conversations/{cid}", json=chat, headers=OWN).status_code == 200
    posted = client.post(
        f"/api/conversations/{cid}/messages", json={"content": content}, headers=OWN
    ).json()
    return cid, posted["run"]["id"]


def test_a_ready_bugfix_checks_its_tests_in_a_project_at_nothing(
    make_client, wait_run, project_dir, monkeypatch
):
    # (Its own Checks step, not the project's After a change - as the chat's switch never did.
    # T1: no Tester of its own - KOLONİ runs the tests.)
    from tests.test_proof_end_scenarios import guess
    from tests.test_recipe_cost_scenarios import THIN, fixed
    from tests.test_recipe_proof_scenarios import PASSED, PYTEST, REPRO, REPRODUCES

    guess(monkeypatch, PYTEST)
    # (and Take in's check of the Debugger's own test - 0.1.7)
    executor = ScriptedExecutor([REPRO, PASSED, PASSED])
    client, _model = make_client(
        {"Lead": THIN, "Debugger": list(REPRODUCES), "Coder": fixed()}, executor=executor
    )
    backend = former(client, "Backend / API")["Backend / API"]  # (a ready team until 0.1.10)
    cid, run_id = begin_at(
        client,
        project_dir,
        {"after_change": "nothing"},
        {
            "permission_mode": "full_auto",
            "spawn_approval": "never",
            "teams_mode": "manual",
            "teams": [{"team_id": backend["id"], "recipe_id": None}],
        },
    )
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    rows = texts(snap)
    assert f"Tests passed: {PYTEST} (guessed) - 4 passed" in rows, rows
    assert proof.NOT_CHECKED not in rows


def test_fix_rounds_0_with_failing_tests_says_check_only(
    make_client, wait_run, project_dir, monkeypatch
):
    # (A test command found, not the user's check command: that one would hold Take in first.)
    from tests.fakes import Script
    from tests.test_proof_end_scenarios import guess

    pytest_q = "python -m pytest -q"
    guess(monkeypatch, pytest_q)
    executor = ScriptedExecutor([Script(["1 failed, 3 passed\n"], exit_code=1)])
    client, model = make_client(
        {
            "Lead": [spawn("Coder", "build it", "c1"), text("done")],
            "Coder": [step(write("a.py", "x = 1\n")), text("built")],
        },
        executor=executor,
    )
    recipe = made(
        client,
        "Build, check only",
        {
            **graph(
                [part("build", "Build it", {"role": "Coder"})],
                [("start", "build"), ("build", "end")],
            ),
            "checks": {"tests": True, "review": False, "fix_rounds": 0},
        },
    )
    web = teams_of(client)["Web app"]
    cid, run_id = begin_at(
        client,
        project_dir,
        {},
        {
            "permission_mode": "full_auto",
            "spawn_approval": "never",
            "teams_mode": "manual",
            "teams": [{"team_id": web["id"], "recipe_id": recipe["id"]}],
        },
    )
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    rows = texts(snap)
    assert proof.CHECK_ONLY in rows and not any(one.startswith("Sent back") for one in rows), rows
    assert [one for one, _cwd in executor.started] == [pytest_q]  # (once: nothing went back)
    assert "1 failed" not in str(model.calls[-1])


def test_a_recipe_the_orchestrator_picks_never_turns_the_projects_checks_off(
    make_client, wait_run, project_dir
):
    # (Review of S5c: picked by the Orchestrator, a recipe with tests off left its own code
    # untested. Its Checks step only adds to the project's then; only your own pick lowers them.)
    from tests.test_chat_teams_scenarios import pick
    from tests.test_proof_end_scenarios import PASS

    executor = ScriptedExecutor([PASS, PASS])
    client, _model = make_client(
        {
            "Lead": [
                pick({"team": "Web app", "recipe": "Write the docs", "why": "a quick change"}),
                spawn("Docs writer", "change the code", "d1"),
                text("done"),
            ],
            "Docs writer": [step(write("app.py", "def f():\n    return 2\n")), text("changed")],
        },
        executor=executor,
    )
    docs_recipe(client, fix_rounds=0)
    cid, run_id = begin_at(
        client,
        project_dir,
        {"check_command": "python check.py"},
        {"permission_mode": "full_auto", "spawn_approval": "never", "teams_mode": "lead"},
    )
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
    own = {
        "tests": False,
        "review": False,
        "docs": True,
        "diagram": False,
        "data": False,
        "slides": False,
        "fix_rounds": 0,
    }
    with client.app.state.session_factory() as session:
        run = session.get_one(Run, run_id)
        team = session.scalars(select_team()).first()
        run.teams = [{"team_id": team}]
        row = ConversationTeam(
            conversation_id=cid,
            team_id=team,
            picked_by="lead",
            position=0,
            state={"run_id": run_id, "graph": {"checks": own}},
        )
        session.add(row)
        session.commit()
        conversation = session.get_one(Conversation, cid)
        by_lead = proof.checks_of(session, conversation, run)
        row.picked_by = "user"
        session.commit()
        by_user = proof.checks_of(session, conversation, run)
    assert by_lead.on >= {"tests", "review", "docs"} and by_lead.rounds == 3, by_lead
    # (A Checks step from before 0.1.7 has no Config, Scripts nor Code style: they read as on.)
    assert by_user.on == {"docs", "config", "scripts", "style"} and by_user.rounds == 0, by_user


def select_team():
    from sqlalchemy import select

    from app.db.models import Team

    return select(Team.id)
