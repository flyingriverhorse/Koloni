"""A long chat opens on its newest turns (`GET /api/conversations/{id}?turns=N`): ~600 turns were
~15 MB in one answer, sent again at every dropped event stream. Older turns come a page at a time
(`before=`); one that still waits for the user comes with the first page, whatever its age. Without
`turns` the answer is the whole chat, as before."""

from datetime import timedelta

from app.db.models import Agent, Merge, Message, Question, Run, now

ORIGIN = "http://127.0.0.1:8790"


def chat_of(client, project_dir, turns: int) -> tuple[str, list[str]]:
    """A chat of `turns` turns, a minute apart, each with its question and its answer; the run ids,
    oldest first."""
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    ids = []
    start = now() - timedelta(days=1)
    with client.app.state.session_factory() as session:
        for n in range(turns):
            at = start + timedelta(minutes=n)
            run = Run(conversation_id=cid, status="completed", created_at=at, by_user=True)
            session.add(run)
            session.flush()
            lead = Agent(run_id=run.id, role_name="Lead", name="Lead", tools=[], status="completed")
            session.add(lead)
            session.flush()
            session.add_all(
                [
                    Message(conversation_id=cid, run_id=run.id, role="user", content=f"ask {n}"),
                    Message(
                        conversation_id=cid,
                        run_id=run.id,
                        agent_id=lead.id,
                        role="assistant",
                        content=f"answer {n}",
                    ),
                ]
            )
            ids.append(run.id)
        session.commit()
    return cid, ids


def lead_of(client, run_id: str) -> str:
    with client.app.state.session_factory() as session:
        return session.query(Agent.id).filter(Agent.run_id == run_id).scalar()


def test_a_long_chat_opens_on_its_newest_turns_and_reads_older_ones_a_page_at_a_time(
    client, project_dir
):
    cid, ids = chat_of(client, project_dir, 12)
    page = client.get(f"/api/conversations/{cid}", params={"turns": 5}).json()
    assert [run["id"] for run in page["runs"]] == ids[7:]
    assert [m["content"] for m in page["messages"]][:2] == ["ask 7", "answer 7"]
    assert len(page["messages"]) == 10 and {a["run_id"] for a in page["agents"]} == set(ids[7:])
    assert (page["older"], page["older_from"]) == (7, ids[7])
    earlier = client.get(
        f"/api/conversations/{cid}", params={"turns": 5, "before": page["older_from"]}
    ).json()
    assert [run["id"] for run in earlier["runs"]] == ids[2:7]
    assert (earlier["older"], earlier["older_from"]) == (2, ids[2])
    first = client.get(
        f"/api/conversations/{cid}", params={"turns": 5, "before": earlier["older_from"]}
    ).json()
    assert [run["id"] for run in first["runs"]] == ids[:2]
    assert (first["older"], first["older_from"]) == (0, None)
    # Whole, as before, where no page is asked for.
    whole = client.get(f"/api/conversations/{cid}").json()
    assert len(whole["runs"]) == 12 and (whole["older"], whole["older_from"]) == (0, None)
    assert (
        client.get(f"/api/conversations/{cid}", params={"before": "nope", "turns": 5}).status_code
        == 404
    )


def test_an_old_turn_that_still_waits_comes_with_the_first_page(client, project_dir):
    cid, ids = chat_of(client, project_dir, 12)
    with client.app.state.session_factory() as session:
        # A copy kept for Take in, and an answer the Orchestrator gave for you not OK'd yet.
        session.add(
            Merge(run_id=ids[1], agent_id=lead_of(client, ids[1]), status="interrupted", files=[])
        )
        session.add(
            Question(
                run_id=ids[3],
                agent_id=lead_of(client, ids[3]),
                question="which?",
                options=["a", "b"],
                status="answered",
                answer="a",
                lead_why="your rules say so",
            )
        )
        # And a message not sent before a restart, still to Send.
        unsent = session.get_one(Run, ids[4])
        unsent.status, unsent.started_at = "interrupted", None
        session.commit()
    page = client.get(f"/api/conversations/{cid}", params={"turns": 5}).json()
    assert [run["id"] for run in page["runs"]] == [ids[1], ids[3], ids[4], *ids[7:]]
    assert [m["status"] for m in page["merges"]] == ["interrupted"]
    assert len(page["questions"]) == 1
    assert (page["older"], page["older_from"]) == (7, ids[7])
