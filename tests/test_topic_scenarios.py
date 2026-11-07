"""Topics' acceptance set (slice 18b): going on with the same piece of work.

Written before the code. A message goes on with the conversation's latest topic unless the
user starts a new one; inside a topic the lead can hand more work to an agent that finished
in an earlier turn, and that agent carries on with what it knows. Going on with an agent is
opening an agent: every limit, approval and permission that holds for opening one holds.
"""

import json
import time

import pytest

pytest.importorskip("app.topics")  # written before the code: skipped until it exists

from tests.test_chat_flow import text  # noqa: E402
from tests.test_spawn import call, step  # noqa: E402

ORIGIN = "http://127.0.0.1:8790"
FIRST = "FIRST-TURN make a greeting"
SECOND = "SECOND-TURN go on with it"
THIRD = "THIRD-TURN once more"
OLD_TASK = "OLD-TASK write greet.py that prints hello"
OLD_WORDS = "OLD-WORDS I wrote greet.py"
MORE = "MORE-WORK add a docstring to it"

SPAWN_CODER = step(call("spawn_agent", {"role": "Coder", "task": OLD_TASK}, "s1"))
WRITE = step(call("write_file", {"path": "greet.py", "content": "print('hello')\n"}, "w1"))
GO_ON = step(call("message_agent", {"to": "Coder", "message": MORE}, "m1"))


def setup(make_client, project_dir, scripts, **conversation):
    client, model = make_client(scripts)
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    settings = {"permission_mode": "full_auto", "spawn_approval": "never", **conversation}
    assert client.patch(f"/api/conversations/{cid}", json=settings).status_code == 200
    return client, model, pid, cid


def say(client, cid, content, **more):
    posted = client.post(f"/api/conversations/{cid}/messages", json={"content": content, **more})
    assert posted.status_code in (200, 201, 202), posted.text
    return posted.json()["run"]


def turn(client, wait_run, cid, content, timeout=10.0, **more):
    run = say(client, cid, content, **more)
    return wait_run(client, cid, run["id"], timeout=timeout), run


def agents_of(snap, run_id):
    return [a for a in snap["agents"] if a["run_id"] == run_id]


def calls_of(snap, run_id, name):
    return [(t["status"], t["result"] or "") for t in snap["tool_calls"]
            if t["run_id"] == run_id and t["name"] == name]


def sent_to(model, *having, lacking=()):
    """The requests to the model that hold every text in `having` and none in `lacking`."""
    found = []
    for request in model.calls:
        whole = json.dumps(request, ensure_ascii=False)
        if all(part in whole for part in having) and not any(part in whole for part in lacking):
            found.append(whole)
    return found


def offered(model, having):
    """The message_agent descriptions offered with the requests that hold `having`."""
    found = []
    for request, tools in zip(model.calls, model.tool_args, strict=True):
        if having in json.dumps(request, ensure_ascii=False) and tools:
            found += [t["function"]["description"] for t in tools
                      if t["function"]["name"] == "message_agent"]
    return found


TWO_TURNS = {
    "Lead": [SPAWN_CODER, text("made"), GO_ON, text("done")],
    "Coder": [WRITE, text(OLD_WORDS), text("NEW-WORDS docstring added")],
}


# --- a message goes on with the latest topic -------------------------------------------------


def test_a_message_goes_on_with_the_latest_topic_until_the_user_starts_a_new_one(
    make_client, wait_run, project_dir
):
    client, model, pid, cid = setup(make_client, project_dir, {
        "Lead": [text("one"), text("two"), text("three"), text("four")]})
    snap, first = turn(client, wait_run, cid, "make a greeting\nwith more detail below")
    snap, second = turn(client, wait_run, cid, "and now in Turkish")
    snap, third = turn(client, wait_run, cid, "something else entirely", new_topic=True)
    snap, fourth = turn(client, wait_run, cid, "more of that")
    assert first["topic_id"] == second["topic_id"] != third["topic_id"] == fourth["topic_id"]
    topics = {t["id"]: t for t in snap["topics"]}
    # a topic is named by the first line of what started it
    assert topics[first["topic_id"]]["title"] == "make a greeting"
    assert topics[third["topic_id"]]["title"] == "something else entirely"
    # an earlier topic can be gone back to by naming it
    snap, fifth = turn(client, wait_run, cid, "back to the greeting", topic_id=first["topic_id"])
    assert fifth["topic_id"] == first["topic_id"]
    renamed = client.patch(f"/api/topics/{first['topic_id']}", json={"title": "  Greeting\nwork "})
    assert renamed.status_code == 200 and renamed.json()["title"] == "Greeting work"
    other = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    assert client.post(f"/api/conversations/{other}/messages", json={
        "content": "x", "topic_id": first["topic_id"]}).status_code == 422


