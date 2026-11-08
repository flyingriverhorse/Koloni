"""Slice 29b's first part: a room the user opens. Written before the code.

A room is two to four agents working on one goal at the same time, in one working copy.
Before they start they share the work out, a step each, with nothing but reading and the
room's list of items; from then on a file is changed only under an item of one's own, and an
item has one holder. What one posts the others read at their next step; a question stays
open until it is answered. The room ends when all are done, at its budget, or at the user's
word; then the project gets the copy as any working copy's, and the turn's lead - who took no
part - is given the room's record and answers the user.
"""

import json

import pytest

from app.db import models

if not hasattr(models, "Room"):  # written before the code: skipped until it exists
    pytest.skip("slice 29b is not built yet", allow_module_level=True)

from app import room as rooms  # noqa: E402
from app.model_client import ModelUnavailable  # noqa: E402
from tests.conftest import Gate  # noqa: E402
from tests.test_chat_flow import text  # noqa: E402
from tests.test_parallel import now_snap, until  # noqa: E402
from tests.test_spawn import call, names, step  # noqa: E402

ORIGIN = "http://127.0.0.1:8790"
# (show: slice 39; recall_output: K-gecmis-zengin)
READING = {"list_dir", "read_file", "search", "recall", "read_notes", "show", "recall_output"}
LONG = 20.0


def add(title, paths=None, id="a"):
    return call("add_item", {"title": title, **({"paths": paths} if paths else {})}, id)


def take(item, id="t"):
    return call("take_item", {"item": item}, id)


def finish(item, result, id="f"):
    return call("finish_item", {"item": item, "result": result}, id)


def post(kind, said, id="p", **more):
    return call("post_to_room", {"type": kind, "text": said, **more}, id)


def wait(id="w"):
    return step(call("wait_for_post", {}, id))


def edit(old, new, id="e", path="hello.py"):
    return call("edit_file", {"path": path, "old_string": old, "new_string": new}, id)


def start(make_client, project_dir, scripts, goal="Fix the greeting together",
          members=("Coder", "Reviewer"), budget=None, steps=None, **conversation):
    """A conversation in which the user opens a room; returns the client, the model, the
    conversation's id, the run's and the room as it was when it opened. `steps`: the app's
    step limit."""
    client, model = make_client({"Lead": [text("The room is over: here is what came of it.")],
                                 **scripts})
    client.headers["Origin"] = ORIGIN
    if steps:
        assert client.put("/api/steps", json={"max_steps": steps}).status_code == 200
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    settings = {"permission_mode": "full_auto", **conversation}
    assert client.patch(f"/api/conversations/{cid}", json=settings).status_code == 200
    body = {"goal": goal, "with": [{"role": role} for role in members]}
    if budget:
        body["budget"] = budget
    opened = client.post(f"/api/conversations/{cid}/rooms", json=body)
    assert opened.status_code == 201, opened.text
    return client, model, cid, opened.json()["run"]["id"], opened.json()["room"]


def results(snap, agent_name, tool):
    wanted = next(a["id"] for a in snap["agents"] if a["name"] == agent_name)
    return [(t["status"], t["result"] or "") for t in snap["tool_calls"]
            if t["agent_id"] == wanted and t["name"] == tool]


def items(snap):
    by = {a["id"]: a["name"] for a in snap["agents"]}
    return [(i["number"], i["title"], i["status"], by.get(i["holder_agent_id"]))
            for i in snap["room_items"]]


def posts(snap):
    by = {a["id"]: a["name"] for a in snap["agents"]}
    return [(p["type"], by.get(p["agent_id"], "You"), p["text"]) for p in snap["room_posts"]]


def asked(model, name):
    """Everything the named agent's model was sent, call by call, as text to look in."""
    return [json.dumps(messages) for messages in model.calls_of[name]]


# --- the room, from its opening to the lead's word --------------------------------------------


