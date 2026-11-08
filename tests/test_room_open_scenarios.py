"""Slice 29b-2's acceptance set: an agent opens a room. Written before the code.

The lead may call a meeting: `open_room` with a goal and two to four members. Its members are
opened as sub-agents are, under the same rule for asking the user; a member the user turns
down leaves the room unopened. The one that opened it waits until it is over and is given its
record - how it ended, and what came of each item - and then goes on. Another role may open a
room only if the user gives it the tool; nobody opens one inside a room. A room never asks for
more than the conversation lets one spend. Inside a room a member may invite one more, up to
four.
"""

import json

import pytest

from app import tools

if not hasattr(tools, "OPEN_ROOM_SCHEMA"):  # written before the code: skipped until it exists
    pytest.skip("slice 29b-2 is not built yet", allow_module_level=True)

from tests.test_chat_flow import text  # noqa: E402
from tests.test_parallel import until  # noqa: E402
from tests.test_room_scenarios import (  # noqa: E402
    LONG,
    ORIGIN,
    add,
    edit,
    finish,
    items,
    post,
    posts,
    take,
    wait,
)
from tests.test_spawn import call, names, step  # noqa: E402


def open_room(goal="Fix the greeting together", members=("Coder", "Reviewer"), id="o",
              follow=False, **more):
    """The call; `follow` (K-oda-lead): its opener follows the room, as when it is left out -
    these tests' leads mostly only wait for the record, as before."""
    return step(call("open_room", {"goal": goal, "with": list(members), **more,
                                   **({} if follow else {"follow": False})}, id))


def begin(make_client, project_dir, scripts, mode="full_auto", **settings):
    """A conversation whose lead is scripted by `scripts["Lead"]`; returns the client, the
    model, the conversation's id and the run's."""
    client, model = make_client(scripts)
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    patched = client.patch(f"/api/conversations/{cid}",
                           json={"permission_mode": mode, **settings})
    assert patched.status_code == 200, patched.text
    posted = client.post(f"/api/conversations/{cid}/messages", json={"content": "fix it"})
    return client, model, cid, posted.json()["run"]["id"]


def lead_calls(snap, tool="open_room"):
    lead = next(a["id"] for a in snap["agents"] if a["name"] == "Lead")
    return [t for t in snap["tool_calls"] if t["agent_id"] == lead and t["name"] == tool]


def calls_of(snap, agent_name, tool):
    wanted = [a["id"] for a in snap["agents"] if a["name"] == agent_name]
    return [t for t in snap["tool_calls"] if t["agent_id"] in wanted and t["name"] == tool]


WORK = {
    "Coder": [step(add("Change the greeting", ["hello.py"], "a1"), take(1, "t1")),
              step(edit("hi", "yo")),
              step(finish(1, "hello.py prints yo", "f1")),
              text("My part is done.")],
    "Reviewer": [step(add("Review the greeting", id="a2"), take(2, "t2")),
                 step(finish(2, "It prints yo, as asked.", "f2")),
                 text("Looked at it: fine.")],
}


# --- the lead calls a meeting ------------------------------------------------------------------


def test_the_lead_opens_a_room_waits_for_it_and_is_given_its_record(
    make_client, wait_run, project_dir
):
    client, model, cid, run_id = begin(make_client, project_dir, {
        "Lead": [open_room(), text("The room fixed it: the greeting says yo.")], **WORK})
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]

    (room,) = snap["rooms"]
    assert room["goal"] == "Fix the greeting together"
    assert [m["role"] for m in room["members"]] == ["Coder", "Reviewer"]
    assert (room["status"], room["outcome"]) == ("ended", "agreed")
    assert items(snap) == [(1, "Change the greeting", "done", "Coder"),
                           (2, "Review the greeting", "done", "Reviewer")]
    # the project has the copy, as after any room (full auto: nobody is asked)
    assert (project_dir / "hello.py").read_text(encoding="utf-8") == "print('yo')\n"

    # the lead waited for the room and was given its record as the tool's answer
    (opened,) = lead_calls(snap)
    assert opened["status"] == "succeeded", opened["result"]
    for said in ("every member's work was over", "Change the greeting", "hello.py prints yo",
                 "It prints yo, as asked."):
        assert said in opened["result"], opened["result"]
    # and spoke only after it was over: its last step was asked with the record in hand
    assert "It prints yo, as asked." in json.dumps(model.calls_of["Lead"][-1])
    # (Under the answer, KOLONİ's line on where the work is: B-205.)
    assert [m["content"] for m in snap["messages"][-2:]] == [
        "The room fixed it: the greeting says yo.", "In the project: hello.py (+1 −1)."]


