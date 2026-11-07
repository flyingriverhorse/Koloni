"""Slice 49's acceptance set: plan first. Written before the code.

With "Plan first" on, a new request starts a plan turn: the Lead may only read and search, and what
it answers is a plan put before the user. Nothing is changed, run or opened in it. Approved (as it is
or edited), the work starts in a new turn that carries the plan; turned down, nothing more happens.
The decision is the user's, from the app's own page.

Contract:
- `ConversationOut.plan_first` / `ConversationPatch.plan_first` (bool, default false).
- `RunOut.plan`: `{text, status: "proposed" | "approved" | "rejected", model_id}` or null.
- `POST /api/runs/{id}/plan/approve` {text?} (own origin) → `{run_id}` of the work turn;
  `POST /api/runs/{id}/plan/reject` {why?} (own origin).
"""

import json

import pytest

from app.schemas import ConversationOut

if "plan_first" not in ConversationOut.model_fields:
    pytest.skip("slice 49 is not built yet", allow_module_level=True)  # written before the code

from tests.test_agent_writes import read, write  # noqa: E402
from tests.test_chat_flow import text  # noqa: E402
from tests.test_spawn import names  # noqa: E402

ORIGIN = {"Origin": "http://127.0.0.1:8790"}
CHANGES = {"write_file", "edit_file", "run_command", "spawn_agent", "open_room", "create_role"}
PLAN = "PLAN: 1. write a.txt with one line. 2. say done."


def planned(client, project_dir, wait_run, words="make a.txt", delegates=False):
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    patched = client.patch(
        f"/api/conversations/{cid}",
        json={"permission_mode": "full_auto", "plan_first": True, "lead_hands_code": delegates},
        headers=ORIGIN,
    )
    assert patched.status_code == 200, patched.text
    run_id = client.post(f"/api/conversations/{cid}/messages", json={"content": words}).json()[
        "run"
    ]["id"]
    return cid, run_id, wait_run(client, cid, run_id)


def run_of(snap, run_id):
    return next(r for r in snap["runs"] if r["id"] == run_id)


def test_off_by_default(make_client, project_dir):
    client, _model = make_client([])
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    assert client.get(f"/api/conversations/{cid}").json()["conversation"]["plan_first"] is False


def test_the_plan_turn_only_reads_and_its_answer_is_a_plan_put_before_the_user(
    make_client, wait_run, project_dir
):
    client, model = make_client([text(PLAN)])
    cid, run_id, snap = planned(client, project_dir, wait_run)
    assert not CHANGES & set(names(model.tool_args[0]))
    plan = run_of(snap, run_id)["plan"]
    assert (plan["text"], plan["status"]) == (PLAN, "proposed") and plan["model_id"]
    assert snap["file_changes"] == [] and snap["commands"] == []


@pytest.mark.parametrize("delegates", [True, False])
def test_a_delegating_leads_plan_is_told_to_name_who_makes_each_change(
    make_client, wait_run, project_dir, delegates
):
    # (REA, live: its plan said "I will append…", and the work turn could not.)
    client, model = make_client([text(PLAN)])
    planned(client, project_dir, wait_run, delegates=delegates)
    system = model.calls[0][0]["content"]
    assert "This turn is for a plan only" in system
    assert ("say which sub-agent or role makes it" in system) is delegates

def test_approved_the_work_turn_carries_the_plan_and_may_change_files(
    make_client, wait_run, project_dir
):
    client, model = make_client([text(PLAN), write("a.txt", "one\n"), text("done")])
    cid, run_id, _snap = planned(client, project_dir, wait_run)
    assert client.post(f"/api/runs/{run_id}/plan/approve", json={}).status_code == 403
    edited = PLAN + " 3. keep it short."
    answer = client.post(f"/api/runs/{run_id}/plan/approve", json={"text": edited}, headers=ORIGIN)
    assert answer.status_code in (200, 201), answer.text
    work = answer.json()["run_id"]
    snap = wait_run(client, cid, work)
    assert run_of(snap, run_id)["plan"]["status"] == "approved"
    assert run_of(snap, run_id)["plan"]["text"] == edited
    assert edited in json.dumps(model.calls[1])
    assert {"write_file"} <= set(names(model.tool_args[1]))
    assert read(project_dir, "a.txt") == "one\n"


def test_turned_down_nothing_more_happens(make_client, wait_run, project_dir):
    client, model = make_client([text(PLAN)])
    cid, run_id, _snap = planned(client, project_dir, wait_run)
    answer = client.post(f"/api/runs/{run_id}/plan/reject", json={"why": "not now"}, headers=ORIGIN)
    assert answer.status_code == 200, answer.text
    snap = client.get(f"/api/conversations/{cid}").json()
    assert run_of(snap, run_id)["plan"]["status"] == "rejected"
    assert len(snap["runs"]) == 1 and len(model.calls) == 1
