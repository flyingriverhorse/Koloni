"""Slice 26, beside its acceptance set: the place an agent at work holds in its project is
given back however its work ends or waits; a provider's own limit; who may set a limit."""

import asyncio
import threading

from app.model_client import ModelUnavailable
from tests.conftest import Gate
from tests.test_board_scenarios import ORIGIN, board, go, on_board, project, talk
from tests.test_chat_flow import text
from tests.test_claim_scenarios import agent, write
from tests.test_parallel import until
from tests.test_spawn import spawn, step


def queued(client, cid):
    return until(client, cid, lambda s: s["agents"] and agent(s, "Lead")["status"] == "queued")


def cancel(client, run_id):
    assert client.post(f"/api/runs/{run_id}/cancel").status_code == 202


# --- the place comes back ----------------------------------------------------------


def test_a_queued_lead_that_is_stopped_leaves_the_line_and_the_next_one_starts(
    make_client, wait_run, project_dir
):
    first = Gate()
    client, model, pid = project(
        make_client, project_dir, [first.step(text("A done")), text("C done")], max_agents=1)
    a, b, c = talk(client, pid), talk(client, pid), talk(client, pid)
    run_a = go(client, a)
    first.wait_partial()
    run_b = go(client, b)
    queued(client, b)
    run_c = go(client, c)
    queued(client, c)
    cancel(client, run_b)
    assert wait_run(client, b, run_b)["runs"][0]["status"] == "cancelled"
    assert board(client, pid)["running"] == 1 and len(model.calls) == 1   # C still waits
    first.release()
    assert wait_run(client, a, run_a)["runs"][0]["status"] == "completed"
    assert wait_run(client, c, run_c)["runs"][0]["status"] == "completed"
    assert len(model.calls) == 2                       # B's lead was never asked anything
    assert board(client, pid)["running"] == 0


def test_stopping_the_agent_at_work_lets_the_one_in_line_start(
    make_client, wait_run, project_dir
):
    first = Gate()
    client, model, pid = project(
        make_client, project_dir, [first.step(text("A done")), text("B done")], max_agents=1)
    a, b = talk(client, pid), talk(client, pid)
    run_a = go(client, a)
    first.wait_partial()
    run_b = go(client, b)
    queued(client, b)
    cancel(client, run_a)
    assert wait_run(client, a, run_a)["runs"][0]["status"] == "cancelled"
    assert wait_run(client, b, run_b)["runs"][0]["status"] == "completed"
    assert board(client, pid)["running"] == 0


def test_an_agent_whose_model_fails_gives_its_place_back(make_client, wait_run, project_dir):
    seen, let_go = threading.Event(), threading.Event()

    async def fails(on_delta):
        seen.set()
        while not let_go.is_set():
            await asyncio.sleep(0.01)
        raise ModelUnavailable("model server unreachable: refused")

    client, model, pid = project(
        make_client, project_dir, [fails, text("B done")], max_agents=1)
    a, b = talk(client, pid), talk(client, pid)
    run_a = go(client, a)
    assert seen.wait(5)
    run_b = go(client, b)
    queued(client, b)
    let_go.set()
    assert wait_run(client, a, run_a)["runs"][0]["status"] == "failed"
    assert wait_run(client, b, run_b)["runs"][0]["status"] == "completed"
    assert board(client, pid)["running"] == 0


def test_an_agent_waiting_for_the_users_word_holds_no_place(make_client, wait_run, project_dir):
    client, model, pid = project(
        make_client, project_dir,
        [step(write("a.txt", "A")), text("B done"), text("A done")], max_agents=1)
    a, b = talk(client, pid, permission_mode="ask"), talk(client, pid)
    run_a = go(client, a)
    snap = until(client, a, lambda s: s["runs"][0]["status"] == "waiting_approval")
    told = board(client, pid)
    assert told["running"] == 0
    assert [x["status"] for x in on_board(told, a)["agents"]] == ["waiting_approval"]
    # The whole of B's turn fits in while A waits for the user.
    assert wait_run(client, b, go(client, b))["runs"][0]["status"] == "completed"
    change = snap["file_changes"][0]["id"]
    assert client.post(f"/api/file-changes/{change}/approve").status_code == 200
    assert wait_run(client, a, run_a)["runs"][0]["status"] == "completed"
    assert (project_dir / "a.txt").read_text() == "A"
    assert board(client, pid)["running"] == 0


def test_once_the_user_has_spoken_the_agent_waits_for_a_place_not_for_them(
    make_client, wait_run, project_dir
):
    held = Gate()
    client, model, pid = project(
        make_client, project_dir,
        [step(write("a.txt", "A")), held.step(text("B done")), text("A done")], max_agents=1)
    a, b = talk(client, pid, permission_mode="ask"), talk(client, pid)
    run_a = go(client, a)
    snap = until(client, a, lambda s: s["runs"][0]["status"] == "waiting_approval")
    run_b = go(client, b)
    held.wait_partial()                                  # B's lead has the one place now
    change = snap["file_changes"][0]["id"]
    assert client.post(f"/api/file-changes/{change}/approve").status_code == 200
    snap = queued(client, a)
    assert snap["runs"][0]["status"] == "running"        # nothing is asked of the user
    assert board(client, pid)["running"] == 1 and len(model.calls) == 2
    held.release()
    assert wait_run(client, b, run_b)["runs"][0]["status"] == "completed"
    assert wait_run(client, a, run_a)["runs"][0]["status"] == "completed"
    assert (project_dir / "a.txt").read_text() == "A"


