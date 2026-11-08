"""A room the user opens (slice 29b, first part), beyond its acceptance set
(`test_room_scenarios`): what each of the room's tools refuses, the rest of the list and
the post types, the budgets of tokens and of minutes and adding to them, three and four
members, who is woken by what, the places a room's members hold, the room's one copy on its
way into the project, what is left of a room after a restart, and the migration.
"""

import sqlite3
import time

import pytest
from alembic import command as alembic

from app.agent import AgentRunner, recover_interrupted
from app.config import load_settings
from app.db.models import Agent, Room, RoomMember, Run
from app.db.session import make_engine, make_session_factory, upgrade_db
from app.main import create_app
from app.model_client import ModelUnavailable, StepResult
from tests.conftest import Gate
from tests.fakes import ScriptedModel
from tests.keyed import TestClient
from tests.test_chat_flow import text
from tests.test_copy_scenarios import seen
from tests.test_migration_0002 import _config
from tests.test_parallel import now_snap, until
from tests.test_recovery import seed
from tests.test_room_scenarios import (
    LONG,
    ORIGIN,
    add,
    asked,
    edit,
    finish,
    items,
    post,
    posts,
    results,
    start,
    take,
    wait,
)
from tests.test_spawn import call, names, role_id, step
from tests.test_take_in_scenarios import CHECK, LINES, card, lines, meanwhile, needs_git, of
from tests.test_triggers import HeldClock, cli_app, on_loop  # noqa: F401 (cli_app: a fixture)

TWO = [{"role": "Coder"}, {"role": "Reviewer"}]


def drop(item, why, id="d"):
    return call("drop_item", {"item": item, "why": why}, id)


def room_in(make_client, project_dir, scripts, members=TWO, budget=None, before=None,
            lead=None, project=None, **conversation):
    """Like the acceptance set's `start`, with what that one cannot say: a member's
    provider, the project's settings, the lead's own script, and something done to the
    app before the room is opened (`before`)."""
    client, model = make_client({
        "Lead": lead or [text("The room is over: here is what came of it.")], **scripts})
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    if project:
        assert client.patch(f"/api/projects/{pid}", json=project).status_code == 200
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    settings = {"permission_mode": "full_auto", **conversation}
    assert client.patch(f"/api/conversations/{cid}", json=settings).status_code == 200
    if before:
        before(client)
    body = {"goal": "Work on it together", "with": members}
    if budget:
        body["budget"] = budget
    opened = client.post(f"/api/conversations/{cid}/rooms", json=body)
    assert opened.status_code == 201, opened.text
    return client, model, cid, opened.json()["run"]["id"], opened.json()["room"]


def said_by(model, at):
    """Whose step the model's `at`-th request was."""
    system = str(model.calls[at][0]["content"])
    return system.split("Your name here is ", 1)[1].split(".", 1)[0]


def member(snap, name):
    agent = next(a for a in snap["agents"] if a["name"] == name)
    return next(m for m in snap["rooms"][0]["members"] if m["agent_id"] == agent["id"])


def agent(snap, name):
    return next(a for a in snap["agents"] if a["name"] == name)


# --- what the room's tools refuse ------------------------------------------------------------


def test_what_the_list_and_a_post_refuse_and_what_the_sharing_round_does_not_offer(
    make_client, wait_run, project_dir
):
    held = Gate()
    client, _model, cid, run_id, _room = start(make_client, project_dir, {
        "Coder": [
            step(call("add_item", {"paths": ["hello.py"]}, "a0"),              # no title
                 call("add_item", {"title": "Out", "paths": ["../out.txt"]}, "a1"),
                 add("Change the greeting", ["hello.py"], "a2"),
                 take(9, "t0"), take(1, "t1"), take(1, "t2"),
                 edit("hi", "yo", "e0"),                                       # not in this round
                 finish(1, "too early", "f0"),
                 post("shout", "hello", "p0"), post("result", "  ", "p1"),
                 post("result", "x", "p2", to="Nobody"),
                 post("result", "x", "p3", reply_to=7), post("answer", "x", "p4")),
            step(call("finish_item", {"item": 1}, "f1"), finish(2, "x", "f2"),
                 call("drop_item", {"item": 1}, "d0"), finish(1, "left as it is", "f3"),
                 take(1, "t3"), finish(1, "again", "f4")),
            held.step(text("Done.")),
        ],
        "Reviewer": [text("Nothing to add."), step(finish(1, "not mine", "f5")),
                     wait("w1"), wait("w2"), text("Done.")],
    })
    until(client, cid, lambda s: member(s, "Reviewer")["status"] == "waiting", timeout=LONG)
    held.release()
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    # every call by the name it has above, in the order each of the two made them
    ids = (["a0", "a1", "a2", "t0", "t1", "t2", "e0", "f0", "p0", "p1", "p2", "p3", "p4",
            "f1", "f2", "d0", "f3", "t3", "f4"], ["f5", "w1", "w2"])
    said = {}
    for name, calls in zip(("Coder", "Reviewer"), ids, strict=True):
        made = sorted((t for t in snap["tool_calls"] if t["agent_id"] == agent(snap, name)["id"]),
                      key=lambda t: t["seq"])
        said.update(zip(calls, ((t["status"], t["result"]) for t in made), strict=True))

    def refused(call_id, *words):
        status, why = said[call_id]
        assert status == "failed" and all(word in why for word in words), (call_id, why)

    refused("a0", "title")
    refused("a1", "inside the project")
    refused("t0", "no item 9")
    assert said["t1"][0] == "succeeded"
    refused("t2", "yours already")
    # before the work starts nothing is changed, and no item is closed
    refused("e0", "edit_file", "shared out")
    refused("f0", "finish_item", "shared out")
    refused("p0", "result, review, question, answer, blocked")
    refused("p1", "text")
    refused("p2", "Nobody", "Reviewer")
    refused("p3", "no post 7")
    refused("p4", "reply_to")
    refused("f1", "result")
    refused("f2", "no item 2")
    refused("d0", "why")
    assert said["f3"][0] == "succeeded"
    refused("t3", "done")
    refused("f4", "not yours")
    refused("f5", "not yours")                                  # only its holder closes it
    # nothing that was refused is in the room
    assert items(snap) == [(1, "Change the greeting", "done", "Coder")]
    assert [kind for kind, _who, _said in posts(snap)] == ["done", "done"]
    # the Coder's last words woke the one that waited; then nobody was at work to wait for
    assert said["w1"][0] == "succeeded"
    refused("w2", "no other member is at work")


def test_an_item_that_will_not_be_done_is_dropped_with_why_and_stays_closed(
    make_client, wait_run, project_dir
):
    client, _model, cid, run_id, _room = start(make_client, project_dir, {
        "Coder": [step(add("Rewrite it all", ["hello.py"], "a1"), take(1, "t1")),
                  step(drop(1, "Not needed: the greeting is fine.")),
                  step(add("Say so in the notes", ["notes.txt"], "a2"), take(2, "t2")),
                  step(call("write_file", {"path": "notes.txt", "content": "fine\n"}, "w")),
                  step(finish(2, "noted", "f")), text("Done.")],
        "Reviewer": [text("Nothing to add."), wait(), step(take(1, "t3")), text("Done.")],
    })
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert items(snap) == [(1, "Rewrite it all", "dropped", "Coder"),
                           (2, "Say so in the notes", "done", "Coder")]
    assert snap["room_items"][0]["result"] == "Not needed: the greeting is fine."
    # a dropped item is not there to be taken again
    ((status, why),) = results(snap, "Reviewer", "take_item")
    assert status == "failed" and "dropped" in why
    # the file its item no longer covers was not changed; the other one's was
    assert (project_dir / "hello.py").read_text(encoding="utf-8") == "print('hi')\n"
    assert (project_dir / "notes.txt").read_text(encoding="utf-8") == "fine\n"
    assert snap["rooms"][0]["outcome"] == "agreed"


# --- the other kinds of posts ----------------------------------------------------------------


def test_at_full_auto_a_blocked_post_is_answered_by_the_lead_for_the_user(
    make_client, wait_run, project_dir
):
    """K-fullauto-sorma 2: a member's blocked post is a question of a sub-agent's - the Lead's
    to answer at once at Full auto, with its reason on record."""
    from tests.test_lead_decides import says
    client, _model, cid, run_id, _room = start(make_client, project_dir, {
        "Lead": [says("Postgres", "The project uses it."),
                 text("The room is over: here is what came of it.")],
        "Coder": [text("Nothing to add."), step(post("blocked", "Which database is it for?")),
                  text("Done.")],
        "Reviewer": [text("Nothing to add."), wait("w1"), wait("w2"), text("Done.")],
    })
    snap = wait_run(client, cid, run_id, timeout=LONG)
    (question,) = snap["questions"]
    assert (question["answer"], question["lead_why"]) == ("Postgres", "The project uses it.")
    assert posts(snap)[:2] == [("blocked", "Coder", "Which database is it for?"),
                               ("said", "You", "Postgres")]


