"""Slice 21's acceptance set: what was spent and where, and a limit on a turn's tokens.
Written before the code.

Only what a model reported is counted: an agent that reported nothing is "unknown", never a
zero. What an agent sent is the sum of what every step of it sent (a step sends the whole
conversation again), not the size of its last step.
"""

import importlib.util

import pytest

if importlib.util.find_spec("app.api.usage") is None:  # skipped until the code exists
    pytest.skip("slice 21 is not built yet", allow_module_level=True)

from app.model_client import StepResult  # noqa: E402
from tests.test_chat_flow import text  # noqa: E402
from tests.test_spawn import call, step  # noqa: E402
from tests.test_trigger_scenarios import finished, run_now, trigger  # noqa: E402

ORIGIN = "http://127.0.0.1:8790"
LOOK = "list_dir"


def began(make_client, project_dir, steps, **project):
    client, model = make_client(steps)
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    if project:
        assert client.patch(f"/api/projects/{pid}", json=project).status_code == 200
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    assert client.patch(f"/api/conversations/{cid}", json={
        "permission_mode": "full_auto", "spawn_approval": "never"}).status_code == 200
    return client, model, pid, cid


def turn(client, wait_run, cid, said="go"):
    run_id = client.post(f"/api/conversations/{cid}/messages", json={"content": said}).json()[
        "run"]["id"]
    snap = wait_run(client, cid, run_id)
    return next(run for run in snap["runs"] if run["id"] == run_id)


def usage(client, **asked):
    answer = client.get("/api/usage", params=asked)
    assert answer.status_code == 200, answer.text
    return answer.json()


def test_what_every_step_of_every_agent_reported_is_added_up(make_client, wait_run, project_dir):
    client, model, pid, cid = began(make_client, project_dir, [
        step(call("spawn_agent", {"role": "Reviewer", "task": "t"}), i=5, o=2),
        text("r", 7, 4), text("l", 9, 1)])
    assert turn(client, wait_run, cid)["status"] == "completed"
    told = usage(client, project_id=pid)
    (row,) = told["by_model"]
    assert row["model_id"] == "fake-model" and (row["runs"], row["agents"]) == (1, 2)
    # the lead sent 5 and then 9, the reviewer 7; they wrote 2 + 1 and 4
    assert (row["input_tokens"], row["output_tokens"]) == (21, 7)
    assert row["unknown_agents"] == 0 and row["cost"] is None
    (talk,) = told["by_conversation"]
    assert talk["conversation_id"] == cid and (talk["input_tokens"], talk["output_tokens"]) == (21, 7)


def test_one_chats_usage_is_only_its_own_turns(make_client, wait_run, project_dir):
    client, model, pid, cid = began(make_client, project_dir, [text("a", 5, 2), text("b", 9, 1)])
    other = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    assert turn(client, wait_run, cid)["status"] == "completed"
    assert turn(client, wait_run, other)["status"] == "completed"
    assert {t["conversation_id"] for t in usage(client, project_id=pid)["by_conversation"]} == {cid, other}
    told = usage(client, conversation_id=cid)
    (row,) = told["by_model"]
    assert (row["runs"], row["input_tokens"], row["output_tokens"]) == (1, 5, 2)
    assert [t["conversation_id"] for t in told["by_conversation"]] == [cid]
    assert client.get("/api/usage", params={"conversation_id": "nope"}).status_code == 404


def test_an_agent_that_reported_nothing_is_unknown_and_not_a_zero(make_client, wait_run,
                                                                  project_dir):
    client, model, pid, cid = began(make_client, project_dir, [StepResult("x", [], None, None)])
    turn(client, wait_run, cid)
    (row,) = usage(client, project_id=pid)["by_model"]
    assert (row["agents"], row["unknown_agents"]) == (1, 1)
    assert row["input_tokens"] is None and row["output_tokens"] is None


def test_a_period_leaves_out_what_was_before_it(make_client, wait_run, project_dir):
    client, model, pid, cid = began(make_client, project_dir, [text("a")])
    turn(client, wait_run, cid)
    assert usage(client, project_id=pid, since="2020-01-01T00:00:00Z")["by_model"]
    later = usage(client, project_id=pid, since="2999-01-01T00:00:00Z")
    assert later["by_model"] == [] and later["by_conversation"] == []


def test_a_triggers_turns_are_told_apart_from_the_users(make_client, wait_run, project_dir):
    client, model, pid, cid = began(make_client, project_dir, [text("mine", 5, 3),
                                                               text("its own", 11, 2)])
    turn(client, wait_run, cid)
    finished(client, wait_run, cid, run_now(client, trigger(client, pid, cid)["id"]))
    by_start = {row["started_by"]: row for row in usage(client, project_id=pid)["by_start"]}
    assert (by_start["user"]["runs"], by_start["user"]["input_tokens"]) == (1, 5)
    assert (by_start["trigger"]["runs"], by_start["trigger"]["input_tokens"]) == (1, 11)