def test_the_user_opens_a_room_its_members_share_the_work_out_and_do_it_in_one_copy(
    make_client, wait_run, project_dir
):
    client, model, cid, run_id, room = start(make_client, project_dir, {
        "Coder": [step(add("Change the greeting", ["hello.py"], "a1"), take(1, "t1")),
                  step(edit("hi", "yo")),
                  step(post("result", "The greeting says yo now.", "p1"),
                       finish(1, "hello.py prints yo", "f1")),
                  text("My part is done.")],
        "Reviewer": [step(add("Review the greeting", id="a2"), take(2, "t2")),
                     wait(),                                    # until the Coder has posted
                     step(call("read_file", {"path": "hello.py"}, "r")),
                     step(finish(2, "It prints yo, as asked.", "f2")),
                     text("Looked at it: fine.")],
    })
    assert room["goal"] == "Fix the greeting together" and len(room["members"]) == 2
    assert room["summary"] is None  # (AC: said once it is over, not while it runs)
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]

    # before the work starts, a step each, in the order they were named: reading, the room's
    # list and a word to the room - nothing that changes or runs anything
    for offered in (names(model.tool_args[0]), names(model.tool_args[1])):
        assert {"add_item", "take_item", "post_to_room"} <= set(offered)
        assert set(offered) <= READING | {"add_item", "take_item", "post_to_room",
                                          "invite_to_room"}

    assert items(snap) == [(1, "Change the greeting", "done", "Coder"),
                           (2, "Review the greeting", "done", "Reviewer")]
    assert [i["result"] for i in snap["room_items"]] == [
        "hello.py prints yo", "It prints yo, as asked."]
    # one copy for both: the Reviewer read what the Coder had just written
    assert "yo" in results(snap, "Reviewer", "read_file")[0][1]
    # and the project has it now that the room is over (full auto: nobody is asked)
    assert (project_dir / "hello.py").read_text(encoding="utf-8") == "print('yo')\n"
    assert [m["status"] for m in snap["merges"]] == ["applied"]

    (ended,) = snap["rooms"]
    assert (ended["status"], ended["outcome"]) == ("ended", "agreed")
    assert ("result", "Coder", "The greeting says yo now.") in posts(snap)
    # a member whose work is over is on record as done, with its last words
    assert ("done", "Coder", "My part is done.") in posts(snap)
    assert ("done", "Reviewer", "Looked at it: fine.") in posts(snap)
    # AC: the user is served what it came to in a line - its done items' first lines - and the
    # room's own record (room, posts, items) has no line of KOLONİ's saying a member's work is
    # over: its status says that. (What the Lead and the members read keep it: `rooms.said`.)
    assert ended["summary"] == "hello.py prints yo. It prints yo, as asked."
    served = json.dumps([snap["rooms"], snap["room_posts"], snap["room_items"]])
    assert "work is over" not in served

    # the lead took no part: one request, after the room, with the goal and what came of it
    (told,) = asked(model, "Lead")
    for held in ("Fix the greeting together", "Change the greeting", "hello.py prints yo",
                 "It prints yo, as asked."):
        assert held in told
    # (AC) what the Lead reads still says whose work is over, with its last words; and so does
    # what a member is handed of the others' posts
    assert "Coder's work is over. Its last words:" in told and "You took no part in it." in told
    assert any("work is over. Its last words:" in m["content"] for m in snap["messages"]
               if m["room_post_id"])
    # (Under the answer, KOLONİ's line on where the work is: B-205.)
    assert [m["content"] for m in snap["messages"][-2:]] == [
        "The room is over: here is what came of it.", "In the project: hello.py (+1 −1)."]
    lead, coder, reviewer = snap["agents"]
    assert (lead["depth"], coder["depth"], reviewer["depth"]) == (0, 1, 1)


def test_an_item_has_one_holder_and_a_file_is_changed_only_under_an_item_of_ones_own(
    make_client, wait_run, project_dir
):
    held = Gate()
    client, _model, cid, run_id, _room = start(make_client, project_dir, {
        "Coder": [step(add("Change the greeting", ["hello.py"], "a1"), take(1, "t1")),
                  step(edit("hi", "yo")),
                  held.step(step(finish(1, "done", "f1"))),     # holds its item meanwhile
                  text("Done.")],
        "Coder 2": [step(take(1, "t2")),                            # somebody has it
                    step(call("write_file", {"path": "hello.py", "content": "mine\n"}, "w")),
                    step(add("Also the greeting", ["hello.py"], "a2"), take(2, "t3")),
                    step(call("write_file", {"path": "notes.txt", "content": "n\n"}, "w2")),
                    text("Nothing for me to change.")],
    }, members=("Coder", "Coder"))
    snap = until(client, cid, lambda s: len(results(s, "Coder 2", "write_file")) == 2,
                 timeout=LONG)
    ((status, said),) = results(snap, "Coder 2", "take_item")[:1]
    assert status == "failed" and "Coder" in said               # who holds it, by name
    for status, said in results(snap, "Coder 2", "write_file"):
        assert status == "failed" and "item" in said            # no item of its own covers it
    # an item whose files another's item already covers cannot be taken beside it
    assert results(snap, "Coder 2", "take_item")[1][0] == "failed"
    assert not (project_dir / "notes.txt").exists()
    held.release()
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert (project_dir / "hello.py").read_text(encoding="utf-8") == "print('yo')\n"
    assert items(snap)[0] == (1, "Change the greeting", "done", "Coder")
    assert items(snap)[1][2] == "open"                          # asked for, never held


