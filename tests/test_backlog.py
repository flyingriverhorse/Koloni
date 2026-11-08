"""Slice 52's own checks beside its acceptance set: the order kept through moves and deletes,
each path of a decision, what an agent's call is refused, the end of a turn, the board's count
and the Lead of an existing database given the tools."""

import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest
from alembic import command

from app import backlog
from app.agent import recover_interrupted
from app.db.models import BacklogTask, Run
from tests.test_chat_flow import text
from tests.test_migration_0002 import _config

ORIGIN = {"Origin": "http://127.0.0.1:8790"}


def setup(client, project_dir, *titles):
    client.headers.update(ORIGIN)
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    return pid, [client.post(f"/api/projects/{pid}/backlog", json={"title": t}).json()["id"]
                 for t in titles]


def titles(client, pid):
    return [(t["title"], t["position"]) for t in client.get(f"/api/projects/{pid}/backlog").json()]


def test_moves_up_and_down_keep_the_places_whole_after_a_delete(client, project_dir):
    pid, (a, b, c, d) = setup(client, project_dir, "a", "b", "c", "d")
    assert client.delete(f"/api/backlog/{b}").status_code == 204
    assert titles(client, pid) == [("a", 0), ("c", 1), ("d", 2)]
    # down past c: the place after it, as the page asks
    client.patch(f"/api/backlog/{a}", json={"position": 2})
    assert titles(client, pid) == [("c", 0), ("a", 1), ("d", 2)]
    client.patch(f"/api/backlog/{d}", json={"position": 0})  # up to the top
    assert titles(client, pid) == [("d", 0), ("c", 1), ("a", 2)]
    client.patch(f"/api/backlog/{c}", json={"position": 99})  # past the end: last
    assert titles(client, pid) == [("d", 0), ("a", 1), ("c", 2)]
    assert client.patch(f"/api/backlog/{c}", json={"position": -1}).status_code == 422
    assert client.patch(f"/api/backlog/{c}", json={"title": "  "}).status_code == 422
    assert client.patch(f"/api/backlog/{c}", json={"status": "proposed"}).status_code == 422


def agent(client, pid, name, **args):
    with client.app.state.session_factory() as session:
        said = getattr(backlog, name)(session, pid, args)
        session.commit()
    return said


def test_each_decision_and_what_an_agent_is_refused(client, project_dir):
    pid, (mine,) = setup(client, project_dir, "mine")
    # (Another folder beside it: the one above holds the test's home, which is no project.)
    (project_dir.parent / "theirs").mkdir()
    other, _ = setup(client, project_dir.parent / "theirs", "theirs")
    for name, args in (
        ("add_task", {}), ("add_task", {"title": " "}), ("add_task", {"title": "x", "priority": "soon"}),
        ("add_task", {"title": "x" * 201}), ("change_task", {"task_id": mine}),
        ("change_task", {"task_id": mine, "status": "proposed"}),
        # doing and review are Work the backlog's
        ("change_task", {"task_id": mine, "status": "doing"}),
        ("change_task", {"task_id": mine, "status": "review"}),
        ("read_backlog", {"task_id": "nope"}),
        ("change_task", {"task_id": "nope", "title": "x"}),
        ("assess_task", {"task_id": mine, "text": ""}),
    ):
        with pytest.raises(backlog.Refused):
            agent(client, pid, name, **args)
    with pytest.raises(backlog.Refused):  # a task of another project is none of this one's
        agent(client, other, "assess_task", task_id=mine, text="fine")
    agent(client, pid, "add_task", title="proposed one")
    (proposed,) = [t for t in client.get(f"/api/projects/{pid}/backlog").json() if t["status"] == "proposed"]
    with pytest.raises(backlog.Refused):  # a proposal waits for the user as it is
        agent(client, pid, "change_task", task_id=proposed["id"], title="other")
    agent(client, pid, "change_task", task_id=mine, title="first")
    agent(client, pid, "change_task", task_id=mine, status="blocked")  # the newer one stands
    listed = agent(client, pid, "read_backlog").splitlines()
    assert [line.split("] ", 1)[1] for line in listed[1:]] == [
        '"mine"; a change waits for the user', '"proposed one"']
    assert listed[1].startswith(f"- {mine} [todo, normal, 20")
    assert agent(client, other, "read_backlog").count("\n- ") == 1  # its own task only
    whole = agent(client, pid, "read_backlog", task_id=mine)
    assert 'Title: "mine"' in whole and 'A change waiting for the user: {"status": "blocked"}' in whole
    assert client.get(f"/api/projects/{pid}/board").json()["backlog_waiting"] == 2
    decide = f"/api/backlog/{mine}/decide"
    assert client.post(decide, json={"decision": "reject"}).status_code == 200
    seen = client.get(f"/api/projects/{pid}/backlog").json()
    assert [(t["title"], t["status"], t["pending"]) for t in seen if t["id"] == mine] == [
        ("mine", "todo", None)]
    assert client.post(decide, json={"decision": "approve"}).status_code == 409  # nothing waits
    assert client.post(decide, json={"decision": "maybe"}).status_code == 422
    rejected = client.post(f"/api/backlog/{proposed['id']}/decide", json={"decision": "reject"})
    assert rejected.status_code == 200 and rejected.json() is None
    assert titles(client, pid) == [("mine", 0)]


