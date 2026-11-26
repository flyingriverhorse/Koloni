"""☾ Away, park and continue (§10), its questions: in a job whose night runs the Orchestrator decides
what it can - its own question too (B-181 holds only in a turn the user watches) - and what only the
user can know it answers `park`: the question is parked for the morning and the job goes on. A
question the Orchestrator could not answer is parked too; nothing of it waits, nothing is told."""

import json

from sqlalchemy import select

from app.agent import questions_mixin as questions
from app.agent.questions_mixin import LEAD_ANSWERED, ORCHESTRATOR_AWAY, PARK_TOO
from app.db.away_models import Parked
from app.db.models import Question
from app.parked import COULD_NOT_ANSWER, PARKED_ASKED
from app.team import quoted
from tests.test_away_scenarios import ORIGIN, ended, evening, go_away, night
from tests.test_backlog_auto import until
from tests.test_chat_flow import text
from tests.test_spawn import call, spawn, step
from tests.turn_helpers import HeldClock

DB = ["Postgres", "SQLite"]
ONE = {"jobs": [{"title": "one"}], "kept_out": []}
LEAD_ANSWERED_START = LEAD_ANSWERED.split("(")[0]  # "The Orchestrator answered for the user "


def ask(question="Which database?", options=DB, id="q1"):
    return step(
        call("ask_user", {"question": question, **({"options": options} if options else {})}, id)
    )


def says(answer, why="the repo uses it"):
    return text(json.dumps({"answer": answer, "why": why}), i=40, o=12)


def chat(client, cid):
    return client.get(f"/api/conversations/{cid}").json()


def call_result(client, cid, call_id):
    (found,) = [t for t in chat(client, cid)["tool_calls"] if t["provider_call_id"] == call_id]
    return found["result"]


def lead_requests(model):
    """The one-shot requests KOLONİ made of the Lead for the user (`LEAD_ASKED`)."""
    return [
        one[-1]["content"]
        for one in model.calls
        if isinstance(one[-1].get("content"), str)
        and "answer for them what you" in one[-1]["content"]
    ]


def rows(client):
    with client.app.state.session_factory() as session:
        return list(session.scalars(select(Parked).order_by(Parked.seq)))


def questions_of(client):
    with client.app.state.session_factory() as session:
        return list(session.scalars(select(Question)))


def test_in_a_job_the_orchestrators_own_question_is_decided_and_is_in_decided_for_you(
    make_client, wait_run, project_dir
):
    client, model, pid, cid, run_id = evening(
        make_client, project_dir, [ask(), says("Postgres"), text("one done")], plan=ONE
    )
    wait_run(client, cid, run_id)
    go_away(client, cid)
    done = ended(client, pid)
    (one,) = done["jobs"]
    assert one["state"] == "done"
    (asked,) = lead_requests(model)
    assert ORCHESTRATOR_AWAY in asked and quoted("park") in asked  # (an option among the rest)
    assert call_result(client, one["conversation_id"], "q1").startswith(LEAD_ANSWERED_START)
    (question,) = questions_of(client)
    assert (question.answer, question.lead_why, question.status) == (
        "Postgres",
        "the repo uses it",
        "answered",
    )
    assert done["decided"] == ['"Which database?": Postgres'] and rows(client) == []


def test_park_from_the_lead_parks_its_own_question(make_client, wait_run, project_dir):
    client, _m, pid, cid, run_id = evening(
        make_client,
        project_dir,
        [
            ask("Which account do I deploy to?", None),
            says("park", "only the user knows it"),
            text("one done"),
        ],
        plan=ONE,
    )
    wait_run(client, cid, run_id)
    go_away(client, cid)
    (one,) = ended(client, pid)["jobs"]
    assert (one["state"], one["why"]) == ("waits", "1 parked")
    (question,) = questions_of(client)
    assert (question.status, question.answer, question.lead_why) == ("parked", None, None)
    (row,) = rows(client)
    assert (row.kind, row.ref_id, row.what) == ("question", question.id, question.question)
    assert row.data == {"options": [], "why": "only the user knows it"}
    assert call_result(client, one["conversation_id"], "q1") == PARKED_ASKED.format(
        what=quoted("Which account do I deploy to?")
    )


def test_an_option_spelled_park_is_parked_not_picked(make_client, wait_run, project_dir):
    client, _m, pid, cid, run_id = evening(
        make_client,
        project_dir,
        [
            ask("Park or drive?", ["Park", "Drive"]),
            says("Park", "the user's car"),
            text("one done"),
        ],
        plan=ONE,
    )
    wait_run(client, cid, run_id)
    go_away(client, cid)
    (one,) = ended(client, pid)["jobs"]
    (question,) = questions_of(client)
    assert (question.status, question.answer) == ("parked", None)
    assert one["why"] == "1 parked" and rows(client)[0].data["options"] == ["Park", "Drive"]