def test_a_question_is_read_at_the_others_next_step_and_stays_open_until_it_is_answered(
    make_client, wait_run, project_dir
):
    client, model, cid, run_id, _room = start(make_client, project_dir, {
        "Coder": [step(add("Change the greeting", ["hello.py"], "a1"), take(1, "t1")),
                  step(post("question", "Which greeting do you want?", "q", to="Reviewer")),
                  wait(),                                           # until it is answered
                  step(finish(1, "left as it is", "f1")),
                  text("Done.")],
        "Reviewer": [text("Nothing to add to the list."),
                     wait(),                                        # until somebody posts
                     step(post("answer", "Keep hi.", "ans", reply_to=1)),
                     text("Answered.")],
    })
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    question, answer = [p for p in snap["room_posts"] if p["type"] in ("question", "answer")]
    assert (question["number"], question["open"], answer["reply_to"]) == (1, False, 1)
    # each read the other's word at the step after it was said
    assert "Which greeting do you want?" in asked(model, "Reviewer")[2]
    assert "Keep hi." in asked(model, "Coder")[3]
    assert snap["rooms"][0]["outcome"] == "agreed"


# --- the user in the room, and its budget ----------------------------------------------------


def test_the_user_speaks_in_the_room_and_ends_it(make_client, wait_run, project_dir):
    held = Gate()
    client, model, cid, run_id, room = start(make_client, project_dir, {
        "Coder": [text("Nothing to add."), held.step(text("Never said."))],   # at work all along
        "Reviewer": [text("Nothing to add."), wait(), text("Heard you.")],
    })
    held.wait_partial()
    said = client.post(f"/api/rooms/{room['id']}/posts", json={"text": "Tests first!"})
    assert said.status_code == 201, said.text
    assert client.post(f"/api/rooms/{room['id']}/posts", json={"text": "  "}).status_code == 422
    # the one that waited for a word is woken by the user's, and reads it at its next step
    until(client, cid, lambda s: ("done", "Reviewer", "Heard you.") in posts(s), timeout=LONG)
    assert "Tests first!" in asked(model, "Reviewer")[2]
    ended = client.post(f"/api/rooms/{room['id']}/end")
    assert ended.status_code == 200, ended.text
    snap = wait_run(client, cid, run_id, timeout=LONG)        # the one still at work is ended
    held.release()
    assert (snap["rooms"][0]["status"], snap["rooms"][0]["outcome"]) == ("ended", "ended_by_user")
    assert snap["runs"][0]["status"] == "completed"           # the lead still has its word
    assert ("said", "You", "Tests first!") in posts(snap)
    assert client.post(f"/api/rooms/{room['id']}/posts", json={"text": "late"}).status_code == 409


def test_a_room_ends_at_its_budget_and_the_lead_is_told(make_client, wait_run, project_dir):
    client, model, cid, run_id, room = start(make_client, project_dir, {
        "Coder": [text("Nothing to add."),
                  step(post("result", "one", "p1")), step(post("result", "two", "p2")),
                  step(post("result", "three", "p3")), text("Done.")],
        "Reviewer": [text("Nothing to add."), wait(), wait(), wait(), text("Done.")],
    }, budget={"posts": 2})
    assert room["budget"]["posts"] == 2
    snap = wait_run(client, cid, run_id, timeout=LONG)
    (ended,) = snap["rooms"]
    assert (ended["status"], ended["outcome"]) == ("ended", "budget")
    assert [said for kind, _who, said in posts(snap) if kind == "result"] == ["one", "two"]
    assert "budget" in asked(model, "Lead")[0]
    assert snap["runs"][0]["status"] == "completed"