# --- an agent carries on in the topic's next turn ----------------------------------------------


def test_the_lead_goes_on_with_the_coder_of_the_turn_before_and_it_knows_what_it_did(
    make_client, wait_run, project_dir
):
    client, model, pid, cid = setup(make_client, project_dir, TWO_TURNS)
    snap, first = turn(client, wait_run, cid, FIRST)
    (old,) = [a for a in agents_of(snap, first["id"]) if a["name"] == "Coder"]
    snap, second = turn(client, wait_run, cid, SECOND)
    assert second["topic_id"] == first["topic_id"]
    # the lead is told who it can go on with, and that it is opening an agent
    (told,) = offered(model, SECOND)[:1]
    assert "Coder" in told and "earlier turn" in told and "counts as opening an agent" in told
    lead, coder = agents_of(snap, second["id"])
    assert (coder["name"], coder["continues_id"], coder["status"]) == (
        "Coder", old["id"], "completed")
    assert lead["continues_id"] is not None        # the lead goes on from the lead before
    # the Coder's request: what it was first asked, what it said then, and the new work
    (request,) = sent_to(model, MORE, lacking=[SECOND])
    assert OLD_TASK in request and OLD_WORDS in request
    assert request.count(OLD_TASK) == 1            # its past is there once, not twice
    ((status, said),) = calls_of(snap, second["id"], "message_agent")
    assert status == "succeeded" and "NEW-WORDS docstring added" in said
    # and its record of the first turn is as it was
    again = next(a for a in snap["agents"] if a["id"] == old["id"])
    assert (again["status"], again["run_id"]) == ("completed", first["id"])


def test_three_turns_are_one_chain(make_client, wait_run, project_dir):
    scripts = {
        "Lead": [SPAWN_CODER, text("made"), GO_ON, text("done"),
                 step(call("message_agent", {"to": "Coder", "message": "LAST-WORK tidy up"}, "m2")),
                 text("done again")],
        "Coder": [WRITE, text(OLD_WORDS), text("MID-WORDS docstring added"), text("tidied")],
    }
    client, model, pid, cid = setup(make_client, project_dir, scripts)
    turn(client, wait_run, cid, FIRST)
    snap, second = turn(client, wait_run, cid, SECOND)
    snap, third = turn(client, wait_run, cid, THIRD)
    middle = next(a for a in agents_of(snap, second["id"]) if a["name"] == "Coder")
    last = next(a for a in agents_of(snap, third["id"]) if a["name"] == "Coder")
    assert last["continues_id"] == middle["id"]    # the newest link, not the first
    (request,) = sent_to(model, "LAST-WORK tidy up", lacking=[THIRD])
    for part in (OLD_TASK, OLD_WORDS, MORE, "MID-WORDS docstring added"):
        assert request.count(part) == 1, part


def test_an_agent_of_another_topic_cannot_be_gone_on_with(make_client, wait_run, project_dir):
    client, model, pid, cid = setup(make_client, project_dir, TWO_TURNS)
    turn(client, wait_run, cid, FIRST)
    snap, second = turn(client, wait_run, cid, SECOND, new_topic=True)
    assert all("Coder" not in told for told in offered(model, SECOND))
    ((status, said),) = calls_of(snap, second["id"], "message_agent")
    assert status == "failed"
    assert [a["name"] for a in agents_of(snap, second["id"])] == ["Lead"]
    assert sent_to(model, MORE, lacking=[SECOND]) == []      # the Coder was asked nothing


def test_a_new_topic_starts_clean_and_a_continued_one_does_not(
    make_client, wait_run, project_dir
):
    client, model, pid, cid = setup(make_client, project_dir, {
        "Lead": [text("REPLY-ALPHA it is done"), text("two"), text("three")]})
    turn(client, wait_run, cid, "fix the greeting\nSECRET-ALPHA the detail of it")
    turn(client, wait_run, cid, SECOND)
    (going_on,) = sent_to(model, SECOND)
    assert "SECRET-ALPHA" in going_on and "REPLY-ALPHA" in going_on
    turn(client, wait_run, cid, THIRD, new_topic=True)
    (fresh,) = sent_to(model, THIRD)
    assert "SECRET-ALPHA" not in fresh and "REPLY-ALPHA" not in fresh and SECOND not in fresh
    # it is told only that there were earlier topics, by their names
    assert "fix the greeting" in fresh and "Earlier topics" in fresh