def test_a_blocked_post_asks_the_user_and_their_answer_is_the_rooms_too(
    make_client, wait_run, project_dir
):
    client, model, cid, run_id, _room = start(make_client, project_dir, {
        "Coder": [text("Nothing to add."), step(post("blocked", "Which database is it for?")),
                  text("Done.")],
        "Reviewer": [text("Nothing to add."), wait("w1"), wait("w2"), text("Done.")],
    }, permission_mode="auto_edit")  # (at Full auto the Lead answers it: above)
    snap = until(client, cid, lambda s: [q["status"] for q in s["questions"]] == ["pending"],
                 timeout=LONG)
    (question,) = snap["questions"]
    assert question["question"] == "Which database is it for?"
    assert question["agent_id"] == agent(snap, "Coder")["id"]
    assert snap["runs"][0]["status"] == "waiting_approval"
    # it is in the room as said, and whoever waited has read it; it is no open question
    (blocked,) = snap["room_posts"]
    assert (blocked["type"], blocked["open"]) == ("blocked", False)
    answered = client.post(f"/api/questions/{question['id']}/answer", json={"answer": "Postgres"})
    assert answered.status_code == 200, answered.text
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert posts(snap)[:2] == [("blocked", "Coder", "Which database is it for?"),
                               ("said", "You", "Postgres")]
    assert snap["room_posts"][1]["reply_to"] == 1
    assert "The user answered: Postgres" in results(snap, "Coder", "post_to_room")[0][1]
    # the other member waited for the user's word too, and was handed it
    assert "Postgres" in asked(model, "Reviewer")[3]
    assert snap["rooms"][0]["outcome"] == "agreed"


def test_a_review_is_for_one_member_and_everybody_reads_it(make_client, wait_run, project_dir):
    client, model, cid, run_id, _room = start(make_client, project_dir, {
        "Coder": [text("Nothing to add."), wait(), text("Read it.")],
        "Reviewer": [text("Nothing to add."),
                     step(post("review", "Line 1 greets nobody by name.", to="Coder")),
                     text("Reviewed.")],
        "Tester": [text("Nothing to add."), wait(), text("Read it too.")],
    }, members=("Coder", "Reviewer", "Tester"))
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    review = snap["room_posts"][0]
    assert (review["type"], review["open"], review["number"]) == ("review", False, 1)
    assert review["to_agent_id"] == agent(snap, "Coder")["id"]
    # the one it is for is told so; the third member reads it as said to the Coder
    for_coder = next(m["content"] for m in model.calls_of["Coder"][2]
                     if "Line 1 greets nobody" in str(m["content"]))
    assert "Said in the room" in for_coder and "Reviewer (review, to you)" in for_coder
    for_tester = next(m["content"] for m in model.calls_of["Tester"][2]
                      if "Line 1 greets nobody" in str(m["content"]))
    assert "Reviewer (review, to Coder)" in for_tester
    # what a member is handed of the room is on its own record, as it read it
    handed = [m for m in snap["messages"] if m["room_post_id"] == review["id"]]
    assert sorted(m["agent_id"] for m in handed) == sorted(
        agent(snap, name)["id"] for name in ("Coder", "Tester"))
    assert snap["rooms"][0]["outcome"] == "agreed"


# --- who is told what, and who is woken ----------------------------------------------------


def test_a_post_that_comes_as_a_member_sets_out_to_wait_still_wakes_it(
    make_client, wait_run, project_dir, monkeypatch
):
    """B-201: something said between the member's look at what it has not read and its
    wait - where an await on the way would let one in - is one it wakes for."""
    real = AgentRunner._unread
    said = []

    def unread(self, room, member, question=False):
        found = real(self, room, member, question)
        if not question and member.ctx.name == "Coder" and not said:
            said.append(self._post_room(room, None, "said", "Meanwhile, keep it short."))
        return found

    monkeypatch.setattr(AgentRunner, "_unread", unread)
    held, woke = Gate(), Gate()
    client, model, cid, run_id, _room = start(make_client, project_dir, {
        "Coder": [text("Nothing to add."), wait(), woke.step(text("Kept it short."))],
        # at work all along: nobody else's post would wake the Coder meanwhile
        "Reviewer": [text("Nothing to add."), held.step(text("Reviewed."))],
    })
    woke.wait_partial()
    assert not held.released
    assert "Meanwhile, keep it short." in asked(model, "Coder")[2]
    # at work again, and on record so: not left "waiting" for a post it was given
    assert member(now_snap(client, cid), "Coder")["status"] == "in"
    held.release()
    woke.release()
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert snap["rooms"][0]["outcome"] == "agreed"


def test_before_each_step_a_member_is_told_how_the_room_stands(make_client, wait_run, project_dir):
    client, model, cid, run_id, _room = start(make_client, project_dir, {
        "Coder": [step(add("Change the greeting", ["hello.py"], "a1"), take(1, "t1")),
                  step(post("question", "Shall it say yo?", "q")),
                  wait(), step(finish(1, "left as it is", "f")), text("Done.")],
        "Reviewer": [text("I only review."), wait(),
                     step(post("answer", "No.", "ans", reply_to=1)), text("Answered.")],
    }, budget={"posts": 9, "tokens": None})
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    sharing, _waits, answering, _last = (calls[-1]["content"] for calls in model.calls_of["Reviewer"])
    # in the round before the work: what that round is, and the list as the Coder left it
    assert "shared out" in sharing and '"Change the greeting" (hello.py) - taken by Coder' in sharing
    assert "The others: Coder - at work" in sharing
    # at the step after the question: it is open, by its number, and the budget is said
    assert "Open questions" in answering and 'post 1, from Coder: "Shall it say yo?"' in answering
    assert "1 of 9 posts" in answering and "tokens" not in answering.split("Spent of its budget")[1]
    # only how it stands now is said: what was said a step ago is not said again
    assert sum("The room now" in str(m["content"]) for m in model.calls_of["Reviewer"][-1]) == 1
    # every member is told once how a room works, and who is in it with it
    system = model.calls_of["Coder"][0][0]["content"]
    assert "You are in a room with Reviewer" in system and "Your task comes from the user" in system
    # what was said without a tool in the sharing round is not in the room
    assert "I only review." not in [said for _kind, _who, said in posts(snap)]


def test_a_question_for_a_member_whose_work_is_over_takes_it_back_to_work(
    make_client, wait_run, project_dir
):
    client, model, cid, run_id, _room = start(make_client, project_dir, {
        "Coder": [text("Nothing to add."), wait("w1"),            # until the Reviewer is done
                  step(post("question", "Did you look at line 1?", "q", to="Reviewer")),
                  wait("w2"), text("Thanks.")],
        "Reviewer": [text("Nothing to add."), text("Done early."),
                     step(post("answer", "I did: it is fine.", "ans", reply_to=2)),
                     text("Answered.")],
    })
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert posts(snap) == [
        ("done", "Reviewer", "Done early."),
        ("question", "Coder", "Did you look at line 1?"),
        ("answer", "Reviewer", "I did: it is fine."),
        ("done", "Reviewer", "Answered."),
        ("done", "Coder", "Thanks."),
    ]
    assert not [p for p in snap["room_posts"] if p["open"]]
    assert "Did you look at line 1?" in asked(model, "Reviewer")[2]
    reviewer = agent(snap, "Reviewer")
    assert (reviewer["status"], reviewer["report"]) == ("completed", "Answered.")
    assert snap["rooms"][0]["outcome"] == "agreed"


@pytest.mark.parametrize("limit, raised", [(2, None), (1, 2)])
def test_a_member_woken_again_has_its_roles_steps_as_they_stand_each_time(
    make_client, wait_run, project_dir, limit, raised
):
    """B-325: each time a member is woken its steps count on their own - a Reviewer that used
    its one step of two before the question still answers it - and under its role's limit as
    it stands then: raised from 1 to 2 while it waited, it takes both."""
    gate = Gate()

    def limited(client):
        assert client.patch(f"/api/roles/{role_id(client, 'Reviewer')}",
                            json={"max_steps": limit}).status_code == 200

    client, model, cid, run_id, _room = room_in(make_client, project_dir, {
        "Coder": [text("Nothing to add."), wait("w1"),
                  gate.step(step(post("question", "Did you look at line 1?", "q", to="Reviewer"))),
                  wait("w2"), text("Thanks.")],
        "Reviewer": [text("Nothing to add."), text("Done early."),
                     step(post("answer", "I did: it is fine.", "ans", reply_to=2)),
                     text("Answered.")],
    }, before=limited)
    gate.wait_partial()
    if raised is not None:
        assert client.patch(f"/api/roles/{role_id(client, 'Reviewer')}",
                            json={"max_steps": raised}).status_code == 200
    gate.release()
    snap = wait_run(client, cid, run_id, timeout=LONG)
    reviewer = agent(snap, "Reviewer")
    assert (reviewer["status"], reviewer["report"]) == ("completed", "Answered."), reviewer
    assert snap["rooms"][0]["outcome"] == "agreed"