def test_the_lead_is_offered_open_room_and_a_sub_agent_only_if_the_user_gives_it(
    make_client, wait_run, project_dir
):
    client, model, cid, run_id = begin(make_client, project_dir, {
        "Lead": [step(call("spawn_agent", {"role": "Coder", "task": "look"}, "s")), text("ok")],
        "Coder": [text("looked")]})
    wait_run(client, cid, run_id, timeout=LONG)
    lead_offered, coder_offered = names(model.tool_args[0]), names(model.tool_args[1])
    assert "open_room" in lead_offered
    assert "open_room" not in coder_offered

    coder = next(r for r in client.get("/api/roles").json() if r["name"] == "Coder")
    granted = client.patch(f"/api/roles/{coder['id']}",
                           json={"tools": [*coder["tools"], "open_room"]})
    assert granted.status_code == 200, granted.text
    client, model, cid, run_id = begin(make_client, project_dir, {
        "Lead": [step(call("spawn_agent", {"role": "Coder", "task": "look"}, "s")), text("ok")],
        "Coder": [text("looked")]})
    wait_run(client, cid, run_id, timeout=LONG)
    assert "open_room" in names(model.tool_args[1])


# --- asked as sub-agents are -------------------------------------------------------------------


def test_its_members_are_asked_for_as_sub_agents_are(make_client, wait_run, project_dir):
    client, _model, cid, run_id = begin(make_client, project_dir, {
        "Lead": [open_room(), text("Done.")], **WORK}, spawn_approval="always")
    snap = until(client, cid, lambda s: len([a for a in s["agents"]
                                             if a["status"] == "proposed"]) == 2, timeout=LONG)
    assert snap["runs"][0]["status"] == "waiting_approval"
    assert snap["rooms"] == [] or snap["rooms"][0]["status"] == "sharing"
    for member in [a for a in snap["agents"] if a["status"] == "proposed"]:
        assert client.post(f"/api/agents/{member['id']}/approve").status_code == 200
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["rooms"][0]["outcome"] == "agreed"
    assert lead_calls(snap)[0]["status"] == "succeeded"


def test_a_member_turned_down_leaves_the_room_unopened_and_the_lead_is_told(
    make_client, wait_run, project_dir
):
    client, _model, cid, run_id = begin(make_client, project_dir, {
        "Lead": [open_room(), text("Understood, I will do it myself.")], **WORK},
        mode="ask")                                  # Ask: sub-agents are asked for
    snap = until(client, cid, lambda s: len([a for a in s["agents"]
                                             if a["status"] == "proposed"]) == 2, timeout=LONG)
    first, second = [a for a in snap["agents"] if a["status"] == "proposed"]
    assert client.post(f"/api/agents/{first['id']}/approve").status_code == 200
    assert client.post(f"/api/agents/{second['id']}/reject").status_code == 200
    snap = wait_run(client, cid, run_id, timeout=LONG)
    (opened,) = lead_calls(snap)
    assert opened["status"] == "failed" and "turned down" in opened["result"], opened["result"]
    # nobody worked: no item, no post, no copy, nothing changed
    assert all(r["status"] != "working" for r in snap["rooms"])
    assert snap["room_items"] == [] and snap["merges"] == []
    assert (project_dir / "hello.py").read_text(encoding="utf-8") == "print('hi')\n"
    assert snap["runs"][0]["status"] == "completed"


# --- limits ------------------------------------------------------------------------------------


