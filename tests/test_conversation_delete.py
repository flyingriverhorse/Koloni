"""Slice 76: archived conversations deleted for good, with their turns and all that hangs off
them; the project's memory stays, no longer pointing at them. One at work, with a trigger, or
with changes still the user's to decide is not deleted, and the answer says why."""

from sqlalchemy import select
from sqlalchemy import text as sql

from app.db.models import Base, Memory, Run
from tests.test_agent_writes import write
from tests.test_chat_flow import text
from tests.test_usage_scenarios import ORIGIN, began, turn


def delete(client, *ids):
    told = client.post("/api/conversations/delete", json={"ids": list(ids)})
    assert told.status_code == 200, told.text
    return told.json()


def test_an_archived_conversation_is_deleted_with_everything_of_its_turns(
    make_client, wait_run, project_dir
):
    (project_dir / "README.md").write_text("mine\n")
    client, _model, pid, cid = began(make_client, project_dir, [
        write("hello.txt", "hi\n"), text("wrote it", 3, 1), text("again", 2, 1)])
    turn(client, wait_run, cid)
    turn(client, wait_run, cid, "and again")
    keep = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    factory = client.app.state.session_factory
    with factory() as session:
        runs = list(session.scalars(select(Run.id).where(Run.conversation_id == cid)))
        session.add(Memory(project_id=pid, tier="note", text="kept", origin="agent",
                           conversation_id=cid, run_id=runs[0]))
        session.commit()
    gone = {cid, *runs}

    def pointing():  # the tables with a row of it or of its turns
        with factory() as session:
            return {f"{table.name}.{name}" for table in Base.metadata.sorted_tables
                    for name in ("conversation_id", "run_id") if name in table.c
                    and session.execute(select(table.c[name]).where(
                        table.c[name].in_(gone)).limit(1)).first()}

    assert {"runs.conversation_id", "agents.run_id", "messages.run_id", "tool_calls.run_id",
            "events.conversation_id", "memories.run_id"} <= pointing()
    # Only one put away first.
    refused = delete(client, cid)
    assert refused["deleted"] == [] and "archive" in refused["refused"][0]["why"]
    assert client.patch(f"/api/conversations/{cid}", json={"archived": True}).status_code == 200
    assert delete(client, cid) == {"deleted": [cid], "refused": []}
    assert client.get(f"/api/conversations/{cid}").status_code == 404
    assert client.get(f"/api/conversations/{keep}").status_code == 200
    assert (project_dir / "README.md").exists()  # the project's files stay
    # Nothing anywhere points at it or its turns any more...
    assert pointing() == set()
    with factory() as session:
        # ...not even what was said, as recall finds it; the memory stays, pointing nowhere.
        assert session.execute(sql(
            "SELECT count(*) FROM said_in_turns WHERE conversation_id = :c"), {"c": cid}).scalar() == 0
        note = session.scalars(select(Memory).where(Memory.text == "kept")).one()
        assert (note.conversation_id, note.run_id) == (None, None)