def test_a_question_asked_while_the_other_took_its_last_step_still_reaches_it(
    make_client, wait_run, project_dir
):
    held = Gate()
    client, model, cid, run_id, _room = start(make_client, project_dir, {
        # its last step is under way when the question is asked: it never read it there
        "Reviewer": [text("Nothing to add."), held.step(text("Done.")), text("I do not know.")],
        "Coder": [text("Nothing to add."), step(post("question", "Anybody?", "q")),
                  wait(), text("So be it.")],
    }, members=("Reviewer", "Coder"))
    until(client, cid, lambda s: [p["type"] for p in s["room_posts"]] == ["question"],
          timeout=LONG)
    held.release()
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert "Anybody?" in asked(model, "Reviewer")[2]            # handed to it when it went on
    # nobody answered it, and nobody is left to: that is not "agreed", and the lead is told -
    # last words close no question that was for nobody in particular (B-156: only one for it)
    (ended,) = snap["rooms"]
    assert (ended["status"], ended["outcome"], ended["why"]) == ("ended", "too_few", "unanswered")
    assert [p["open"] for p in snap["room_posts"] if p["type"] == "question"] == [True]
    told = asked(model, "Lead")[0]
    assert "Left open" in told and "Anybody?" in told
    # its own reason, not that fewer than two were left
    assert "nobody left to answer it" in told and "fewer than two" not in told


def test_a_question_to_a_member_whose_work_is_over_is_answered_by_its_last_words(
    make_client, wait_run, project_dir
):
    """B-156 (live): the Coder asked the Tester after the Tester's work was over; the Tester was
    woken, said its answer without post_to_room, and the room ended with the question open."""
    client, model, cid, run_id, _room = start(make_client, project_dir, {
        "Tester": [text("Nothing to add."), text("Tests pass."), text("Yes: all 7 passed.")],
        "Coder": [text("Nothing to add."), wait("w1"),
                  step(post("question", "Did the median tests pass?", "q", to="Tester")),
                  wait("w2"), text("Good, done.")],
    }, members=("Tester", "Coder"))
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    question = next(p for p in snap["room_posts"] if p["type"] == "question")
    assert not question["open"]
    answer = next(p for p in snap["room_posts"] if p["text"] == "Yes: all 7 passed.")
    assert (answer["type"], answer["reply_to"]) == ("done", question["number"])
    assert "replying to post" in asked(model, "Coder")[-1]      # the Coder read it as the reply
    assert snap["rooms"][0]["outcome"] == "agreed"


def test_a_member_whose_work_is_over_takes_no_step_for_a_question_answered_before_its_turn(
    make_client, wait_run, project_dir
):
    """B-169 (live): "Anybody?" woke both members that were done; the Reviewer answered, and the
    Docs writer, woken after that, spent a step on it and wrote a second done. With one place,
    the Tester waits behind the Reviewer here: by its turn the question is answered."""
    client, model, cid, run_id, _room = start(make_client, project_dir, {
        "Reviewer": [text("Nothing to add."), text("Done early."),
                     step(post("answer", "It is fine.", "ans", reply_to=3)), text("Answered.")],
        "Tester": [text("Nothing to add."), text("Tests pass."), text("I did not answer it.")],
        "Coder": [text("Nothing to add."), wait("w1"), wait("w2"),
                  step(post("question", "Anybody?", "q")), wait("w3"), text("Thanks.")],
    }, members=("Reviewer", "Tester", "Coder"), spawn_max_parallel=1)
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert posts(snap) == [
        ("done", "Reviewer", "Done early."),
        ("done", "Tester", "Tests pass."),
        ("question", "Coder", "Anybody?"),
        ("answer", "Reviewer", "It is fine."),
        ("done", "Reviewer", "Answered."),
        ("done", "Coder", "Thanks."),
    ]
    assert len(model.calls_of["Tester"]) == 2                   # no step for it
    tester = agent(snap, "Tester")
    assert (tester["status"], tester["report"]) == ("completed", "Tests pass.")
    assert snap["rooms"][0]["outcome"] == "agreed"


def test_a_question_to_a_member_that_left_is_left_unanswered_and_the_lead_is_told(
    make_client, wait_run, project_dir
):
    client, model, cid, run_id, _room = start(make_client, project_dir, {
        "Tester": [text("Nothing to add."), ModelUnavailable("the model went away")],
        "Coder": [text("Nothing to add."),
                  step(post("question", "Anybody ran the tests?", "q", to="Tester")),
                  text("So be it.")],
        "Reviewer": [text("Nothing to add."), text("Nothing from me.")],
    }, members=("Tester", "Coder", "Reviewer"))
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    # nobody answered it, and nobody is left to: that is not "agreed", and the lead is told
    (ended,) = snap["rooms"]
    assert (ended["status"], ended["outcome"], ended["why"]) == ("ended", "too_few", "unanswered")
    assert [p["open"] for p in snap["room_posts"] if p["type"] == "question"] == [True]
    told = asked(model, "Lead")[0]
    assert "Left open" in told and "Anybody ran the tests?" in told
    # its own reason, not that fewer than two were left
    assert "nobody left to answer it" in told and "fewer than two" not in told


def test_a_paused_room_posts_nothing_and_asks_no_model_until_it_is_resumed(
    make_client, wait_run, project_dir
):
    """29c: Pause lets the step at hand finish - its model is not cut off - and then nothing:
    the post that step asked for waits, no model is asked, the clock stands. Resume goes on."""
    held = Gate()
    client, model, cid, run_id, room = start(make_client, project_dir, {
        "Coder": [text("Nothing to add."), held.step(step(post("result", "It is fixed.", "p"))),
                  text("Done.")],
        "Reviewer": [text("Nothing to add."), wait(), text("Looks fine.")],
    })
    held.wait_partial()
    # the user's, from the app's own page: not a command that says nothing of where it is from
    assert client.post(f"/api/rooms/{room['id']}/pause", headers={"Origin": ""}).status_code == 403
    paused = client.post(f"/api/rooms/{room['id']}/pause")
    assert paused.status_code == 200, paused.text
    assert paused.json()["paused"] is True
    asked_so_far = len(model.calls)
    held.release()
    time.sleep(1.0)
    snap = now_snap(client, cid)
    assert [p for p in snap["room_posts"] if p["type"] == "result"] == []    # held before posting
    assert len(model.calls) == asked_so_far                                 # and no model asked
    (now,) = snap["rooms"]
    assert (now["status"], now["paused"]) == ("working", True)
    assert agent(snap, "Coder")["status"] == "waiting"                      # its place is free
    (held_room,) = client.app.state.runner._rooms.values()
    assert held_room.since is None                                          # the clock stands
    resumed = client.post(f"/api/rooms/{room['id']}/resume")
    assert resumed.status_code == 200 and resumed.json()["paused"] is False
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert ("result", "Coder", "It is fixed.") in posts(snap)
    (ended,) = snap["rooms"]
    assert (ended["outcome"], ended["paused"]) == ("agreed", False)
    assert client.post(f"/api/rooms/{room['id']}/pause").status_code == 409  # over: no pause


def test_a_last_step_that_ends_while_paused_says_nothing_and_ends_nothing_until_resume(
    make_client, wait_run, project_dir
):
    """29c: its "done" would end the room - and take its copy into the project - while paused."""
    held = Gate()
    client, _model, cid, run_id, room = start(make_client, project_dir, {
        "Coder": [text("Nothing to add."), held.step(text("Done."))],
        "Reviewer": [text("Nothing to add."), wait(), text("Fine.")],
    })
    held.wait_partial()
    assert client.post(f"/api/rooms/{room['id']}/pause").status_code == 200
    held.release()
    time.sleep(1.0)
    snap = now_snap(client, cid)
    assert [p for p in snap["room_posts"] if p["type"] == "done"] == []
    assert (snap["rooms"][0]["status"], snap["rooms"][0]["paused"]) == ("working", True)
    assert snap["runs"][0]["status"] == "running"
    assert client.post(f"/api/rooms/{room['id']}/resume").status_code == 200
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert ("done", "Coder", "Done.") in posts(snap)
    assert snap["rooms"][0]["outcome"] == "agreed"


