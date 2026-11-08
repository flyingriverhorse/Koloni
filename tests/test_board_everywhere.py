"""Slice 86a's fix round: one board of every chat - of every folder and of none - so that what
waits for the user (the rail's badge, the toasts, the list) is said wherever it waits."""

from app.db.models import Agent, BacklogTask, Run

ORIGIN = "http://127.0.0.1:8790"


def test_the_board_of_every_chat_has_another_folders_and_a_plain_chats_waiting_cards(
    client, project_dir, tmp_path
):
    client.headers["Origin"] = ORIGIN
    (tmp_path / "other").mkdir()
    a = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    b = client.post("/api/projects", json={"root_path": str(tmp_path / "other")}).json()["id"]
    in_a, in_b, plain = (
        client.post("/api/conversations", json=body).json()["id"]
        for body in ({"project_id": a}, {"project_id": b}, {}))
    with client.app.state.session_factory() as session:
        for cid in (in_b, plain):  # an agent of each asks the user
            run = Run(conversation_id=cid, status="waiting_approval")
            session.add(run)
            session.flush()
            session.add(Agent(run_id=run.id, role_name="Lead", name="Lead", tools=[],
                              status="waiting_approval"))
        session.add(BacklogTask(project_id=b, title="Add a farewell", status="proposed",
                                position=1, created_by="agent"))
        session.commit()

    everywhere = client.get("/api/board")
    assert everywhere.status_code == 200, everywhere.text
    told = everywhere.json()
    asking = {row["conversation_id"]: [x["status"] for x in row["agents"]]
              for row in told["conversations"]}
    assert asking == {in_a: [], in_b: ["waiting_approval"], plain: ["waiting_approval"]}
    assert (told["limit"], told["backlog_waiting"], told["conflicts"]) == (None, 1, [])
    # A folder's own board keeps to its chats.
    of_a = client.get(f"/api/projects/{a}/board").json()
    assert [row["conversation_id"] for row in of_a["conversations"]] == [in_a]
    assert of_a["backlog_waiting"] == 0