def test_a_sub_agent_a_room_a_discussion_its_talk_and_a_compare_go_with_it(
    make_client, wait_run, project_dir
):
    from app.db import models as m

    client, _model, _pid, cid = began(make_client, project_dir, [text("a", 1, 1)])
    run_id = turn(client, wait_run, cid)["id"]
    factory = client.app.state.session_factory
    with factory() as session:  # each as the record keeps it; no model is run
        lead = session.scalars(select(m.Agent).where(m.Agent.run_id == run_id)).one()
        sub = m.Agent(run_id=run_id, role_name="Coder", tools=[], parent_agent_id=lead.id, depth=1)
        session.add(sub)
        session.flush()
        message = session.scalars(select(m.Message).where(m.Message.run_id == run_id)).first()
        call = m.ToolCall(run_id=run_id, agent_id=lead.id, message_id=message.id, seq=9,
                          provider_call_id="c9", name="discuss", arguments="{}")
        room = m.Room(run_id=run_id, goal="agree")
        session.add_all([call, room])
        session.flush()
        talk = m.Discussion(run_id=run_id, agent_id=lead.id, tool_call_id=call.id, topic="t",
                            max_rounds=1)
        session.add(talk)
        session.flush()
        made = [sub, call, room, talk, m.Compare(conversation_id=cid, sides=[]),
                m.RoomMember(room_id=room.id, position=0, role="Coder", agent_id=sub.id),
                m.RoomPost(room_id=room.id, number=1, type="note", text="hi"),
                m.RoomItem(room_id=room.id, number=1, title="do it"),
                m.DiscussionMember(discussion_id=talk.id, agent_id=sub.id, position=0),
                m.DiscussionPost(discussion_id=talk.id, round=1, content="mine"),
                m.ChannelMessage(run_id=run_id, from_agent_id=sub.id, to_agent_id=lead.id,
                                 kind="message", content="done")]
        session.add_all(made)
        session.commit()
        kept = [(type(one), one.id) for one in made]
    assert client.patch(f"/api/conversations/{cid}", json={"archived": True}).status_code == 200
    assert delete(client, cid)["deleted"] == [cid]
    with factory() as session:
        assert [(kind.__name__, key) for kind, key in kept if session.get(kind, key)] == []


def test_one_with_a_trigger_is_not_deleted_and_the_rest_are(make_client, wait_run, project_dir):
    client, _model, pid, cid = began(make_client, project_dir, [text("a", 1, 1)])
    turn(client, wait_run, cid)
    other = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    made = client.post(f"/api/projects/{pid}/triggers", json={
        "name": "Nightly", "kind": "schedule", "conversation_id": cid, "message": "look",
        "config": {"every_minutes": 60}})
    assert made.status_code == 201, made.text
    for one in (cid, other):
        assert client.patch(f"/api/conversations/{one}", json={"archived": True}).status_code == 200
    told = delete(client, cid, other)
    assert told["deleted"] == [other]
    assert told["refused"][0]["id"] == cid and "Nightly" in told["refused"][0]["why"]
    assert client.get(f"/api/conversations/{cid}").status_code == 200


def test_one_at_work_or_with_changes_still_to_decide_is_not_deleted(
    make_client, wait_run, project_dir
):
    from app.db.models import Agent, Merge

    client, _model, _pid, cid = began(make_client, project_dir, [text("a", 1, 1)])
    run_id = turn(client, wait_run, cid)["id"]
    assert client.patch(f"/api/conversations/{cid}", json={"archived": True}).status_code == 200
    factory = client.app.state.session_factory

    def refused_for():
        told = delete(client, cid)
        assert told["deleted"] == []
        return told["refused"][0]["why"]

    with factory() as session:  # (as the record would say it: no model is run)
        session.get_one(Run, run_id).status = "running"
        session.commit()
    assert "at work" in refused_for()
    with factory() as session:
        session.get_one(Run, run_id).status = "completed"
        lead = session.scalars(select(Agent.id).where(Agent.run_id == run_id)).first()
        # A card still to answer; and a copy kept on disk, as a compare's side waits in one.
        merge = Merge(run_id=run_id, agent_id=lead, files=[])
        session.add(merge)
        session.commit()
        merge_id = merge.id
    assert "yours to take in or discard" in refused_for()
    with factory() as session:
        kept = session.get_one(Merge, merge_id)
        kept.status, kept.kept_in = "interrupted", str(project_dir)
        session.commit()
    assert "yours to take in or discard" in refused_for()
    assert client.get(f"/api/conversations/{cid}").status_code == 200


def test_only_from_the_apps_own_page(make_client, project_dir):
    client, _model, _pid, cid = began(make_client, project_dir, [])
    del client.headers["Origin"]  # an agent's command against the app's address
    assert client.post("/api/conversations/delete", json={"ids": [cid]}).status_code == 403
    client.headers["Origin"] = ORIGIN
    assert client.post("/api/conversations/delete", json={"ids": ["nope"]}).json()["refused"][0][
        "why"] == "not found"