def test_a_paused_room_can_still_be_ended(make_client, wait_run, project_dir):
    held = Gate()
    client, _model, cid, run_id, room = start(make_client, project_dir, {
        "Coder": [text("Nothing to add."), held.step(step(post("result", "never posted", "p")))],
        "Reviewer": [text("Nothing to add."), wait(), text("never said")],
    })
    held.wait_partial()
    assert client.post(f"/api/rooms/{room['id']}/pause").status_code == 200
    held.release()
    assert client.post(f"/api/rooms/{room['id']}/end").status_code == 200
    snap = wait_run(client, cid, run_id, timeout=LONG)
    (ended,) = snap["rooms"]
    assert (ended["status"], ended["outcome"], ended["paused"]) == ("ended", "ended_by_user", False)
    assert "never posted" not in [p["text"] for p in snap["room_posts"]]


def test_a_member_that_stops_at_a_limit_has_left_and_the_others_are_told(
    make_client, wait_run, project_dir
):
    def two_steps(client):
        assert client.patch(f"/api/roles/{role_id(client, 'Coder')}",
                            json={"max_steps": 2}).status_code == 200

    reads = [step(call("read_file", {"path": "hello.py"}, f"r{i}")) for i in range(2)]
    client, model, cid, run_id, _room = room_in(make_client, project_dir, {
        "Coder": [step(add("Change the greeting", ["hello.py"], "a1"), take(1, "t1")), *reads,
                  text("never said")],
        "Reviewer": [text("Nothing to add."), wait(), step(take(1, "t2")),
                     step(finish(1, "left as it is", "f")), text("Done.")],
        "Tester": [text("Nothing to add."), wait(), text("Done.")],
    }, members=[{"role": "Coder"}, {"role": "Reviewer"}, {"role": "Tester"}], before=two_steps)
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    coder = agent(snap, "Coder")
    assert coder["status"] == "failed" and "limit of 2 steps" in coder["error"]
    assert member(snap, "Coder")["status"] == "left"
    # KOLONİ says so in the room: why, and that what it held is nobody's again
    kind, who, said = posts(snap)[0]
    assert (kind, who) == ("left", "Coder") and "limit of 2 steps" in said and "item 1" in said
    assert "Coder left the room" in asked(model, "Reviewer")[2]
    # two are left, and the room goes on: the item is taken up and done
    assert items(snap) == [(1, "Change the greeting", "done", "Reviewer")]
    assert snap["rooms"][0]["outcome"] == "agreed"
    assert len(model.calls_of["Coder"]) == 3                    # the fourth step was not taken


# --- the budgets ----------------------------------------------------------------------------


def billed(client, agent_ids):
    """What these agents sent and wrote, as usage counts it."""
    from app.db.models import Agent
    with client.app.state.session_factory() as session:
        return sum((one.input_tokens_total or 0) + (one.output_tokens or 0)
                   for one in map(lambda id: session.get_one(Agent, id), agent_ids))


def test_a_room_ends_at_its_tokens_and_a_member_that_waited_is_done_with_it(
    make_client, wait_run, project_dir
):
    read = call("read_file", {"path": "hello.py"}, "r")
    client, model, cid, run_id, room = start(make_client, project_dir, {
        # 8 for each sharing step and 7 for the Reviewer's one of its own, then 70: 93 of
        # 100 - and with the next 70 it is reached
        "Coder": [text("Nothing to add."), step(read, i=60, o=10),
                  step(call("read_file", {"path": "hello.py"}, "r2"), i=60, o=10),
                  text("never said")],
        "Reviewer": [text("Nothing to add."), wait(), text("never said")],
    }, budget={"tokens": 100, "posts": None})
    assert room["budget"] == {"posts": None, "tokens": 100, "minutes": 30}
    snap = wait_run(client, cid, run_id, timeout=LONG)
    (ended,) = snap["rooms"]
    assert (ended["status"], ended["outcome"]) == ("ended", "budget")
    assert ended["spent"]["tokens"] == 163 and ended["spent"]["posts"] == 0
    # B-390: what its members' steps sent and wrote while it ran, as billed - each step once
    assert billed(client, [agent(snap, name)["id"] for name in ("Coder", "Reviewer")]) == 163
    assert ended["why"] == "tokens"
    assert "budget of tokens" in asked(model, "Lead")[0]
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    # the one that waited when it ended: its call cut short, and still on record as having
    # waited - and (B-386) done with the room, not stopped: only Stop or a failure stops one
    reviewer = agent(snap, "Reviewer")
    assert reviewer["status"] == "completed" and member(snap, "Reviewer")["status"] == "waiting"
    assert results(snap, "Reviewer", "wait_for_post")[0][0] == "interrupted"
    assert agent(snap, "Coder")["status"] == "completed"
    assert len(model.calls_of["Coder"]) == 3                    # no step after the limit


def test_a_room_counts_every_step_its_members_sent_as_usage_does_not_their_cards_in(
    make_client, wait_run, project_dir
):
    # B-390 (R188): each step resends the context, so the room is many times the cards' "in" -
    # which is the last prompt's size, not spend. The room counts what was billed, as the Usage
    # page does (the user, 6 Nov): each step once, nothing twice.
    def reads(*sizes):
        return [step(call("read_file", {"path": "hello.py"}, f"r{n}"), i=size, o=10)
                for n, size in enumerate(sizes)]

    client, _model, cid, run_id, _room = start(make_client, project_dir, {
        "Coder": [text("Nothing to add."), *reads(100, 200, 300), text("Done.")],
        "Reviewer": [text("Nothing to add."), *reads(150, 250), text("Done.")],
    })
    snap = wait_run(client, cid, run_id, timeout=LONG)
    (ended,) = snap["rooms"]
    members = [agent(snap, name) for name in ("Coder", "Reviewer")]
    assert ended["outcome"] == "agreed"
    assert ended["spent"]["tokens"] == billed(client, [m["id"] for m in members]) == 1082
    cards = sum(m["input_tokens"] + m["output_tokens"] for m in members)
    assert cards < ended["spent"]["tokens"]


def test_a_room_ends_at_its_minutes_and_more_can_be_given_while_it_runs(
    make_client, wait_run, project_dir
):
    held = Gate()
    clock = HeldClock()
    client, model, cid, run_id, room = room_in(make_client, project_dir, {
        "Coder": [text("Nothing to add."), held.step(text("never said"))],
        "Reviewer": [text("Nothing to add."), wait(), text("never said")],
    }, budget={"minutes": 2}, before=lambda c: setattr(c.app.state.runner, "call_later", clock))
    held.wait_partial()
    assert len(clock.set) == 1 and 2 * 60 - 30 < clock.set[0].delay <= 2 * 60
    more = client.post(f"/api/rooms/{room['id']}/more", json={"minutes": 3, "tokens": 5})
    assert more.status_code == 200, more.text
    # (more tokens for a room with no limit of them: still none - R185)
    assert more.json()["budget"] == {"posts": 40, "tokens": None, "minutes": 5}
    # the clock is set anew, for what is left of the five
    assert clock.set[0].cancelled and 5 * 60 - 30 < clock.set[1].delay <= 5 * 60
    assert client.post(f"/api/rooms/{room['id']}/more", json={}).status_code == 422
    assert client.post(f"/api/rooms/{room['id']}/more", json={"posts": 0}).status_code == 422
    on_loop(client, clock.set[1].fire)
    snap = wait_run(client, cid, run_id, timeout=LONG)
    held.release()
    (ended,) = snap["rooms"]
    assert (ended["status"], ended["outcome"]) == ("ended", "budget")
    assert "budget of minutes" in asked(model, "Lead")[0]
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    # a room that is over is given nothing more
    assert client.post(f"/api/rooms/{room['id']}/more", json={"posts": 1}).status_code == 409
    assert client.post(f"/api/rooms/{room['id']}/end").status_code == 409


def test_what_a_room_may_spend_is_the_conversations_unless_the_user_says_otherwise(
    make_client, wait_run, project_dir
):
    client, _model, cid, run_id, room = room_in(make_client, project_dir, {
        "Coder": [text("Nothing to add."), text("Done.")],
        "Reviewer": [text("Nothing to add."), text("Done.")],
    }, budget={"tokens": 9000}, room_posts=7, room_minutes=None)
    conversation = now_snap(client, cid)["conversation"]
    assert (conversation["room_posts"], conversation["room_tokens"],
            conversation["room_minutes"]) == (7, None, None)  # (no tokens by default: R185)
    # the conversation's posts, the room's own tokens, and no limit of minutes
    assert room["budget"] == {"posts": 7, "tokens": 9000, "minutes": None}
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["rooms"][0]["outcome"] == "agreed"
    assert client.patch(f"/api/conversations/{cid}", json={"room_posts": 0}).status_code == 422
    # what a room may spend is leave to spend: set from the app's own page only
    assert client.patch(f"/api/conversations/{cid}", json={"room_posts": 500},
                        headers={"Origin": "http://evil.example"}).status_code == 403
    assert now_snap(client, cid)["conversation"]["room_posts"] == 7
    # a limit a room does not have stays none, whatever is added
    again = client.post(f"/api/conversations/{cid}/rooms", json={
        "goal": "Once more", "with": TWO, "budget": {"posts": None}})
    assert again.status_code == 201 and again.json()["room"]["budget"]["posts"] is None


