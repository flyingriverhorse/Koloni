"""B-398 (REA's R191, PLAN-T81-05: five teams given, Quality never opened, the Orchestrator out of
steps after merging): the Orchestrator is told once of a team the user gave the chat that it did
not open, and so is the user; it has steps for each of its teams; Settings › The app's "Steps an
agent may take" is the app's step limit."""

import json
from dataclasses import replace
from types import SimpleNamespace

from app.config import load_settings
from app.main import create_app
from tests.fakes import ScriptedModel
from tests.keyed import TestClient
from tests.test_chat_flow import text
from tests.test_chat_teams_scenarios import teams_of
from tests.test_spawn import begin, call, spawn, step
from tests.test_team_requests_scenarios import API, agent, two_teams

OWN = {"Origin": "http://127.0.0.1:8790"}


def looking(n):
    return [step(call("list_dir", {}, f"k{i}")) for i in range(n)]


def test_steps_an_agent_may_take_is_a_setting_of_the_app_and_is_the_limit(
        make_client, wait_run, project_dir):
    client, _model = make_client([*looking(6), text("never said")])
    assert client.get("/api/steps").json() == {"max_steps": 25}
    for wrong in (4, 201, "9"):
        assert client.put("/api/steps", json={"max_steps": wrong}, headers=OWN).status_code == 422
    assert client.put("/api/steps", json={"max_steps": 5}).status_code == 403  # (the app's page)
    assert client.put("/api/steps", json={"max_steps": 5}, headers=OWN).json() == {"max_steps": 5}
    assert client.get("/api/steps").json() == {"max_steps": 5}
    cid, run_id = begin(client, project_dir)
    snap = wait_run(client, cid, run_id, timeout=20)
    assert (agent(snap, "Lead")["error"], len(_model.calls)) == ("step_limit", 5)


def test_a_team_the_user_gave_the_chat_and_the_lead_did_not_open_is_said_once(
        make_client, wait_run, project_dir):
    client, model = make_client({
        "Lead": [spawn("Web app lead", "build the page", "l1"), text("done"),
                 text("Backend had nothing to do")],
        "Web app lead": [spawn("Coder", "build the page", "c1"), text("web done")],
        "Coder": [step(call("write_file", {"path": "page.html", "content": "<p>hi</p>\n"}, "f1")),
                  text("built")],
    })
    cid, run_id = two_teams(client, project_dir)
    snap = wait_run(client, cid, run_id, timeout=20)
    told = [m["content"] for m in model.calls_of["Lead"][-1]
            if f"{API} was not opened" in str(m["content"])]
    assert len(told) == 1 and f"{API} was not opened: open {API} lead with spawn_agent, or say " \
        "why not" in told[0]
    assert agent(snap, "Lead")["status"] == "completed"
    assert [m["content"] for m in snap["messages"] if m["role"] == "koloni"] == [
        f"{API} was not opened in this turn."]


def test_the_orchestrators_steps_grow_with_its_teams(make_client, wait_run, project_dir):
    # 3 + 8 for each of two teams with a coordinator: twelve steps fit, where 3 would not.
    client, _model = make_client([*looking(12), text("looked myself")])
    runner = client.app.state.runner
    runner.settings = replace(runner.settings, max_steps=3)
    cid, run_id = two_teams(client, project_dir)
    snap = wait_run(client, cid, run_id, timeout=20)
    assert agent(snap, "Lead")["status"] == "completed", agent(snap, "Lead")["error"]


# B-413 (REA's R219-R220, PLAN-T112-05: three teams, a room, messages between leads; the
# Orchestrator ended on `step_limit` after the work was in the project, "at 25"): it had the
# app's 25 and 8 for each of its three led teams - 49 - on a session's path as on a step's.
THREE = ("Backend / API", "Web app", "Docs")


def three_teams(client, project_dir, mode="ask"):
    teams = teams_of(client)
    return begin(client, project_dir, mode=mode, teams_mode="manual",
                 teams=[{"team_id": teams[name]["id"]} for name in THREE])


def looks(n):  # (each another call: none is the same as one before it)
    return [step(call("list_dir", {"path": f"nowhere{i}"}, f"k{i}")) for i in range(n)]


def test_the_orchestrator_of_three_led_teams_has_25_and_8_for_each(
        make_client, wait_run, project_dir):
    client, model = make_client([*looks(60), text("never said")])
    cid, run_id = three_teams(client, project_dir)
    snap = wait_run(client, cid, run_id, timeout=30)
    assert (agent(snap, "Lead")["error"], len(model.calls)) == ("step_limit", 25 + 3 * 8)


class Looking(ScriptedModel):
    """A CLI session for the Lead: a message and a call of another path, 60 times."""

    session = True

    def __init__(self):
        super().__init__([])
        self.looked = 0

    async def run_session(self, model_id, messages, tools, call_tool, on_text, on_message=None,
                          effort=None, on_live=None):
        for i in range(60):
            await on_text(f"Looking at nowhere{i}.")
            await call_tool("list_dir", json.dumps({"path": f"nowhere{i}"}))
            self.looked += 1
        await on_text("never said")
        return SimpleNamespace(input_tokens=5, output_tokens=1, model=None)


def test_a_session_orchestrator_of_three_led_teams_has_25_and_8_for_each(
        settings_env, wait_run, project_dir):
    cli = Looking()
    with TestClient(create_app(load_settings(settings_env), model=cli),
                    base_url="http://127.0.0.1:8790") as client:
        client.headers["Origin"] = OWN["Origin"]
        cid, run_id = three_teams(client, project_dir)
        snap = wait_run(client, cid, run_id, timeout=30)
    assert (snap["runs"][0]["error"], cli.looked) == ("step_limit", 25 + 3 * 8)
