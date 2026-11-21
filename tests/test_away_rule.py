"""☾ Away's one rule (`AgentRunner._decide_after`): a card KOLONİ marks as the Orchestrator's to
decide is decided at once while the project is away, after the project's minutes otherwise -
in a To-do task's turn too - and never while the user types an answer; a card that always waits
(a command, a change, the web, another model, KOLONİ's own kept-work card below Full auto) is
never reached by it."""

from types import SimpleNamespace

from sqlalchemy import select

from app.agent.questions_mixin import TYPING_HOLD_SECONDS
from app.db.models import AwayRun, Conversation
from tests.test_agent_writes import wait_status
from tests.test_b397 import at_steps, looking
from tests.test_backlog import setup
from tests.test_backlog_auto import tasks, until
from tests.test_chat_flow import text
from tests.test_lead_decides import (
    CODER,
    OWN,
    ask,
    fire,
    held,
    lead_timers,
    question_of,
    says,
    until_answered,
)
from tests.test_spawn import begin, call, spawn, step
from tests.test_team import team  # noqa: F401  (a fixture)


def away_chat(client, project_dir, **settings):
    """A chat of a project that is away (Go away's running row); returns (pid, cid)."""
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    assert client.patch(f"/api/conversations/{cid}", json=settings, headers=OWN).status_code == 200
    with client.app.state.session_factory() as session:
        session.add(AwayRun(project_id=pid, conversation_id=cid, run_id="r", status="running"))
        session.commit()
    return pid, cid


def post(client, cid, words="sort it"):
    # (Not from the app's own page: a message of the user's own would end Away.)
    return client.post(f"/api/conversations/{cid}/messages",
                       json={"content": words}).json()["run"]["id"]


def test_a_to_do_tasks_question_is_decided_after_the_projects_minutes(
        make_client, project_dir):
    # K-r135 lifted: a To-do task's card is no longer only the user's.
    client, _model = make_client([CODER, ask(), says("by date"), text("sorted"), text("done")])
    clock = held(client)
    pid, _ = setup(client, project_dir, "sort the list")
    assert client.patch(f"/api/projects/{pid}", json={
        "when_away": "lead", "away_minutes": 10, "spawn_approval": "never"}).status_code == 200
    cid = client.post(f"/api/projects/{pid}/backlog/next").json()["conversation_id"]
    fire(client, until(lambda: lead_timers(clock, 600.0))[0])
    question = until_answered(client, cid)
    assert (question["answer"], question["lead_why"]) == ("by date", "The spec says newest first.")
    until(lambda: tasks(client, pid)["sort the list"]["status"] == "review")


def test_going_away_decides_a_question_already_waiting(make_client, wait_run, project_dir):
    client, _model = make_client([CODER, ask(), says("by name"), text("ok"), text("done")])
    clock = held(client)
    cid, run_id = begin(client, project_dir, mode="auto_edit", spawn_approval="never",
                        when_away="waits")
    wait_status(client, cid, "waiting_approval")
    assert lead_timers(clock, 0.0) == [] and question_of(client, cid)["status"] == "pending"
    pid = client.get(f"/api/conversations/{cid}").json()["conversation"]["project_id"]
    with client.app.state.session_factory() as session:
        session.add(AwayRun(project_id=pid, conversation_id=cid, run_id="r", status="running"))
        session.commit()
    client.portal.call(client.app.state.runner.away_now, cid)
    assert until_answered(client, cid)["answer"] == "by name"
    wait_run(client, cid, run_id)


def test_typing_an_answer_holds_the_timeout(make_client, wait_run, project_dir):
    client, model = make_client([CODER, ask(), text("ok"), text("done")])
    clock = held(client)
    cid, run_id = begin(client, project_dir, mode="auto_edit", spawn_approval="never",
                        when_away="lead", away_minutes=10)
    wait_status(client, cid, "waiting_approval")
    (timer,) = lead_timers(clock, 600.0)
    typing = f"/api/questions/{question_of(client, cid)['id']}/typing"
    assert client.post(typing).status_code == 403  # (not from the app's own page)
    assert client.post(typing, headers=OWN).status_code == 204
    fire(client, timer)
    (again,) = [t for t in clock.set if 0 < t.delay <= TYPING_HOLD_SECONDS and not t.cancelled]
    assert len(model.calls) == 2  # (the Lead is not asked while you type)
    client.post(f"/api/questions/{question_of(client, cid)['id']}/answer",
                json={"answer": "by name"}, headers=OWN)
    (question,) = wait_run(client, cid, run_id)["questions"]
    assert (question["answer"], question["lead_why"]) == ("by name", None) and again.cancelled
    # a ping for a question nobody waits on is nothing kept
    assert client.post(typing, headers=OWN).status_code == 204
    assert client.app.state.runner._typing_at == {}


