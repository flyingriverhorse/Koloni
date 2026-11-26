"""Kanıtlı bitiş S2: a turn that changed source and no test is asked, once, for a test (a bug fix:
one that fails without the fix first) - the gate's last step, after the tests and the review; its
Checked section names the new tests, a test it removed, or the Orchestrator's one-line reason for
none. Agents that write and run code are told to run the tests near their change; the Orchestrator
what KOLONİ checks at the end."""

import pytest
from sqlalchemy import select

from app.agent.words import NEAR_TESTS, PROOF_LEAD
from app.changes import DELETED_SHA
from app.db.models import Agent, FileChange, Run
from app.model_client import StepResult
from tests.fakes import ScriptedExecutor
from tests.test_agent_writes import write
from tests.test_chat_flow import text
from tests.test_proof_end_scenarios import OWN, PASS, begin, checked, texts
from tests.test_spawn import spawn

pytestmark = pytest.mark.no_po  # (the Scout's own request would take a scripted step)

ASKED = "Not the end yet: a.py changed and no test did."
TEST_A = "def test_a():\n    assert True\n"


def asked(model) -> int:
    """How often the Orchestrator was asked for a test, in its last request."""
    return sum(
        str(m.get("content")).startswith(ASKED) for m in model.calls[-1] if m["role"] == "user"
    )


def test_a_change_without_a_test_is_asked_for_one_once(make_client, wait_run, project_dir):
    executor = ScriptedExecutor([PASS, PASS])
    client, model = make_client(
        [
            write("a.py", "x = 1\n"),
            text("done"),
            write("tests/test_a.py", TEST_A, "w2"),
            text("done, with its test"),
        ],
        executor=executor,
    )
    cid, run_id = begin(client, project_dir, check_command="python check.py")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert asked(model) == 1  # (once: the answer with its test ends the turn)
    # (The test written after the first run: the tests run again on it - not fresh.)
    assert len(executor.started) == 2
    assert texts(snap) == [
        "Tests passed: python check.py - 4 passed in 0.1s",
        "New tests: tests/test_a.py",
    ]


def test_a_reason_instead_of_a_test_is_quoted_and_ends_it(make_client, wait_run, project_dir):
    executor = ScriptedExecutor([PASS])
    client, model = make_client(
        [
            write("a.py", "x = 1\n"),
            text("done"),
            text("No test fits: a.py is a one-off script.\nIt runs once."),
        ],
        executor=executor,
    )
    cid, run_id = begin(client, project_dir, check_command="python check.py")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed" and len(executor.started) == 1
    assert asked(model) == 1
    assert texts(snap)[-1] == (
        "No new test: the Orchestrator said “No test fits: a.py is a one-off script.”"
    )
    assert checked(snap)[-1]["state"] == "note"


def test_a_project_with_the_box_off_is_not_asked(make_client, wait_run, project_dir):
    # (0.1.10: A test for the change is off unless ticked - this module ticks it by default,
    # conftest; a project that unticked it is never asked)
    executor = ScriptedExecutor([PASS])
    client, model = make_client([write("a.py", "x = 1\n"), text("done")], executor=executor)
    cid, run_id = begin(
        client, project_dir, check_command="python check.py", check_kinds={"test": False}
    )
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert asked(model) == 0
    assert texts(snap) == ["Tests passed: python check.py - 4 passed in 0.1s"]


def test_a_turn_with_a_test_changed_is_not_asked(make_client, wait_run, project_dir):
    executor = ScriptedExecutor([PASS])
    client, model = make_client(
        [write("a.py", "x = 1\n"), write("tests/test_a.py", TEST_A, "w2"), text("done")],
        executor=executor,
    )
    cid, run_id = begin(client, project_dir, check_command="python check.py")
    snap = wait_run(client, cid, run_id)
    assert asked(model) == 0 and len(model.calls) == 3
    assert texts(snap)[-1] == "New tests: tests/test_a.py"


def deletes(client, project_dir, path):
    """A step that deletes a file of the project, recorded as a CLI with tools of its own records
    a deletion (KOLONİ's own tools delete none), then answers."""

    async def deleted(_on_delta):
        with client.app.state.session_factory() as session:
            run = session.scalar(select(Run).order_by(Run.created_at.desc()).limit(1))
            lead = session.scalar(select(Agent).where(Agent.run_id == run.id, Agent.depth == 0))
            before = (project_dir / path).read_text(encoding="utf-8")
            session.add(
                FileChange(
                    run_id=run.id,
                    agent_id=lead.id,
                    path=path,
                    kind="delete",
                    before_content=before,
                    after_content="",
                    after_sha=DELETED_SHA,
                    status="applied",
                )
            )
            session.commit()
        (project_dir / path).unlink()
        return StepResult("done", [], 1, 1)

    return deleted


def test_a_deleted_test_is_a_failed_row(make_client, wait_run, project_dir):
    (project_dir / "tests").mkdir()
    (project_dir / "tests" / "test_old.py").write_text(TEST_A, encoding="utf-8")
    executor = ScriptedExecutor([PASS])
    client, model = make_client([write("a.py", "x = 1\n")], executor=executor)
    model.steps += [
        deletes(client, project_dir, "tests/test_old.py"),
        text("The test was for code that is gone."),
    ]
    cid, run_id = begin(client, project_dir, check_command="python check.py")
    snap = wait_run(client, cid, run_id)
    rows = [(row["state"], row["text"]) for row in checked(snap)]
    assert ("failed", "Test removed: tests/test_old.py") in rows, rows
    # (a.py changed and no test did: asked - its reason quoted)
    assert rows[-1] == (
        "note",
        "No new test: the Orchestrator said “The test was for code that is gone.”",
    ), rows


