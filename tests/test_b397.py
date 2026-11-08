"""B-397 (REA's R191, PLAN-T81-05: the Docs lead, waiting for Data's script, spent 33 steps reading
and died at its step limit, with no card): a team waits for another with wait_for_team, spending
no steps; a sub-agent at its step limit with nothing kept asks the user Continue / Stop here; its
opener is told its part is not done."""

import asyncio
import time
from dataclasses import replace
from datetime import datetime

from app import team_requests
from app.agent.words import TEAM_STOPPED
from tests.test_chat_flow import text
from tests.test_chat_teams_scenarios import teams_of
from tests.test_lead_decides import says
from tests.test_parallel import until
from tests.test_recipe_ends_scenarios import SCRIPTS
from tests.test_recipe_run_scenarios import OWN, READY, answer, asked, manual, one_step
from tests.test_spawn import begin, call, role_id, spawn, step
from tests.test_team_requests_scenarios import API, LEADS, WEB, agent, calls_of, two_teams


def looking(n, last=""):
    return [step(call("list_dir", {}, f"k{i}"), content=last if i == n - 1 else "")
            for i in range(n)]


def after(model, name, result, then=1.0):
    """A step that comes once `name` took its first step, and `then` seconds later."""
    async def held(on_delta):
        while name not in model.calls_of:
            await asyncio.sleep(0.01)
        await asyncio.sleep(then)
        await on_delta(result.content)  # (what it says is what it streams)
        return result
    return held


def spent(call_):
    return (datetime.fromisoformat(call_["ended_at"])
            - datetime.fromisoformat(call_["started_at"])).total_seconds()


# --- B-397 (a): wait_for_team ----------------------------------------------------------------


def test_a_lead_waits_for_another_team_with_one_call_and_wakes_when_it_ends(
        make_client, wait_run, project_dir):
    client, model = make_client({
        "Lead": [LEADS, text("done")],
        "Web app lead": [step(call("wait_for_team", {"team": API}, "w1")), text("web done")],
        "Backend / API lead": [text("api done: scripts/stats.py is there")],
    })
    model.by_agent["Backend / API lead"][0] = after(model, "Web app lead", text(
        "api done: scripts/stats.py is there"))
    cid, run_id = two_teams(client, project_dir)
    snap = wait_run(client, cid, run_id, timeout=20)
    (waited,) = calls_of(snap, "wait_for_team", "Web app lead")
    assert waited["status"] == "succeeded", waited["result"]
    assert waited["result"].startswith(f"{API} has ended its work in this turn (completed). "
                                       f"{API} lead: api done: scripts/stats.py is there")
    # It waited (the other lead ended a second after its call), in one step: no step was spent.
    assert spent(waited) >= 0.5
    assert len(model.calls_of["Web app lead"]) == 2
    # Taught in its brief, offered beside request_work.
    assert team_requests.WAIT_TEAMS in agent(snap, "Web app lead")["task"]


def test_the_wait_ends_after_its_time_and_says_who_is_still_at_work(
        make_client, wait_run, project_dir, monkeypatch):
    monkeypatch.setattr(team_requests, "WAIT_SECONDS", 1)
    client, model = make_client({
        "Lead": [LEADS, text("done")],
        "Web app lead": [step(call("wait_for_team", {"team": API}, "w1")), text("went on")],
        "Backend / API lead": [text("api done")],
    })
    # (Backend ends only once the Web app lead's wait is over: its second step.)
    async def late(on_delta):
        while len(model.calls_of.get("Web app lead", [])) < 2:
            await asyncio.sleep(0.01)
        await on_delta("api done")
        return text("api done")
    model.by_agent["Backend / API lead"][0] = late
    cid, run_id = two_teams(client, project_dir)
    snap = wait_run(client, cid, run_id, timeout=20)
    (waited,) = calls_of(snap, "wait_for_team", "Web app lead")
    assert waited["result"].startswith(f"{API} is still at work after 0 minutes ({API} lead ")
    assert "Wait again, go on without it" in waited["result"]


# --- B-397 (b): the card at a step limit ----------------------------------------------------


