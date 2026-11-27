"""Task 10 (0.1.11): note_decision - the Orchestrator notes a decision it took for the user; it is a
row of Decided for you (who and when KOLONİ's, its words masked, cut, on one line), changes
nothing by itself, at most 10 a turn; the user's OK and Change on it are theirs alone."""

from sqlalchemy import select

from app import status_now
from app.api.decisions import JOB_CHAT
from app.db.models import AwayRun, BacklogTask, Conversation, Question, Run
from app.tools_at_work import NOTED_FULL
from tests.conftest import Gate
from tests.test_background_spawn import bg, said_in, tool_result
from tests.test_chat_flow import text
from tests.test_claim_scenarios import setup
from tests.test_parallel import statuses, until
from tests.test_spawn import call, step

KEY = "sk-ant-api03-" + "q" * 40
EVIL = {"Origin": "http://evil.example"}


def note(id, what="Use SQLite for the cart", why="One user, no server to run"):
    return call("note_decision", {"what": what, "why": why}, id)


def log(client, cid):
    pid = client.get(f"/api/conversations/{cid}").json()["conversation"]["project_id"]
    rows = client.get(f"/api/projects/{pid}/decisions", params={"unseen": True}).json()["rows"]
    return [row for row in rows if row["kind"] == "noted"]


def test_a_noted_decision_is_a_row_of_decided_for_you_and_changes_nothing(
    make_client, wait_run, project_dir
):
    long = f"Use SQLite; the key {KEY} stays.\nNo server. " + "x" * 300
    client, model, cid, run_id = setup(
        make_client,
        project_dir,
        {"Lead": [step(note("n1", what=long, why="It is\nsmall")), text("done")]},
    )
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    told = tool_result(model.calls_of["Lead"][1], "n1")
    assert told.startswith("Noted as decision ") and "changes nothing by itself" in told
    (row,) = log(client, cid)
    assert (row["who"], row["what"], row["seen"], row["undo"]) == (
        "orchestrator",
        "Decided",
        False,
        "change",
    )
    assert KEY not in row["quote"] and "***" in row["quote"]  # masked
    assert "\n" not in row["quote"] and len(row["quote"]) <= 200 and row["quote"].endswith("…")
    assert row["why"] == "It is small" and row["conversation_id"] == cid
    assert row["id"] == f"noted:{row['link']['id']}" and told.startswith(
        f"Noted as decision {row['link']['id']} "
    )
    # (no card, no task, no change of its own)
    with client.app.state.session_factory() as session:
        assert not session.scalars(select(Question)).all()
        assert not session.scalars(select(BacklogTask)).all()
    assert snap["file_changes"] == [] and snap["commands"] == []


def test_an_eleventh_note_in_a_turn_is_refused(make_client, wait_run, project_dir):
    client, model, cid, run_id = setup(
        make_client,
        project_dir,
        {"Lead": [step(*(note(f"n{i}", what=f"choice {i}") for i in range(11))), text("done")]},
    )
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    notes = [c for c in snap["tool_calls"] if c["name"] == "note_decision"]
    assert sorted(c["status"] for c in notes) == ["failed", *["succeeded"] * 10]
    assert [c["result"] for c in notes if c["status"] == "failed"] == [f"error: {NOTED_FULL}"]
    assert len(log(client, cid)) == 10


def test_ok_is_the_users_own_and_marks_it_seen(make_client, wait_run, project_dir):
    client, model, cid, run_id = setup(
        make_client, project_dir, {"Lead": [step(note("n1")), text("done")]}
    )
    wait_run(client, cid, run_id)
    (row,) = log(client, cid)
    one = row["link"]["id"]
    assert client.post(f"/api/decisions/{one}/ok", headers=EVIL).status_code == 403
    assert (
        client.post(f"/api/decisions/{one}/change", json={"words": "x"}, headers=EVIL).status_code
        == 403
    )
    assert client.post("/api/decisions/nobody/ok").status_code == 404
    assert client.post(f"/api/decisions/{one}/ok").status_code == 204
    assert log(client, cid) == []  # (seen: Not seen no longer lists it)


def test_change_while_its_turn_works_goes_into_it_as_the_users_word(
    make_client, wait_run, project_dir
):
    a = Gate()
    client, model, cid, run_id = setup(
        make_client,
        project_dir,
        {
            "Lead": [
                step(note("n1"), bg("Coder", "do A", "s1")),
                text("noted"),
                text("heard the change"),
                text("coder back"),
                text("spare"),
            ],
            "Coder": [a.step(text("A done"))],
        },
    )
    until(client, cid, lambda s: statuses(s) == {"Lead": "waiting", "Coder": "running"})
    (row,) = log(client, cid)
    one = row["link"]["id"]
    changed = client.post(f"/api/decisions/{one}/change", json={"words": "use Postgres"})
    assert changed.status_code == 201, changed.text
    assert changed.json()["run"]["id"] == run_id and changed.json()["queued_why"] is None
    until(client, cid, lambda s: len(model.calls_of["Lead"]) >= 3)
    words = f"I change your decision {one}: use Postgres"
    assert said_in(model.calls_of["Lead"][2], words) == 1
    assert not any(
        "Use SQLite" in m["content"]
        for m in client.get(f"/api/conversations/{cid}").json()["messages"]
        if m["role"] == "user"
    )  # (no agent's word)
    a.release()
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert len(snap["runs"]) == 1


def test_change_after_its_turn_starts_a_turn_of_kolonis(make_client, wait_run, project_dir):
    client, model, cid, run_id = setup(
        make_client,
        project_dir,
        {"Lead": [step(note("n1", what="Use SQLite")), text("done"), text("changed it")]},
    )
    wait_run(client, cid, run_id)
    (row,) = log(client, cid)
    changed = client.post(f"/api/decisions/{row['link']['id']}/change", json={"words": "Postgres"})
    assert changed.status_code == 201, changed.text
    later = changed.json()["run"]["id"]
    assert later != run_id
    snap = wait_run(client, cid, later)
    assert snap["runs"][-1]["status"] == "completed", snap["runs"][-1]["error"]
    told = changed.json()["message"]["content"]
    assert told.startswith('KOLONİ: the user changed your decision "Use SQLite"')
    assert '"Postgres"' in told
    with client.app.state.session_factory() as session:
        assert session.get_one(Run, later).by_user is False  # (KOLONİ's: not read as the user's)


def test_change_of_a_jobs_decision_is_refused_and_read_status_names_it(
    make_client, wait_run, project_dir
):
    client, model, cid, run_id = setup(
        make_client, project_dir, {"Lead": [step(note("n1", what="Use SQLite")), text("done")]}
    )
    wait_run(client, cid, run_id)
    (row,) = log(client, cid)
    with client.app.state.session_factory() as session:
        pid = session.get_one(Conversation, cid).project_id
        night = AwayRun(project_id=pid, conversation_id=cid, run_id="r", status="ended")
        session.add(night)
        session.flush()
        session.add(
            BacklogTask(
                project_id=pid,
                title="job",
                status="done",
                position=0,
                created_by="user",
                conversation_id=cid,
                away_run_id=night.id,
            )
        )
        session.commit()
        # (read_status, the Orchestrator's look at its project, names it as the log does)
        assert 'the Orchestrator: Decided "Use SQLite"' in status_now.answer(session, pid)
    changed = client.post(f"/api/decisions/{row['link']['id']}/change", json={"words": "Postgres"})
    assert changed.status_code == 409 and changed.json()["detail"] == JOB_CHAT
    assert log(client, cid) == [row]  # (nothing sent: not seen)