# --- more than two --------------------------------------------------------------------------


def test_three_and_four_members_share_in_the_order_named_and_work_two_at_a_time(
    make_client, wait_run, project_dir
):
    for crowd in (("Tester", "Coder", "Reviewer"), ("Coder", "Coder", "Reviewer", "Tester")):
        called = [name if crowd[:at].count(name) == 0 else f"{name} {crowd[:at].count(name) + 1}"
                  for at, name in enumerate(crowd)]
        client, model, cid, run_id, room = start(
            make_client, project_dir,
            {name: [step(add(f"The part of {name}", id="a"), take(at + 1, "t")),
                    step(finish(at + 1, f"{name} did it", "f")), text(f"{name} is done.")]
             for at, name in enumerate(called)},
            members=crowd)
        assert len(room["members"]) == len(crowd)
        snap = wait_run(client, cid, run_id, timeout=LONG)
        assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
        # a step each first, in the order the user named them - then the work
        assert [said_by(model, at) for at in range(len(crowd))] == called
        assert [a["name"] for a in snap["agents"]] == ["Lead", *called]
        assert items(snap) == [
            (at + 1, f"The part of {name}", "done", name) for at, name in enumerate(called)]
        assert snap["rooms"][0]["outcome"] == "agreed"
        assert [m["status"] for m in snap["rooms"][0]["members"]] == ["done"] * len(crowd)
        told = asked(model, "Lead")[0]
        assert all(f"{name} did it" in told for name in called)


def test_five_is_refused_and_so_is_more_than_the_conversation_lets_a_turn_open(
    make_client, project_dir
):
    client, _model = make_client({})
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    assert client.patch(f"/api/conversations/{cid}", json={"spawn_max_agents": 2}).status_code == 200
    rooms = f"/api/conversations/{cid}/rooms"
    three = client.post(rooms, json={"goal": "x", "with": [*TWO, {"role": "Tester"}]})
    assert three.status_code == 422 and "2 sub-agent" in three.text
    assert now_snap(client, cid)["runs"] == []                  # nothing was started


# --- who a member runs on --------------------------------------------------------------------


def test_a_member_runs_where_the_user_says_and_is_opened_without_a_card(
    make_client, wait_run, project_dir
):
    def other_provider(client):
        made = client.post("/api/providers", json={
            "name": "Other", "kind": "openai_compat", "base_url": "http://127.0.0.1:9/v1",
            "default_model": "other-default"})
        assert made.status_code == 201, made.text

    client, _model, cid, run_id, _room = room_in(make_client, project_dir, {
        "Coder": [text("Nothing to add."), text("Done.")],
        "Reviewer": [text("Nothing to add."), text("Done.")],
    }, members=[{"role": "Coder", "provider": "other", "model": "special"},
                {"role": "Reviewer", "provider": "Other"}],
        before=other_provider, spawn_approval="always")
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    coder, reviewer = agent(snap, "Coder"), agent(snap, "Reviewer")
    assert (coder["provider_name"], reviewer["provider_name"]) == ("Other", "Other")
    # the user's own choice: not an agent's pick, and nobody was asked about either
    assert not coder["chosen"] and not reviewer["chosen"]
    assert coder["parent_agent_id"] == agent(snap, "Lead")["id"] and coder["task"] == "Work on it together"
    assert {"add_item", "wait_for_post"} <= set(coder["tools"])
    with client.app.state.session_factory() as session:
        named = {m.role: m.model_id for m in session.query(RoomMember)}
    assert named == {"Coder": "special", "Reviewer": None}       # its default: nothing named


def test_who_cannot_be_a_member_is_said_before_anything_is_started(make_client, project_dir):
    client, _model = make_client({})
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    assert client.post("/api/providers", json={
        "name": "Own tools", "kind": "codex_cli", "mode": "native"}).status_code == 201
    rooms = f"/api/conversations/{cid}/rooms"

    def refused(with_, *words):
        answer = client.post(rooms, json={"goal": "x", "with": [{"role": "Coder"}, with_]})
        assert answer.status_code == 422 and all(word in answer.text for word in words), answer.text

    refused({"role": "Reviewer", "provider": "Nowhere"}, "unknown provider")
    refused({"role": "Reviewer", "model": "m"}, "model needs provider")
    # a CLI at work with tools of its own cannot be held to the room's list of items
    refused({"role": "Reviewer", "provider": "Own tools"}, "tools of its own", "Reviewer")
    assert now_snap(client, cid)["runs"] == []
    # opening a room opens agents without a card: it is the user's, from the app's own page
    del client.headers["Origin"]
    assert client.post(rooms, json={"goal": "x", "with": TWO}).status_code == 403


# --- places ---------------------------------------------------------------------------------


def test_a_member_that_waits_for_a_post_holds_no_place(make_client, wait_run, project_dir):
    held = Gate()
    client, _model, cid, run_id, room = start(make_client, project_dir, {
        "Reviewer": [text("Nothing to add."), wait(), text("Done.")],
        "Coder": [text("Nothing to add."), held.step(text("Done."))],
    }, members=("Reviewer", "Coder"), spawn_max_parallel=1)
    # one place in the turn: the Coder has it, for the Reviewer left it to wait
    held.wait_partial()
    snap = until(client, cid, lambda s: agent(s, "Reviewer")["status"] == "waiting", timeout=LONG)
    assert agent(snap, "Coder")["status"] == "running"
    assert member(snap, "Reviewer")["status"] == "waiting" and member(snap, "Coder")["status"] == "in"
    assert client.app.state.runner.at_work(str(project_dir)) == 1
    assert client.get(f"/api/conversations/{cid}").json()["rooms"][0]["id"] == room["id"]
    held.release()
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["rooms"][0]["outcome"] == "agreed"
    assert client.app.state.runner.at_work(str(project_dir)) == 0


def test_the_projects_limit_on_agents_at_work_holds_in_a_room(make_client, wait_run, project_dir):
    held = Gate()
    client, _model, cid, run_id, _room = room_in(make_client, project_dir, {
        "Coder": [text("Nothing to add."), held.step(text("Done."))],
        "Reviewer": [text("Nothing to add."), text("Done.")],
    }, project={"max_agents": 1})
    held.wait_partial()
    # the project lets one agent work: the second member stands in line, its model unasked
    snap = until(client, cid, lambda s: agent(s, "Reviewer")["status"] == "queued", timeout=LONG)
    assert agent(snap, "Coder")["status"] == "running" and agent(snap, "Lead")["status"] == "waiting"
    assert client.app.state.runner.at_work(str(project_dir)) == 1
    held.release()
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert snap["rooms"][0]["outcome"] == "agreed"


def test_a_rooms_minutes_are_not_counted_while_it_is_only_kept_waiting_for_room(
    make_client, wait_run, project_dir
):
    """As an unattended turn's (slice 26): the clock is put away while none of the
    room's members has a place and one stands in line, and set again for what is left."""
    first = Gate()
    clock = HeldClock()
    client, _model = make_client({
        "Lead": [first.step(text("A done")), text("The room is over.")],
        "Coder": [text("Nothing to add."), text("Done.")],
        "Reviewer": [text("Nothing to add."), text("Done.")],
    })
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    assert client.patch(f"/api/projects/{pid}", json={"max_agents": 1}).status_code == 200
    a, b = (client.post(f"/api/projects/{pid}/conversations").json()["id"] for _ in range(2))
    run_a = client.post(f"/api/conversations/{a}/messages", json={"content": "go"}).json()["run"]["id"]
    first.wait_partial()                                        # the project's one place is taken
    client.app.state.runner.call_later = clock
    opened = client.post(f"/api/conversations/{b}/rooms", json={"goal": "x", "with": TWO})
    assert opened.status_code == 201, opened.text
    run_b = opened.json()["run"]["id"]
    until(client, b, lambda s: len(s["agents"]) == 3 and agent(s, "Coder")["status"] == "queued",
          timeout=LONG)
    deadline = time.monotonic() + 5
    while not (clock.set and clock.set[-1].cancelled):
        assert time.monotonic() < deadline, "the clock is put away while it stands in line"
        time.sleep(0.02)
    assert now_snap(client, b)["rooms"][0]["spent"]["minutes"] == 0
    first.release()
    assert wait_run(client, a, run_a, timeout=LONG)["runs"][0]["status"] == "completed"
    snap = wait_run(client, b, run_b, timeout=LONG)
    assert snap["rooms"][0]["outcome"] == "agreed"
    assert len(clock.set) >= 2 and 30 * 60 - 30 < clock.set[-1].delay <= 30 * 60


# --- the room's one copy, on its way into the project ----------------------------------------