def test_a_sub_agent_at_its_step_limit_asks_the_user_and_stop_here_ends_it(
        make_client, wait_run, project_dir):
    client, model = make_client([spawn("Researcher"), *looking(5, "still looking"),
                                 text("gave up")])
    runner = client.app.state.runner
    runner.settings = replace(runner.settings, max_steps=5)
    cid, run_id = begin(client, project_dir)
    snap = until(client, cid, asked, timeout=20)
    card = asked(snap)
    assert card["question"].startswith("Researcher came to its limit of 5 steps before its work "
                                       "was done. Continue gives it 25 more")
    assert card["options"] == ["Continue (+25 steps)", "Stop here"]
    answer(client, card, "Stop here")
    snap = wait_run(client, cid, run_id, timeout=20)
    kid = snap["agents"][1]
    assert (kid["status"], kid["error"], kid["steps_given"]) == ("failed", "step_limit", 0)
    result = model.calls[-1][-1]["content"]
    assert result.startswith("Researcher stopped after 5 steps.") and "still looking" in result
    # (c) its opener is told its part is not done, and what it can do about it.
    assert "Its part is not done, and the user chose Stop here on its card" in result
    assert snap["runs"][0]["status"] == "completed"


def test_continue_on_the_card_gives_it_more_steps_and_it_goes_on_where_it_is(
        make_client, wait_run, project_dir):
    client, model = make_client({
        "Lead": [spawn("Researcher"), text("done")],
        "Researcher": [*looking(4), text("found it")],
    })
    runner = client.app.state.runner
    runner.settings = replace(runner.settings, max_steps=3)
    cid, run_id = begin(client, project_dir)
    card = asked(until(client, cid, asked, timeout=20))
    answer(client, card, "Continue (+25 steps)")
    snap = wait_run(client, cid, run_id, timeout=20)
    kid = agent(snap, "Researcher")
    assert (kid["status"], kid["steps_given"]) == ("completed", 25)
    # One job: it went on from its 3 steps, told so - not opened again.
    assert len(model.calls_of["Researcher"]) == 5
    assert "KOLONİ: you were given 25 more steps" in str(model.calls_of["Researcher"][3])
    assert any(str(m["content"]).startswith("Researcher finished.")
               for m in model.calls_of["Lead"][-1])
    assert [m["content"] for m in snap["messages"] if m["role"] == "agent" and (
        m["from_agent_id"] is None) and "more steps" in m["content"]] == [
        "Researcher gets 25 more steps (the user's Continue)."]


def test_after_the_users_stop_here_the_opener_is_told_so_and_cannot_tell_it_to_go_on(
        make_client, wait_run, project_dir):
    client, model = make_client({
        "Lead": [spawn("Researcher"),
                 step(call("message_agent", {"to": "Researcher", "message": "go on"}, "m1")),
                 text("left undone: the rest of the search")],
        "Researcher": [*looking(3), text("never said")],
    })
    runner = client.app.state.runner
    runner.settings = replace(runner.settings, max_steps=3)
    cid, run_id = begin(client, project_dir)
    answer(client, asked(until(client, cid, asked, timeout=20)), "Stop here")
    snap = wait_run(client, cid, run_id, timeout=20)
    (spawned,) = [t for t in snap["tool_calls"] if t["name"] == "spawn_agent"]
    assert "the user chose Stop here on its card: do not tell it to go on" in spawned["result"]
    (go_on,) = [t for t in snap["tool_calls"] if t["name"] == "message_agent"]
    assert go_on["status"] == "failed" and go_on["result"].startswith(
        "Researcher is not told to go on: the user chose Stop here")
    assert len(model.calls_of["Researcher"]) == 3


def test_a_teams_coordinator_running_its_recipe_gets_the_card_and_goes_on_in_its_job(
        make_client, wait_run, project_dir):
    # B-397's own case: a recipe's coordinator keeps no copy of its own (the recipe's copy is
    # the turn's), so nothing else offers it Continue. 3 + 4 for its one-step recipe: 7 steps.
    client, model = make_client({
        "Lead": [step(spawn("Web app lead", "the page", "l1").tool_calls[0],
                      spawn("Docs lead", "the words", "l2").tool_calls[0]), text("all done")],
        **SCRIPTS,
        "Web app lead": [*looking(7), spawn("Coder", "build a.py", "c"), text("web done")],
    })
    runner = client.app.state.runner
    runner.settings = replace(runner.settings, max_steps=3)
    teams = teams_of(client)
    cid, run_id = manual(client, project_dir,
                         (teams["Web app"], one_step(client, "Just build", "Coder")),
                         (teams["Docs"], one_step(client, "Just write", "Docs writer")))
    card = asked(until(client, cid, asked, timeout=20))
    assert card["question"].startswith("Web app lead came to its limit of 7 steps")
    answer(client, card, "Continue (+25 steps)")
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"], timeout=20)
    lead = agent(snap, "Web app lead")
    assert (lead["status"], lead["steps_given"]) == ("completed", 25)
    assert len(model.calls_of["Web app lead"]) == 9  # (one job: not opened again)
    answer(client, asked(snap), "Take in")
    wait_run(client, cid, run_id)


