"""Slice 81c's acceptance set: a provider's limits (79's Settings -> Limits, in the provider window's
Limits tab) and a key that is a plan. Written before the code.

Design: `tasarim/specs/2026-10-23-dilim-81-agents-models-yeniden-design.md` §3 ("Settings → Limits")
and `tasarim/plans/kalan-isler.md` ("Plan anahtarı (kredi) para saymasın").

Contract:
- A provider has `plan` (bool, default false: "this key is a plan - count no money"),
  `step_down_at` (a subscription's plan share, 50-100, or null), `day_limit` and `month_limit`
  (money in the user's price currency, > 0, or null). Set from the app's own page only.
- A provider with `plan` true: its runs have no cost on Usage and count nothing in a budget (they
  are counted apart, as unpriced runs are).
- A provider whose spend today (or this month) at the user's prices reached its limit: a new turn
  whose Lead runs on it waits for the user's word - `POST .../messages` 409 naming the provider and
  the limit; `"over_budget": true` goes on, as for the project's budget (55). (An agent's pick that
  lands on such a provider takes the next model of its tier in the user's order instead, and says
  so in `chosen_why` - and a subscription past `step_down_at` gives a pick one tier lower, saying
  the plan's share: both left to the implementer's own tests, as they need a plan reading.)
"""

import pytest

from app.schemas import ProviderOut

if "day_limit" not in ProviderOut.model_fields:
    pytest.skip("slice 81c is not built yet", allow_module_level=True)  # written before the code

from tests.test_budget_scenarios import PRICE, budget  # noqa: E402
from tests.test_chat_flow import text  # noqa: E402
from tests.test_usage_scenarios import ORIGIN, began, turn, usage  # noqa: E402


def local(client):
    return client.get("/api/providers").json()[0]


def test_a_providers_limits_are_set_from_the_apps_own_page(make_client, project_dir):
    client, _model, _pid, _cid = began(make_client, project_dir, [])
    pid = local(client)["id"]
    body = {"plan": False, "step_down_at": 80, "day_limit": 5, "month_limit": 50}
    del client.headers["Origin"]
    assert client.patch(f"/api/providers/{pid}", json=body).status_code == 403
    client.headers["Origin"] = ORIGIN
    saved = client.patch(f"/api/providers/{pid}", json=body)
    assert saved.status_code == 200, saved.text
    assert {k: saved.json()[k] for k in body} == body
    for wrong in ({"step_down_at": 30}, {"step_down_at": 101}, {"day_limit": 0}, {"month_limit": -1}):
        assert client.patch(f"/api/providers/{pid}", json=wrong).status_code == 422, wrong
    cleared = client.patch(f"/api/providers/{pid}", json={"day_limit": None, "step_down_at": None})
    assert (cleared.json()["day_limit"], cleared.json()["step_down_at"]) == (None, None)


def test_a_key_that_is_a_plan_counts_no_money(make_client, wait_run, project_dir):
    client, _model, pid, cid = began(make_client, project_dir, [text("a", 1_000_000, 500_000)])
    client.put("/api/prices", json=PRICE)
    assert client.patch(f"/api/providers/{local(client)['id']}", json={"plan": True}).status_code == 200
    turn(client, wait_run, cid)
    (row,) = usage(client, project_id=pid)["by_model"]
    assert row.get("cost") is None
    assert client.patch(f"/api/projects/{pid}", json={"monthly_budget": 5}).status_code == 200
    seen = budget(client, pid)
    assert seen["spent"] == 0 and seen["unpriced_runs"] == 1 and seen["over"] is False


@pytest.mark.parametrize("limit", ["day_limit", "month_limit"])
def test_a_provider_past_its_limit_asks_before_a_new_turn(make_client, wait_run, project_dir, limit):
    client, _model, _pid, cid = began(make_client, project_dir,
                                      [text("a", 1_000_000, 500_000), text("b", 10, 10)])
    client.put("/api/prices", json=PRICE)
    provider = local(client)
    assert client.patch(f"/api/providers/{provider['id']}", json={limit: 5}).status_code == 200
    turn(client, wait_run, cid)  # 10.50 USD at PRICE: past the limit of 5
    refused = client.post(f"/api/conversations/{cid}/messages", json={"content": "more"})
    assert refused.status_code == 409, refused.text
    assert provider["name"] in refused.text and ("today" in refused.text or "month" in refused.text)
    went = client.post(f"/api/conversations/{cid}/messages", json={"content": "more", "over_budget": True})
    assert went.status_code == 201, went.text


def test_under_its_limit_a_provider_asks_nothing(make_client, wait_run, project_dir):
    client, _model, _pid, cid = began(make_client, project_dir,
                                      [text("a", 1_000, 500), text("b", 10, 10)])
    client.put("/api/prices", json=PRICE)
    assert client.patch(f"/api/providers/{local(client)['id']}", json={"day_limit": 5}).status_code == 200
    turn(client, wait_run, cid)  # a cent
    assert client.post(f"/api/conversations/{cid}/messages", json={"content": "more"}).status_code == 201