def test_nothing_asks_for_no_test(make_client, wait_run, project_dir):
    client, model = make_client(
        [write("a.py", "x = 1\n"), text("done")], executor=ScriptedExecutor([])
    )
    cid, run_id = begin(client, project_dir, after_change="nothing")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed" and asked(model) == 0
    assert texts(snap) == ["Not checked: After a change is set to Nothing"]
    assert all(PROOF_LEAD not in str(call[0]["content"]) for call in model.calls)


def test_tests_only_asks_too(make_client, wait_run, project_dir):
    client, model = make_client(
        [write("a.py", "x = 1\n"), text("done"), text("No test fits: settings only.")],
        executor=ScriptedExecutor([PASS]),
    )
    cid, run_id = begin(client, project_dir, check_command="python check.py", after_change="tests")
    snap = wait_run(client, cid, run_id)
    assert asked(model) == 1 and texts(snap)[-1].startswith("No new test:")


def test_a_chat_with_checks_off_is_not_asked(make_client, wait_run, project_dir):
    # (S10: off for this chat - nothing is checked, nothing asked, nothing told.)
    client, model = make_client(
        [write("a.py", "x = 1\n"), text("done")], executor=ScriptedExecutor([])
    )
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    assert (
        client.patch(
            f"/api/conversations/{cid}",
            json={"permission_mode": "full_auto", "lead_hands_code": False, "after_change": "off"},
            headers=OWN,
        ).status_code
        == 200
    )
    run_id = client.post(f"/api/conversations/{cid}/messages", json={"content": "go"}).json()[
        "run"
    ]["id"]
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed" and asked(model) == 0
    assert texts(snap) == ["Not checked: off for this chat"]
    assert all(PROOF_LEAD not in str(call[0]["content"]) for call in model.calls)


def test_the_lead_is_told_what_koloni_checks_at_every_step(make_client, wait_run, project_dir):
    client, model = make_client(
        [write("a.py", "x = 1\n"), text("done"), text("No test fits.")],
        executor=ScriptedExecutor([PASS]),
    )
    cid, run_id = begin(client, project_dir, check_command="python check.py")
    wait_run(client, cid, run_id)
    systems = [str(call[0]["content"]) for call in model.calls]
    assert len(systems) == 3 and all(PROOF_LEAD in one for one in systems)
    assert len(set(systems)) == 1  # (the same words at every step: the cache's prefix holds)


def test_a_coder_is_told_to_run_nearby_tests(make_client, wait_run, project_dir):
    client, model = make_client(
        {
            "Lead": [spawn("Coder", "fix it"), text("done"), text("No test fits.")],
            "Coder": [write("calc.py", "x = 1\n"), text("fixed")],
        },
        executor=ScriptedExecutor([PASS]),
    )
    cid, run_id = begin(client, project_dir, check_command="python check.py")
    wait_run(client, cid, run_id)
    assert NEAR_TESTS in str(model.calls_of["Coder"][0][0]["content"])
    assert NEAR_TESTS not in str(model.calls_of["Lead"][0][0]["content"])


def test_a_coder_is_told_nothing_of_nearby_tests_under_nothing(make_client, wait_run, project_dir):
    client, model = make_client(
        {
            "Lead": [spawn("Coder", "fix it"), text("done")],
            "Coder": [write("calc.py", "x = 1\n"), text("fixed")],
        },
        executor=ScriptedExecutor([]),
    )
    cid, run_id = begin(client, project_dir, after_change="nothing")
    wait_run(client, cid, run_id)
    assert NEAR_TESTS not in str(model.calls_of["Coder"][0][0]["content"])


def test_a_recipe_whose_reproduce_step_wrote_a_test_is_not_asked(
    make_client, wait_run, project_dir
):
    from tests.test_recipe_proof_scenarios import PASSED, REPRO, bugfix_run, ran_tests, scripts

    # (S7's R4: its Reproduce step writes tests/test_repro.py and runs it failing - `REPRODUCES`)
    client, model = make_client(
        scripts(ran_tests()), executor=ScriptedExecutor([REPRO, PASSED, PASSED, PASSED])
    )
    cid, run_id = bugfix_run(client, project_dir)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert not [
        m
        for call in model.calls_of["Lead"]
        for m in call
        if str(m.get("content")).startswith("Not the end yet: ")
        and "no test did" in str(m.get("content"))
    ]
    assert "New tests: tests/test_repro.py" in texts(snap), texts(snap)


@pytest.mark.skipif(__import__("shutil").which("git") is None, reason="git is not installed")
def test_a_test_a_command_deleted_is_said_removed(make_client, wait_run, project_dir, monkeypatch):
    from app import proof
    from tests.fakes import Script
    from tests.test_proof_end_scenarios import _Deletes, _git_project, run

    # (CL-329 G: no Checked section, no "Test removed" - the command's deletion was unseen)
    (project_dir / "test_b.py").write_text("def test_b():\n    pass\n")
    _git_project(project_dir, monkeypatch)
    executor = _Deletes([Script(["\n"]), PASS])
    client, _model = make_client([run("python rm.py"), text("done")], executor=executor)
    cid, run_id = begin(client, project_dir, check_command="python check.py")
    rows = texts(wait_run(client, cid, run_id))
    assert proof.UNRECORDED.format(command="test_b.py - python rm.py") in rows, rows
    assert proof.TEST_REMOVED.format(path="test_b.py") in rows, rows