def with_lines(project_dir):
    (project_dir / "lines.txt").write_bytes(LINES.encode())
    (project_dir / "check.py").write_bytes(CHECK.encode())


def lines_coder(held, old="two", new="TWO-agent"):
    return [step(add("Change a line", ["lines.txt"], "a1"), take(1, "t1")),
            step(edit(old, new, path="lines.txt")),
            held.step(step(finish(1, "changed", "f1"))), text("Done.")]


@needs_git
def test_the_rooms_copy_meets_the_project_like_any_copy_a_clash_is_asked_about(
    make_client, wait_run, project_dir
):
    with_lines(project_dir)
    held = Gate()
    client, model, cid, run_id, _room = start(make_client, project_dir, {
        "Coder": lines_coder(held),
        "Reviewer": [text("Nothing to add."), text("Done.")],
    })
    held.wait_partial()
    meanwhile(project_dir, "two", "TWO-user")                   # the same line, in the project
    held.release()
    merge = card(client, cid)                                   # asked, even in full auto
    snap = now_snap(client, cid)
    # the card is the room's: in the name of the lead, who holds the copy and took no part
    assert merge["agent_id"] == agent(snap, "Lead")["id"]
    assert (snap["rooms"][0]["status"], snap["rooms"][0]["outcome"]) == ("ended", "agreed")
    assert of(merge)["state"] == "conflict" and lines(project_dir)[1] == "TWO-user"
    assert client.post(f"/api/merges/{merge['id']}/approve",
                       json={"choices": {"lines.txt": "project"}, "shown": seen(merge)}).status_code == 200
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert lines(project_dir)[1] == "TWO-user"
    # what did not reach the project is said to the lead, as the room's
    assert "the room" in asked(model, "Lead")[0] and "TWO-agent" not in (
        project_dir / "lines.txt").read_text(encoding="utf-8")


@needs_git
def test_the_projects_check_runs_on_the_rooms_copy_and_lines_of_both_go_together(
    make_client, wait_run, project_dir
):
    with_lines(project_dir)
    held = Gate()
    client, _model, cid, run_id, _room = room_in(make_client, project_dir, {
        "Coder": lines_coder(held),
        "Reviewer": [text("Nothing to add."), text("Done.")],
    }, project={"check_command": "python check.py TWO-agent SIX-user"})
    held.wait_partial()
    meanwhile(project_dir, "six", "SIX-user")                   # another line: no clash
    held.release()
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    (merge,) = snap["merges"]
    assert (merge["status"], merge["check"]["state"], merge["check"]["exit_code"]) == (
        "applied", "passed", 0)
    assert lines(project_dir)[1] == "TWO-agent" and lines(project_dir)[5] == "SIX-user"
    # the check is nobody's call: a command of the lead's, which holds the room's copy
    (check,) = [c for c in snap["commands"] if c["command"].startswith("python check.py")]
    assert check["tool_call_id"] is None and check["agent_id"] == agent(snap, "Lead")["id"]
    # the two sides went into the project as one change, which is nobody's call either
    (joined,) = [f for f in snap["file_changes"] if f["status"] == "applied"]
    assert joined["tool_call_id"] is None and joined["path"] == "lines.txt"


def test_a_room_that_did_not_end_with_everybody_done_is_not_taken_unasked(
    make_client, wait_run, project_dir
):
    held = Gate()
    client, _model, cid, run_id, room = start(make_client, project_dir, {
        "Coder": [step(add("Change the greeting", ["hello.py"], "a1"), take(1, "t1")),
                  step(edit("hi", "yo")), held.step(text("never said"))],
        "Reviewer": [text("Nothing to add."), text("Done.")],
    })
    held.wait_partial()
    assert client.post(f"/api/rooms/{room['id']}/end").status_code == 200
    merge = card(client, cid)                                   # full auto, and still asked
    held.release()
    assert (project_dir / "hello.py").read_text(encoding="utf-8") == "print('hi')\n"
    assert client.post(f"/api/merges/{merge['id']}/reject").status_code == 200
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert (project_dir / "hello.py").read_text(encoding="utf-8") == "print('hi')\n"
    assert items(snap) == [(1, "Change the greeting", "taken", "Coder")]    # as it was left


# --- after the room -------------------------------------------------------------------------


def test_after_the_room_its_members_are_the_leads_sub_agents_like_any_other(
    make_client, wait_run, project_dir
):
    client, model, cid, run_id, _room = room_in(make_client, project_dir, {
        "Coder": [text("Nothing to add."), text("Done."),
                  step(call("write_file", {"path": "notes.txt", "content": "n\n"}, "w")),
                  text("Written.")],
        "Reviewer": [text("Nothing to add."), text("Done.")],
    }, lead=[step(call("message_agent", {"to": "Coder", "message": "Write notes.txt too."}, "m")),
             text("All of it is done.")])
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    # no item is asked for any more, and the room's tools are gone with the room
    assert (project_dir / "notes.txt").read_text(encoding="utf-8") == "n\n"
    offered = names(model.tool_args[model.calls.index(model.calls_of["Coder"][2])])
    assert "write_file" in offered and not {"add_item", "post_to_room"} & set(offered)
    assert "You are in a room" not in model.calls_of["Coder"][2][0]["content"]
    # (Under the answer, KOLONİ's line on where the work is: B-205.)
    assert [m["content"] for m in snap["messages"][-2:]] == [
        "All of it is done.", "In the project: notes.txt (+1 −0)."]


def test_the_lead_of_a_later_turn_still_has_what_it_was_given_of_the_room(
    make_client, wait_run, project_dir
):
    client, model, cid, run_id, _room = room_in(make_client, project_dir, {
        "Coder": [step(add("Look at the greeting", id="a1"), take(1, "t1")),
                  step(finish(1, "it greets with hi", "f1")), text("Done.")],
        "Reviewer": [text("Nothing to add."), text("Done.")],
    }, lead=[text("The room found that it greets with hi."), text("As I said: hi.")])
    wait_run(client, cid, run_id, timeout=LONG)
    again = client.post(f"/api/conversations/{cid}/messages", json={"content": "What was it?"})
    snap = wait_run(client, cid, again.json()["run"]["id"], timeout=LONG)
    assert snap["messages"][-1]["content"] == "As I said: hi."
    first, second = asked(model, "Lead")
    assert "it greets with hi" in first and "it greets with hi" in second
    assert second.count("The user opened a room") == 1


# --- a restart ------------------------------------------------------------------------------


def test_a_room_that_was_running_is_interrupted_after_a_restart_and_nothing_is_made_up(tmp_path):
    db = tmp_path / "r.db"
    upgrade_db(db)
    factory = make_session_factory(make_engine(db))
    seed(factory, tmp_path)
    with factory() as s:
        s.add(Agent(id="k", run_id="r1", parent_agent_id="a", role_name="Coder", name="Coder",
                    tools=[], depth=1, status="waiting"))
        s.add(Room(id="o", run_id="r1", goal="g", status="working", max_posts=40, seconds=12.0,
                   clock_since=s.get(Run, "r1").created_at))
        s.add(Room(id="o2", run_id="r3", goal="g", status="ended", outcome="agreed"))
        s.flush()
        s.add(RoomMember(room_id="o", position=0, role="Coder", agent_id="k", status="waiting"))
        s.commit()
    recover_interrupted(factory)
    with factory() as s:
        room = s.get(Room, "o")
        assert (room.status, room.outcome, room.clock_since) == ("interrupted", None, None)
        assert room.ended_at is not None and room.seconds == 12.0      # as last written down
        assert (s.get(Room, "o2").status, s.get(Room, "o2").outcome) == ("ended", "agreed")
        assert s.get(Agent, "k").status == "interrupted"
        # its member is as it was last seen in the room: nobody says it finished
        assert s.query(RoomMember).one().status == "waiting"


def test_the_app_going_down_under_a_room_leaves_it_interrupted_and_its_copy_kept(
    settings_env, project_dir
):
    held = Gate()
    model = ScriptedModel({
        "Lead": [text("never said")],
        "Coder": [step(add("Change the greeting", ["hello.py"], "a1"), take(1, "t1")),
                  step(edit("hi", "yo")), held.step(text("never said"))],
        "Reviewer": [text("Nothing to add."), wait(), text("never said")],
    })
    settings = load_settings(settings_env)
    with TestClient(create_app(settings, model=model), base_url="http://127.0.0.1:8790") as client:
        client.headers["Origin"] = ORIGIN
        pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
        cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
        assert client.patch(
            f"/api/conversations/{cid}", json={"permission_mode": "full_auto"}).status_code == 200
        opened = client.post(f"/api/conversations/{cid}/rooms", json={"goal": "x", "with": TWO})
        assert opened.status_code == 201, opened.text
        held.wait_partial()
    held.release()
    with TestClient(create_app(settings, model=ScriptedModel([])),
                    base_url="http://127.0.0.1:8790") as client:
        snap = client.get(f"/api/conversations/{cid}").json()
        (room,) = snap["rooms"]
        assert (room["status"], room["outcome"]) == ("interrupted", None)
        assert snap["runs"][0]["status"] == "interrupted"
        assert {a["name"]: a["status"] for a in snap["agents"]} == {
            "Lead": "interrupted", "Coder": "interrupted", "Reviewer": "interrupted"}
        # what the Coder changed never reached the project: its copy is kept, as any is
        assert (project_dir / "hello.py").read_text(encoding="utf-8") == "print('hi')\n"
        (kept,) = snap["merges"]
        assert kept["status"] == "kept" and [f["path"] for f in kept["files"]] == ["hello.py"]
        assert kept["room_id"] == room["id"]  # (its card stays the room's)
        assert snap["room_items"][0]["status"] == "taken"       # as it stood


