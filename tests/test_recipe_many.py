"""K-rol-cogul (the user's, 28 Oct): a recipe's role step may draw "at most N" of its role
(`WhoRole.most`, 1 to 5; 1, as before, is left out of what is written). Its lead opens as many as
the work splits into, up to N, in one reply; the step is done once every agent it opened
finished, fewer than N too; one more than N is refused by what the step draws."""

import asyncio
import json
from dataclasses import replace

import pytest
from pydantic import ValidationError

from app import recipe_run
from app.agent import AgentRunner
from app.db.models import ToolCall
from app.model_client import ToolCallRequest
from app.schemas import RecipeStep
from tests.conftest import Gate
from tests.test_chat_flow import text
from tests.test_chat_teams_scenarios import teams_of
from tests.test_parallel import statuses, until
from tests.test_recipe_checks_scenarios import run_of
from tests.test_recipe_run_scenarios import by_call, made, manual, row
from tests.test_recipes_scenarios import graph
from tests.test_recipes_scenarios import step as part
from tests.test_spawn import begin, call, step

OWN = {"Origin": "http://127.0.0.1:8790"}
THREE = step(call("spawn_agent", {"role": "Coder", "task": "do A"}, "s1"),
             call("spawn_agent", {"role": "Tester", "task": "do B"}, "s2"),
             call("spawn_agent", {"role": "Reviewer", "task": "do C"}, "s3"))

BUILD = part("build", "Build it", {"role": "Coder", "most": 2})
TEST = part("test", "Test it", {"role": "Tester"})
WAY = [("start", "build"), ("build", "test"), ("test", "end")]


def opened(state, role="Coder"):
    return recipe_run.opened(state, f"a{len(state['agents'])}", role)


def test_one_is_left_out_of_what_is_written_and_more_only_on_a_role_step():
    assert part("a", "Build it", {"role": "Coder"})["who"] == RecipeStep.model_validate(
        part("a", "Build it", {"role": "Coder", "most": 1})).model_dump(mode="json", by_alias=True)["who"]
    assert RecipeStep.model_validate(BUILD).model_dump(mode="json", by_alias=True)["who"] == {
        "role": "Coder", "most": 2}
    for who in ({"role": "Coder", "most": 0}, {"role": "Coder", "most": 6},
                {"room": ["Coder", "Reviewer"], "most": 2}, {"lead": True, "most": 2}):
        with pytest.raises(ValidationError):
            RecipeStep.model_validate(part("a", "Build it", who))


def test_two_drawn_two_open_and_both_done_go_on():
    state = run_of(graph([BUILD, TEST], WAY))
    assert recipe_run.size(recipe_run.graph_of(state), state["slots"], "build") == 2
    first = opened(state)
    assert recipe_run.has_room(state, "Coder")
    second = opened(state)
    assert not recipe_run.has_room(state, "Coder")  # (a third: "draws 2 agents, and has them")
    first["ok"] = True
    assert not recipe_run.complete(state)  # (the other still works)
    second["ok"] = True
    assert recipe_run.complete(state) and recipe_run.advance(state) == "Next: Test it - open Tester."


def test_one_opened_of_two_drawn_is_done_once_it_finished():
    state = run_of(graph([BUILD, TEST], WAY))
    opened(state)["ok"] = True
    assert recipe_run.complete(state)
    recipe_run.advance(state)
    assert state["at"] == "test" and recipe_run.open_to(state) == ["Tester"]


def test_the_opener_is_told_up_to_how_many_and_how_to_split():
    state = run_of(graph([BUILD, TEST], WAY))
    said = AgentRunner._where("Web app", state)
    assert ("for Coder: it draws 2 agents, 3 in all for the run - up to 2 Coder: where the work "
            "splits into independent parts") in said
    assert "never the same file to two; a small job gets one" in said
    recipe_run.advance(state)  # (a step of one says nothing of it)
    assert "splits" not in AgentRunner._where("Web app", state)


