from app.agent import recover_interrupted
from app.config import load_settings
from app.db.models import Agent, Conversation, FileChange, Message, Project, Run, ToolCall, now
from app.db.session import make_engine, make_session_factory, upgrade_db
from app.main import create_app
from tests.fakes import ScriptedModel
from tests.keyed import TestClient
from tests.test_chat_flow import text
from tests.test_chat_teams_scenarios import OWN


def seed(factory, root):
    with factory() as s:
        s.add(Project(id="p", name="p", root_path=str(root)))
        s.flush()
        s.add(Conversation(id="c", project_id="p"))
        s.flush()
        s.add_all([
            Run(id="r1", conversation_id="c", status="waiting_approval"),
            Run(id="r2", conversation_id="c", status="queued"),
            Run(id="r3", conversation_id="c", status="completed"),
        ])
        s.flush()
        s.add(Agent(id="a", run_id="r1", role_name="Lead", tools=[]))
        s.flush()
        s.add(Message(id="m", conversation_id="c", run_id="r1", role="assistant",
                      content="par", status="streaming"))
        s.flush()

        def call(id, seq, name, status, result=None):
            return ToolCall(id=id, run_id="r1", agent_id="a", message_id="m", seq=seq, provider_call_id=id,
                            name=name, arguments="{}", status=status, result=result)

        s.add_all([
            call("t1", 1, "write_file", "running"),
            call("t2", 2, "read_file", "pending"),
            call("t3", 0, "read_file", "succeeded", "ok"),
        ])
        s.flush()
        s.add(FileChange(id="f", run_id="r1", agent_id="a", tool_call_id="t1", path="f.txt", kind="create",
                         after_content="x", after_sha="0" * 64, status="proposed"))
        s.commit()


def test_restart_marks_open_work_interrupted_and_runs_nothing(tmp_path):
    db = tmp_path / "r.db"
    upgrade_db(db)
    factory = make_session_factory(make_engine(db))
    seed(factory, tmp_path)

    assert recover_interrupted(factory) == 2
    assert recover_interrupted(factory) == 0  # a second pass finds nothing to do

    with factory() as s:
        assert {r.id: r.status for r in s.query(Run)} == {
            "r1": "interrupted", "r2": "interrupted", "r3": "completed"}
        assert s.get(Run, "r1").ended_at is not None
        assert {t.id: t.status for t in s.query(ToolCall)} == {
            "t1": "interrupted", "t2": "interrupted", "t3": "succeeded"}
        assert "server restarted" in s.get(ToolCall, "t1").result
        assert s.get(ToolCall, "t3").result == "ok"
        assert s.get(FileChange, "f").status == "rejected"
        assert s.get(Message, "m").status == "complete" and s.get(Message, "m").content == "par"
    assert not (tmp_path / "f.txt").exists()


def test_app_startup_recovers_and_the_conversation_is_usable_again(tmp_path):
    settings = load_settings({"KOLONI_RUNTIME_ROOT": str(tmp_path / "rt")})
    upgrade_db(settings.db_path)
    seed(make_session_factory(make_engine(settings.db_path)), tmp_path)

    model = ScriptedModel([])
    with TestClient(create_app(settings, model=model), base_url="http://127.0.0.1:8790") as client:
        snap = client.get("/api/conversations/c").json()
        assert [r["status"] for r in snap["runs"]] == ["interrupted", "interrupted", "completed"]
        assert snap["file_changes"][0]["status"] == "rejected"
        assert model.calls == []  # nothing was re-run
        approve = client.post("/api/file-changes/f/approve")
        assert approve.status_code == 409
    assert not (tmp_path / "f.txt").exists()