# --- the migration --------------------------------------------------------------------------

AT = "'2026-10-13 10:00:00'"


def test_migration_0039_and_back(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    alembic.upgrade(cfg, "0038")
    with sqlite3.connect(db) as conn:
        conn.execute(f"INSERT INTO projects (id, name, root_path, created_at) VALUES ('p', 'p', 'C:/p', {AT})")
        conn.execute("INSERT INTO conversations (id, project_id, title, created_at, updated_at) "
                     f"VALUES ('c', 'p', 't', {AT}, {AT})")
        conn.execute(f"INSERT INTO runs (id, conversation_id, status, created_at) VALUES ('r', 'c', 'completed', {AT})")
        conn.execute("INSERT INTO agents (id, run_id, role_name, name, tools, depth, status, created_at)"
                     f" VALUES ('a', 'r', 'Lead', 'Lead', '[]', 0, 'completed', {AT})")
        conn.execute("INSERT INTO messages (id, conversation_id, run_id, role, content, status, created_at)"
                     f" VALUES ('m', 'c', 'r', 'assistant', '', 'complete', {AT})")
        conn.execute("INSERT INTO tool_calls (id, run_id, agent_id, message_id, seq, provider_call_id,"
                     " name, arguments, status) VALUES ('t', 'r', 'a', 'm', 1, 't', 'run_command', '{}',"
                     " 'succeeded')")
        conn.execute("INSERT INTO commands (id, run_id, agent_id, tool_call_id, command, location, status,"
                     " timeout_seconds, origin, output, output_truncated, created_at) VALUES"
                     f" ('k1', 'r', 'a', 't', 'pytest', 'host', 'exited', 120, 'koloni', '', 0, {AT})")
    alembic.upgrade(cfg, "0039")
    with sqlite3.connect(db) as conn:
        # a conversation from before lets a room spend what a new one does
        assert conn.execute(
            "SELECT room_posts, room_tokens, room_minutes FROM conversations").fetchall() == [
            (40, 400_000, 30)]
        assert conn.execute("SELECT room_post_id FROM messages").fetchall() == [(None,)]
        assert conn.execute("SELECT id, tool_call_id FROM commands").fetchall() == [("k1", "t")]
        conn.execute("INSERT INTO rooms (id, run_id, goal, status, seconds, created_at) "
                     f"VALUES ('o', 'r', 'g', 'ended', 0, {AT})")
        conn.execute("INSERT INTO room_posts (id, room_id, number, type, text, open, created_at) "
                     f"VALUES ('s', 'o', 1, 'said', 'hi', 0, {AT})")
        # what only a room leaves: a command no call asked for, a post handed to a member
        conn.execute("INSERT INTO commands (id, run_id, agent_id, tool_call_id, command, location, status,"
                     " timeout_seconds, origin, output, output_truncated, created_at) VALUES"
                     f" ('k2', 'r', 'a', NULL, 'pytest', 'host', 'exited', 120, 'koloni', '', 0, {AT})")
        conn.execute("INSERT INTO messages (id, conversation_id, run_id, role, content, status,"
                     f" room_post_id, created_at) VALUES ('m2', 'c', 'r', 'agent', 'x', 'complete', 's', {AT})")
    alembic.downgrade(cfg, "0038")
    with sqlite3.connect(db) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert not {"rooms", "room_members", "room_items", "room_posts"} & tables
        assert "room_posts" not in [row[1] for row in conn.execute("PRAGMA table_info(conversations)")]
        assert conn.execute("SELECT id FROM commands").fetchall() == [("k1",)]
        assert conn.execute("SELECT id FROM messages").fetchall() == [("m",)]
        notnull = {row[1]: row[3] for row in conn.execute("PRAGMA table_info(commands)")}
        assert notnull["tool_call_id"] == 1
    alembic.upgrade(cfg, "0039")                                # and up again, as it was


def test_a_member_whose_model_fails_in_the_sharing_round_has_left_before_the_work(
    make_client, wait_run, project_dir
):
    client, model, cid, run_id, _room = start(make_client, project_dir, {
        "Coder": [ModelUnavailable("the model went away")],
        "Reviewer": [text("Nothing to add."), text("Done.")],
        "Tester": [text("Nothing to add."), text("Done.")],
    }, members=("Coder", "Reviewer", "Tester"))
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert [m["status"] for m in snap["rooms"][0]["members"]] == ["left", "done", "done"]
    assert snap["rooms"][0]["outcome"] == "agreed"              # two were left, and did it
    assert posts(snap)[0][:2] == ("left", "Coder") and "the model went away" in posts(snap)[0][2]
    assert len(model.calls_of["Coder"]) == 1


# --- a CLI that keeps its own loop ----------------------------------------------------------


def test_a_cli_session_is_a_member_like_any_other(cli_app, wait_run, project_dir):  # noqa: F811
    """Claude Code as it runs by default keeps its own loop: KOLONİ's tools reach it over
    MCP, and what a member is told before a step rides on a tool's result. Its one step
    before the work is its first message, with the calls that message makes. (The stand-in
    follows its script from the top each time it is started.)"""
    client, _provider, _model = cli_app("claude session", default_steps={
        "Lead": [text("The room is over.")],
        "Reviewer": [text("Nothing to add."), wait(), text("Looked at it.")],
    }, script=[
        {"call": "add_item", "args": {"title": "Change the greeting", "paths": ["hello.py"]},
         "message": "m1"},
        {"call": "take_item", "args": {"item": 1}, "message": "m1"},
        {"call": "edit_file", "args": {"path": "hello.py", "old_string": "hi", "new_string": "yo"}},
        {"call": "post_to_room", "args": {"type": "result", "text": "It says yo now."}},
        {"call": "finish_item", "args": {"item": 1, "result": "hello.py prints yo"}},
        {"say": "My part is done."},
    ])
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    assert client.patch(
        f"/api/conversations/{cid}", json={"permission_mode": "full_auto"}).status_code == 200
    opened = client.post(f"/api/conversations/{cid}/rooms", json={
        "goal": "Fix the greeting together",
        "with": [{"role": "Coder", "provider": "Cli"}, {"role": "Reviewer"}]})
    assert opened.status_code == 201, opened.text
    snap = wait_run(client, cid, opened.json()["run"]["id"], timeout=60)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert snap["rooms"][0]["outcome"] == "agreed"
    coder = agent(snap, "Coder")
    assert (coder["provider_name"], coder["status"], coder["report"]) == (
        "Cli", "completed", "My part is done.")
    # in the round before the work: its first message, and nothing after it
    taken = results(snap, "Coder", "take_item")
    assert taken[0][0] == "succeeded" and "yours already" in taken[1][1]
    assert len(results(snap, "Coder", "edit_file")) == 1
    assert items(snap)[0] == (1, "Change the greeting", "done", "Coder")
    assert (project_dir / "hello.py").read_text(encoding="utf-8") == "print('yo')\n"
    assert ("result", "Coder", "It says yo now.") in posts(snap)
    # at its work it had the room's tools beside its role's, and was told how the room stood
    record = cli_app.record()
    assert {"finish_item", "wait_for_post", "edit_file"} <= set(record["tools"])
    assert any("The room now" in str(result) for result in record["results"])


def test_a_cli_session_member_of_a_paused_room_is_not_started_until_it_is_resumed(
    cli_app, wait_run, project_dir  # noqa: F811
):
    """29c: a CLI keeps its own loop - held before its session starts, and before it is given a
    tool's answer, it asks its model nothing while the room is paused."""
    held = Gate()
    client, _provider, _model = cli_app("claude session", default_steps={
        "Lead": [text("The room is over.")],
        "Reviewer": [held.step(text("Nothing to add.")), text("Looked at it.")],
    }, script=[{"say": "My part is done."}])
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    assert client.patch(
        f"/api/conversations/{cid}", json={"permission_mode": "full_auto"}).status_code == 200
    opened = client.post(f"/api/conversations/{cid}/rooms", headers={"Origin": ORIGIN}, json={
        "goal": "Look at it together",
        "with": [{"role": "Reviewer"}, {"role": "Coder", "provider": "Cli"}]})
    assert opened.status_code == 201, opened.text
    room_id = opened.json()["room"]["id"]
    held.wait_partial()
    assert client.post(f"/api/rooms/{room_id}/pause").status_code == 200
    held.release()                          # the Reviewer's step finishes; the Coder's turn comes
    time.sleep(1.0)
    assert not cli_app.ran()                # its CLI was not started
    assert client.post(f"/api/rooms/{room_id}/resume", headers={"Origin": ORIGIN}).status_code == 200
    snap = wait_run(client, cid, opened.json()["run"]["id"], timeout=60)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert cli_app.ran() and snap["rooms"][0]["outcome"] == "agreed"


def test_a_members_own_sub_agent_works_under_the_members_items_in_the_rooms_copy(
    make_client, wait_run, project_dir
):
    client, model, cid, run_id, _room = start(make_client, project_dir, {
        "Coder": [step(add("Change the greeting", ["hello.py"], "a1"), take(1, "t1")),
                  step(call("spawn_agent", {"role": "Coder", "task": "Make hello.py say yo"}, "s")),
                  step(finish(1, "it says yo", "f1")), text("Done.")],
        # opened by a member: no member itself, so it has none of the room's tools
        "Coder 2": [step(call("write_file", {"path": "notes.txt", "content": "n\n"}, "w")),
                    step(edit("hi", "yo")), text("It says yo now.")],
        "Reviewer": [text("Nothing to add."), text("Done.")],
    }, spawn_approval="never")
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    helper = agent(snap, "Coder 2")
    assert (helper["depth"], helper["parent_agent_id"]) == (2, agent(snap, "Coder")["id"])
    assert not {"add_item", "post_to_room"} & set(helper["tools"])
    assert not {"add_item", "post_to_room"} & set(names(model.tool_args[model.calls.index(
        model.calls_of["Coder 2"][0])]))
    # a file no item of its member covers is refused; one that is covered is changed
    ((status, why),) = results(snap, "Coder 2", "write_file")
    assert status == "failed" and "item" in why
    assert results(snap, "Coder 2", "edit_file")[0][0] == "succeeded"
    assert not (project_dir / "notes.txt").exists()
    # in the room's one copy: taken into the project with the room's, not when the helper ended
    assert [m["agent_id"] for m in snap["merges"]] == [agent(snap, "Lead")["id"]]
    assert (project_dir / "hello.py").read_text(encoding="utf-8") == "print('yo')\n"
    # only the members themselves are members: two, and both done
    assert [m["status"] for m in snap["rooms"][0]["members"]] == ["done", "done"]
    assert snap["rooms"][0]["outcome"] == "agreed"


def test_a_room_ended_while_the_work_is_shared_out_never_starts_the_work(
    make_client, wait_run, project_dir
):
    held = Gate()
    client, model, cid, run_id, room = start(make_client, project_dir, {
        "Coder": [held.step(step(add("Change the greeting", ["hello.py"], "a1")))],
        "Reviewer": [text("never said")],
    })
    held.wait_partial()
    assert now_snap(client, cid)["rooms"][0]["status"] == "sharing"
    assert client.post("/api/rooms/no-such-room/end").status_code == 404
    assert client.post("/api/rooms/no-such-room/posts", json={"text": "x"}).status_code == 404
    assert client.post(f"/api/rooms/{room['id']}/end").status_code == 200
    snap = wait_run(client, cid, run_id, timeout=LONG)
    held.release()
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    (ended,) = snap["rooms"]
    assert (ended["status"], ended["outcome"]) == ("ended", "ended_by_user")
    # the one whose step it was is cut short; the other never took its own - both done with the
    # room, which the user ended (B-386: only Stop or a failure stops them)
    assert "Reviewer" not in model.calls_of and items(snap) == []
    assert {a["name"]: a["status"] for a in snap["agents"]} == {
        "Lead": "completed", "Coder": "completed", "Reviewer": "completed"}
    assert "the user ended it" in asked(model, "Lead")[0]


# --- the review's round ---------------------------------------------------------------------


@pytest.mark.parametrize("closes", ["finish", "drop"])
def test_an_item_that_is_closed_lets_its_files_go_and_the_next_item_over_them_is_not_kept_waiting(
    make_client, wait_run, project_dir, closes
):
    """The one who wrote hello.py under its item closes the item and waits for a post: the
    file is not its own any more, so the next member's change to it is not held up behind
    one that waits (that was a deadlock: each waited for the other)."""
    close = finish(1, "it says yo", "f1") if closes == "finish" else drop(1, "done with it", "f1")
    client, _model, cid, run_id, _room = start(make_client, project_dir, {
        "Coder": [step(add("Change the greeting", ["hello.py"], "a1"), take(1, "t1")),
                  step(edit("hi", "yo")),
                  step(post("result", "It says yo.", "p1"), close),
                  wait(), text("Done.")],
        "Coder 2": [text("Nothing to add."), wait(),
                    step(add("Make it louder", ["hello.py"], "a2"), take(2, "t2")),
                    step(edit("yo", "YO", "e2")), step(finish(2, "it says YO", "f2")),
                    text("Louder.")],
    }, members=("Coder", "Coder"))
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert results(snap, "Coder 2", "edit_file")[0][0] == "succeeded"
    assert (project_dir / "hello.py").read_text(encoding="utf-8") == "print('YO')\n"
    assert snap["rooms"][0]["outcome"] == "agreed"


def test_a_member_cannot_open_a_sub_agent_on_a_cli_that_works_with_its_own_tools(
    make_client, wait_run, project_dir
):
    def own_tools_for_testers(client):
        made = client.post("/api/providers", json={
            "name": "Own tools", "kind": "codex_cli", "mode": "native"})
        assert made.status_code == 201, made.text
        assert client.patch(f"/api/roles/{role_id(client, 'Tester')}",
                            json={"provider_id": made.json()["id"]}).status_code == 200

    client, _model, cid, run_id, _room = room_in(make_client, project_dir, {
        "Coder": [text("Nothing to add."),
                  step(call("spawn_agent", {"role": "Tester", "task": "Run the tests"}, "s")),
                  text("Done.")],
        "Reviewer": [text("Nothing to add."), text("Done.")],
    }, before=own_tools_for_testers, spawn_approval="never")
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    # it would write with its own tools, where no item of the member's holds it
    ((status, why),) = results(snap, "Coder", "spawn_agent")
    assert status == "failed" and "Own tools" in why and "tools of its own" in why
    assert [a["name"] for a in snap["agents"]] == ["Lead", "Coder", "Reviewer"]


def test_a_member_cannot_message_the_lead_while_the_room_runs(make_client, wait_run, project_dir):
    client, model, cid, run_id, _room = start(make_client, project_dir, {
        "Coder": [text("Nothing to add."),
                  step(call("message_agent", {"to": "Lead", "message": "Which greeting?"}, "m")),
                  text("Done.")],
        "Reviewer": [text("Nothing to add."), text("Done.")],
    })
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    ((status, why),) = results(snap, "Coder", "message_agent")
    assert status == "failed" and "post_to_room" in why
    assert len(asked(model, "Lead")) == 1                     # its one step, after the room


def test_tokens_no_model_reported_are_not_known_and_hold_nobody_to_a_limit(
    make_client, wait_run, project_dir
):
    quiet = [StepResult("Nothing to add.", [], None, None), StepResult("Done.", [], None, None)]
    client, model, cid, run_id, _room = start(make_client, project_dir, {
        "Coder": list(quiet), "Reviewer": list(quiet),
    }, budget={"tokens": 10})
    snap = wait_run(client, cid, run_id, timeout=LONG)
    (ended,) = snap["rooms"]
    assert (ended["outcome"], ended["spent"]["tokens"]) == ("agreed", None)   # not a zero
    assert "none reported of 10 tokens" in asked(model, "Coder")[1]


def test_the_post_that_reaches_the_limit_is_made_and_its_call_says_so(
    make_client, wait_run, project_dir
):
    client, _model, cid, run_id, _room = start(make_client, project_dir, {
        "Coder": [text("Nothing to add."), step(post("result", "one", "p1")), text("never said")],
        "Reviewer": [text("Nothing to add."), wait(), text("never said")],
    }, budget={"posts": 1})
    snap = wait_run(client, cid, run_id, timeout=LONG)
    (ended,) = snap["rooms"]
    assert (ended["outcome"], ended["why"]) == ("budget", "posts")
    ((status, said),) = results(snap, "Coder", "post_to_room")
    assert status == "succeeded" and "budget of posts is reached" in said
    assert posts(snap)[0] == ("result", "Coder", "one")
