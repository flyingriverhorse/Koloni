"""☾ Away, park and continue (§10), its first part: in a job while the user is away, a command's card
does not stop the job - KOLONİ parks it (`Parked`), the agent is told it did not run, and the job goes
on; the job then waits, "N parked", its copy kept for the morning. Only a job of a night that runs
parks: I'm back makes the next card the user's again, and a turn they watch never parks."""

import inspect

import pytest
from alembic import command as alembic
from sqlalchemy import select

from app import away
from app.agent import AgentRunner, recover_interrupted
from app.db.away_models import Parked
from app.db.models import BacklogTask, Command
from app.parked import needs_project
from tests.test_away_rules_scenarios import start
from tests.test_away_scenarios import ORIGIN, ended, evening, go_away, lines, night, to_do
from tests.test_backlog_auto import until
from tests.test_chat_flow import text
from tests.test_claude_native import claude_app  # noqa: F401  (a fixture)
from tests.test_migration_0002 import _config
from tests.test_migration_0177 import AT, tables
from tests.test_spawn import call, step

PARKED_HI = (
    'KOLONİ parked this for the user, who is away: run "echo hi". It did not run. '
    "Do what you can without it, and say in your summary what waits."
)


def run(command, id="c1", **more):
    return step(call("run_command", {"command": command, **more}, id))


def chat(client, cid):
    return client.get(f"/api/conversations/{cid}").json()


def commands_in(client, cid):
    return chat(client, cid)["commands"]


def call_result(client, cid, call_id):
    (found,) = [t for t in chat(client, cid)["tool_calls"] if t["provider_call_id"] == call_id]
    return found["result"]


def parked_rows(client):
    with client.app.state.session_factory() as session:
        return list(session.scalars(select(Parked).order_by(Parked.seq)))


def test_a_command_card_in_a_job_is_parked_and_the_job_goes_on(make_client, wait_run, project_dir):
    client, _m, pid, cid, run_id = evening(
        make_client, project_dir, [run("echo hi"), text("one done"), text("two done")], mode="ask"
    )
    wait_run(client, cid, run_id)
    go_away(client, cid)
    one, two = ended(client, pid)["jobs"]
    assert (one["state"], one["why"], two["state"]) == ("waits", "1 parked", "done")
    assert one["asks"] == [] and one["kept"]  # its copy was made at park time, and kept
    (row,) = commands_in(client, one["conversation_id"])
    assert row["status"] == "parked"
    # (and, its copy made as it was parked, what working in it means - `_told_of_copy`)
    assert call_result(client, one["conversation_id"], "c1").startswith(PARKED_HI)
    assert lines(client, cid) == ["1 of 2 To-do done · 1 waits"]
    (parked,) = parked_rows(client)
    assert (parked.kind, parked.what, parked.ref_id, parked.seq) == (
        "command",
        "echo hi",
        row["id"],
        1,
    )
    assert parked.decision is None and parked.data["cwd"] == "."
    with client.app.state.session_factory() as session:
        task = session.get_one(BacklogTask, one["task_id"])
        from app.db.models import Merge

        (kept,) = one["kept"]
        assert parked.data["copy"] == session.get_one(Merge, kept).kept_in
        assert away.parked_left(session, task.id) == 1


def test_the_same_line_parked_twice_is_one_row(make_client, wait_run, project_dir):
    client, _m, pid, cid, run_id = evening(
        make_client,
        project_dir,
        [run("echo hi"), run("echo hi", "c2"), text("one done"), text("two done")],
        mode="ask",
    )
    wait_run(client, cid, run_id)
    go_away(client, cid)
    one = ended(client, pid)["jobs"][0]
    assert [c["status"] for c in commands_in(client, one["conversation_id"])] == [
        "parked",
        "parked",
    ]
    (parked,) = parked_rows(client)
    assert parked.seq == 1 and one["why"] == "1 parked"


def test_back_mid_job_keeps_what_was_parked_and_a_later_card_waits(
    make_client, wait_run, project_dir, gate
):
    # (RF5) the first card parked; the user back; the next card is theirs, the job waits on it
    client, _m, pid, cid, run_id = evening(
        make_client,
        project_dir,
        [run("echo hi"), gate.step(run("echo two", "c2")), text("left")],
        mode="ask",
        plan={"jobs": [{"title": "one"}], "kept_out": []},
    )
    wait_run(client, cid, run_id)
    go_away(client, cid)
    gate.wait_partial()
    found = night(client, pid)
    job_cid = found["jobs"][0]["conversation_id"]
    assert [c["status"] for c in commands_in(client, job_cid)] == ["parked"]
    assert client.post(f"/api/away/{found['id']}/back", headers=ORIGIN).status_code == 200
    gate.release()
    one = until(lambda: (n := night(client, pid))["jobs"][0]["state"] == "waits" and n["jobs"][0])
    assert [c["status"] for c in commands_in(client, job_cid)] == ["parked", "proposed"]
    assert one["asks"][0]["kind"] == "commands"
    assert len(parked_rows(client)) == 1
    client.post(f"/api/commands/{one['asks'][0]['id']}/reject", headers=ORIGIN)


def test_nothing_is_parked_outside_a_job(make_client, wait_run, project_dir):
    # a turn the user watches at Ask: the card waits for them, as ever
    client, _m = make_client([run("echo hi"), text("left it")])
    client.headers.update(ORIGIN)
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(f"/api/conversations/{cid}", json={"permission_mode": "ask"})
    run_id = client.post(f"/api/conversations/{cid}/messages", json={"content": "hi"}).json()[
        "run"
    ]["id"]
    (asked,) = until(
        lambda: [c for c in commands_in(client, cid) if c["status"] == "proposed"] or None
    )
    assert client.post(f"/api/commands/{asked['id']}/reject").status_code == 200
    wait_run(client, cid, run_id)
    assert parked_rows(client) == []