# --- the review's: once a turn, its role's limit, the month's budget, a stop ------------------


def go_on(id):
    return step(call("message_agent", {"to": "Researcher", "message": "go on"}, id))


def results(snap, name):
    return [(t["status"], t["result"]) for t in snap["tool_calls"] if t["name"] == name]


def at_steps(client, steps):
    client.app.state.runner.settings = replace(client.app.state.runner.settings, max_steps=steps)


def test_at_full_auto_the_orchestrators_continue_is_once_and_no_go_on_comes_after_it(
        make_client, wait_run, project_dir):
    # 3 steps, the Orchestrator's Continue (+2), 2 more: its go on after that is refused.
    client, model = make_client({
        "Lead": [spawn("Researcher"), says("Continue (+2 steps)", "It is nearly there."),
                 go_on("m1"), text("left undone: the rest")],
        "Researcher": [*looking(5), text("never said")],
    })
    at_steps(client, 3)
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    assert client.patch(f"/api/projects/{pid}", json={"continue_steps": 2},
                        headers=OWN).status_code == 200
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    snap = wait_run(client, cid, run_id, timeout=20)
    (card,) = snap["questions"]
    assert (card["answer"], card["lead_why"]) == ("Continue (+2 steps)", "It is nearly there.")
    ((_s, spawned),) = results(snap, "spawn_agent")
    assert "it had more steps once in this turn already: do not tell it to go on" in spawned
    assert "with message_agent" not in spawned
    ((status, said),) = results(snap, "message_agent")
    assert status == "failed" and said.startswith(
        "Researcher is not told to go on: it stopped at its step limit, and had 2 more steps "
        "once in this turn already"), said
    assert len(model.calls_of["Researcher"]) == 5


def test_a_go_on_by_message_after_a_step_limit_is_the_agents_once_in_the_turn(
        make_client, wait_run, project_dir):
    # The Orchestrator ends it on its card; a go on then runs once - the second is refused.
    client, model = make_client({
        "Lead": [spawn("Researcher"), says("Stop here", "Enough found."), go_on("m1"),
                 go_on("m2"), text("left undone: the rest")],
        "Researcher": [*looking(6), text("never said")],
    })
    at_steps(client, 3)
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    snap = wait_run(client, cid, run_id, timeout=20)
    ((_s, spawned),) = results(snap, "spawn_agent")
    assert "tell it to go on with message_agent" in spawned  # (no more steps yet: it may)
    (first, second) = results(snap, "message_agent")
    assert first[0] == "failed" and first[1].startswith("Researcher stopped after 3 steps.")
    assert "it had more steps once in this turn already" in first[1]
    assert second[0] == "failed" and second[1].startswith(
        "Researcher is not told to go on: it stopped at its step limit, and had 3 more steps "
        "once in this turn already"), second[1]
    assert len(model.calls_of["Researcher"]) == 6


def test_continue_gives_no_more_than_its_role_has_left(make_client, wait_run, project_dir):
    # The role lets it take 5, the app 3: Continue gives the 2 left, not the project's 25.
    client, model = make_client({
        "Lead": [spawn("Researcher"), text("done")],
        "Researcher": [*looking(5), text("never said")],
    })
    at_steps(client, 3)
    assert client.patch(f"/api/roles/{role_id(client, 'Researcher')}", json={"max_steps": 5},
                        headers=OWN).status_code == 200
    cid, run_id = begin(client, project_dir)
    card = asked(until(client, cid, asked, timeout=20))
    assert card["options"] == ["Continue (+2 steps)", "Stop here"]
    answer(client, card, "Continue (+2 steps)")
    snap = wait_run(client, cid, run_id, timeout=20)
    kid = agent(snap, "Researcher")
    assert (kid["steps_given"], kid["error"]) == (2, "stopped after the 5 steps it was given")
    assert len(model.calls_of["Researcher"]) == 5


def test_no_card_where_its_role_has_no_step_left(make_client, wait_run, project_dir):
    client, model = make_client({
        "Lead": [spawn("Researcher"), text("done")],
        "Researcher": [*looking(3), text("never said")],
    })
    at_steps(client, 3)
    assert client.patch(f"/api/roles/{role_id(client, 'Researcher')}", json={"max_steps": 3},
                        headers=OWN).status_code == 200
    cid, run_id = begin(client, project_dir)
    snap = wait_run(client, cid, run_id, timeout=20)
    assert snap["questions"] == [] and len(model.calls_of["Researcher"]) == 3