def test_a_step_of_at_most_two_coders_opens_two_at_once_and_refuses_a_third(
        make_client, wait_run, project_dir):
    client, model = make_client({
        "Lead": [step(call("spawn_agent", {"role": "Coder", "task": "a.py"}, "c1"),
                      call("spawn_agent", {"role": "Coder", "task": "b.py"}, "c2"),
                      call("spawn_agent", {"role": "Coder", "task": "c.py"}, "c3")),
                 text("done")],
        "Coder": [text("built a")],
        "Coder 2": [text("built b")],
    })
    web = teams_of(client)["Web app"]
    two = made(client, "Two coders", graph([BUILD], [("start", "build"), ("build", "end")],
                                           ends=({"id": "end", "then": "report"},)))
    cid, run_id = manual(client, project_dir, (web, two))
    snap = wait_run(client, cid, run_id)
    # (Not waited for: the first done at once does not end the step before the others opened.)
    calls = sorted(by_call(snap))
    assert [status for status, _said in calls] == ["failed", "succeeded", "succeeded"]
    assert ("recipe draws 2 agents, and has them: ask for at most 2 in one reply; do this part "
            "yourself or give it to one of them") in calls[0][1]
    state = row(snap)
    assert state["status"] == "done" and state["passes"] == [{"part": "build", "agents": state["agents"]}]
    assert len(state["agents"]) == 2
    # (What the strip counts its "Coder ×2" by: a step of one has none.)
    assert [s.get("draws") for s in state["steps"]] == [{"Coder": 2}, None]
    offered = next(t["function"] for t in model.tool_args[0] if t["function"]["name"] == "spawn_agent")
    assert "up to 2 Coder: where the work splits into independent parts" in offered["description"]


# --- a reply's spawns open together (`AgentRunner._run_tools`) ---------------------------------


def test_three_spawns_of_one_reply_on_a_provider_of_two_open_together_and_the_third_waits_its_place(
        make_client, wait_run, project_dir):
    # (The wait is for the others to be opened, never for a place: none is taken before.)
    a, b = Gate(), Gate()
    client, _model = make_client({
        "Lead": [THREE, text("all done")],
        "Coder": [a.step(text("A done"))], "Tester": [b.step(text("B done"))],
        "Reviewer": [text("C done")],
    })
    local = client.get("/api/providers").json()[0]
    assert client.patch(f"/api/providers/{local['id']}", json={"max_running": 2},
                        headers=OWN).status_code == 200
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_max_parallel=4)
    a.wait_partial()
    b.wait_partial()
    snap = until(client, cid, lambda s: statuses(s).get("Reviewer") == "queued")
    assert (statuses(snap)["Coder"], statuses(snap)["Tester"]) == ("running", "running")
    a.release()
    b.release()
    assert set(statuses(wait_run(client, cid, run_id)).values()) == {"completed"}


def test_stop_while_a_spawn_waits_for_its_siblings_to_open_ends_the_turn(
        make_client, wait_run, project_dir, monkeypatch):
    client, _model = make_client({
        "Lead": [THREE, text("all done")],
        "Coder": [text("A done")], "Tester": [text("B done")], "Reviewer": [text("C done")],
    })
    runner = client.app.state.runner
    kept_first = runner._kept_first

    async def held(ctx, call_id, args):  # (the Tester's opening never gets past its checks)
        if args.get("role") == "Tester":
            await asyncio.sleep(3600)
        await kept_first(ctx, call_id, args)

    monkeypatch.setattr(runner, "_kept_first", held)
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_max_parallel=4)
    snap = until(client, cid, lambda s: {"Coder", "Reviewer"} <= set(statuses(s)))
    assert "Tester" not in statuses(snap)
    assert client.post(f"/api/runs/{run_id}/cancel").status_code == 202
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "cancelled"
    # Opened, held for the Tester, and stopped there: neither started its work.
    assert statuses(snap)["Coder"] != "completed" and statuses(snap)["Reviewer"] != "completed"
    assert all(status not in ("running", "queued", "proposed")
               for status in statuses(snap).values()), statuses(snap)


def test_an_answer_of_the_same_agent_with_spawns_of_its_own_does_not_strand_a_held_reply(
        make_client, wait_run, project_dir, monkeypatch):
    # (Review of K-rol-cogul: held by agent, the answer's two spawns took the reply's place.)
    client, _model = make_client({
        "Lead": [THREE, text("all done")],
        "Coder": [text("A done")], "Tester": [text("B done")], "Reviewer": [text("C done")],
    })
    runner = client.app.state.runner
    kept_first = runner._kept_first

    async def answer_first(ctx, call_id, args):
        if args.get("role") == "Tester":  # (while the Coder and the Reviewer wait for it)
            with runner._factory() as session:
                message_id = session.get_one(ToolCall, call_id).message_id
            asked = [ToolCallRequest(f"x{n}", "spawn_agent", json.dumps(
                {"role": "Coder", "task": "more"})) for n in (1, 2)]
            # (Refused: an answer opens nobody - but held by agent, its group was gone.)
            await runner._run_tools(replace(ctx, answering=True, own_calls=set()), None,
                                    message_id, asked)
        await kept_first(ctx, call_id, args)

    monkeypatch.setattr(runner, "_kept_first", answer_first)
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_max_parallel=4)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", (snap["runs"][0]["error"], statuses(snap))
    assert {statuses(snap)[name] for name in ("Coder", "Tester", "Reviewer")} == {"completed"}
