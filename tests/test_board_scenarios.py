"""Slice 26's acceptance set: a coordinator without a model. Written before the code.

Several conversations of one project work at once. What holds them together is plain code,
not another agent: one limit on the agents at work in the whole project, one board that
shows every conversation's agents, and a warning where two conversations want the same file.
"""

import importlib.util

import pytest

if importlib.util.find_spec("app.api.board") is None:  # skipped until the code exists
    pytest.skip("slice 26 is not built yet", allow_module_level=True)

from tests.conftest import Gate  # noqa: E402
from tests.test_chat_flow import text  # noqa: E402
from tests.test_claim_scenarios import agent, write  # noqa: E402
from tests.test_parallel import until  # noqa: E402
from tests.test_spawn import step  # noqa: E402

ORIGIN = "http://127.0.0.1:8790"


def project(make_client, project_dir, lead_steps, **settings):
    client, model = make_client({"Lead": lead_steps})
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    if settings:
        assert client.patch(f"/api/projects/{pid}", json=settings).status_code == 200
    return client, model, pid


def talk(client, pid, **settings):
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    assert client.patch(f"/api/conversations/{cid}", json={
        "permission_mode": "full_auto", **settings}).status_code == 200
    return cid


def go(client, cid):
    return client.post(f"/api/conversations/{cid}/messages", json={"content": "go"}).json()[
        "run"]["id"]


def board(client, pid):
    shown = client.get(f"/api/projects/{pid}/board")
    assert shown.status_code == 200, shown.text
    return shown.json()


def on_board(told, cid):
    return next(c for c in told["conversations"] if c["conversation_id"] == cid)


def test_the_projects_limit_holds_a_second_conversations_agent_until_there_is_room(
    make_client, wait_run, project_dir
):
    first = Gate()
    client, model, pid = project(
        make_client, project_dir, [first.step(text("A done")), text("B done")], max_agents=1)
    a, b = talk(client, pid), talk(client, pid)
    run_a = go(client, a)
    first.wait_partial()
    run_b = go(client, b)
    snap = until(client, b, lambda s: s["agents"] and agent(s, "Lead")["status"] == "queued")
    assert len(model.calls) == 1                     # B's lead has not been asked anything
    told = board(client, pid)
    assert (told["limit"], told["running"]) == (1, 1)
    assert [x["status"] for x in on_board(told, a)["agents"]] == ["running"]
    assert [x["status"] for x in on_board(told, b)["agents"]] == ["queued"]
    first.release()
    assert wait_run(client, a, run_a)["runs"][0]["status"] == "completed"
    assert wait_run(client, b, run_b)["runs"][0]["status"] == "completed"
    assert snap["runs"][0]["status"] in ("running", "queued")
    assert client.patch(f"/api/projects/{pid}", json={"max_agents": 0}).status_code == 422


def test_without_a_limit_two_conversations_work_at_once(make_client, wait_run, project_dir):
    first = Gate()
    client, model, pid = project(
        make_client, project_dir, [first.step(text("A done")), text("B done")])
    a, b = talk(client, pid), talk(client, pid)
    run_a = go(client, a)
    first.wait_partial()
    assert wait_run(client, b, go(client, b))["runs"][0]["status"] == "completed"
    assert board(client, pid)["limit"] is None
    first.release()
    wait_run(client, a, run_a)


def test_the_board_shows_every_conversations_agents_and_what_they_hold(
    make_client, wait_run, project_dir
):
    first = Gate()
    client, model, pid = project(
        make_client, project_dir,
        [step(write("a.txt", "A")), first.step(text("A done"))])
    a = talk(client, pid)
    idle = talk(client, pid)
    run_a = go(client, a)
    first.wait_partial()
    told = board(client, pid)
    (lead,) = on_board(told, a)["agents"]
    assert (lead["name"], lead["status"]) == ("Lead", "running") and lead["holds"] == ["a.txt"]
    assert lead["provider_name"] and "model_id" in lead
    assert on_board(told, idle)["agents"] == [] and told["conflicts"] == []
    first.release()
    wait_run(client, a, run_a)
    assert on_board(board(client, pid), a)["agents"] == []      # only agents at work are on it


def test_two_conversations_that_want_one_file_are_named_on_the_board(
    make_client, wait_run, project_dir
):
    first = Gate()
    client, model, pid = project(
        make_client, project_dir,
        [step(write("a.txt", "A")), first.step(text("A done")),
         step(write("a.txt", "B")), text("B done"), text("B done")])
    a, b = talk(client, pid), talk(client, pid)
    run_a = go(client, a)
    first.wait_partial()
    run_b = go(client, b)
    snap = until(client, b, lambda s: s["agents"] and agent(s, "Lead").get("waiting_for"))
    # B-140 (live): the waiting chat said nothing of where the file is held: its holder's chat is named.
    held = agent(snap, "Lead")["waiting_for"]
    assert (held["conversation_id"], held["asks_you"]) == (a, False)
    assert held["conversation_title"] == client.get(f"/api/conversations/{a}").json()["conversation"]["title"]
    (conflict,) = board(client, pid)["conflicts"]
    assert conflict["path"] == "a.txt"
    assert (conflict["holder"]["conversation_id"], conflict["holder"]["agent_name"]) == (a, "Lead")
    assert [(w["conversation_id"], w["agent_name"]) for w in conflict["waiting"]] == [(b, "Lead")]
    first.release()
    wait_run(client, a, run_a)
    wait_run(client, b, run_b)
    assert board(client, pid)["conflicts"] == []


def test_a_conversation_whose_sub_agents_changes_wait_for_the_user_says_so_on_the_board(
    make_client, wait_run, project_dir
):
    # (Slice 38d's review: the Coder's own work is over while its changes wait, so it is
    # no longer an agent at work - the board says what waits all the same.)
    from tests.test_copy_scenarios import one

    client, model, cid, run_id = one(
        make_client, project_dir, [step(write("a.txt", "A")), text("A done")],
        permission_mode="ask")
    snap = until(client, cid, lambda s: [m["status"] for m in s["merges"]] == ["pending"])
    pid = snap["conversation"]["project_id"]
    told = on_board(board(client, pid), cid)
    assert "Coder" not in [a["name"] for a in told["agents"]]
    assert told["merges_pending"] == 1
    client.headers["Origin"] = ORIGIN
    assert client.post(f"/api/merges/{snap['merges'][0]['id']}/reject").status_code == 200
    wait_run(client, cid, run_id)
    assert on_board(board(client, pid), cid)["merges_pending"] == 0