# --- going on with an agent is opening an agent ------------------------------------------------


def test_going_on_with_an_agent_is_asked_about_like_opening_one(
    make_client, wait_run, project_dir
):
    client, model, pid, cid = setup(make_client, project_dir, TWO_TURNS)
    snap, first = turn(client, wait_run, cid, FIRST)
    (old,) = [a for a in agents_of(snap, first["id"]) if a["name"] == "Coder"]
    client.patch(f"/api/conversations/{cid}", json={"spawn_approval": "always"})
    run = say(client, cid, SECOND)
    for _ in range(400):
        snap = client.get(f"/api/conversations/{cid}").json()
        waiting = [a for a in agents_of(snap, run["id"]) if a["status"] == "proposed"]
        if waiting:
            break
        time.sleep(0.02)
    (card,) = waiting
    assert (card["name"], card["continues_id"]) == ("Coder", old["id"])
    assert client.post(f"/api/agents/{card['id']}/reject").status_code == 200
    snap = wait_run(client, cid, run["id"])
    ((status, _said),) = calls_of(snap, run["id"], "message_agent")
    assert status == "denied"
    assert sent_to(model, MORE, lacking=[SECOND]) == []      # it never took the turn


def test_going_on_with_an_agent_counts_against_the_turns_agents(
    make_client, wait_run, project_dir
):
    scripts = {
        "Lead": [SPAWN_CODER, text("made"),
                 step(call("spawn_agent", {"role": "Reviewer", "task": "look"}, "s2")),
                 GO_ON, text("done")],
        "Coder": [WRITE, text(OLD_WORDS), text("must not be asked")],
        "Reviewer": [text("looked")],
    }
    client, model, pid, cid = setup(make_client, project_dir, scripts)
    turn(client, wait_run, cid, FIRST)
    client.patch(f"/api/conversations/{cid}", json={"spawn_max_agents": 1})
    snap, second = turn(client, wait_run, cid, SECOND)
    ((status, said),) = calls_of(snap, second["id"], "message_agent")
    assert status == "failed" and "limit" in said
    assert [a["name"] for a in agents_of(snap, second["id"])] == ["Lead", "Reviewer"]


def test_a_continued_agent_has_what_its_role_may_do_today(make_client, wait_run, project_dir):
    scripts = {
        "Lead": [SPAWN_CODER, text("made"), GO_ON, text("done")],
        "Coder": [WRITE, text(OLD_WORDS),
                  step(call("write_file", {"path": "more.py", "content": "x"}, "w2")),
                  text("could not write")],
    }
    client, model, pid, cid = setup(make_client, project_dir, scripts)
    turn(client, wait_run, cid, FIRST)
    coder_role = next(r for r in client.get("/api/roles").json() if r["name"] == "Coder")
    narrowed = client.patch(f"/api/roles/{coder_role['id']}", json={
        "tools": ["list_dir", "read_file", "search"]})
    assert narrowed.status_code == 200, narrowed.text
    snap, second = turn(client, wait_run, cid, SECOND)
    coder = next(a for a in agents_of(snap, second["id"]) if a["name"] == "Coder")
    assert "write_file" not in coder["tools"]
    assert not (project_dir / "more.py").exists()
    ((status, _said),) = calls_of(snap, second["id"], "write_file")
    assert status != "succeeded"


def test_an_agent_whose_role_is_gone_cannot_be_gone_on_with(make_client, wait_run, project_dir):
    scripts = {
        "Lead": [step(call("spawn_agent", {"role": "Helper", "task": OLD_TASK}, "s1")),
                 text("made"),
                 step(call("message_agent", {"to": "Helper", "message": MORE}, "m1")),
                 text("done")],
        "Helper": [text(OLD_WORDS), text("must not be asked")],
    }
    client, model, pid, cid = setup(make_client, project_dir, scripts)
    made = client.post("/api/roles", json={
        "name": "Helper", "description": "helps", "instructions": "", "tools": ["read_file"]})
    assert made.status_code == 201, made.text
    turn(client, wait_run, cid, FIRST)
    assert client.delete(f"/api/roles/{made.json()['id']}").status_code in (200, 204)
    snap, second = turn(client, wait_run, cid, SECOND)
    ((status, said),) = calls_of(snap, second["id"], "message_agent")
    assert status == "failed" and "role" in said
    assert [a["name"] for a in agents_of(snap, second["id"])] == ["Lead"]


