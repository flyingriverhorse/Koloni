"""Slice 55's acceptance set: a project's monthly budget. Written before the code.

The user sets a monthly budget for a project (from the app's own page). What this month's turns
cost at the user's own prices is added up; a turn on a model with no price is counted apart and
never guessed. At 80% the budget warns; at 100% a new turn is not started unless the user says to
go on over it.

Contract:
- `ProjectPatch.monthly_budget` / `ProjectOut.monthly_budget` (number or null; own origin to set).
- `GET /api/projects/{id}/budget` → `{budget, currency, spent, share, warn, over, unpriced_runs}`.
- `POST /api/conversations/{cid}/messages` → 409 (detail names the budget) when over;
  `{"content": …, "over_budget": true}` goes on anyway.
"""

import pytest
from sqlalchemy import select

from app.db.models import Agent
from app.schemas import ProjectOut

if "monthly_budget" not in ProjectOut.model_fields:
    pytest.skip("slice 55 is not built yet", allow_module_level=True)  # written before the code

from tests.test_chat_flow import text  # noqa: E402
from tests.test_usage_scenarios import ORIGIN, began, turn  # noqa: E402

PRICE = {"model_id": "fake-model", "input": 3, "output": 15, "currency": "USD"}


def budget(client, pid):
    answer = client.get(f"/api/projects/{pid}/budget")
    assert answer.status_code == 200, answer.text
    return answer.json()


def test_spent_this_month_is_added_up_at_the_users_prices(make_client, wait_run, project_dir):
    client, _model, pid, cid = began(make_client, project_dir, [text("a", 1_000_000, 500_000)])
    turn(client, wait_run, cid)
    assert budget(client, pid)["budget"] is None
    client.put("/api/prices", json=PRICE)
    assert client.patch(f"/api/projects/{pid}", json={"monthly_budget": 12}).status_code == 200
    seen = budget(client, pid)
    assert (seen["budget"], seen["currency"], seen["spent"]) == (12, "USD", 10.5)
    assert seen["warn"] is True and seen["over"] is False  # 87.5%
    assert round(seen["share"], 3) == 0.875


def test_a_turn_on_a_model_with_no_price_is_counted_apart(make_client, wait_run, project_dir):
    client, _model, pid, cid = began(make_client, project_dir, [text("a", 1_000_000, 500_000)])
    turn(client, wait_run, cid)
    client.patch(f"/api/projects/{pid}", json={"monthly_budget": 5})
    seen = budget(client, pid)
    assert seen["spent"] == 0 and seen["unpriced_runs"] == 1 and seen["over"] is False


def test_a_turn_on_two_models_with_no_price_is_one_turn(make_client, wait_run, project_dir):
    client, _model, pid, cid = began(make_client, project_dir, [text("a", 1_000, 500)])
    run = turn(client, wait_run, cid)
    with client.app.state.session_factory() as session:
        lead = session.scalars(select(Agent)).one()
        session.add(Agent(run_id=run["id"], role_name="Other", tools=[], provider_name="Elsewhere",
                          model_id="big", input_tokens_total=10, output_tokens=5,
                          started_at=lead.started_at))
        session.commit()
    assert budget(client, pid)["unpriced_runs"] == 1
    # with a price for one of them, the turn still has a part that has none
    assert client.put("/api/prices", json=PRICE).status_code == 200
    seen = budget(client, pid)
    assert seen["unpriced_runs"] == 1 and seen["spent"] > 0


def test_over_the_budget_a_new_turn_waits_for_the_users_word(make_client, wait_run, project_dir):
    client, _model, pid, cid = began(
        make_client, project_dir, [text("a", 1_000_000, 500_000), text("b", 1, 1)]
    )
    turn(client, wait_run, cid)
    client.put("/api/prices", json=PRICE)
    client.patch(f"/api/projects/{pid}", json={"monthly_budget": 10})
    assert budget(client, pid)["over"] is True
    refused = client.post(f"/api/conversations/{cid}/messages", json={"content": "more"})
    assert refused.status_code == 409 and "budget" in refused.text.lower()
    going = client.post(
        f"/api/conversations/{cid}/messages", json={"content": "more", "over_budget": True}
    )
    assert going.status_code in (200, 201), going.text


def test_the_budget_is_set_only_from_the_apps_own_page(make_client, project_dir):
    client, _model, pid, _cid = began(make_client, project_dir, [])
    del client.headers["Origin"]
    assert client.patch(f"/api/projects/{pid}", json={"monthly_budget": 1}).status_code == 403
    client.headers["Origin"] = ORIGIN
    assert client.patch(f"/api/projects/{pid}", json={"monthly_budget": -1}).status_code == 422
    assert client.patch(f"/api/projects/{pid}", json={"monthly_budget": None}).status_code == 200