def test_over_the_months_budget_the_orchestrator_does_not_answer_continue(
        make_client, wait_run, project_dir, monkeypatch):
    monkeypatch.setattr("app.agent.questions_mixin.over_month", lambda session, project: "over")
    client, model = make_client({
        "Lead": [spawn("Researcher"), text("done")],
        "Researcher": [*looking(3), text("never said")],
    })
    at_steps(client, 3)
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    asked(until(client, cid, asked, timeout=20))
    time.sleep(0.5)  # (the Orchestrator would have answered by now)
    card = asked(until(client, cid, asked))
    assert card["lead_why"] is None and len(model.calls_of["Lead"]) == 1
    answer(client, card, "Stop here")
    snap = wait_run(client, cid, run_id, timeout=20)
    assert agent(snap, "Researcher")["steps_given"] == 0


def test_a_card_closed_by_a_stop_is_not_the_users_stop_here(make_client, wait_run, project_dir):
    client, model = make_client({
        "Lead": [spawn("Researcher"), text("done")],
        "Researcher": [*looking(3), text("never said")],
    })
    runner = client.app.state.runner
    at_steps(client, 3)
    cid, run_id = begin(client, project_dir)
    kid = agent(until(client, cid, asked, timeout=20), "Researcher")
    client.portal.call(runner._halt, run_id, [kid["id"]], TEAM_STOPPED)
    snap = wait_run(client, cid, run_id, timeout=20)
    ((_s, spawned),) = results(snap, "spawn_agent")
    assert "the user chose Stop here" not in spawned


def test_stop_team_ends_a_wait_for_team(make_client, wait_run, project_dir):
    client, model = make_client({
        "Lead": [LEADS, text("done")],
        "Web app lead": [step(call("wait_for_team", {"team": API}, "w1")), text("never said")],
        "Backend / API lead": [text("api done")],
    })
    runner = client.app.state.runner

    async def late(on_delta):  # (Backend ends once the waiter was stopped)
        while not runner._halted:
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.5)
        return text("api done")
    model.by_agent["Backend / API lead"][0] = late
    cid, run_id = two_teams(client, project_dir)
    until(client, cid, lambda _s: runner._waiting_on, timeout=20)
    client.portal.call(runner._halt, run_id, list(runner._waiting_on), TEAM_STOPPED)
    snap = wait_run(client, cid, run_id, timeout=20)
    (waited,) = calls_of(snap, "wait_for_team", "Web app lead")
    assert waited["result"] == team_requests.STOPPED_WAITING.format(why=TEAM_STOPPED)
    assert spent(waited) < 5


def test_two_teams_waiting_on_each_other_are_told_at_once(make_client, wait_run, project_dir):
    client, model = make_client({
        "Lead": [LEADS, text("done")],
        "Web app lead": [step(call("wait_for_team", {"team": API}, "w1")), text("web done")],
        "Backend / API lead": [step(call("wait_for_team", {"team": WEB}, "w2")),
                               text("api done")],
    })
    model.by_agent["Backend / API lead"][0] = after(
        model, "Web app lead", step(call("wait_for_team", {"team": WEB}, "w2")))
    cid, run_id = two_teams(client, project_dir)
    snap = wait_run(client, cid, run_id, timeout=20)
    (mutual,) = calls_of(snap, "wait_for_team", "Backend / API lead")
    assert mutual["result"] == team_requests.BOTH_WAIT.format(team=WEB)
    (waited,) = calls_of(snap, "wait_for_team", "Web app lead")
    assert waited["result"].startswith(f"{API} has ended its work in this turn (completed)")


def test_an_agent_waits_at_most_three_times_in_a_turn(
        make_client, wait_run, project_dir, monkeypatch):
    monkeypatch.setattr(team_requests, "WAIT_SECONDS", 0)
    client, model = make_client({
        "Lead": [LEADS, text("done")],
        "Web app lead": [*(step(call("wait_for_team", {"team": API}, f"w{i}")) for i in range(4)),
                         text("went on")],
        "Backend / API lead": [text("api done")],
    })

    async def late(on_delta):  # (Backend ends once the waiter is past its waits)
        while len(model.calls_of.get("Web app lead", [])) < 5:
            await asyncio.sleep(0.01)
        return text("api done")
    model.by_agent["Backend / API lead"][0] = late
    cid, run_id = two_teams(client, project_dir)
    snap = wait_run(client, cid, run_id, timeout=20)
    waits = calls_of(snap, "wait_for_team", "Web app lead")
    assert [w["status"] for w in waits] == ["succeeded"] * 3 + ["failed"]
    assert team_requests.WAITED_ENOUGH in waits[-1]["result"]