def test_a_task_like_one_not_done_is_still_proposed_and_said_like_it_and_criteria_keep_lines(
    client, project_dir
):
    """B-91: the Lead proposed a copy of "Fix calc.average" without reading the backlog, and
    haiku's criteria came with their line breaks written out as \\n."""
    pid, (average, done) = setup(client, project_dir, "Fix calc.average", "Add calc.median")
    client.patch(f"/api/backlog/{done}", json={"status": "done"})
    said = agent(client, pid, "add_task", title="calc.average: divides by the wrong count",
                 criteria="average([1, 2]) is 1.5\\n- AverageTest passes")
    assert said.endswith(f'. It looks like task {average}: "Fix calc.average" - if it is the '
                         "same work, tell the user, who can reject this one")
    (proposed,) = [t for t in client.get(f"/api/projects/{pid}/backlog").json()
                   if t["status"] == "proposed"]
    assert proposed["criteria"] == "average([1, 2]) is 1.5\n- AverageTest passes"
    # Nothing like it, or like only a task that is done: nothing more is said.
    assert "looks like" not in agent(client, pid, "add_task", title="dark mode")
    assert "looks like" not in agent(client, pid, "add_task", title="calc.median for lists")


def test_a_turn_that_did_not_complete_puts_its_task_back(client, project_dir):
    pid, (failed, done, other) = setup(client, project_dir, "failed", "done", "other")
    factory = client.app.state.session_factory
    with factory() as session:
        for task_id, status in ((failed, "doing"), (done, "done"), (other, "doing")):
            task = session.get_one(BacklogTask, task_id)
            task.status, task.conversation_id = status, "c1" if task_id != other else "c2"
        # A side of a comparison is not c1's own turn: it moves nothing.
        assert not backlog.turn_ended(session, Run(conversation_id="c1", compare_id="x"), "failed")
        assert backlog.turn_ended(session, Run(conversation_id="c1"), "interrupted")
        session.commit()
        assert not backlog.turn_ended(session, Run(conversation_id="c3"), "completed")
    seen = {t["title"]: t for t in client.get(f"/api/projects/{pid}/backlog").json()}
    assert (seen["failed"]["status"], seen["failed"]["conversation_id"]) == ("todo", "c1")
    assert seen["done"]["status"] == "done" and seen["other"]["status"] == "doing"
    assert client.get(f"/api/projects/{pid}/board").json()["backlog_waiting"] == 0


def test_done_tasks_are_listed_last(client, project_dir):
    pid, (done, *_rest) = setup(client, project_dir, *(f"t{n}" for n in range(backlog.LISTED + 1)))
    client.patch(f"/api/backlog/{done}", json={"status": "done"})
    listed = agent(client, pid, "read_backlog")
    more = f"... and 1 more: read_backlog with from {backlog.LISTED} lists them."
    assert done not in listed and listed.endswith(more)
    # the next page: what is left, from where the first ended
    rest = agent(client, pid, "read_backlog", **{"from": backlog.LISTED}).splitlines()
    assert len(rest) == 2 and rest[1].startswith(f"- {done} [done,")
    assert "from 61 on" in agent(client, pid, "read_backlog", **{"from": 61})
    assert agent(client, pid, "read_backlog", **{"from": None}) == listed  # a model's null
    for wrong in (-1, "2", True):
        with pytest.raises(backlog.Refused):
            agent(client, pid, "read_backlog", **{"from": wrong})