def test_a_finished_sub_agent_whose_copy_the_user_decides_takes_no_place_again(
    make_client, wait_run, project_dir
):
    held = Gate()
    client, model = make_client({
        "Lead": [spawn("Coder"), held.step(text("B done")), text("A done")],
        "Coder": [step(write("x.txt", "x")), text("coded")],
    })
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    assert client.patch(f"/api/projects/{pid}", json={"max_agents": 1}).status_code == 200
    a = talk(client, pid, permission_mode="ask", spawn_approval="never")
    b = talk(client, pid)
    run_a = go(client, a)
    card = until(client, a, lambda s: s["merges"])["merges"][0]   # the Coder is done; you are asked
    run_b = go(client, b)
    held.wait_partial()                                  # B's lead has the one place now
    assert client.post(f"/api/merges/{card['id']}/approve").status_code == 200
    snap = until(client, a, lambda s: s["merges"][0]["status"] == "applied")
    assert agent(snap, "Coder")["status"] == "completed"
    assert (project_dir / "x.txt").read_text() == "x"    # taken in without a place
    snap = queued(client, a)                             # its lead waits for B's place
    assert agent(snap, "Coder")["status"] == "completed"
    held.release()
    assert wait_run(client, b, run_b)["runs"][0]["status"] == "completed"
    assert wait_run(client, a, run_a)["runs"][0]["status"] == "completed"


def test_a_sub_agent_counts_and_its_waiting_lead_does_not(make_client, wait_run, project_dir):
    held = Gate()
    client, model = make_client({
        "Lead": [spawn("Coder"), text("A done"), text("B done")],
        "Coder": [held.step(text("coded"))],
    })
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    assert client.patch(f"/api/projects/{pid}", json={"max_agents": 1}).status_code == 200
    a, b = talk(client, pid, spawn_approval="never"), talk(client, pid)
    run_a = go(client, a)
    held.wait_partial()
    told = board(client, pid)
    assert told["running"] == 1                         # the Coder; its lead only waits
    assert {x["name"]: x["status"] for x in on_board(told, a)["agents"]} == {
        "Lead": "waiting", "Coder": "running"}
    run_b = go(client, b)
    queued(client, b)
    held.release()
    assert wait_run(client, a, run_a)["runs"][0]["status"] == "completed"
    assert wait_run(client, b, run_b)["runs"][0]["status"] == "completed"


# --- the limits themselves ---------------------------------------------------------


def test_raising_the_limit_lets_the_waiting_agent_start_at_once(
    make_client, wait_run, project_dir
):
    first = Gate()
    client, model, pid = project(
        make_client, project_dir, [first.step(text("A done")), text("B done")], max_agents=1)
    a, b = talk(client, pid), talk(client, pid)
    run_a = go(client, a)
    first.wait_partial()
    run_b = go(client, b)
    queued(client, b)
    assert client.patch(f"/api/projects/{pid}", json={"max_agents": None}).status_code == 200
    assert wait_run(client, b, run_b)["runs"][0]["status"] == "completed"   # A still works
    first.release()
    wait_run(client, a, run_a)


def test_the_projects_limit_is_the_users_to_set_from_the_apps_own_page(client, project_dir):
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    assert client.get(f"/api/projects/{pid}").json()["max_agents"] is None
    assert client.patch(f"/api/projects/{pid}", json={"max_agents": 3}).status_code == 403
    client.headers["Origin"] = ORIGIN
    assert client.patch(f"/api/projects/{pid}", json={"max_agents": 3}).json()["max_agents"] == 3
    for bad in (0, -1, "3", True, 1.5):
        assert client.patch(f"/api/projects/{pid}", json={"max_agents": bad}).status_code == 422
    # Another setting leaves it alone; null takes it away.
    assert client.patch(
        f"/api/projects/{pid}", json={"docker_network": True}).json()["max_agents"] == 3
    assert client.patch(
        f"/api/projects/{pid}", json={"max_agents": None}).json()["max_agents"] is None


def test_a_providers_limit_holds_agents_of_any_project(
    make_client, wait_run, project_dir, tmp_path
):
    first = Gate()
    client, model, pid = project(
        make_client, project_dir, [first.step(text("A done")), text("B done")])
    elsewhere = tmp_path / "other"
    elsewhere.mkdir()
    other = client.post("/api/projects", json={"root_path": str(elsewhere)}).json()["id"]
    provider = client.get("/api/providers").json()[0]
    assert provider["max_running"] is None
    # The user's to say from the app's own page, as the project's limit is.
    assert client.patch(f"/api/providers/{provider['id']}", json={"max_running": 1},
                        headers={"Origin": ""}).status_code == 403
    for bad in (0, -1, "2", True):
        assert client.patch(
            f"/api/providers/{provider['id']}", json={"max_running": bad}).status_code == 422
    assert client.patch(
        f"/api/providers/{provider['id']}", json={"max_running": 1}).json()["max_running"] == 1
    a, b = talk(client, pid), talk(client, other)
    run_a = go(client, a)
    first.wait_partial()
    run_b = go(client, b)
    queued(client, b)
    assert len(model.calls) == 1 and board(client, other)["limit"] is None
    assert client.patch(
        f"/api/providers/{provider['id']}", json={"note": "busy"}).json()["max_running"] == 1
    assert client.patch(
        f"/api/providers/{provider['id']}", json={"max_running": None}).status_code == 200
    assert wait_run(client, b, run_b)["runs"][0]["status"] == "completed"   # A still works
    first.release()
    assert wait_run(client, a, run_a)["runs"][0]["status"] == "completed"


def test_the_board_of_a_project_that_is_not_there(client):
    assert client.get("/api/projects/nope/board").status_code == 404
