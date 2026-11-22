"""Kanıtlı bitiş S8 (plan decision 3): the project's CI lint, typecheck and test lines are offered
once under the answer and run at a turn's end only after the user's Run these - never at Full auto
or away before it; a change to a workflow asks again, one changed in the turn is not used, and the
user's own check command wins. A fake model and a scripted executor."""

import pytest

from app.agent import found_mixin
from tests.fakes import ScriptedExecutor
from tests.test_agent_writes import write
from tests.test_chat_flow import text
from tests.test_ci_commands import write as workflow
from tests.test_proof_end_scenarios import OWN, PASS, begin, checked

pytestmark = pytest.mark.no_po

FLOW = """
jobs:
  ci:
    steps:
      - name: Lint
        run: ruff check app
      - name: Tests
        run: python -m pytest -q
      - name: e2e
        run: npx playwright test
"""
OFFERED = found_mixin.CI_OFFERED.format(lines="ruff check app, python -m pytest -q")


def rows_of(snap, run_id):
    return [(r["kind"], r["text"]) for m in snap["messages"] if m["role"] == "checked"
            and m["run_id"] == run_id for r in m["checked"]]


def again(client, wait_run, cid, content="more"):
    posted = client.post(f"/api/conversations/{cid}/messages", json={"content": content}).json()
    run_id = posted["run"]["id"]
    return run_id, wait_run(client, cid, run_id)


def test_found_ci_lines_are_offered_once_and_not_run_before_run_these(make_client, wait_run,
                                                                      project_dir):
    workflow(project_dir, FLOW)
    executor = ScriptedExecutor([PASS, PASS])
    client, _model = make_client([write("a.py", "x = 1\n"), text("done"),
                                  write("a.py", "x = 2\n", "w2"), text("done")], executor=executor)
    cid, run_id = begin(client, project_dir)  # (Full auto: still not run before it is approved)
    snap = wait_run(client, cid, run_id)
    assert ("ci_offer", OFFERED) in rows_of(snap, run_id) and executor.started == []
    # (Run these: exactly those lines, from the next change on - one row each, "from CI")
    assert client.post(f"/api/runs/{run_id}/ci/approve", headers=OWN).json() == {"approved": 2}
    second, snap = again(client, wait_run, cid)
    rows = rows_of(snap, second)
    assert [one for one, _cwd in executor.started] == ["ruff check app", "python -m pytest -q"]
    assert ("tests", "Tests passed: python -m pytest -q (from CI) - 4 passed in 0.1s") in rows
    assert ("ci", "e2e not run: e2e") in rows


def test_a_change_to_a_workflow_asks_again(make_client, wait_run, project_dir):
    workflow(project_dir, FLOW)
    client, _model = make_client([write("a.py", "x = 1\n"), text("done"),
                                  write("a.py", "x = 2\n", "w2"), text("done")],
                                 executor=ScriptedExecutor([PASS, PASS]))
    cid, run_id = begin(client, project_dir)
    wait_run(client, cid, run_id)
    client.post(f"/api/runs/{run_id}/ci/approve", headers=OWN)
    workflow(project_dir, FLOW.replace("ruff check app", "ruff check ."))  # (by hand, between turns)
    second, snap = again(client, wait_run, cid)
    assert ("ci_offer", found_mixin.CI_OFFERED.format(
        lines="ruff check ., python -m pytest -q")) in rows_of(snap, second)


def test_run_these_after_the_files_changed_is_refused(make_client, wait_run, project_dir):
    workflow(project_dir, FLOW)
    client, _model = make_client([write("a.py", "x = 1\n"), text("done")],
                                 executor=ScriptedExecutor([]))
    cid, run_id = begin(client, project_dir)
    wait_run(client, cid, run_id)
    workflow(project_dir, FLOW + "\n# changed\n")
    assert client.post(f"/api/runs/{run_id}/ci/approve", headers=OWN).status_code == 409
    assert client.post(f"/api/runs/{run_id}/ci/approve",
                       headers={"Origin": None}).status_code == 403


def test_a_workflow_changed_this_turn_is_not_used(make_client, wait_run, project_dir):
    workflow(project_dir, FLOW)
    executor = ScriptedExecutor([PASS])
    client, _model = make_client([write("a.py", "x = 1\n"), text("done"),
                                  write(".github/workflows/ci.yml", FLOW + "\n# mine\n", "w2"),
                                  text("done")], executor=executor)
    cid, run_id = begin(client, project_dir)
    wait_run(client, cid, run_id)
    client.post(f"/api/runs/{run_id}/ci/approve", headers=OWN)
    from tests.test_agent_writes import wait_status
    second = client.post(f"/api/conversations/{cid}/messages",
                         json={"content": "more"}).json()["run"]["id"]
    # (a write to a workflow waits on its card even at Full auto: approved)
    snap = wait_status(client, cid, "waiting_approval")
    (change,) = [c for c in snap["file_changes"] if c["status"] == "proposed"]
    assert client.post(f"/api/file-changes/{change['id']}/approve", headers=OWN).status_code == 200
    snap = wait_run(client, cid, second)
    assert ("ci", found_mixin.CI_CHANGED) in rows_of(snap, second)
    assert executor.started == []


def test_the_users_check_command_wins_over_ci(make_client, wait_run, project_dir):
    workflow(project_dir, FLOW)
    executor = ScriptedExecutor([PASS])
    client, _model = make_client([write("a.py", "x = 1\n"), text("done")], executor=executor)
    cid, run_id = begin(client, project_dir, check_command="python check.py")
    rows = checked(wait_run(client, cid, run_id))
    assert executor.started == [("python check.py", str(project_dir))]
    assert not any(r["kind"].startswith("ci") for r in rows), rows