def test_nobody_opens_a_room_inside_a_room(make_client, wait_run, project_dir):
    client, _model, cid, run_id = begin(make_client, project_dir, {
        "Lead": [open_room(), text("ok")],
        "Coder": [open_room("Another meeting", ("Tester", "Reviewer"), "inner"),
                  text("I am done.")],
        "Reviewer": [text("I am done.")]})
    snap = wait_run(client, cid, run_id, timeout=LONG)
    (inner,) = calls_of(snap, "Coder", "open_room")
    assert inner["status"] == "failed" and "room" in inner["result"]
    assert len(snap["rooms"]) == 1


def test_one_room_a_turn(make_client, wait_run, project_dir):
    client, _model, cid, run_id = begin(make_client, project_dir, {
        "Lead": [open_room(id="o1"), open_room("Again", id="o2"), text("ok")],
        "Coder": [text("Done."), text("Never.")],
        "Reviewer": [text("Done."), text("Never.")]})
    snap = wait_run(client, cid, run_id, timeout=LONG)
    first, second = lead_calls(snap)
    assert first["status"] == "succeeded" and second["status"] == "failed"
    assert len(snap["rooms"]) == 1


# (R185: a conversation's rooms have no token limit by default - the agent's own, where it sets one.)
@pytest.mark.parametrize("asked,expected", [
    ({"posts": 1000, "tokens": 10**9, "minutes": 999}, {"posts": 40, "tokens": 10**9,
                                                         "minutes": 30}),
    ({"posts": 5}, {"posts": 5, "tokens": None, "minutes": 30}),
    ({}, {"posts": 40, "tokens": None, "minutes": 30}),
])
def test_a_room_asks_for_no_more_than_the_conversation_lets_one_spend(
    make_client, wait_run, project_dir, asked, expected
):
    more = {"budget": asked} if asked else {}
    client, _model, cid, run_id = begin(make_client, project_dir, {
        "Lead": [open_room(**more), text("ok")],
        "Coder": [text("Done.")], "Reviewer": [text("Done.")]})
    snap = wait_run(client, cid, run_id, timeout=LONG)
    budget = snap["rooms"][0]["budget"]
    assert {k: budget[k] for k in expected} == expected


def big(*calls, content=""):
    """A step as a real one costs: some 8,500 tokens with its context (B-414, measured live)."""
    return step(*calls, content=content, i=8000, o=500)


def test_a_room_asked_for_with_5000_tokens_is_given_the_least_and_its_members_post(
    make_client, wait_run, project_dir
):
    """B-414 (live): a room asked for with 5000 tokens ended on them with no post - one member's
    first step alone came to some 8,500. Its ask is raised to the least a room is given."""
    client, model, cid, run_id = begin(make_client, project_dir, {
        "Lead": [open_room(budget={"tokens": 5000, "posts": 15, "minutes": 10}), text("ok")],
        "Coder": [big(content="Nothing to add."), big(post("result", "It prints hi.", "p1")),
                  text("Done.")],
        "Reviewer": [big(content="Nothing to add."), big(post("result", "Fine as it is.", "p2")),
                     text("Done.")]})
    snap = wait_run(client, cid, run_id, timeout=LONG)
    (room,) = snap["rooms"]
    assert room["budget"] == {"posts": 15, "tokens": 60_000, "minutes": 10}
    assert room["outcome"] != "budget" and room["spent"]["posts"] >= 1, room
    assert "60000" in json.dumps(model.tool_args[0])  # (the Lead is told the least)


@pytest.mark.parametrize("settings,given", [
    ({"room_min_tokens": 30_000}, 30_000),                    # the user's own least
    ({"room_tokens": 20_000}, 20_000),                        # below the least: the most wins
    ({"room_min_tokens": None}, 5000),                        # none: as asked
])
def test_a_rooms_least_tokens_is_the_users_and_never_past_its_most(
    make_client, wait_run, project_dir, settings, given
):
    client, _model, cid, run_id = begin(make_client, project_dir, {
        "Lead": [open_room(budget={"tokens": 5000}), text("ok")],
        "Coder": [text("Done.")], "Reviewer": [text("Done.")]}, **settings)
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["rooms"][0]["budget"]["tokens"] == given
    assert snap["conversation"]["room_min_tokens"] == settings.get("room_min_tokens", 60_000)


