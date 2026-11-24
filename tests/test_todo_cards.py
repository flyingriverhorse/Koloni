"""0.1.8, the To-do cards in a chat: the queue's Remove puts a task back on To-do, Fix it gives a
stuck task another round in its topic, and a turn says its task, a topic its story."""

from tests.test_backlog import setup
from tests.test_chat_flow import text
from tests.test_todo_chat import do_in_chat, ended, said, snap, story, task

OWN = {"Origin": "http://127.0.0.1:8790"}


def test_unqueue_puts_a_task_back_on_the_to_do_list(client, project_dir):
    pid, (a, b) = setup(client, project_dir, "a", "b")
    client.post("/api/hold")  # (nothing starts: both wait)
    cid = do_in_chat(client, pid, [a, b]).json()["conversation_id"]
    assert (
        client.delete(
            f"/api/backlog/{b}/queue", headers={"Origin": "http://evil.example"}
        ).status_code
        == 403
    )
    assert client.delete(f"/api/backlog/{b}/queue").status_code == 204
    assert task(client, b) == {
        "status": "todo",
        "place": None,
        "stuck": None,
        "conversation_id": None,
    }
    assert task(client, a)["place"] and task(client, a)["conversation_id"] == cid
    assert client.delete(f"/api/backlog/{b}/queue").status_code == 409  # (in no queue)


def test_fix_it_gives_a_stuck_task_another_round_in_its_topic(make_client, project_dir):
    client, _model = make_client(
        [text("Not finished: no db"), text("Not finished: still no db"), text("fixed now")]
    )
    pid, (a,) = setup(client, project_dir, "a")
    cid = do_in_chat(client, pid, [a]).json()["conversation_id"]
    ended(client, cid, 2)
    assert task(client, a)["status"] == "blocked" and task(client, a)["stuck"] == "still no db"
    refused = client.post(f"/api/backlog/{a}/fix", headers={"Origin": "http://evil.example"})
    assert refused.status_code == 403
    assert client.post(f"/api/backlog/{a}/fix").json()["status"] == "doing"
    runs = ended(client, cid, 3)
    assert runs[2]["task_id"] == a and runs[2]["topic_id"] == runs[0]["topic_id"]
    assert said(client, cid, runs[2]["id"]).startswith(
        "KOLONİ: this task is not finished: still no db."
    )
    assert task(client, a)["status"] == "review" and task(client, a)["stuck"] is None
    assert client.post(f"/api/backlog/{a}/fix").status_code == 409  # (not stuck now)


def test_a_run_says_its_task_and_a_topic_its_story(make_client, project_dir):
    client, _model = make_client([text("done")])
    pid, (a,) = setup(client, project_dir, "a")
    s = story(client, pid, "S", a)
    cid = do_in_chat(client, pid, [a]).json()["conversation_id"]
    (run,) = ended(client, cid, 1)
    assert run["task_id"] == a
    (topic,) = [t for t in snap(client, cid)["topics"] if t["id"] == run["topic_id"]]
    assert topic["story_id"] == s


def test_fix_it_is_refused_while_another_task_of_its_story_is_in_another_chat(client, project_dir):
    # (The review's M1: two chats on one story's branch.)
    from app.db.models import BacklogTask
    from tests.test_todo_chat import story

    pid, (a, b) = setup(client, project_dir, "a", "b")
    story(client, pid, "S", a, b)
    client.post("/api/hold")
    chat_a = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    chat_b = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    with client.app.state.session_factory() as session:
        stuck = session.get_one(BacklogTask, a)
        stuck.status, stuck.conversation_id, stuck.flow = "blocked", chat_a, {"stuck": "no db"}
        waits = session.get_one(BacklogTask, b)
        waits.conversation_id, waits.flow = chat_b, {"place": 1}
        session.commit()
    refused = client.post(f"/api/backlog/{a}/fix")
    assert refused.status_code == 409 and "in another chat" in refused.json()["detail"]
    assert task(client, a)["status"] == "blocked"


def test_a_deleted_chats_queue_goes_back_to_to_do_and_an_archived_chats_does_not_start(
    client, project_dir
):
    # (The review's L1.)
    pid, (a, b) = setup(client, project_dir, "a", "b")
    client.post("/api/hold")
    first = do_in_chat(client, pid, [a]).json()["conversation_id"]
    second = do_in_chat(client, pid, [b]).json()["conversation_id"]
    for cid in (first, second):
        client.patch(f"/api/conversations/{cid}", json={"archived": True}, headers=OWN)
    assert client.post("/api/conversations/delete", json={"ids": [first]}).json()["deleted"] == [
        first
    ]
    assert task(client, a)["place"] is None and task(client, a)["conversation_id"] is None
    client.post("/api/hold/resume")  # (the archived chat's queue stops - nothing starts there)
    assert task(client, b)["place"] is None and task(client, b)["status"] == "todo"
    assert snap(client, second)["runs"] == []


def test_do_in_chat_refuses_a_chat_of_another_folder_named_in_this_ones_address(
    client, project_dir, tmp_path
):
    # (The review's L2: the chat's folder, not only its tasks', is the address's.)
    pid, (a,) = setup(client, project_dir, "a")
    (tmp_path / "other").mkdir()
    other = client.post("/api/projects", json={"root_path": str(tmp_path / "other")}).json()["id"]
    (b,) = [client.post(f"/api/projects/{other}/backlog", json={"title": "b"}).json()["id"]]
    theirs = client.post(f"/api/projects/{other}/conversations").json()["id"]
    answer = do_in_chat(client, pid, [b], theirs)
    assert answer.status_code == 422 and task(client, b)["place"] is None


def test_a_task_added_to_a_closed_story_opens_it_again(client, project_dir):
    # (T1b: a closed story with a todo task under it read "done".)
    from tests.test_todo_chat import story

    pid, (a,) = setup(client, project_dir, "a")
    s = story(client, pid, "S", a)
    client.patch(f"/api/backlog/{a}", json={"status": "done"})
    assert client.patch(f"/api/stories/{s}", json={"closed": True}).json()["closed_at"]
    added = client.post(f"/api/projects/{pid}/backlog", json={"title": "b", "story_id": s})
    assert added.status_code == 201
    (row,) = client.get(f"/api/projects/{pid}/stories").json()["stories"]
    assert (row["closed_at"], row["state"]) == (None, "todo")