def test_a_step_limit_card_is_decided_while_away_below_full_auto(make_client, wait_run,
                                                                 project_dir):
    client, _model = make_client({
        "Lead": [spawn("Researcher"), says("Stop here", "Enough looking."), text("done")],
        "Researcher": [*looking(3)],
    })
    at_steps(client, 3)
    _pid, cid = away_chat(client, project_dir, permission_mode="auto_edit",
                          spawn_approval="never", when_away="waits")
    snap = wait_run(client, cid, post(client, cid), timeout=20)
    (card,) = snap["questions"]
    assert (card["answer"], card["lead_why"]) == ("Stop here", "Enough looking.")


def test_the_rule_never_reaches_a_card_that_always_waits(make_client, wait_run, project_dir):
    # Review focus 5: while away, at once - and yet a command (a delete) and a web request (a
    # send) are never the Orchestrator's to decide: each waits, and nothing is kept for Go away.
    client, _model = make_client([
        step(call("run_command", {"command": "rm -rf x"})),
        step(call("http_request", {"method": "POST", "url": "https://example.com/up",
                                   "body": "the report"}, "h")),
        text("done")])
    _pid, cid = away_chat(client, project_dir, permission_mode="auto_edit", when_away="lead",
                          away_minutes=0)
    run_id = post(client, cid, "clean up and send the report")
    runner = client.app.state.runner
    for kind in ("commands", "web_requests"):
        (asked,) = until(lambda kind=kind: client.get(f"/api/conversations/{cid}").json()[kind])
        assert asked["status"] == "proposed" and runner._decidable == {}, kind
        path = "commands" if kind == "commands" else "web-requests"
        assert client.post(f"/api/{path}/{asked['id']}/reject", json={},
                           headers=OWN).status_code == 200
    wait_run(client, cid, run_id)


def test_the_rule_never_reaches_kolonis_own_cards_below_full_auto(make_client, wait_run,
                                                                 project_dir):
    # ...nor KOLONİ's own kept-work card ("card"), "Who checks?" ("checker") or a card of no kind
    # (None: a sub-agent on another model, below) - while away, below Full auto.
    client, _model = make_client([text("hi")])
    _pid, cid = away_chat(client, project_dir, permission_mode="auto_edit")
    run_id = post(client, cid)
    wait_run(client, cid, run_id)
    runner = client.app.state.runner
    ctx = SimpleNamespace(run_id=run_id, cid=cid, agent_id="a")
    with client.app.state.session_factory() as session:
        conversation = session.get_one(Conversation, cid)
        assert [runner._decide_after(ctx, kind, conversation, True)
                for kind in (None, "card", "checker", "steps", "spawn")] == [
            None, None, None, 0.0, 0.0]


def test_while_away_a_sub_agent_on_another_model_waits_for_you(team, wait_run,  # noqa: F811
                                                               project_dir):
    # ...and a sub-agent to open on a model other than its role's own (money): it waits.
    from tests.test_tier_scenarios import spawn as tiered_spawn
    client, default, _fast = team([step(tiered_spawn("Coder", "strongest", "It needs care.")),
                                   text("done")], [text("fixed")])
    assert client.patch(f"/api/providers/{team.providers['Fast']['id']}", json={
        "models": [{"name": "deep", "tier": "strongest"}]}, headers=OWN).status_code == 200
    clock = held(client)
    _pid, cid = away_chat(client, project_dir, permission_mode="auto_edit",
                          spawn_approval="always", when_away="lead", away_minutes=0)
    post(client, cid)
    snap = wait_status(client, cid, "waiting_approval")
    assert snap["agents"][1]["provider_name"] == "Fast"
    runner = client.app.state.runner
    assert lead_timers(clock, 0.0) == [] and runner._decidable == {}
    assert len(default.calls) == 1
    assert client.get(f"/api/conversations/{cid}").json()["agents"][1]["status"] == "proposed"


def test_a_kept_work_card_at_full_auto_is_the_leads_at_once_and_never_go_aways(
        make_client, wait_run, project_dir):
    import asyncio
    client, _model = make_client([text("hi")])
    clock = held(client)
    cid, run_id = begin(client, project_dir, mode="full_auto")
    wait_run(client, cid, run_id)
    runner = client.app.state.runner
    ctx = SimpleNamespace(run_id=run_id, cid=cid, agent_id="a")

    async def asked():
        before = len(clock.set)
        future = asyncio.get_running_loop().create_future()
        stand_down = runner._lead_may_answer(ctx, "card", "Keep the work?", ["Keep", "Drop"],
                                             future, lambda *_said: None)
        armed, kept = [t.delay for t in clock.set[before:]], dict(runner._decidable)
        stand_down()
        return armed, kept

    assert client.portal.call(asked) == ([0.0], {})