@pytest.mark.parametrize("members", [("Coder",),
                                     ("Coder", "Reviewer", "Tester", "Debugger", "Docs writer",
                                      "Refactorer", "UI designer"),
                                     ("Nobody", "Coder")])
def test_two_to_six_members_of_known_roles(make_client, wait_run, project_dir, members):
    client, _model, cid, run_id = begin(make_client, project_dir, {
        "Lead": [open_room(members=members), text("ok")]})
    snap = wait_run(client, cid, run_id, timeout=LONG)
    (opened,) = lead_calls(snap)
    assert opened["status"] == "failed"
    assert snap["rooms"] == []


# --- inviting one more -------------------------------------------------------------------------


def test_a_member_invites_one_more_and_never_past_six(make_client, wait_run, project_dir):
    # (R178, the user: more than four when needed - five open, one invited, the next refused.)
    client, _model, cid, run_id = begin(make_client, project_dir, {
        "Lead": [open_room(members=("Coder", "Reviewer", "Docs writer", "Debugger", "Refactorer")),
                 text("ok")],
        "Coder": [step(call("invite_to_room", {"role": "Tester", "why": "run the tests"}, "i1")),
                  step(call("invite_to_room", {"role": "Reviewer"}, "i2")),
                  wait(), text("Done.")],
        "Reviewer": [text("Done.")], "Docs writer": [text("Done.")],
        "Debugger": [text("Done.")], "Refactorer": [text("Done.")],
        "Tester": [text("Ran them: green.")]})
    snap = wait_run(client, cid, run_id, timeout=LONG)
    invited, past_six = calls_of(snap, "Coder", "invite_to_room")
    assert invited["status"] == "succeeded", invited["result"]
    assert past_six["status"] == "failed" and "six members at most" in past_six["result"]
    room = snap["rooms"][0]
    assert [m["role"] for m in room["members"]] == ["Coder", "Reviewer", "Docs writer", "Debugger",
                                                  "Refactorer", "Tester"]
    assert ("done", "Tester", "Ran them: green.") in posts(snap)


def test_the_user_ending_the_room_hands_the_lead_its_record(make_client, wait_run, project_dir):
    client, _model, cid, run_id = begin(make_client, project_dir, {
        "Lead": [open_room(), text("The user ended it; here is where it stood.")],
        "Coder": [text("Nothing to add."), wait(), text("Done.")],
        "Reviewer": [text("Nothing to add."), wait(), text("Done.")]})
    snap = until(client, cid, lambda s: s["rooms"] and s["rooms"][0]["status"] == "working",
                 timeout=LONG)
    assert client.post(f"/api/rooms/{snap['rooms'][0]['id']}/end").status_code == 200
    snap = wait_run(client, cid, run_id, timeout=LONG)
    (opened,) = lead_calls(snap)
    assert opened["status"] == "succeeded" and "the user ended it" in opened["result"]
    assert snap["messages"][-1]["content"] == "The user ended it; here is where it stood."


def test_a_room_past_what_the_turn_may_still_open_is_refused_up_front(
        make_client, wait_run, project_dir):
    # R178 review: with one agent opened already, a room of six failed only at its sixth member.
    client, _model, cid, run_id = begin(make_client, project_dir, {
        "Lead": [step(call("spawn_agent", {"role": "Coder", "task": "look"}, "s1")),
                 open_room(members=("Coder", "Reviewer", "Tester")), text("ok")],
        "Coder": [text("looked")]}, spawn_max_agents=3)
    snap = wait_run(client, cid, run_id, timeout=LONG)
    (opened,) = lead_calls(snap)
    assert opened["status"] == "failed" and opened["result"].startswith(
        "error: this turn may open 2 more agents; the room needs 3"), opened["result"]
    assert snap["rooms"] == []