def test_work_opens_no_folder_a_task_names_and_says_who_wrote_it(make_client, project_dir, tmp_path):
    client, _model = make_client([text("ok"), text("ok")])
    outside = tmp_path / "outside"
    outside.mkdir()
    pid, _ = setup(client, project_dir)
    agent(client, pid, "add_task", title="tidy", detail=f"Look in `{outside}` first.")
    (task,) = client.get(f"/api/projects/{pid}/backlog").json()
    client.post(f"/api/backlog/{task['id']}/decide", json={"decision": "approve"})
    cid = client.post(f"/api/projects/{pid}/backlog/next").json()["conversation_id"]
    snap = client.get(f"/api/conversations/{cid}").json()
    assert snap["conversation"]["also_in"] == []
    assert snap["conversation"]["title"] == "tidy"  # its title comes first, on its own line
    assert "proposed by an agent, approved by you" in snap["messages"][0]["content"]
    # the same words from the user open it (what was kept from before)
    own = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.post(f"/api/conversations/{own}/messages", json={"content": f"Look in `{outside}` first."})
    assert client.get(f"/api/conversations/{own}").json()["conversation"]["read_in"] == [str(outside)]


def test_a_tasks_chat_is_named_by_its_whole_title_and_listed_as_the_tasks(make_client, wait_run, project_dir):
    client, _model = make_client([text("ok")])
    title = "Let the notes page export every note as CSV, with its tags and its dates kept as they are"
    pid, (tid,) = setup(client, project_dir, title)
    own = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    cid = client.post(f"/api/projects/{pid}/backlog/next").json()["conversation_id"]
    wait_run(client, cid, client.get(f"/api/conversations/{cid}").json()["runs"][0]["id"])
    listed = {c["id"]: c for c in client.get(f"/api/projects/{pid}/conversations").json()}
    assert listed[cid]["title"] == title  # not cut at a chat's 60 characters (K-backlog-sohbet)
    assert listed[cid]["backlog_task"] == {"id": tid, "status": "review", "waiting": False}
    assert listed[own]["backlog_task"] is None
    every = {c["id"]: c["backlog_task"] for c in client.get("/api/conversations").json()}
    assert every[cid]["id"] == tid and every[own] is None


def test_a_turn_the_restart_cut_short_puts_its_task_back(client, project_dir):
    pid, (task_id,) = setup(client, project_dir, "work")
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    factory = client.app.state.session_factory
    with factory() as session:
        session.add(Run(conversation_id=cid, status="running"))
        task = session.get_one(BacklogTask, task_id)
        task.status, task.conversation_id = "doing", cid
        session.commit()
    recover_interrupted(factory)
    (seen,) = client.get(f"/api/projects/{pid}/backlog").json()
    assert (seen["status"], seen["conversation_id"]) == ("todo", cid)


# Read off the migration itself: it is renumbered when the slices are merged.
MIGRATION = next(Path(__file__).parents[1].glob("alembic/versions/*_backlog.py"))
_spec = importlib.util.spec_from_file_location("backlog_migration", MIGRATION)
assert _spec and _spec.loader
_migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_migration)


def test_the_lead_of_an_existing_database_is_given_the_backlogs_tools(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, _migration.down_revision)
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO roles (id, name, description, instructions, tools, builtin, "
                     "created_by_agent, created_at, updated_at, skills) VALUES ('l', 'Lead', '', "
                     "'', '[\"read_file\"]', 1, 0, '2026-10-20', '2026-10-20', '[]')")
    command.upgrade(cfg, _migration.revision)
    with sqlite3.connect(db) as conn:
        tools = json.loads(conn.execute("SELECT tools FROM roles").fetchone()[0])
    assert tools == ["read_file", "read_backlog", "add_task", "change_task", "assess_task"]
    command.downgrade(cfg, _migration.down_revision)
    with sqlite3.connect(db) as conn:
        assert json.loads(conn.execute("SELECT tools FROM roles").fetchone()[0]) == ["read_file"]


def test_a_task_whose_turn_waits_for_the_user_is_at_work_while_another_agent_of_it_works(make_client, project_dir):
    # (The review of B-147, S8: a turn waiting for an approval may still have an agent at work.)
    from app.db.models import Agent
    client, _model = make_client([])
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    with client.app.state.runner._factory() as session:
        session.add(BacklogTask(project_id=pid, title="night job", status="doing", position=0, conversation_id=cid,
                                created_by="user"))
        session.add(Run(id="r", conversation_id=cid, status="waiting_approval"))
        session.flush()
        session.add_all([Agent(id="a", run_id="r", role_name="Lead", tools=[], status="waiting"),
                         Agent(id="b", run_id="r", role_name="Coder", tools=[], depth=1, status="running")])
        session.commit()
        assert backlog.busy(session, pid, waiting=True) is not None
        session.get_one(Agent, "b").status = "waiting_approval"
        session.commit()
        assert backlog.busy(session, pid, waiting=True) is None
