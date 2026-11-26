"""Slice 55 beyond its acceptance set: the month's edge, triggers held back over the budget,
the user's word to go on, and the desktop told once a month at 80%. Nothing touches the
real desktop: `app.web.desktop` is stood in for."""

import asyncio
import time
from datetime import UTC, datetime, timedelta, timezone

from sqlalchemy import select

import app.web
from app.api.usage import month_start
from app.db.models import Agent, Message, OwnRequest, Run
from tests.test_budget_scenarios import PRICE, budget
from tests.test_chat_flow import text
from tests.test_usage_scenarios import began, turn
from tests.turn_helpers import ORIGIN


def over(make_client, wait_run, project_dir, steps, **project):
    """A project whose one turn so far cost 10.5 USD, against a budget of 10."""
    client, _model, pid, cid = began(
        make_client, project_dir, [text("a", 1_000_000, 500_000), *steps], **project
    )
    run = turn(client, wait_run, cid)
    client.put("/api/prices", json=PRICE)
    client.patch(f"/api/projects/{pid}", json={"monthly_budget": 10})
    return client, pid, cid, run


def test_the_month_starts_at_local_midnight_on_the_first():
    at = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
    first = month_start(at)
    local = first.replace(tzinfo=UTC).astimezone()
    assert (local.day, local.hour, local.minute) == (1, 0, 0) and first.tzinfo is None
    assert first <= at.replace(tzinfo=None) < first + timedelta(days=32)


class InIstanbul(datetime):
    """A time on a machine at UTC+3: its local zone, as `astimezone()` would give it."""

    def astimezone(self, tz=None):
        zone = timezone(timedelta(hours=3))
        return datetime.astimezone(self if self.tzinfo else self.replace(tzinfo=zone), tz or zone)


def test_the_month_is_the_machines_own_not_utcs():
    # 22:00 UTC on 30 September is already 1 October there: October's month, from 21:00 UTC.
    assert month_start(InIstanbul(2026, 9, 30, 22, tzinfo=UTC)) == datetime(2026, 9, 30, 21)
    assert month_start(InIstanbul(2026, 9, 30, 20, tzinfo=UTC)) == datetime(2026, 8, 31, 21)


def test_a_turn_of_last_month_is_not_counted(make_client, wait_run, project_dir):
    client, pid, _cid, run = over(make_client, wait_run, project_dir, [])

    def started(at):
        with client.app.state.session_factory() as session:
            session.get_one(Run, run["id"]).created_at = at
            session.commit()
        return budget(client, pid)["spent"]

    start = month_start()
    assert started(start) == 10.5
    assert started(start - timedelta(seconds=1)) == 0


def test_going_on_over_the_budget_is_the_users_word(make_client, wait_run, project_dir):
    client, _pid, cid, _run = over(make_client, wait_run, project_dir, [text("b", 1, 1)])
    del client.headers["Origin"]
    going = client.post(
        f"/api/conversations/{cid}/messages", json={"content": "more", "over_budget": True}
    )
    assert going.status_code == 403


def test_the_desktop_is_told_once_a_month_at_80_percent(
    make_client, wait_run, project_dir, monkeypatch
):
    shown = []
    monkeypatch.setattr(app.web, "has_desktop", lambda: True)
    monkeypatch.setattr(app.web, "desktop", lambda title, said: shown.append(said))
    client, pid, cid, _run = over(
        make_client, wait_run, project_dir, [text("b", 1, 1)], notify_desktop=True
    )
    client.patch(f"/api/projects/{pid}", json={"monthly_budget": 12})  # 87.5%
    turn(client, wait_run, cid, "b")
    deadline = time.monotonic() + 5
    while not shown and time.monotonic() < deadline:
        time.sleep(0.02)
    asyncio.run(client.app.state.runner._tell_budget(cid))  # as the next turn's end would
    assert shown == ["This project has used 87% of its monthly budget"]


def test_80_percent_is_80_percent_however_the_division_falls(make_client, wait_run, project_dir):
    client, pid, _cid, _run = over(make_client, wait_run, project_dir, [])
    client.put("/api/prices", json={**PRICE, "input": 0.72, "output": 0})
    client.patch(f"/api/projects/{pid}", json={"monthly_budget": 0.9})  # 0.72 / 0.9 in floats
    seen = budget(client, pid)
    assert (seen["share"], seen["warn"], seen["over"]) == (0.8, True, False)


