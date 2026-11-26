"""K-symphony, in a chat's queue since 0.1.8: what a task waits for is checked; a task not
finished gets one fix round, then is stuck and the next goes on; a limit stops the queue."""

from types import SimpleNamespace

from app import agent, backlog
from app.db.models import Agent, BacklogTask, Merge, Run
from app.model_client import ModelUnavailable
from tests.test_backlog import setup
from tests.test_backlog_auto import auto, run_todo, tasks, until, worked
from tests.test_chat_flow import text
from tests.test_claude_native import claude_app  # noqa: F401  (a fixture)
from tests.test_usage_scenarios import looks


def run(client, pid):
    return run_todo(client, pid)


def after(client, task_id, ids):
    return client.patch(f"/api/backlog/{task_id}", json={"after": ids})


def said(client, cid):
    return [
        m["content"]
        for m in client.get(f"/api/conversations/{cid}").json()["messages"]
        if m["role"] == "user"
    ]


def test_what_a_task_waits_for_is_checked(client, project_dir, tmp_path):
    pid, (a, b, c) = setup(client, project_dir, "a", "b", "c")
    (tmp_path / "other").mkdir()
    other, (elsewhere,) = setup(client, tmp_path / "other", "x")
    assert after(client, a, [a]).status_code == 422
    assert after(client, a, [elsewhere]).status_code == 422
    assert after(client, b, [a]).status_code == 200 and after(client, c, [b]).status_code == 200
    circle = after(client, a, [c])  # c waits for b, which waits for a
    assert circle.status_code == 422 and "waits for it" in circle.json()["detail"]
    assert after(client, c, []).json()["after"] == []
    assert other != pid


def test_a_failed_turn_gets_one_fix_round(make_client, wait_run, project_dir):
    client, _model = make_client(
        [ModelUnavailable("model server unreachable: refused"), text("fixed it")]
    )
    pid, _ = setup(client, project_dir, "one")
    auto(client, pid, True)
    cid = tasks(client, pid)["one"]["conversation_id"]
    task = until(lambda: (t := tasks(client, pid)["one"])["status"] == "review" and t)
    fix = said(client, cid)[-1]
    assert fix.startswith("KOLONİ: this task is not finished: model server unreachable")
    assert task["conversation_id"] == cid and task["stuck"] is None


def test_still_stuck_after_its_fix_round_it_says_why_and_the_next_starts(
    make_client, wait_run, project_dir, monkeypatch
):
    client, _model = make_client(
        [
            ModelUnavailable("model server unreachable: refused"),
            ModelUnavailable("model server unreachable: refused"),
            text("two done"),
        ]
    )
    pid, _ = setup(client, project_dir, "one", "two")
    ids = [t["id"] for t in tasks(client, pid).values()]  # (one chat: one, then two)
    client.post(f"/api/projects/{pid}/backlog/do-in-chat", json={"task_ids": ids})
    one = until(lambda: (t := tasks(client, pid)["one"])["status"] == "blocked" and t)
    assert one["stuck"].startswith("model server unreachable")
    assert (
        sum(
            m.startswith("KOLONİ: this task is not finished")
            for m in said(client, one["conversation_id"])
        )
        == 1
    )
    until(lambda: tasks(client, pid)["two"]["conversation_id"])
    assert worked(client, wait_run, pid, "two")["status"] == "review"
    # the user's word on it clears why
    client.patch(f"/api/backlog/{one['id']}", json={"status": "todo"})
    assert tasks(client, pid)["one"]["stuck"] is None


def test_an_orchestrator_that_says_it_could_not_finish_gets_its_fix_round(
    make_client, wait_run, project_dir
):
    client, _model = make_client(
        [text("Tried.\n\n**Not finished: the tests need a database.**"), text("done now")]
    )
    pid, _ = setup(client, project_dir, "one")
    cid = run(client, pid)["conversation_id"]
    assert backlog.SAY_NOT_FINISHED in said(client, cid)[0]  # it is told how to say so
    until(lambda: tasks(client, pid)["one"]["status"] == "review")
    assert said(client, cid)[-1].startswith(
        "KOLONİ: this task is not finished: the tests need a database. "
    )


def test_a_check_failed_on_work_left_out_is_not_finished(make_client, wait_run, project_dir):
    client, _model = make_client([text("made it")])
    pid, _ = setup(client, project_dir, "one")
    cid = run(client, pid)["conversation_id"]
    snap = wait_run(client, cid, client.get(f"/api/conversations/{cid}").json()["runs"][0]["id"])
    with client.app.state.session_factory() as session:
        turn = session.get_one(Run, snap["runs"][0]["id"])
        assert backlog.not_finished(session, turn, "completed") is None
        session.add(
            Merge(
                run_id=turn.id,
                agent_id=snap["agents"][0]["id"],
                files=[],
                check={"command": "pytest", "state": "failed"},
            )
        )
        session.flush()
        assert backlog.not_finished(session, turn, "completed") == 'the check "pytest" did not pass'


