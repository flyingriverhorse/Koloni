"""0.1.8, To-do in a chat (the user, 23-24 Nov): ticked To-do tasks wait in a chat's queue and run
there one by one, each story in a topic of its own and a task of no story in one of its own;
the user's own message goes first; Stop, a restart and the budget stop the queue, Stop
everything and Away only hold it."""

import pytest
from sqlalchemy import select

from app import backlog
from app.agent import recover_interrupted
from app.db.models import AwayRun, BacklogTask, Conversation, Message, Run, now
from tests.test_backlog import agent, setup
from tests.test_backlog_auto import until
from tests.test_chat_flow import text

QUEUE_STOPPED = "The To-do queue stopped:"


def do_in_chat(client, pid, ids, cid=None):
    return client.post(
        f"/api/projects/{pid}/backlog/do-in-chat", json={"task_ids": ids, "conversation_id": cid}
    )


def snap(client, cid):
    return client.get(f"/api/conversations/{cid}").json()


def turns(client, cid):
    """The chat's turns, oldest first."""
    return snap(client, cid)["runs"]


def task(client, task_id):
    with client.app.state.session_factory() as session:
        one = session.get(BacklogTask, task_id)
        return one and {
            "status": one.status,
            "place": one.place,
            "stuck": one.stuck,
            "conversation_id": one.conversation_id,
        }


def said(client, cid, run_id):
    """What the user (or KOLONİ for a task) said to start the turn."""
    return next(
        m["content"]
        for m in snap(client, cid)["messages"]
        if m["run_id"] == run_id and m["role"] == "user"
    )


def ended(client, cid, count):
    """Waits for `count` turns of the chat to be over; its turns then."""
    return until(
        lambda: (
            (runs := turns(client, cid))
            and len(runs) >= count
            and all(r["status"] in backlog.ENDED for r in runs)
            and runs
        )
    )


def story(client, pid, title, *task_ids):
    story_id = client.post(f"/api/projects/{pid}/stories", json={"title": title}).json()["id"]
    for task_id in task_ids:
        client.patch(f"/api/backlog/{task_id}", json={"story_id": story_id})
    return story_id


def test_tasks_wait_in_the_chat_and_run_one_by_one(make_client, project_dir, gate):
    client, _model = make_client([gate.step(text("a done")), text("b done")])
    pid, (a, b) = setup(client, project_dir, "a", "b")
    # from the app's own page only: an agent's command against the app's address queues nothing
    assert do_in_chat(client, pid, [a, b]).status_code == 200  # (the client is the page)
    cid = task(client, a)["conversation_id"]
    gate.wait_partial()
    (first,) = turns(client, cid)
    assert first["task_id"] == a and said(client, cid, first["id"]).startswith("a\n")
    assert task(client, b)["place"] and task(client, b)["status"] == "todo"
    assert snap(client, cid)["conversation"]["title"] == "a"  # (the new chat named by the first)
    gate.release()
    runs = ended(client, cid, 2)
    assert [r["task_id"] for r in runs] == [a, b]
    assert runs[0]["topic_id"] != runs[1]["topic_id"]  # (no story: a topic each)
    assert task(client, a)["status"] == task(client, b)["status"] == "review"
    assert task(client, b)["place"] is None


def test_do_in_chat_is_the_users_own_click(client, project_dir):
    pid, (a,) = setup(client, project_dir, "a")
    answer = client.post(
        f"/api/projects/{pid}/backlog/do-in-chat",
        json={"task_ids": [a]},
        headers={"Origin": "http://evil.example"},
    )
    assert answer.status_code == 403 and task(client, a)["conversation_id"] is None


def test_a_storys_tasks_share_its_topic_and_a_lone_task_gets_its_own(make_client, project_dir):
    client, _model = make_client([text("one"), text("two"), text("three")])
    pid, (t1, t2, t3) = setup(client, project_dir, "Hatayı bul", "Test ekle", "Footer")
    s = story(client, pid, "Login düzelt", t1, t2)
    cid = do_in_chat(client, pid, [t3, t2, t1]).json()["conversation_id"]
    runs = ended(client, cid, 3)
    # the tree's order: the story's tasks first, in the list's order; the lone one last
    assert [r["task_id"] for r in runs] == [t1, t2, t3]
    topic = {r["task_id"]: r["topic_id"] for r in runs}
    assert topic[t1] == topic[t2] != topic[t3]
    topics = {t["id"]: t for t in snap(client, cid)["topics"]}
    assert topics[topic[t1]]["story_id"] == s and topics[topic[t1]]["title"] == "Login düzelt"
    assert topics[topic[t3]]["story_id"] is None
    assert snap(client, cid)["conversation"]["title"] == "Login düzelt"
    # the brief says the story and which of its tasks this is
    assert 'Story: "Login düzelt" — task 2 of 2.' in said(client, cid, runs[1]["id"])