def test_costs_in_two_currencies_are_not_added_and_the_budget_holds_nothing_back(
    make_client, wait_run, project_dir
):
    client, pid, cid, run = over(make_client, wait_run, project_dir, [text("b", 1, 1)])
    with client.app.state.session_factory() as session:
        agent = session.scalar(select(Agent).where(Agent.run_id == run["id"]))
        session.add(
            OwnRequest(
                run_id=run["id"],
                agent_id=agent.id,
                provider_name="other",
                model_id="other-model",
                input_tokens=1_000_000,
                output_tokens=0,
            )
        )
        session.commit()
    client.put("/api/prices", json={**PRICE, "model_id": "other-model", "currency": "EUR"})
    seen = budget(client, pid)
    assert (seen["spent"], seen["currency"], seen["over"]) == (None, None, False)
    assert (
        client.post(f"/api/conversations/{cid}/messages", json={"content": "b"}).status_code == 201
    )
    # "usd" is USD: the same currency, added up - and over the budget again.
    client.put("/api/prices", json={**PRICE, "model_id": "other-model", "currency": "usd"})
    seen = budget(client, pid)
    assert (seen["currency"], seen["over"]) == ("USD", True) and seen["spent"] >= 13.5


def test_an_approved_plan_starts_its_work_over_the_budget_only_on_the_users_word(
    make_client, wait_run, project_dir
):
    client, _pid, cid, _run = over(
        make_client, wait_run, project_dir, [text("PLAN: look", 1, 1), text("done", 1, 1)]
    )
    assert client.patch(f"/api/conversations/{cid}", json={"plan_first": True}).status_code == 200
    planned = client.post(
        f"/api/conversations/{cid}/messages", json={"content": "plan", "over_budget": True}
    )
    run_id = planned.json()["run"]["id"]
    wait_run(client, cid, run_id)
    refused = client.post(f"/api/runs/{run_id}/plan/approve", json={})
    assert refused.status_code == 409 and "month's budget" in refused.text
    runs = client.get(f"/api/conversations/{cid}").json()["runs"]
    assert next(r for r in runs if r["id"] == run_id)["plan"]["status"] == "proposed"
    assert len(runs) == 2
    going = client.post(f"/api/runs/{run_id}/plan/approve", json={"over_budget": True})
    assert going.status_code == 200, going.text
    wait_run(client, cid, going.json()["run_id"])


def test_a_message_not_sent_before_a_restart_is_sent_over_the_budget_only_on_the_users_word(
    make_client, wait_run, project_dir
):
    client, _pid, cid, _run = over(make_client, wait_run, project_dir, [text("done", 1, 1)])
    with client.app.state.session_factory() as session:  # (queued when KOLONİ restarted)
        session.add(Run(id="q", conversation_id=cid, status="interrupted", by_user=True))
        session.flush()
        session.add(Message(conversation_id=cid, run_id="q", role="user", content="and then"))
        session.commit()
    own = {"Origin": ORIGIN}
    refused = client.post("/api/runs/q/send", json={}, headers=own)
    assert refused.status_code == 409 and "month's budget" in refused.text
    going = client.post("/api/runs/q/send", json={"over_budget": True}, headers=own)
    assert going.status_code == 200, going.text
    wait_run(client, cid, "q")


def test_an_agent_is_told_once_its_project_has_used_most_of_its_budget(
    make_client, wait_run, project_dir
):
    from app.agent import BUDGET_NEAR
    from tests.test_spawn import call, step
    from tests.test_usage_scenarios import began, turn

    told = BUDGET_NEAR.split("{used}")[1]  # (with "at least" or without: one turn is unpriced)
    client, model, pid, cid = began(
        make_client,
        project_dir,
        [
            text("a", 1_000_000, 500_000),
            text("b", 1, 1),
            step(call("list_files", {"path": "."})),
            text("c", 1, 1),
        ],
    )
    turn(client, wait_run, cid)
    client.put("/api/prices", json=PRICE)

    def said(calls):
        return [any(told in str(m.get("content")) for m in sent) for sent in calls]

    # no budget: nothing is said, as nothing is known of it
    turn(client, wait_run, cid, "b")
    assert said(model.calls) == [False, False]
    client.patch(f"/api/projects/{pid}", json={"monthly_budget": 12})  # 87.5%
    turn(client, wait_run, cid, "c")
    # told at its first step, not again at its next
    assert said(model.calls[2:]) == [True, False]


def test_a_projects_month_is_not_added_up_for_it_at_every_step(
    make_client, wait_run, project_dir, monkeypatch
):
    import app.agent
    from tests.test_spawn import call, step

    added = []
    plain = app.agent.limits_mixin.month_spend
    monkeypatch.setattr(
        app.agent.limits_mixin, "month_spend", lambda *a: added.append(1) or plain(*a)
    )
    monkeypatch.setattr(
        app.agent.tiers_mixin, "month_spend", lambda *a: added.append(1) or plain(*a)
    )
    client, _model, pid, cid = began(
        make_client,
        project_dir,
        [
            step(call("list_files", {"path": "."})),
            step(call("list_files", {"path": "."})),
            text("done"),
        ],
    )
    client.patch(f"/api/projects/{pid}", json={"monthly_budget": 1000})  # far under it
    turn(client, wait_run, cid)
    assert len(added) == 1  # three steps, one reading