def test_an_agent_that_never_worked_cannot_be_gone_on_with(make_client, wait_run, project_dir):
    client, model, pid, cid = setup(make_client, project_dir, TWO_TURNS,
                                    spawn_approval="always")
    run = say(client, cid, FIRST)
    for _ in range(400):
        snap = client.get(f"/api/conversations/{cid}").json()
        waiting = [a for a in agents_of(snap, run["id"]) if a["status"] == "proposed"]
        if waiting:
            break
        time.sleep(0.02)
    client.post(f"/api/agents/{waiting[0]['id']}/reject")
    wait_run(client, cid, run["id"])
    client.patch(f"/api/conversations/{cid}", json={"spawn_approval": "never"})
    model.by_agent["Lead"] = [GO_ON, text("done")]
    snap, second = turn(client, wait_run, cid, SECOND)
    assert all("Coder" not in told for told in offered(model, SECOND))
    ((status, _said),) = calls_of(snap, second["id"], "message_agent")
    assert status == "failed"


def test_a_name_taken_in_this_turn_means_the_agent_of_this_turn(
    make_client, wait_run, project_dir
):
    scripts = {
        "Lead": [SPAWN_CODER, text("made"),
                 step(call("spawn_agent", {"role": "Coder", "task": "NEW-TASK other work"}, "s2")),
                 GO_ON, text("done")],
        "Coder": [WRITE, text(OLD_WORDS), text("new coder done"), text("new coder again")],
    }
    client, model, pid, cid = setup(make_client, project_dir, scripts)
    turn(client, wait_run, cid, FIRST)
    snap, second = turn(client, wait_run, cid, SECOND)
    coders = [a for a in agents_of(snap, second["id"]) if a["name"] == "Coder"]
    assert len(coders) == 1 and coders[0]["continues_id"] is None
    (request,) = sent_to(model, MORE, lacking=[SECOND])
    assert "NEW-TASK other work" in request and OLD_TASK not in request


# --- triggers have topics of their own ----------------------------------------------------------


def test_a_triggers_turns_are_a_topic_of_their_own_and_hold_to_its_agents(
    make_client, wait_run, project_dir
):
    scripts = {
        "Lead": [text("mine"),
                 step(call("spawn_agent", {"role": "Reviewer", "task": OLD_TASK}, "s1")),
                 text("looked"),
                 step(call("message_agent", {"to": "Reviewer", "message": MORE}, "m1")),
                 text("could not"),
                 step(call("message_agent", {"to": "Reviewer", "message": MORE}, "m2")),
                 text("went on"), text("mine again")],
        "Reviewer": [text(OLD_WORDS), text("looked again")],
    }
    client, model, pid, cid = setup(make_client, project_dir, scripts)
    snap, mine = turn(client, wait_run, cid, FIRST)

    def trigger_turn(agents):
        patched = client.patch(f"/api/triggers/{made['id']}", json={
            "permissions": {"write": False, "commands": [], "agents": agents}})
        assert patched.status_code == 200, patched.text
        run_id = client.post(f"/api/triggers/{made['id']}/run").json()["run_id"]
        return wait_run(client, cid, run_id), run_id

    made = client.post(f"/api/projects/{pid}/triggers", json={
        "name": "watch", "kind": "webhook", "config": {}, "conversation_id": cid,
        "message": "TRIGGER-MESSAGE look it over"}).json()
    snap, one = trigger_turn(1)
    snap, two = trigger_turn(0)
    snap, three = trigger_turn(1)
    runs = {r["id"]: r for r in snap["runs"]}
    topic = runs[one]["topic_id"]
    assert topic == runs[two]["topic_id"] == runs[three]["topic_id"] != mine["topic_id"]
    assert next(t for t in snap["topics"] if t["id"] == topic)["trigger_id"] == made["id"]
    # with no agents allowed, going on with one is refused like opening one
    ((status, said),) = calls_of(snap, two, "message_agent")
    assert status != "succeeded" and "nobody is here to ask" in said
    ((status, _said),) = calls_of(snap, three, "message_agent")
    assert status == "succeeded"
    # the user's next message goes on with the user's own topic, not the trigger's
    snap, again = turn(client, wait_run, cid, SECOND)
    assert again["topic_id"] == mine["topic_id"]
