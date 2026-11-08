"""Slice 56's acceptance set: the day's summary of a project. Written before the code.

Since a moment the page gives (its own midnight), every conversation of the project is counted from
the record - no model is asked: turns, the agents that worked, the files changed, what waits for the
user, what failed, tokens and the known cost. Nothing before that moment is counted.

Contract: `GET /api/projects/{id}/day?since=<ISO datetime>` →
`{turns, agents, changed_files: [path], waiting, failed, input_tokens, output_tokens, cost,
conversations: [{conversation_id, title, turns, changed_files, failed}]}`; cost is null with no price.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.model_client import ModelUnavailable
from tests.test_agent_writes import write
from tests.test_chat_flow import text
from tests.test_usage_scenarios import began, turn


def day(client, pid, since):
    if "/api/projects/{project_id}/day" not in client.app.openapi()["paths"]:
        pytest.skip("slice 56 is not built yet")  # written before the code
    answer = client.get(f"/api/projects/{pid}/day", params={"since": since.isoformat()})
    assert answer.status_code == 200, answer.text
    return answer.json()


def test_the_day_is_counted_from_the_record(make_client, wait_run, project_dir):
    before = datetime.now(UTC) - timedelta(minutes=5)
    client, _model, pid, cid = began(
        make_client,
        project_dir,
        [write("a.txt", "one\n"), text("made a", 10, 2), ModelUnavailable("refused")],
    )
    client.patch(f"/api/conversations/{cid}", json={"lead_hands_code": False})
    turn(client, wait_run, cid, "make a")
    turn(client, wait_run, cid, "again")

    seen = day(client, pid, before)
    assert seen["turns"] == 2 and seen["failed"] == 1
    assert seen["changed_files"] == ["a.txt"]
    assert seen["input_tokens"] >= 10 and seen["cost"] is None
    (one,) = seen["conversations"]
    assert (one["conversation_id"], one["turns"], one["changed_files"], one["failed"]) == (
        cid,
        2,
        1,
        1,
    )


def test_nothing_before_the_moment_is_counted(make_client, wait_run, project_dir):
    client, _model, pid, cid = began(make_client, project_dir, [text("hi")])
    turn(client, wait_run, cid)
    later = datetime.now(UTC) + timedelta(minutes=1)
    seen = day(client, pid, later)
    assert (seen["turns"], seen["changed_files"], seen["conversations"]) == (0, [], [])