def test_a_turn_stopped_by_the_token_limit_stops_its_chats_queue(make_client, project_dir):
    client, _model = make_client([])
    pid, (one, two) = setup(client, project_dir, "one", "two")
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    error = agent.OVER_LIMIT.format(used=1200, limit=1000)
    assert error.startswith(backlog.OVER_LIMIT)
    with client.app.state.session_factory() as session:
        session.add(Run(id="r", conversation_id=cid, status="failed", error=error, task_id=one))
        task = session.get_one(BacklogTask, one)
        task.status, task.conversation_id = "doing", cid
        queued = session.get_one(BacklogTask, two)
        queued.conversation_id = cid
        backlog.set_flow(queued, place=1)
        session.flush()
        assert backlog.turn_ended(session, session.get_one(Run, "r"), "failed")
        session.commit()
    # no fix round - it would spend more: back to To-do, and so is what waited, said in the chat
    assert (
        tasks(client, pid)["one"]["status"] == "todo" and tasks(client, pid)["two"]["place"] is None
    )
    said = [m["content"] for m in client.get(f"/api/conversations/{cid}").json()["messages"]]
    assert said == [f"The To-do queue stopped: {error}. 2 tasks went back to To-do."]


def test_a_providers_limit_reached_by_the_orchestrator_stops_the_queue(
    make_client, wait_run, project_dir
):
    client, _model = make_client([text("done")])
    pid, (one,) = setup(client, project_dir, "one")
    cid = run(client, pid)["conversation_id"]
    snap = wait_run(client, cid, client.get(f"/api/conversations/{cid}").json()["runs"][0]["id"])
    with client.app.state.session_factory() as session:
        turn = session.get_one(Run, snap["runs"][0]["id"])
        lead = session.get_one(Agent, snap["agents"][0]["id"])
        lead.failure = "rate_limited"
        session.get_one(BacklogTask, one).status = "doing"
        turn.error = "Claude Code: you've hit your limit"
        assert backlog.turn_ended(session, turn, "failed")
        session.commit()
    assert tasks(client, pid)["one"]["status"] == "todo"  # (no fix round: the same limit)
    assert tasks(client, pid)["one"]["stuck"] is None


def test_a_marked_line_is_found_at_a_lines_start_only():
    assert backlog.marked("x\n- `Not finished:` no db `", backlog.NOT_FINISHED) == "no db"
    assert backlog.marked("it is Not finished: maybe", backlog.NOT_FINISHED) is None
    # B-350's small item: a name in backticks that starts why keeps its pair
    assert backlog.marked("Not finished: `rea.py` does not exist.", backlog.NOT_FINISHED) == (
        "`rea.py` does not exist."
    )
    assert backlog.marked("`Not finished: no db`", backlog.NOT_FINISHED) == "no db"
    for wrapped in (
        "`Not finished:` `rea.py` does not exist.",
        "`Not finished: `rea.py` does not exist.`",
    ):  # (one cut: both go)
        assert backlog.marked(wrapped, backlog.NOT_FINISHED) == "rea.py does not exist."


# --- K-r135: a backlog task's turns hold to a night's rules, at any level (the user's word) ----


def test_a_marker_with_nothing_after_it_is_no_reason():
    for said in ("Not finished: `", "Not finished:   ", "**Not finished:** ``` "):
        assert backlog.marked(said, backlog.NOT_FINISHED) is None, said
    assert backlog.marked("Not finished: `\nNot finished: no db", backlog.NOT_FINISHED) == "no db"
    task = SimpleNamespace(flow=None)
    backlog.set_flow(task, fix="")  # (a fix due for nothing would never come)
    assert task.flow is None


def test_a_todo_tasks_turn_over_the_jobs_budget_stops_with_its_words(
    make_client, wait_run, project_dir
):
    # k-butce (the user, 26 Nov: "hepsini kontrol edelim"): a job's budget - the project's limit on
    # a turn's tokens - holds a To-do task's turn as it holds a message's, in the same words.
    client, model = make_client([looks(1, 5, 2), looks(2, 9, 1), text("never said")])
    pid, _ = setup(client, project_dir, "one")
    assert client.patch(f"/api/projects/{pid}", json={"turn_token_limit": 10}).status_code == 200
    run(client, pid)
    task = worked(client, wait_run, pid, "one")
    runs = client.get(f"/api/conversations/{task['conversation_id']}").json()["runs"]
    first = next(r for r in runs if r["task_id"] == task["id"])
    # 7 after the first step, 17 after the second: no third step of it is asked for.
    assert (first["status"], first["error"]) == (
        "failed",
        "this turn used 17 tokens, over the project's limit of 10",
    ), runs