def test_what_a_room_may_be_and_when_it_may_be_opened(make_client, wait_run, project_dir):
    held = Gate()
    client, _model, cid, run_id, room = start(make_client, project_dir, {
        "Coder": [text("Nothing to add."), held.step(text("Done."))],
        "Reviewer": [text("Nothing to add."), text("Done.")],
    })
    rooms = f"/api/conversations/{cid}/rooms"
    two = [{"role": "Coder"}, {"role": "Reviewer"}]
    # one room to a turn, and none while the conversation is at work
    assert client.post(rooms, json={"goal": "another", "with": two}).status_code == 409
    more = client.post(f"/api/rooms/{room['id']}/more", json={"posts": 5})
    assert more.status_code == 200 and more.json()["budget"]["posts"] == room["budget"]["posts"] + 5
    held.release()
    wait_run(client, cid, run_id, timeout=LONG)
    for bad in ({"goal": "x", "with": two[:1]},                              # alone is no room
                {"goal": "x", "with": two * 3 + two[:1]},                    # seven is a crowd
                {"goal": "x", "with": [{"role": "Coder"}, {"role": "No such role"}]},
                {"goal": "  ", "with": two},
                {"goal": "x", "with": two, "budget": {"posts": 0}}):
        assert client.post(rooms, json=bad).status_code == 422, bad
    del client.headers["Origin"]
    assert client.post(rooms, json={"goal": "x", "with": two},
                       headers={"Origin": "http://evil.example"}).status_code == 403


# --- how it ends otherwise -------------------------------------------------------------------


def test_where_the_user_is_asked_the_rooms_copy_is_one_card(make_client, wait_run, project_dir):
    client, _model, cid, run_id, room = start(make_client, project_dir, {
        "Coder": [step(add("Change the greeting", ["hello.py"], "a1"), take(1, "t1")),
                  step(edit("hi", "yo")), step(finish(1, "done", "f1")), text("Done.")],
        "Reviewer": [text("Nothing to add."), text("Done.")],
    }, permission_mode="ask")
    snap = until(client, cid, lambda s: [m["status"] for m in s["merges"]] == ["pending"],
                 timeout=LONG)
    assert (project_dir / "hello.py").read_text(encoding="utf-8") == "print('hi')\n"
    assert [f["path"] for f in snap["merges"][0]["files"]] == ["hello.py"]
    # the room's own: its card is in the room, and no other copy of its lead's is
    assert snap["merges"][0]["room_id"] == room["id"]
    assert client.post(f"/api/merges/{snap['merges'][0]['id']}/approve").status_code == 200
    wait_run(client, cid, run_id, timeout=LONG)
    assert (project_dir / "hello.py").read_text(encoding="utf-8") == "print('yo')\n"


def test_stop_ends_the_room_and_takes_nothing(make_client, wait_run, project_dir):
    held = Gate()
    client, _model, cid, run_id, _room = start(make_client, project_dir, {
        "Coder": [step(add("Change the greeting", ["hello.py"], "a1"), take(1, "t1")),
                  step(edit("hi", "yo")), held.step(text("Done."))],
        "Reviewer": [text("Nothing to add."), wait(), text("Done.")],
    })
    held.wait_partial()
    assert client.post(f"/api/runs/{run_id}/cancel").status_code in (200, 202)
    snap = wait_run(client, cid, run_id, timeout=LONG)
    held.release()
    assert snap["runs"][0]["status"] == "cancelled"
    assert snap["rooms"][0]["status"] == "cancelled" and snap["rooms"][0]["outcome"] is None
    assert (project_dir / "hello.py").read_text(encoding="utf-8") == "print('hi')\n"
    assert not [m for m in snap["merges"] if m["status"] in ("pending", "applied")]


def test_a_member_that_fails_gives_its_item_back_and_one_alone_is_no_room(
    make_client, wait_run, project_dir
):
    client, model, cid, run_id, _room = start(make_client, project_dir, {
        "Coder": [step(add("Change the greeting", ["hello.py"], "a1"), take(1, "t1")),
                  ModelUnavailable("the model went away")],
        "Reviewer": [text("Nothing to add."), wait(), text("Alone now.")],
    })
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert items(snap) == [(1, "Change the greeting", "open", None)]    # nobody's again
    (ended,) = snap["rooms"]
    assert (ended["status"], ended["outcome"]) == ("ended", "too_few")
    assert next(m for m in ended["members"]
                if m["agent_id"] == snap["agents"][1]["id"])["status"] == "left"
    assert "Change the greeting" in asked(model, "Lead")[0]            # left open: said
    assert now_snap(client, cid)["rooms"][0]["status"] == "ended"


