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
