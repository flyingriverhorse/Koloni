"""Task 6 (0.1.11): what a turn cost so far, for the line over its chat - its agents' tokens at the
user's prices (`GET /api/runs/{id}/spent`); null where nothing of it is priced, never a zero."""

from pytest import approx

from tests.test_budget_scenarios import PRICE
from tests.test_chat_flow import text
from tests.test_spawn import call, step
from tests.test_usage_scenarios import began, turn


def spawned(make_client, project_dir):
    return began(
        make_client,
        project_dir,
        {
            "Lead": [
                step(call("spawn_agent", {"role": "Coder", "task": "do it"}, "s1"), i=10**6, o=0),
                text("done", 0, 0),
            ],
            "Coder": [text("ok", 0, 100_000)],
        },
    )


def test_two_priced_agents_are_added_up(make_client, wait_run, project_dir):
    client, _model, _pid, cid = spawned(make_client, project_dir)
    run = turn(client, wait_run, cid)
    assert run["status"] == "completed", run["error"]
    client.put("/api/prices", json=PRICE)
    got = client.get(f"/api/runs/{run['id']}/spent").json()
    # (1M in at 3 USD a million; 100k out at 15)
    assert got == {"spent": approx(4.5), "currency": "USD", "at_least": False}


def test_a_turn_with_no_price_says_none_not_zero(make_client, wait_run, project_dir):
    client, _model, _pid, cid = spawned(make_client, project_dir)
    run = turn(client, wait_run, cid)
    assert client.get(f"/api/runs/{run['id']}/spent").json() == {
        "spent": None,
        "currency": None,
        "at_least": False,
    }
    assert client.get("/api/runs/nobody/spent").status_code == 404