def waits_out(make_client, project_dir):
    """B-203: the Reviewer waits for the Coder's item seven times at an app step limit of five
    - the first till it is finished, the rest given what came of it at once. (Once the room is
    over: one whose member left asks the user to take its work in.) No timing: the sharing
    round runs one member after another, so item 1 is the Coder's before the Reviewer works -
    held while the Coder is at it, closed (given at once) after."""
    client, _model, cid, _run_id, _room = start(make_client, project_dir, {
        "Coder": [step(add("Change the greeting", ["hello.py"], "a1"), take(1, "t1")),
                  step(edit("hi", "yo")), step(finish(1, "hello.py prints yo", "f1")),
                  text("My part is done.")],
        "Reviewer": [text("I review the greeting once it is changed."),
                     *[step(call("wait_for_item", {"item": 1}, f"w{at}")) for at in range(7)],
                     text("Looked at it: fine.")],
    }, steps=5)
    snap = until(client, cid, lambda s: s["rooms"][0]["status"] == "ended", timeout=LONG)
    reviewer = next(a for a in snap["agents"] if a["name"] == "Reviewer")
    (ended,) = snap["rooms"]
    return snap, reviewer, ended


def test_a_members_steps_that_only_wait_in_its_room_take_none_of_its_steps(
    make_client, project_dir
):
    snap, reviewer, ended = waits_out(make_client, project_dir)
    assert [status for status, _ in results(snap, "Reviewer", "wait_for_item")] == ["succeeded"] * 7
    assert (reviewer["status"], reviewer["error"]) == ("completed", None)
    assert (ended["status"], ended["outcome"]) == ("ended", "agreed")


def test_a_members_steps_that_only_wait_are_free_only_up_to_their_cap(
    make_client, project_dir, monkeypatch
):
    """(A wait may come back at once: a model that kept asking for it would never stop.)"""
    monkeypatch.setattr(rooms, "FREE_WAITS", 2)
    snap, reviewer, ended = waits_out(make_client, project_dir)
    assert len(results(snap, "Reviewer", "wait_for_item")) == 7       # two free, five counted
    assert (reviewer["status"], reviewer["error"]) == ("failed", "step_limit")
    assert (ended["status"], ended["outcome"]) == ("ended", "too_few")


# --- K-oda-onbellek: a post handed over does not move in the steps after -----------------------


def test_a_members_next_request_begins_with_its_last_one_posts_and_all(
    make_client, wait_run, project_dir
):
    """B-34: what a member was sent at one step is the start of what it is sent at the next -
    the room's posts handed to it stay where they were handed, so a prompt cache keeps it. Only
    how the room stands now, said at the end of each step, is not sent again."""
    client, model, cid, run_id, _room = start(make_client, project_dir, {
        "Coder": [step(add("Change the greeting", ["hello.py"], "a1"), take(1, "t1")),
                  step(post("result", "The greeting says yo now.", "p1")),
                  step(post("result", "And it is tested.", "p2")),
                  step(finish(1, "hello.py prints yo", "f1")),
                  text("My part is done.")],
        "Reviewer": [step(add("Review the greeting", id="a2"), take(2, "t2")),
                     wait("w1"), wait("w2"),
                     step(call("read_file", {"path": "hello.py"}, "r")),
                     step(finish(2, "It prints yo, as asked.", "f2")),
                     text("Looked at it: fine.")],
    })
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]

    def kept(messages):  # (how the room stands goes with one step only)
        return [m for m in messages if not str(m["content"]).startswith("The room now")]

    working = model.calls_of["Reviewer"][1:]  # (after its sharing step, offered other tools)
    handed = [m["content"] for m in working[-1] if str(m["content"]).startswith("Said in the room")]
    assert len(handed) >= 2, handed  # (both posts reached it, at one step or two)
    for earlier, later in zip(working, working[1:], strict=False):
        assert kept(later)[:len(kept(earlier))] == kept(earlier)