def queued_then_restarted(tmp_path):
    """`seed`'s turns as they are: r1 at work, r2 the user's message queued behind it."""
    settings = load_settings({"KOLONI_RUNTIME_ROOT": str(tmp_path / "rt")})
    upgrade_db(settings.db_path)
    factory = make_session_factory(make_engine(settings.db_path))
    seed(factory, tmp_path)
    with factory() as s:
        s.get_one(Run, "r1").started_at = now()
        s.get_one(Run, "r2").by_user = True
        s.add(Message(id="q", conversation_id="c", run_id="r2", role="user",
                      content="then run the tests"))
        s.commit()
    return settings, factory


def test_a_message_queued_before_a_restart_is_not_sent_until_the_user_sends_it(tmp_path, wait_run):
    # (Code review, 14 Nov: it was "interrupted" and never given to the Lead, whatever was said.)
    settings, _factory = queued_then_restarted(tmp_path)
    model = ScriptedModel([text("They pass.")])
    with TestClient(create_app(settings, model=model), base_url="http://127.0.0.1:8790") as client:
        runs = {r["id"]: r for r in client.get("/api/conversations/c").json()["runs"]}
        assert (runs["r2"]["status"], runs["r2"]["started_at"]) == ("interrupted", None)
        assert model.calls == []  # (nothing runs by itself)
        assert client.post("/api/runs/r2/send").status_code == 403  # (the user's, from the page)
        assert client.post("/api/runs/r1/send", headers=OWN).status_code == 409  # (it ran)
        sent = client.post("/api/runs/r2/send", headers=OWN)
        assert sent.status_code == 200, sent.text
        assert (sent.json()["run"]["status"], sent.json()["message"]["id"]) == ("running", "q")
        snap = wait_run(client, "c", "r2")
        assert next(r for r in snap["runs"] if r["id"] == "r2")["status"] == "completed"
        assert "then run the tests" in str(model.calls[0])
        # Its turn is the newest now: last in the chat and in what the Lead is given.
        assert [r["id"] for r in snap["runs"]][-1] == "r2"
        assert client.post("/api/runs/r2/send", headers=OWN).status_code == 409  # (sent once)


def test_a_message_sent_again_while_a_turn_is_at_work_waits_behind_it(tmp_path):
    settings, factory = queued_then_restarted(tmp_path)
    model = ScriptedModel([])
    with TestClient(create_app(settings, model=model), base_url="http://127.0.0.1:8790") as client:
        with factory() as s:  # (a turn the user started since)
            s.add(Run(id="r4", conversation_id="c", status="running", started_at=now()))
            s.commit()
        sent = client.post("/api/runs/r2/send", headers=OWN)
        assert sent.status_code == 200, sent.text
        assert (sent.json()["run"]["status"], sent.json()["run"]["started_at"]) == ("queued", None)
        assert model.calls == []


def test_an_agent_that_had_finished_and_was_only_answering_stays_finished(tmp_path):
    from datetime import UTC, datetime

    db = tmp_path / "r.db"
    upgrade_db(db)
    factory = make_session_factory(make_engine(db))
    seed(factory, tmp_path)
    done = datetime(2026, 10, 5, 10, 0, 0, tzinfo=UTC)
    with factory() as s:
        # Both had finished; another agent's message had them answering when the server died.
        s.add_all([
            Agent(id="k1", run_id="r1", parent_agent_id="a", role_name="Coder", name="Coder",
                  tools=[], depth=1, status="running", report="coded", ended_at=done),
            Agent(id="k2", run_id="r1", parent_agent_id="a", role_name="Tester", name="Tester",
                  tools=[], depth=1, status="running", error="step_limit", ended_at=done),
        ])
        s.commit()
    recover_interrupted(factory)
    with factory() as s:
        assert s.get(Agent, "a").status == "interrupted"  # it was at work
        coder, tester = s.get(Agent, "k1"), s.get(Agent, "k2")
        assert (coder.status, coder.report, coder.ended_at) == ("completed", "coded", done)
        assert (tester.status, tester.error, tester.ended_at) == ("failed", "step_limit", done)
