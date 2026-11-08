"""B-398 (REA's R191, PLAN-T81-05: five teams given, Quality never opened, the Orchestrator out of
steps after merging): the Orchestrator is told once of a team the user gave the chat that it did
not open, and so is the user; Settings › The app's "Steps an agent may take" is the app's step
limit (a sub-agent's: B-413 took the Orchestrator's away)."""

from tests.test_chat_flow import text
from tests.test_parallel import until
from tests.test_recipe_run_scenarios import answer, asked
from tests.test_spawn import begin, call, spawn, step
from tests.test_team_requests_scenarios import API, agent, two_teams

OWN = {"Origin": "http://127.0.0.1:8790"}


def looking(n):
    return [step(call("list_dir", {"path": f"d{i}"}, f"k{i}")) for i in range(n)]


def test_steps_an_agent_may_take_is_a_setting_of_the_app_and_is_the_limit(
        make_client, wait_run, project_dir):
    client, _model = make_client([spawn("Researcher"), *looking(6), text("never said")])
    assert client.get("/api/steps").json() == {"max_steps": 25}
    for wrong in (4, 201, "9"):
        assert client.put("/api/steps", json={"max_steps": wrong}, headers=OWN).status_code == 422
    assert client.put("/api/steps", json={"max_steps": 5}).status_code == 403  # (the app's page)
    assert client.put("/api/steps", json={"max_steps": 5}, headers=OWN).json() == {"max_steps": 5}
    assert client.get("/api/steps").json() == {"max_steps": 5}
    cid, run_id = begin(client, project_dir)
    card = asked(until(client, cid, asked, timeout=20))
    assert card["question"].startswith("Researcher came to its limit of 5 steps")
    answer(client, card, "Stop here")
    snap = wait_run(client, cid, run_id, timeout=20)
    assert agent(snap, "Researcher")["error"] == "step_limit"
    researcher = agent(snap, "Researcher")["id"]
    assert sum(t["agent_id"] == researcher for t in snap["tool_calls"]) == 5


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

