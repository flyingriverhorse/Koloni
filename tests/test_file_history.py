"""K-devir-4: the last works KOLONİ has on record of one file of the project, for the line
over it in the Workspace - newest first, at most three, the path vetted as the file
endpoints vet theirs."""

from datetime import timedelta

from app.db.models import Agent, Conversation, FileChange, Run, now
from app.workspace import sha256_text
from tests.test_topics import db


def _project(client, folder):
    return client.post("/api/projects", json={"root_path": str(folder)}).json()["id"]


def _agent(session, cid, role, name=""):
    run = Run(conversation_id=cid, status="completed")
    session.add(run)
    session.flush()
    agent = Agent(run_id=run.id, role_name=role, name=name, tools=[], depth=1, status="completed")
    session.add(agent)
    session.flush()
    return agent


def test_the_last_three_changes_of_a_file_newest_first_with_their_status(client, project_dir):
    pid = _project(client, project_dir)
    with db(client) as session:
        chat = Conversation(project_id=pid, title="ETL")
        session.add(chat)
        session.flush()
        coder, reviewer = _agent(session, chat.id, "Coder", "Coder 2"), _agent(session, chat.id, "Reviewer")
        start = now() - timedelta(hours=1)
        for n, (agent, path, kind, status) in enumerate((
            (coder, "app/etl.py", "create", "applied"), (reviewer, "app/etl.py", "modify", "rejected"),
            (coder, "app/etl.py", "modify", "merged"), (reviewer, "app/etl.py", "modify", "proposed"),
            (coder, "other.py", "modify", "applied"),
        )):
            session.add(FileChange(run_id=agent.run_id, agent_id=agent.id, path=path, kind=kind,
                                   after_content="x", after_sha=sha256_text("x"), status=status,
                                   created_at=start + timedelta(minutes=n)))
        session.commit()
        ids, cid = (coder.id, reviewer.id), chat.id
    told = client.get(f"/api/projects/{pid}/file-history", params={"path": "app/etl.py"}).json()
    assert [(t["agent_id"], t["agent_role"], t["agent_name"], t["kind"], t["status"]) for t in told] == [
        (ids[1], "Reviewer", "", "modify", "waiting"), (ids[0], "Coder", "Coder 2", "modify", "taken in"),
        (ids[1], "Reviewer", "", "modify", "discarded"),
    ]
    assert told[0]["at"] > told[1]["at"] > told[2]["at"]
    assert {(t["conversation_id"], t["conversation_title"]) for t in told} == {(cid, "ETL")}
    assert client.get(f"/api/projects/{pid}/file-history", params={"path": "hello.py"}).json() is None


def test_a_path_out_of_the_project_or_a_secret_is_refused_as_the_file_endpoints_do(
    client, project_dir,
):
    (project_dir / ".env").write_text("TOKEN=s3cr3t-value\n")
    pid = _project(client, project_dir)
    for path, status in (("../x.py", 400), (".env", 404), ("", 404)):
        answer = client.get(f"/api/projects/{pid}/file-history", params={"path": path})
        assert answer.status_code == status, path
        assert "s3cr3t" not in answer.text and ".env" not in answer.text
