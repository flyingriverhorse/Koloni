"""Slice 38f's acceptance set, the backend's part: a conversation put away. Written before the code.

Archive takes a conversation off the list and into an "Archived" part of it; nothing of it is
deleted, and it comes back with one click. A trigger of an archived conversation still runs and
leaves it archived; the user writing in it again brings it back.
"""

import pytest

from app.schemas import ConversationOut

if "archived_at" not in ConversationOut.model_fields:
    pytest.skip("slice 38f is not built yet", allow_module_level=True)  # written before the code

from tests.test_chat_flow import text  # noqa: E402
from tests.test_trigger_scenarios import one, run_now, setup, trigger  # noqa: E402


def listed(client, pid, cid):
    found = client.get(f"/api/projects/{pid}/conversations")
    assert found.status_code == 200, found.text
    return next(c for c in found.json() if c["id"] == cid)


def archive(client, cid, archived=True):
    answer = client.patch(f"/api/conversations/{cid}", json={"archived": archived})
    assert answer.status_code == 200, answer.text
    return answer.json()


def say(client, wait_run, cid, words="hi"):
    sent = client.post(f"/api/conversations/{cid}/messages", json={"content": words})
    assert sent.status_code in (200, 201), sent.text
    wait_run(client, cid, sent.json()["run"]["id"])


def test_an_archived_conversation_is_listed_as_archived_and_comes_back(
    make_client, wait_run, project_dir
):
    client, _model, pid, cid = setup(make_client, project_dir, {"Lead": [text("hello")]})
    say(client, wait_run, cid)
    assert listed(client, pid, cid)["archived_at"] is None

    assert archive(client, cid)["archived_at"] is not None
    assert listed(client, pid, cid)["archived_at"] is not None
    snap = client.get(f"/api/conversations/{cid}").json()
    said = [m["content"] for m in snap["messages"] if m["role"] == "user"]
    assert said == ["hi"]  # nothing deleted

    assert archive(client, cid, archived=False)["archived_at"] is None
    assert listed(client, pid, cid)["archived_at"] is None


def test_archiving_is_asked_from_the_apps_own_page(make_client, project_dir):
    client, _model, _pid, cid = setup(make_client, project_dir, {"Lead": []})
    del client.headers["Origin"]
    refused = client.patch(f"/api/conversations/{cid}", json={"archived": True})
    assert refused.status_code == 403
    client.headers["Origin"] = "http://evil.example"
    assert client.patch(f"/api/conversations/{cid}", json={"archived": True}).status_code == 403


def test_a_trigger_of_an_archived_conversation_still_runs_and_leaves_it_archived(
    make_client, wait_run, project_dir
):
    client, _model, pid, cid = setup(make_client, project_dir, {"Lead": [text("looked")]})
    made = trigger(client, pid, cid)
    archive(client, cid)
    wait_run(client, cid, run_now(client, made["id"]), timeout=10.0)
    (ran,) = one(client, made["id"])["runs"]
    assert ran["outcome"] == "completed"
    assert listed(client, pid, cid)["archived_at"] is not None


def test_writing_in_an_archived_conversation_brings_it_back(make_client, wait_run, project_dir):
    client, _model, pid, cid = setup(make_client, project_dir, {"Lead": [text("back")]})
    archive(client, cid)
    say(client, wait_run, cid)
    assert listed(client, pid, cid)["archived_at"] is None