def test_tasks_given_to_an_open_chat_wait_behind_what_waits_there(make_client, project_dir):
    client, _model = make_client([text("hi"), text("a"), text("b")])
    pid, (a, b) = setup(client, project_dir, "a", "b")
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.post(f"/api/conversations/{cid}/messages", json={"content": "hello"})
    assert do_in_chat(client, pid, [a], cid).json() == {"conversation_id": cid, "queued": [a]}
    assert do_in_chat(client, pid, [b], cid).json()["queued"] == [b]
    runs = ended(client, cid, 3)
    assert [r["task_id"] for r in runs] == [None, a, b]


def test_the_users_message_goes_before_the_next_task(make_client, project_dir, gate):
    client, _model = make_client([gate.step(text("a done")), text("answered"), text("b done")])
    pid, (a, b) = setup(client, project_dir, "a", "b")
    story(client, pid, "S", a, b)
    cid = do_in_chat(client, pid, [a, b]).json()["conversation_id"]
    gate.wait_partial()
    client.post(f"/api/conversations/{cid}/messages", json={"content": "one more thing"})
    gate.release()
    runs = ended(client, cid, 3)
    assert [r["task_id"] for r in runs] == [a, None, b], runs
    # the user's message goes on in the topic they were last in: the story's
    assert runs[1]["topic_id"] == runs[0]["topic_id"] == runs[2]["topic_id"]
    assert task(client, a)["status"] == task(client, b)["status"] == "review"


def test_a_users_own_turn_in_the_chat_moves_no_task(make_client, project_dir, gate):
    client, _model = make_client(
        [gate.step(text("Not finished: the tests fail")), text("answered"), text("fixed")]
    )
    pid, (a,) = setup(client, project_dir, "a")
    cid = do_in_chat(client, pid, [a]).json()["conversation_id"]
    gate.wait_partial()
    client.post(f"/api/conversations/{cid}/messages", json={"content": "how is it going?"})
    gate.release()
    runs = ended(client, cid, 3)
    assert [r["task_id"] for r in runs] == [a, None, a], runs
    assert said(client, cid, runs[2]["id"]).startswith("KOLONİ: this task is not finished")
    assert runs[2]["topic_id"] == runs[0]["topic_id"]  # (its fix round in its own topic)
    assert task(client, a)["status"] == "review"


def test_a_task_waiting_for_a_done_question_holds_only_itself(make_client, project_dir):
    client, _model = make_client([text("a"), text("b"), text("c")])
    pid, (a, c, b) = setup(client, project_dir, "a", "c", "b")
    client.patch(f"/api/backlog/{c}", json={"after": [a]})
    cid = do_in_chat(client, pid, [a, c, b]).json()["conversation_id"]
    runs = ended(client, cid, 2)
    assert [r["task_id"] for r in runs] == [a, b]
    assert task(client, a)["status"] == "review" and task(client, c)["place"]
    client.patch(f"/api/backlog/{a}", json={"status": "done"})  # (Yes, done)
    assert [r["task_id"] for r in ended(client, cid, 3)] == [a, b, c]


def test_a_fix_round_comes_in_the_tasks_topic_and_then_it_is_stuck(make_client, project_dir):
    client, _model = make_client(
        [text("Not finished: no tests"), text("Not finished: still none"), text("b done")]
    )
    pid, (a, b) = setup(client, project_dir, "a", "b")
    cid = do_in_chat(client, pid, [a, b]).json()["conversation_id"]
    runs = ended(client, cid, 3)
    assert [r["task_id"] for r in runs] == [a, a, b]
    assert runs[0]["topic_id"] == runs[1]["topic_id"] != runs[2]["topic_id"]
    assert said(client, cid, runs[1]["id"]).startswith(
        "KOLONİ: this task is not finished: no tests."
    )
    assert task(client, a) | {"conversation_id": None} == {
        "status": "blocked",
        "place": None,
        "stuck": "still none",
        "conversation_id": None,
    }