def test_money_is_shown_only_for_a_model_the_user_gave_a_price(make_client, wait_run,
                                                               project_dir):
    client, model, pid, cid = began(make_client, project_dir, [text("a", 1_000_000, 500_000)])
    turn(client, wait_run, cid)
    assert usage(client, project_id=pid)["by_model"][0]["cost"] is None
    price = {"model_id": "fake-model", "input": 3, "output": 15, "currency": "USD"}
    assert client.put("/api/prices", json=price).status_code == 200
    assert client.put("/api/prices", json={**price, "input": -1}).status_code == 422
    assert client.put("/api/prices", json=price, headers={"Origin": ""}).status_code == 403
    cost = usage(client, project_id=pid)["by_model"][0]["cost"]
    assert cost == {"amount": 10.5, "currency": "USD"}     # 1 M at 3, half a million at 15
    assert client.delete("/api/prices", params={"model_id": "fake-model"}).status_code == 200
    assert usage(client, project_id=pid)["by_model"][0]["cost"] is None


def test_without_a_project_every_project_is_counted(make_client, wait_run, project_dir,
                                                    tmp_path):
    client, model, pid, cid = began(make_client, project_dir, [text("a", 5, 3), text("b", 6, 1)])
    turn(client, wait_run, cid)
    other = tmp_path / "another"
    other.mkdir()
    pid2 = client.post("/api/projects", json={"root_path": str(other)}).json()["id"]
    cid2 = client.post(f"/api/projects/{pid2}/conversations").json()["id"]
    turn(client, wait_run, cid2)
    assert [row["conversation_id"] for row in usage(client, project_id=pid2)["by_conversation"]] == [cid2]
    everywhere = usage(client)
    assert {row["conversation_id"] for row in everywhere["by_conversation"]} == {cid, cid2}
    assert {row["project_id"] for row in everywhere["by_conversation"]} == {pid, pid2}
    assert everywhere["by_model"][0]["input_tokens"] == 11


def looks(n, i, o):
    return step(call(LOOK, {}, f"c{n}"), i=i, o=o)


def test_a_turn_over_the_projects_limit_is_stopped_and_says_why(make_client, wait_run,
                                                                project_dir):
    client, model, pid, cid = began(
        make_client, project_dir, [looks(1, 5, 2), looks(2, 9, 1), text("never said")],
        turn_token_limit=10)
    run = turn(client, wait_run, cid)                     # 7 after one step, 17 after two
    assert run["status"] != "completed" and "limit" in (run["error"] or "")
    assert len(model.calls) == 2                          # no third step was asked for
    assert client.patch(f"/api/projects/{pid}", json={"turn_token_limit": 0}).status_code == 422


def test_without_a_limit_the_same_turn_ends_as_it_would(make_client, wait_run, project_dir):
    client, model, pid, cid = began(
        make_client, project_dir, [looks(1, 5, 2), looks(2, 9, 1), text("said")])
    assert turn(client, wait_run, cid)["status"] == "completed"


def test_what_a_model_does_not_report_cannot_be_limited(make_client, wait_run, project_dir):
    silent = StepResult("", [call(LOOK, {}, "c1")], None, None)
    client, model, pid, cid = began(
        make_client, project_dir, [silent, StepResult("done", [], None, None)],
        turn_token_limit=1)
    assert turn(client, wait_run, cid)["status"] == "completed"


def test_a_renamed_providers_rows_follow_it_by_its_id(make_client, wait_run, project_dir):
    # K-claude-hesap: the provider's own name everywhere - its record follows a rename.
    client, model, pid, cid = began(make_client, project_dir, [text("a", 5, 2)])
    assert turn(client, wait_run, cid)["status"] == "completed"
    (row,) = usage(client, project_id=pid)["by_model"]
    provider = next(p for p in client.get("/api/providers").json() if p["name"] == row["provider_name"])
    assert row["provider_id"] == provider["id"]
    renamed = client.patch(f"/api/providers/{provider['id']}", json={"name": "Work account"},
                           headers={"Origin": "http://127.0.0.1:8790"})
    assert renamed.status_code == 200, renamed.text
    (row,) = usage(client, project_id=pid)["by_model"]
    assert (row["provider_name"], row["provider_id"], row["input_tokens"]) == (
        "Work account", provider["id"], 5)