def test_kolonis_own_check_command_in_a_job_is_not_parked():
    # shortcut: read from the code - only an agent's command (`_command_call`) and a CLI's own
    # (`_approve_command`) are parked; KOLONİ's own runs (`_run_in_copy`) pass no `park`. Drive a
    # job's own check at Ask through `_run_in_copy(gated="ask")` if this is ever doubted.
    assert "park=" not in inspect.getsource(AgentRunner._run_in_copy)
    assert "park=self._parker(" in inspect.getsource(AgentRunner._command_call)
    assert "park=self._parker(" in inspect.getsource(AgentRunner._approve_command)


def test_a_restart_leaves_a_job_waiting_only_for_parked_items_waiting(
    make_client, wait_run, project_dir, gate
):
    client, _m, pid, cid, run_id = evening(
        make_client,
        project_dir,
        [run("echo hi"), text("one done"), gate.step(text("two done"))],
        mode="ask",
    )
    wait_run(client, cid, run_id)
    go_away(client, cid)
    gate.wait_partial()
    until(lambda: night(client, pid)["jobs"][0]["state"] == "waits")
    factory = client.app.state.session_factory
    recover_interrupted(factory, [])
    one, two = night(client, pid)["jobs"]
    # its turn was over: what it parked waits for the morning; the job cut at work could not be done
    assert (one["state"], one["why"]) == ("waits", "1 parked")
    assert (two["state"], two["why"]) == ("failed", away.CLOSED)
    # (and what it parked is still on record as parked, for the morning)
    assert [c["status"] for c in commands_in(client, one["conversation_id"])] == ["parked"]
    assert [row.decision for row in parked_rows(client)] == [None]
    gate.release()


@pytest.mark.parametrize(
    ("line", "needs"),
    [
        ("git commit -m x", True),
        ("rm -rf build", True),
        ("cd sub && git push", True),
        ("del dist\\a.js", True),
        ("npm test", False),
        ("npm run build", False),
        ("python -m pytest", False),
    ],
)
def test_needs_project(line, needs):
    assert needs_project(line) is needs


def test_a_native_cli_command_is_parked_with_a_fixed_deny(claude_app, wait_run, project_dir):  # noqa: F811
    client, provider, _default = claude_app(
        [
            {"tool": "Bash", "input": {"command": "echo hi"}, "result": "hi"},
            {"say": "done, echo waits"},
        ],
        default_steps=[to_do({"jobs": [{"title": "one"}]}), text("on your To-do")],
    )
    client.headers.update(ORIGIN)
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(f"/api/conversations/{cid}", json={"permission_mode": "ask"})
    wait_run(
        client,
        cid,
        client.post(f"/api/conversations/{cid}/messages", json={"content": "sleep"}).json()["run"][
            "id"
        ],
    )
    client.patch(f"/api/conversations/{cid}", json={"provider_id": provider["id"]})
    start(client, cid, kept_out=[])
    one = ended(client, pid)["jobs"][0]
    assert (one["state"], one["why"]) == ("waits", "1 parked")
    (row,) = commands_in(client, one["conversation_id"])
    assert (row["status"], row["origin"]) == ("parked", "cli")
    (verdict,) = claude_app.record()["asked"]
    # (KOLONİ's own words, whole: `deny(..., fixed=True)`)
    assert (verdict["behavior"], verdict["message"]) == ("deny", PARKED_HI)
    (parked,) = parked_rows(client)
    assert parked.data["copy"] and one["kept"]


def test_0186_up_and_down(tmp_path):
    import sqlite3

    db = tmp_path / "fresh.db"
    cfg = _config(db)
    alembic.upgrade(cfg, "0186")
    with sqlite3.connect(db) as conn:
        assert "parked" in tables(conn)
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute(
            "INSERT INTO commands (id, run_id, agent_id, command, location, status, output, "
            "output_truncated, timeout_seconds, origin, keep_running, web_off, created_at) VALUES "
            "('c', 'r', 'a', 'echo hi', 'host', 'parked', '', 0, 60, 'koloni', 0, 0, ?)",
            (AT,),
        )
        conn.execute(
            "INSERT INTO questions (id, run_id, agent_id, question, options, leave, status, "
            "created_at) VALUES ('q', 'r', 'a', 'Which?', '[]', 0, 'parked', ?)",
            (AT,),
        )
    alembic.downgrade(cfg, "0185")
    with sqlite3.connect(db) as conn:
        assert "parked" not in tables(conn)
        assert conn.execute("SELECT status FROM commands").fetchone() == ("rejected",)
        assert conn.execute("SELECT status FROM questions").fetchone() == ("cancelled",)


def test_a_parked_command_is_on_record_as_not_run(make_client, wait_run, project_dir):
    client, _m, pid, cid, run_id = evening(
        make_client, project_dir, [run("echo hi"), text("one done"), text("two done")], mode="ask"
    )
    wait_run(client, cid, run_id)
    go_away(client, cid)
    ended(client, pid)
    with client.app.state.session_factory() as session:
        (one,) = session.scalars(select(Command)).all()
        assert (one.status, one.started_at, one.ended_at) == ("parked", None, None)