@pytest.mark.parametrize(
    "stale",
    [
        "done",
        "queued_elsewhere",
        "deleted",
        "proposed",
        "unseen",
        "away_job",
        "other_project",
        "plain_chat",
        "archived_chat",
        "other_projects_chat",
    ],
)
def test_do_in_chat_refuses_a_stale_selection(stale, client, project_dir, tmp_path):
    pid, (a, b) = setup(client, project_dir, "a", "b")
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    other = client.post("/api/projects", json={"root_path": str(other_dir)}).json()["id"]
    factory = client.app.state.session_factory
    ids, cid = [a, b], None
    if stale == "done":
        client.patch(f"/api/backlog/{b}", json={"status": "done"})
    elif stale == "queued_elsewhere":
        client.post("/api/hold")  # (nothing starts: b waits in the first chat's queue)
        assert do_in_chat(client, pid, [b]).status_code == 200
    elif stale == "deleted":
        client.delete(f"/api/backlog/{b}")
    elif stale == "proposed":
        agent(client, pid, "add_task", title="an agent's")
        ids = [a, next(t["id"] for t in client.get(f"/api/projects/{pid}/backlog").json()[2:])]
    elif stale in ("unseen", "away_job"):
        with factory() as session:
            one = session.get_one(BacklogTask, b)
            if stale == "unseen":
                one.po = {"lead": "add", "chat": "c", "why": "w"}
            else:
                one.away_run_id = "night"
            session.commit()
    elif stale == "other_project":
        ids = [a, client.post(f"/api/projects/{other}/backlog", json={"title": "x"}).json()["id"]]
    elif stale == "plain_chat":
        cid = client.post("/api/conversations").json()["id"]
    elif stale == "archived_chat":
        cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
        with factory() as session:
            session.get_one(Conversation, cid).archived_at = now()
            session.commit()
    else:
        cid = client.post(f"/api/projects/{other}/conversations").json()["id"]
    answer = do_in_chat(client, pid, ids, cid)
    assert answer.status_code in (404, 409, 422), (stale, answer.text)
    assert task(client, a)["place"] is None and task(client, a)["conversation_id"] is None, stale
    if stale != "queued_elsewhere":
        assert not any(t["place"] for t in client.get(f"/api/projects/{pid}/backlog").json())


def test_an_unknown_chat_is_not_found(client, project_dir):
    pid, (a,) = setup(client, project_dir, "a")
    assert do_in_chat(client, pid, [a], "nope").status_code == 404
    assert task(client, a)["conversation_id"] is None


def test_a_storys_tasks_are_not_split_over_two_chats(client, project_dir):
    pid, (a, b) = setup(client, project_dir, "a", "b")
    story(client, pid, "S", a, b)
    client.post("/api/hold")
    first = do_in_chat(client, pid, [a]).json()["conversation_id"]
    answer = do_in_chat(client, pid, [b])
    assert answer.status_code == 422 and "do the story there" in answer.text
    assert do_in_chat(client, pid, [b], first).status_code == 200


def lines(client, cid):
    return [m["content"] for m in snap(client, cid)["messages"] if m["role"] == "koloni"]


def test_a_stopped_task_stops_the_queue(make_client, project_dir, gate):
    client, _model = make_client([gate.step(text("never"))])
    pid, (a, b) = setup(client, project_dir, "a", "b")
    cid = do_in_chat(client, pid, [a, b]).json()["conversation_id"]
    gate.wait_partial()
    (run,) = turns(client, cid)
    client.post(f"/api/runs/{run['id']}/cancel")
    ended(client, cid, 1)
    until(lambda: lines(client, cid))
    assert task(client, a)["status"] == task(client, b)["status"] == "todo"
    assert task(client, b)["place"] is None and task(client, b)["conversation_id"] is None
    assert task(client, a)["conversation_id"] == cid  # (it worked there: still linked)
    assert lines(client, cid) == [
        'The To-do queue stopped: the turn of "a" was stopped. 2 tasks went back to To-do.'
    ]
    assert len(turns(client, cid)) == 1


