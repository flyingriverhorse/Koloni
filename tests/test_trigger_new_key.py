"""Slice 96: a webhook's key made anew - for an address that got out. The old address stops at
once, the new one is shown that once, and that it was done stays on the trigger's record."""

import json

from tests.keyed import TestClient
from tests.test_chat_flow import text
from tests.test_trigger_scenarios import ORIGIN, setup, trigger


def test_a_new_key_stops_the_old_address_at_once(make_client, project_dir):
    client, _model, pid, cid = setup(make_client, project_dir, {"Lead": [text("ok")]})
    made = trigger(client, pid, cid, kind="webhook", config={})
    old = made["key"]
    renewed = client.post(f"/api/triggers/{made['id']}/key")
    assert renewed.status_code == 200, renewed.text
    new = renewed.json()["key"]
    assert new and new != old
    here = TestClient(client.app, base_url=ORIGIN, client=("127.0.0.1", 50000))
    assert here.post(f"/api/hooks/{old}", content="x").status_code == 404
    listed = client.get(f"/api/projects/{pid}/triggers").json()
    assert new not in json.dumps(listed)  # shown that once only
    (mine,) = listed
    assert any(change["what"] == "new key" for change in mine["changes"])


def test_only_a_webhook_has_a_key_and_only_from_the_apps_own_page(make_client, project_dir):
    client, _model, pid, cid = setup(make_client, project_dir, {"Lead": [text("ok")]})
    clock = trigger(client, pid, cid)
    assert client.post(f"/api/triggers/{clock['id']}/key").status_code == 422
    hook = trigger(client, pid, cid, kind="webhook", config={})
    assert client.post(f"/api/triggers/{hook['id']}/key", headers={"Origin": ""}).status_code == 403
    assert client.post("/api/triggers/nope/key").status_code == 404
