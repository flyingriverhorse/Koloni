"""0.1.10, rooms are gone: an old chat that held one still opens, its room and what was said in it
are kept as they were, the next turn's Orchestrator still reads what it was told of it, and a room
left running is ended at start - nothing resumes it."""

from app.agent.merge import recover_interrupted
from app.db.models import Room, RoomPost
from tests.test_chat_flow import text
from tests.test_spawn import begin
from tests.test_topic_scenarios import turn

TOLD = "The room ended: everybody's work is over. hello.py prints hi there."


def test_an_old_chat_with_a_room_opens_and_its_next_turn_reads_what_the_room_told(
    make_client, wait_run, project_dir
):
    client, model = make_client([text("first"), text("second")])
    cid, run_id = begin(client, project_dir, mode="full_auto")
    wait_run(client, cid, run_id)
    factory = client.app.state.session_factory
    with factory() as session:  # (as a room of before 0.1.10 left it)
        room = Room(run_id=run_id, goal="Fix the greeting together", status="ended", told=TOLD)
        session.add(room)
        session.flush()
        session.add(RoomPost(room_id=room.id, number=1, type="result", text="Done: hi there."))
        session.commit()
        room_id = room.id
    opened = client.get(f"/api/conversations/{cid}")
    assert opened.status_code == 200, opened.text
    assert "rooms" not in opened.json() and "room_posts" not in opened.json()
    turn(client, wait_run, cid, "go on")
    # (After that turn's message, where its goal stood - as before 0.1.10.)
    assert any(m["content"] == TOLD for m in model.calls[-1]), model.calls[-1]
    with factory() as session:
        assert session.get_one(Room, room_id).goal == "Fix the greeting together"
        assert [p.text for p in session.query(RoomPost).filter_by(room_id=room_id)] == [
            "Done: hi there."
        ]


def test_a_room_left_running_is_ended_at_start_and_never_resumed(
    make_client, wait_run, project_dir
):
    client, _model = make_client([text("done")])
    cid, run_id = begin(client, project_dir, mode="full_auto")
    wait_run(client, cid, run_id)
    factory = client.app.state.session_factory
    with factory() as session:
        rooms = [
            Room(run_id=run_id, goal="a", status="sharing"),
            Room(run_id=run_id, goal="b", status="working", paused=True),
            Room(run_id=run_id, goal="c", status="ended", outcome="agreed"),
        ]
        session.add_all(rooms)
        session.commit()
        ids = [room.id for room in rooms]
    recover_interrupted(factory)
    with factory() as session:
        found = [session.get_one(Room, one) for one in ids]
        assert [(r.status, r.paused) for r in found] == [
            ("interrupted", False),
            ("interrupted", False),
            ("ended", False),
        ]
        assert all(r.ended_at is not None for r in found[:2])