def test_a_restart_stops_the_queue_and_says_so(client, project_dir):
    pid, (a, b, c) = setup(client, project_dir, "a", "b", "c")
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    other = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    factory = client.app.state.session_factory
    with factory() as session:
        session.add(Run(conversation_id=cid, status="running", task_id=a))
        session.add(Run(conversation_id=other, status="running"))  # (the user's, c waits)
        for task_id, chat, status, place in ((a, cid, "doing", None), (b, cid, "todo", 1)):
            one = session.get_one(BacklogTask, task_id)
            one.status, one.conversation_id = status, chat
            backlog.set_flow(one, place=place)
        one = session.get_one(BacklogTask, c)
        one.conversation_id = other
        backlog.set_flow(one, place=1)
        session.commit()
    recover_interrupted(factory)
    assert {task(client, t)["status"] for t in (a, b, c)} == {"todo"}
    assert not any(task(client, t)["place"] for t in (a, b, c))
    assert lines(client, cid) == [
        'The To-do queue stopped: the turn of "a" was cut short by a restart. '
        "2 tasks went back to To-do."
    ]
    assert lines(client, other) == [
        "The To-do queue stopped: KOLONİ restarted. 1 task went back to To-do."
    ]


def test_stop_everything_holds_the_queue_until_resume(make_client, project_dir, gate):
    client, _model = make_client([gate.step(text("never")), text("a again"), text("b")])
    pid, (a, b) = setup(client, project_dir, "a", "b")
    cid = do_in_chat(client, pid, [a, b]).json()["conversation_id"]
    gate.wait_partial()
    client.post("/api/hold")
    ended(client, cid, 1)
    # held: the stopped task waits at the head of the queue, nothing starts, nothing is said
    assert task(client, a)["place"] == 1 and task(client, b)["place"] == 2
    assert len(turns(client, cid)) == 1 and not lines(client, cid)
    client.post("/api/hold/resume")
    runs = ended(client, cid, 3)
    assert [r["task_id"] for r in runs] == [a, a, b]
    assert runs[1]["topic_id"] == runs[0]["topic_id"]  # (it goes on where it was)


def test_away_holds_the_queue_and_coming_back_goes_on(make_client, project_dir):
    client, _model = make_client([text("hi"), text("a")])
    pid, (a,) = setup(client, project_dir, "a")
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    first = client.post(f"/api/conversations/{cid}/messages", json={"content": "hi"}).json()
    ended(client, cid, 1)
    with client.app.state.session_factory() as session:
        night = AwayRun(
            project_id=pid,
            conversation_id=cid,
            run_id=first["run"]["id"],
            status="running",
            started_at=now(),
        )
        session.add(night)
        session.commit()
        night_id = night.id
    assert do_in_chat(client, pid, [a], cid).status_code == 200
    assert task(client, a)["place"] and len(turns(client, cid)) == 1  # (held while away)
    client.post(f"/api/away/{night_id}/back")
    assert [r["task_id"] for r in ended(client, cid, 2)] == [None, a]


def test_the_budget_spent_stops_the_queue(make_client, project_dir, gate, monkeypatch):
    client, _model = make_client([gate.step(text("a done"))])
    pid, (a, b) = setup(client, project_dir, "a", "b")
    cid = do_in_chat(client, pid, [a, b]).json()["conversation_id"]
    gate.wait_partial()
    over = "over this month's budget (2.00 of 1.00 USD)"
    monkeypatch.setattr(backlog, "over_budget", lambda session, project, chat=None: over)
    gate.release()
    until(lambda: lines(client, cid))
    assert task(client, a)["status"] == "review" and task(client, b)["status"] == "todo"
    assert task(client, b)["place"] is None and len(turns(client, cid)) == 1
    assert lines(client, cid) == [
        f"The To-do queue stopped: the project is {over}. 1 task went back to To-do."
    ]


def test_tasks_and_stories_deleted_meanwhile_move_nothing_wrong(make_client, project_dir, gate):
    client, _model = make_client([gate.step(text("c done")), text("b done")])
    pid, (a, b, c) = setup(client, project_dir, "a", "b", "c")
    s = story(client, pid, "S", c)
    cid = do_in_chat(client, pid, [a, b, c]).json()["conversation_id"]
    gate.wait_partial()  # (c first: a story's tasks come before the lone ones)
    assert client.delete(f"/api/stories/{s}").status_code == 204  # (the story of the one at work)
    assert client.delete(f"/api/backlog/{c}").status_code == 204  # (at work)
    assert client.delete(f"/api/backlog/{a}").status_code == 204  # (queued)
    gate.release()
    runs = ended(client, cid, 2)
    assert [r["task_id"] for r in runs] == [c, b]
    assert task(client, b)["status"] == "review" and task(client, c) is None
    with client.app.state.session_factory() as session:
        assert session.scalar(select(Message.id).where(Message.role == "koloni")) is None
