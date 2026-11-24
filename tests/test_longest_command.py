"""0.1.8: a project's Longest command - 10 minutes unless the user raises it, at most 60 - is
the most an agent's command may ask for and how long KOLONİ's own test run is given."""

import json

import pytest

from app.model_client import StepResult, ToolCallRequest
from tests.fakes import Script, ScriptedExecutor
from tests.test_agent_writes import write
from tests.test_chat_flow import text
from tests.test_proof_background_scenarios import held, soon  # noqa: F401  (a fixture)
from tests.test_proof_end_scenarios import begin

ORIGIN = {"Origin": "http://127.0.0.1:8790"}


def long_run(seconds):
    args = json.dumps({"command": "pytest -q", "timeout_seconds": seconds})
    return StepResult("", [ToolCallRequest("r1", "run_command", args)], 1, 1)


def timeout_said(tools):
    (schema,) = [t for t in tools if t["function"]["name"] == "run_command"]
    return schema["function"]["parameters"]["properties"]["timeout_seconds"]["description"]


def test_it_is_ten_minutes_until_the_user_raises_it_from_the_apps_own_page(
    make_client, project_dir
):
    client, _model = make_client([])
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    assert client.get(f"/api/projects/{pid}").json()["longest_command"] == 10
    for wrong in (9, 61, True, "30", 12.5):
        sent = client.patch(f"/api/projects/{pid}", json={"longest_command": wrong}, headers=ORIGIN)
        assert sent.status_code == 422, wrong
    # (raising it is the user's, as a budget is: not a command's against the app's address)
    assert client.patch(f"/api/projects/{pid}", json={"longest_command": 30}).status_code == 403
    sent = client.patch(f"/api/projects/{pid}", json={"longest_command": 30}, headers=ORIGIN)
    assert sent.status_code == 200 and sent.json()["longest_command"] == 30


def test_an_agents_command_may_ask_for_the_projects_longest_and_is_told_it(
    make_client, wait_run, project_dir
):
    executor = ScriptedExecutor([Script(["2 passed\n"])])
    client, model = make_client(
        [long_run(1800), text("too long"), long_run(1800), text("ran")], executor=executor
    )
    cid, run_id = begin(client, project_dir, after_change="nothing")
    first = wait_run(client, cid, run_id)
    ((said,),) = [[t["result"]] for t in first["tool_calls"] if t["name"] == "run_command"]
    assert said.startswith("error: timeout_seconds must be between 1 and 600, this project's")
    assert "the user can raise it in its settings, up to 3600" in said
    # The default's schema is word for word what it was (the prompt's cache).
    assert timeout_said(model.tool_args[0]).endswith("Default 120, at most 600.")
    (pid,) = [one["id"] for one in client.get("/api/projects").json()]
    client.patch(f"/api/projects/{pid}", json={"longest_command": 30}, headers=ORIGIN)
    second = client.post(f"/api/conversations/{cid}/messages", json={"content": "again"}).json()
    done = wait_run(client, cid, second["run"]["id"])
    assert timeout_said(model.tool_args[2]).endswith("Default 120, at most 1800.")
    (command,) = done["commands"]
    assert (command["status"], command["timeout_seconds"]) == ("exited", 1800)


@pytest.mark.usefixtures("soon")
def test_kolonis_own_test_run_is_given_the_projects_longest(
    make_client, wait_run, project_dir, gate
):
    executor = ScriptedExecutor([held(gate, "....\n")])
    client, _model = make_client([write("a.py", "x = 1\n"), text("done")], executor=executor)
    cid, run_id = begin(client, project_dir, check_command="python check.py", longest_command=45)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    (ran,) = snap["commands"]
    assert ran["status"] == "running" and ran["timeout_seconds"] == 45 * 60
