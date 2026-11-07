"""A project deleted from KOLONİ (Settings › This project): every row of it goes in one go - its
chats with their turns, memory, knowledge, To-do, triggers, nights, usage, vectors - and another
project's rows and the app's own stay. Its folder on disk, .koloni/ too, is never touched. Not
while anything of it is at work, and only from the app's own page."""

from sqlalchemy import select
from sqlalchemy import text as sql

from app import attachments, knowledge, knows
from app.db.models import (
    Agent,
    AwayRun,
    BacklogTask,
    Base,
    Embedding,
    Memory,
    Merge,
    Project,
    ProjectKnowledge,
    Role,
    Run,
)
from tests.keyed import OWN
from tests.test_chat_flow import text
from tests.test_usage_scenarios import ORIGIN, turn


def made(client, wait_run, root, factory) -> tuple[str, str, str]:
    """A project in `root` with a chat that had a turn, a trigger, memory, a task, knowledge
    and a vector: its id, its chat's and its knowledge's."""
    pid = client.post("/api/projects", json={"root_path": str(root)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    run_id = turn(client, wait_run, cid)["id"]
    trigger = client.post(f"/api/projects/{pid}/triggers", json={
        "name": "Nightly", "kind": "schedule", "conversation_id": cid, "message": "look",
        "config": {"every_minutes": 60}})
    assert trigger.status_code == 201, trigger.text
    with factory() as session:
        note = Memory(project_id=pid, tier="note", text="kept", origin="agent",
                      conversation_id=cid, run_id=run_id)
        known = ProjectKnowledge(project_id=pid, topic="Pay", sources=[], max_pages=1, max_usd=1)
        session.add_all([note, known, BacklogTask(project_id=pid, title="do it", position=0,
                                                  created_by="user")])
        session.flush()
        session.add(Embedding(kind="memory", record_id=note.id, project_id=pid, model="m",
                              vector=[1.0]))
        session.commit()
        return pid, cid, known.id


def rows(factory) -> dict[str, list[str]]:
    """Every row of every table, as it reads. (A role's `updated_at`: the delete moves it.)"""
    with factory() as session:
        found = {table.name: sorted(repr(tuple(row)) for row in session.execute(select(
            *(c for c in table.c if (table.name, c.name) != ("roles", "updated_at")))))
            for table in Base.metadata.sorted_tables}
        found["said_in_turns"] = sorted(map(repr, session.execute(sql(
            "SELECT rowid, * FROM said_in_turns"))))
        return found


def test_the_preview_counts_and_a_delete_leaves_only_what_was_there_without_it(
    make_client, wait_run, tmp_path
):
    client, _model = make_client([text("a", 1, 1), text("b", 1, 1)])
    client.headers["Origin"] = ORIGIN
    factory = client.app.state.session_factory
    kept_root, gone_root = tmp_path / "kept", tmp_path / "gone"
    for root in (kept_root, gone_root):
        (root / ".koloni").mkdir(parents=True)
        (root / ".koloni" / "rules.md").write_text("mine\n")
        (root / "hello.py").write_text("print('hi')\n")
    kept, kept_chat, kept_knowledge = made(client, wait_run, kept_root, factory)
    knew = {"knowledge_id": kept_knowledge, "mode": "map", "topic": "Pay"}
    with factory() as session:  # a role that knows the other's knowledge
        role = session.scalars(select(Role)).first()
        role.knows = [knew]
        session.commit()
        role_id = role.id
    before = rows(factory)  # (as it is with the other project only)
    gone, gone_chat, gone_knowledge = made(client, wait_run, gone_root, factory)
    with factory() as session:  # the other's links to it, and the role knows it too
        session.get_one(Project, kept).memory_links = [gone]
        session.get_one(Role, role_id).knows = [knew, {**knew, "knowledge_id": gone_knowledge}]
        session.commit()
    assert rows(factory) != before
    # KOLONİ's own files of each chat: an attachment.
    runtime = client.app.state.settings.runtime_root
    for cid in (kept_chat, gone_chat):
        attachments.folder(runtime, cid).mkdir(parents=True, exist_ok=True)
        (attachments.folder(runtime, cid) / "a.txt").write_text("x")

    preview = client.get(f"/api/projects/{gone}/delete-preview")
    assert preview.status_code == 200, preview.text
    assert preview.json() == {"chats": 1, "memory": 1, "tasks": 1, "triggers": 1, "knowledge": 1}

    assert client.delete(f"/api/projects/{gone}", headers=OWN).status_code == 204
    assert rows(factory) == before  # every row of it gone, every other row as it was
    assert client.get(f"/api/projects/{gone}").status_code == 404
    assert client.get(f"/api/conversations/{gone_chat}").status_code == 404
    assert [p["id"] for p in client.get("/api/projects").json()] == [kept]
    with factory() as session:
        assert session.get_one(Project, kept).memory_links == []
        assert [one["knowledge_id"] for one in session.get_one(Role, role_id).knows] == [
            kept_knowledge]
    # Its chat's attachments go, as a chat's delete takes them; the other's stay...
    assert not attachments.folder(runtime, gone_chat).exists()
    assert (attachments.folder(runtime, kept_chat) / "a.txt").exists()
    # ...and nothing of the project's folder is touched.
    assert (gone_root / "hello.py").read_text() == "print('hi')\n"
    assert (gone_root / ".koloni" / "rules.md").read_text() == "mine\n"


def test_not_while_anything_of_it_is_at_work_or_waits(make_client, wait_run, project_dir):
    client, _model = make_client([text("a", 1, 1)])
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    run_id = turn(client, wait_run, cid)["id"]
    factory = client.app.state.session_factory
    with factory() as session:  # (as the record would say it: no model is run)
        session.get_one(Run, run_id).status = "running"
        session.commit()
    assert "running" in refused_for(client, pid)
    with factory() as session:
        session.get_one(Run, run_id).status = "completed"
        session.add(AwayRun(project_id=pid, conversation_id=cid, run_id=run_id,
                            status="running"))
        session.commit()
    assert "away" in refused_for(client, pid)
    with factory() as session:
        session.get_one(AwayRun, session.scalars(select(AwayRun.id)).one()).status = "ended"
        lead = session.scalars(select(Agent.id).where(Agent.run_id == run_id)).first()
        merge = Merge(run_id=run_id, agent_id=lead, files=[])  # finished work waits
        session.add(merge)
        session.commit()
        merge_id = merge.id
    assert "Take in or Discard" in refused_for(client, pid)
    with factory() as session:
        session.get_one(Merge, merge_id).status = "applied"
        session.commit()
    # A command kept running past its turn (a dev server).
    commands = client.app.state.runner.commands
    commands._live["c1"] = (cid, "serving")
    try:
        assert "command" in refused_for(client, pid)
    finally:
        del commands._live["c1"]
    # Its knowledge learning.
    with factory() as session:
        row = ProjectKnowledge(project_id=pid, topic="Pay", sources=[], max_pages=1, max_usd=1)
        session.add(row)
        session.commit()
        key = knowledge._key(str(project_dir), knows.knowledge_of(row))
    knowledge._learning[key] = "now"
    try:
        assert "learning" in refused_for(client, pid)
    finally:
        del knowledge._learning[key]
    assert client.get(f"/api/conversations/{cid}").status_code == 200
    assert client.delete(f"/api/projects/{pid}", headers=OWN).status_code == 204


def refused_for(client, pid) -> str:
    refused = client.delete(f"/api/projects/{pid}", headers=OWN)
    assert refused.status_code == 409, refused.text
    return refused.json()["detail"]


def test_only_from_the_apps_own_page(client, project_dir):
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    assert client.delete(f"/api/projects/{pid}").status_code == 403
    assert client.delete(f"/api/projects/{pid}", headers={
        "Origin": "http://evil.example"}).status_code == 403
    assert client.get(f"/api/projects/{pid}").status_code == 200
    assert client.delete(f"/api/projects/{pid}", headers=OWN).status_code == 204
    assert project_dir.is_dir() and (project_dir / "hello.py").exists()