def test_going_away_from_one_chat_leaves_another_chats_card_to_its_own_minutes(
        make_client, wait_run, project_dir):
    # (The review: Go away decided cards in every chat of the project, though its money and Stop
    # all cover only the chat gone from and its jobs.)
    client, _model = make_client([CODER, ask(), says("by name"), text("ok"), text("done")])
    clock = held(client)
    pid, gone_from = away_chat(client, project_dir, when_away="lead", away_minutes=10)
    other = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(f"/api/conversations/{other}", json={"permission_mode": "auto_edit",
                                                      "spawn_approval": "never"}, headers=OWN)
    run_id = post(client, other)
    wait_status(client, other, "waiting_approval")
    assert lead_timers(clock, 0.0) == []
    (timer,) = lead_timers(clock, 600.0)  # (its own minutes, as before)
    client.portal.call(client.app.state.runner.away_now, gone_from)
    assert question_of(client, other)["status"] == "pending" and not timer.cancelled
    fire(client, timer)
    assert until_answered(client, other)["answer"] == "by name"
    wait_run(client, other, run_id)


def test_a_card_held_while_you_typed_is_not_decided_once_you_are_back(make_client, wait_run,
                                                                    project_dir):
    client, model = make_client([CODER, ask(), text("ok"), text("done")])
    clock = held(client)
    pid, cid = away_chat(client, project_dir, permission_mode="auto_edit",
                         spawn_approval="never", when_away="lead", away_minutes=10)
    run_id = post(client, cid)
    wait_status(client, cid, "waiting_approval")
    (timer,) = lead_timers(clock, 0.0)
    question = question_of(client, cid)
    assert client.post(f"/api/questions/{question['id']}/typing", headers=OWN).status_code == 204
    fire(client, timer)  # (held while you type: armed again for the rest)
    (again,) = [t for t in clock.set if 0 < t.delay <= TYPING_HOLD_SECONDS and not t.cancelled]
    with client.app.state.session_factory() as session:  # (I'm back - its summary aside)
        session.scalars(select(AwayRun).where(AwayRun.project_id == pid)).one().status = "ended"
        session.commit()
    fire(client, again)
    # back: the project's own minutes count from here; nobody decided it meanwhile
    assert len(model.calls) == 2 and question_of(client, cid)["status"] == "pending"
    assert lead_timers(clock, 600.0)
    client.post(f"/api/questions/{question['id']}/answer", json={"answer": "by name"}, headers=OWN)
    (answered,) = wait_run(client, cid, run_id)["questions"]
    assert answered["lead_why"] is None


def test_an_answer_still_queued_for_the_orchestrator_is_not_given_once_you_are_back(
        make_client, wait_run, project_dir, gate):
    # (Round 2: three cards decided while away, two with the model; I'm back - the third, which
    # waited for its turn, is not sent.)
    from tests.conftest import Gate
    second = Gate()
    client, model = make_client({
        "Lead": [step(*(call("spawn_agent", {"role": "Coder", "task": f"ask {n}"}, f"s{n}")
                        for n in (1, 2, 3))),
                 gate.step(says("by date")), second.step(says("by name")), text("done")],
        "Coder": [ask("First?", id="q1"), text("ok")],
        "Coder 2": [ask("Second?", id="q2"), text("ok")],
        "Coder 3": [ask("Third?", id="q3"), text("ok")],
    })
    clock = held(client)
    pid, cid = away_chat(client, project_dir, permission_mode="auto_edit", spawn_approval="never",
                         spawn_max_parallel=3, when_away="waits")
    run_id = post(client, cid)
    timers = until(lambda: (found := lead_timers(clock, 0.0)) and len(found) == 3 and found)
    for timer in timers:
        fire(client, timer)
    gate.wait_partial()
    second.wait_partial()  # (two with the model; the third waits for its turn)
    with client.app.state.session_factory() as session:  # (I'm back - its summary aside)
        session.scalars(select(AwayRun).where(AwayRun.project_id == pid)).one().status = "ended"
        session.commit()
    gate.release()
    second.release()
    runner = client.app.state.runner
    until(lambda: not runner._lead_taking)
    asked = client.get(f"/api/conversations/{cid}").json()["questions"]
    assert sorted(q["status"] for q in asked) == ["answered", "answered", "pending"]
    assert len(model.calls_of["Lead"]) == 3  # (its turn's step and two answers - not a third)
    (waiting,) = [q for q in asked if q["status"] == "pending"]
    client.post(f"/api/questions/{waiting['id']}/answer", json={"answer": "by name"},
                headers=OWN)
    wait_run(client, cid, run_id)