def test_a_sub_agents_question_the_lead_cannot_read_is_parked(make_client, wait_run, project_dir):
    client, model, pid, cid, run_id = evening(
        make_client,
        project_dir,
        [
            spawn("Coder", "sort the list"),
            ask("Sort by date or by name?", ["by date", "by name"]),
            text("not a line of JSON"),
            text("coder left it"),
            text("one done"),
        ],
        plan=ONE,
    )
    wait_run(client, cid, run_id)
    go_away(client, cid)
    (one,) = ended(client, pid)["jobs"]
    (asked,) = lead_requests(model)
    assert PARK_TOO in asked and ORCHESTRATOR_AWAY not in asked  # (a sub-agent's: the 2nd alone)
    (question,) = questions_of(client)
    assert question.status == "parked"
    (row,) = rows(client)
    assert row.data["why"] == COULD_NOT_ANSWER and one["why"] == "1 parked"


def test_a_cli_lead_past_its_most_or_with_tools_of_its_own_parks(
    make_client, wait_run, project_dir, monkeypatch
):
    # (a Lead on a CLI with none of its turn's LEAD_CLI_MOST left: no request, the question parked)
    monkeypatch.setattr(questions, "mode_of", lambda _provider: "session")
    monkeypatch.setattr(questions, "LEAD_CLI_MOST", 0)
    client, model, pid, cid, run_id = evening(
        make_client, project_dir, [ask(), text("one done")], plan=ONE
    )
    wait_run(client, cid, run_id)
    go_away(client, cid)
    (one,) = ended(client, pid)["jobs"]
    assert lead_requests(model) == []
    (question,) = questions_of(client)
    assert question.status == "parked" and rows(client)[0].data["why"] == COULD_NOT_ANSWER
    said = [
        m["content"]
        for m in chat(client, one["conversation_id"])["messages"]
        if m["role"] == "koloni"
    ]
    assert any("in this turn, the most on a CLI" in line for line in said), said


def test_parking_starts_no_second_job_and_tells_no_wait(
    make_client, wait_run, project_dir, monkeypatch
):
    # (what the job's waiting would do: put it "waits" at work, and the next job may start)
    from app import away

    moved: list = []
    real = away.waits
    monkeypatch.setattr(
        away,
        "waits",
        lambda session, run_id, waiting: (
            moved.append((waiting, out := real(session, run_id, waiting))) or out
        ),
    )
    client, _m, pid, cid, run_id = evening(
        make_client,
        project_dir,
        [ask(), says("park", "a password"), text("one done"), text("two done")],
    )
    wait_run(client, cid, run_id)
    go_away(client, cid)
    one, two = ended(client, pid)["jobs"]
    assert (one["state"], one["why"], two["state"]) == ("waits", "1 parked", "done")
    assert [one for one in moved if one[0] and one[1] is not None] == []
    # one job at a time: the second started once the first's turn was over
    first, second = (chat(client, job["conversation_id"])["runs"][0] for job in (one, two))
    assert second["created_at"] >= first["ended_at"]


def test_stop_or_a_ceiling_cut_while_the_lead_answers_parks_nothing(
    make_client, wait_run, project_dir, gate
):
    client, _m, pid, cid, run_id = evening(
        make_client, project_dir, [ask(), gate.step(says("park", "x")), text("left")], plan=ONE
    )
    wait_run(client, cid, run_id)
    go_away(client, cid)
    gate.wait_partial()  # (the Orchestrator is asked for the user)
    found = night(client, pid)
    assert client.post(f"/api/away/{found['id']}/stop", headers=ORIGIN).status_code == 200
    gate.release()
    until(lambda: night(client, pid)["status"] == "ended")
    one = until(lambda: (j := night(client, pid)["jobs"][0])["state"] == "stopped" and j)
    assert rows(client) == [] and one["why"] == "Stopped by you."
    (question,) = questions_of(client)
    assert question.status != "parked"


def test_back_before_the_lead_answers_its_own_question_it_waits_for_the_user(
    make_client, wait_run, project_dir
):
    # (RF5) its timer held: the user back first - the Orchestrator is not asked, the question waits
    client, model, pid, cid, run_id = evening(
        make_client, project_dir, [ask(), text("one done")], plan=ONE
    )
    wait_run(client, cid, run_id)
    clock = client.app.state.runner.call_later = HeldClock()
    go_away(client, cid)
    until(lambda: questions_of(client) or None)
    (timer,) = until(lambda: [t for t in clock.set if t.delay == 0.0 and not t.cancelled] or None)
    found = night(client, pid)
    assert client.post(f"/api/away/{found['id']}/back", headers=ORIGIN).status_code == 200
    calls = len(model.calls)
    client.portal.call(timer.fire)
    (question,) = questions_of(client)
    assert question.status == "pending" and len(model.calls) == calls and rows(client) == []
    assert (
        client.post(
            f"/api/questions/{question.id}/answer", json={"answer": "SQLite"}, headers=ORIGIN
        ).status_code
        == 200
    )
    until(lambda: night(client, pid)["jobs"][0]["state"] == "done")
