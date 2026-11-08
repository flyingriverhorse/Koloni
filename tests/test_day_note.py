"""Slice 56: the day's summary sent at a time the user set, once a day, by the project's own
notification path; and the numbers said in words by a model, on the user's own click."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app import web
from app.api import day as day_api
from app.api import projects as projects_api
from app.api.board import waiting_in
from app.db.models import FileChange
from app.model_client import ModelUnavailable
from app.triggers import local_day
from tests.test_agent_writes import write
from tests.test_chat_flow import text
from tests.test_usage_scenarios import ORIGIN, began, turn

HOOK = "https://hooks.example.com/day"
# Once for the file: what is counted from it may only be of later (a run over midnight
# counts more, never less); a test that needs the turn's own day takes that (`midnight_of`).
MIDNIGHT = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


@pytest.fixture(autouse=True)
def utc_clock(monkeypatch):
    """Switching the time on counts "yesterday" by the app's clock; these tests' clock is
    UTC, so between local and UTC midnight the two days would differ."""
    monkeypatch.setattr(projects_api, "local_day", lambda moment, zone=None: local_day(moment, UTC))


def midnight_of(run):
    ran = datetime.fromisoformat(run["created_at"]).replace(tzinfo=UTC)
    return ran.replace(hour=0, minute=0, second=0, microsecond=0)


def at(day, hour, minute=0, midnight=MIDNIGHT):
    """A moment of today (day 0) or of a day after it, by a UTC clock."""
    return midnight + timedelta(days=day, hours=hour, minutes=minute)


def looker(client):
    """Look at the clock at a moment, and wait for what that sent (it goes off the clock)."""
    triggers = client.app.state.triggers
    triggers.zone = UTC

    async def look(moment):
        triggers.day_notes(moment)
        await asyncio.gather(*triggers._sending)

    return lambda moment: client.portal.call(look, moment)


def day_of(client, pid):
    return client.get(f"/api/projects/{pid}/day", params={"since": MIDNIGHT.isoformat()}).json()


def words(client, pid, cid):
    return client.post(f"/api/projects/{pid}/day/words",
                       json={"since": MIDNIGHT.isoformat(), "conversation_id": cid})


def test_the_time_is_the_users_own_and_needs_a_way_to_send(make_client, project_dir):
    client, _model, pid, _cid = began(make_client, project_dir, [])
    # nowhere to send it yet: said, not kept
    assert client.patch(f"/api/projects/{pid}", json={"day_note_at": "18:00"}).status_code == 422
    assert client.patch(f"/api/projects/{pid}", json={"notify_url": HOOK}).status_code == 200
    assert client.patch(f"/api/projects/{pid}", json={"day_note_at": "25:00"}).status_code == 422
    del client.headers["Origin"]  # an agent's command against the app's address
    assert client.patch(f"/api/projects/{pid}", json={"day_note_at": "18:00"}).status_code == 403
    client.headers["Origin"] = ORIGIN
    saved = client.patch(f"/api/projects/{pid}", json={"day_note_at": "18:00"}).json()
    assert saved["day_note_at"] == "18:00"
    # the address taken away while the time stays: nowhere to send it again, so not kept
    gone = client.patch(f"/api/projects/{pid}", json={"notify_url": ""})
    assert gone.status_code == 422 and "empty the summary's time" in gone.json()["detail"]
    assert client.get(f"/api/projects/{pid}").json()["has_notify_url"]
    both = client.patch(f"/api/projects/{pid}", json={"notify_url": "", "day_note_at": None})
    assert both.status_code == 200 and both.json()["day_note_at"] is None


def test_the_note_goes_once_a_day_after_its_time(make_client, wait_run, project_dir, monkeypatch):
    client, _model, pid, cid = began(make_client, project_dir, [text("hi", 3, 1)],
                                     notify_url=HOOK, notify_format="text")
    client.patch(f"/api/projects/{pid}", json={"day_note_at": "18:00"})
    midnight = midnight_of(turn(client, wait_run, cid))  # the turn's day, whenever it ran
    sent: list[tuple[str, str, str]] = []

    async def post(url, message, form="slack"):
        sent.append((url, message, form))
        return "sent"

    monkeypatch.setattr(web, "notify", post)
    look = looker(client)
    today = 0
    look(at(today, 17, 59, midnight))
    assert sent == []
    look(at(today, 18, 1, midnight))
    ((url, message, form),) = sent
    assert (url, form) == (HOOK, "text")
    assert "1 turn" in message and "0 failed" in message and "cost –" in message
    look(at(today, 23, 0, midnight))  # once a day
    assert len(sent) == 1
    look(at(today + 1, 18, 0, midnight))  # the next day: its own day, counted from its own midnight
    assert len(sent) == 2 and "0 turns" in sent[1][1]


def test_a_day_the_app_was_closed_all_evening_is_sent_late_once_and_counts_only_that_day(
    make_client, wait_run, project_dir, monkeypatch
):
    from app.db.models import Project, Run

    client, _model, pid, cid = began(make_client, project_dir, [text("hi", 3, 1), text("on", 3, 1)],
                                     notify_url=HOOK, notify_format="text")
    client.patch(f"/api/projects/{pid}", json={"day_note_at": "18:00"})
    midnight = midnight_of(turn(client, wait_run, cid))
    morning = turn(client, wait_run, cid)
    with client.app.state.session_factory() as session:
        # Sent the day before; the app was closed that evening; this turn is of the next morning.
        session.get_one(Project, pid).day_note_sent = (midnight - timedelta(days=1)).date()
        session.get_one(Run, morning["id"]).created_at = at(1, 7, 0, midnight).replace(tzinfo=None)
        session.commit()
    sent: list[str] = []

    async def post(url, message, form="slack"):
        sent.append(message)

    monkeypatch.setattr(web, "notify", post)
    look = looker(client)
    look(at(1, 8, 0, midnight))
    (late,) = sent
    assert "yesterday" in late and "sent late" in late and "1 turn," in late
    look(at(1, 8, 1, midnight))  # once
    assert len(sent) == 1
    look(at(1, 18, 1, midnight))  # and that day's own, at its time
    assert len(sent) == 2 and "today: 1 turn," in sent[1]


def test_notes_switched_on_again_send_no_late_note_of_a_day_they_were_off(
    make_client, project_dir, monkeypatch
):
    from app.db.models import Project

    client, _model, pid, _cid = began(make_client, project_dir, [], notify_url=HOOK)
    look = looker(client)  # (by a UTC clock, as the switch counts its day)
    client.patch(f"/api/projects/{pid}", json={"day_note_at": "18:00"})
    with client.app.state.session_factory() as session:  # last sent days ago, then off
        session.get_one(Project, pid).day_note_sent = (MIDNIGHT - timedelta(days=5)).date()
        session.commit()
    assert client.patch(f"/api/projects/{pid}", json={"day_note_at": None}).status_code == 200
    assert client.patch(f"/api/projects/{pid}", json={"day_note_at": "18:00"}).status_code == 200
    sent: list[str] = []

    async def post(url, message, form="slack"):
        sent.append(message)

    monkeypatch.setattr(web, "notify", post)
    look(at(0, 8))
    assert sent == []
    look(at(0, 18, 1))  # today's own goes, at its time
    assert len(sent) == 1 and "today:" in sent[0]


def test_a_failed_send_is_not_tried_again_every_few_seconds(make_client, project_dir, monkeypatch):
    client, _model, pid, _cid = began(make_client, project_dir, [], notify_url=HOOK)
    client.patch(f"/api/projects/{pid}", json={"day_note_at": "08:00"})
    tries = []

    async def down(url, message, form="slack"):
        tries.append(message)
        raise web.WebError("the notification was not sent (ConnectError)")

    monkeypatch.setattr(web, "notify", down)
    look = looker(client)
    look(at(0, 9))
    look(at(0, 9, 1))
    assert len(tries) == 1


def test_a_slow_address_never_holds_the_clock(make_client, project_dir, monkeypatch):
    client, _model, pid, _cid = began(make_client, project_dir, [], notify_url=HOOK)
    client.patch(f"/api/projects/{pid}", json={"day_note_at": "08:00"})
    held = asyncio.Event()  # bound to the app's loop where it is first waited on
    reached = []

    async def slow(url, message, form="slack"):
        reached.append(message)
        await held.wait()

    monkeypatch.setattr(web, "notify", slow)
    triggers = client.app.state.triggers
    triggers.zone = UTC
    # back at once, while the address has not answered - and marked sent already
    client.portal.call(triggers.day_notes, at(0, 9))
    assert len(triggers._sending) == 1
    client.portal.call(triggers.day_notes, at(0, 9, 1))
    assert len(triggers._sending) == 1
    client.portal.call(held.set)
    looker(client)(at(0, 9, 2))
    assert len(reached) == 1 and not triggers._sending


def test_one_project_that_cannot_be_counted_keeps_no_other_from_its_note(
    make_client, project_dir, tmp_path, monkeypatch
):
    client, _model, pid, _cid = began(make_client, project_dir, [])
    other = tmp_path / "other"
    other.mkdir()
    second = client.post("/api/projects", json={"root_path": str(other)}).json()["id"]
    for project in (pid, second):
        assert client.patch(f"/api/projects/{project}", json={
            "notify_url": HOOK, "day_note_at": "08:00"}).status_code == 200
    sent = []

    async def post(url, message, form="slack"):
        sent.append(message)

    def note(session, project, since, runner, until):
        if project.id == pid:
            raise RuntimeError("the record could not be read")
        return day_api.day_note(session, project, since, runner, until)

    monkeypatch.setattr(web, "notify", post)
    monkeypatch.setattr(client.app.state.triggers, "_day_note", note)
    look = looker(client)
    look(at(0, 9))
    assert len(sent) == 1  # the other project's
    look(at(0, 9, 1))  # the one that failed is not tried every few seconds
    assert len(sent) == 1


def test_a_cost_is_said_only_when_every_model_has_one_in_one_currency(
    make_client, wait_run, project_dir, monkeypatch
):
    client, _model, pid, cid = began(make_client, project_dir, [text("a", 1_000_000, 500_000)])
    turn(client, wait_run, cid)
    price = {"model_id": "fake-model", "input": 3, "output": 15, "currency": "USD"}
    assert client.put("/api/prices", json=price).status_code == 200
    seen = day_of(client, pid)
    assert (seen["cost"]["amount"], seen["cost"]["currency"]) == (10.5, "USD")
    assert "cost ≈ 10.50 USD." in day_api.note_text(SimpleNamespace(name="p"), seen)

    # two models, priced in two currencies: never a sum of the two
    def two(**_asked):
        row = {"input_tokens": 1, "output_tokens": 1, "unknown_agents": 0}
        return {"by_model": [{**row, "cost": {"amount": 1.0, "currency": "USD"}},
                             {**row, "cost": {"amount": 1.0, "currency": "EUR"}}]}

    monkeypatch.setattr(day_api, "usage", two)
    assert day_of(client, pid)["cost"] is None


def test_only_what_reached_the_project_is_a_changed_file(make_client, wait_run, project_dir):
    client, _model, pid, cid = began(make_client, project_dir,
                                     [write("a.txt", "one\n"), text("made a")])
    client.patch(f"/api/conversations/{cid}", json={"lead_hands_code": False})
    run = turn(client, wait_run, cid, "make a")
    agent = client.get(f"/api/conversations/{cid}").json()["agents"][0]["id"]
    with client.app.state.session_factory() as session:
        for status in ("proposed", "rejected", "in_copy", "discarded", "merged"):
            session.add(FileChange(run_id=run["id"], agent_id=agent, path=f"{status}.txt",
                                   kind="create", after_content="x", after_sha="0",
                                   status=status))
        session.commit()
    assert day_of(client, pid)["changed_files"] == ["a.txt", "merged.txt"]


def test_at_most_20_paths_are_said():
    said = day_api._first([f"{i}.txt" for i in range(23)])
    assert len(said) == 21 and said[-1] == "and 3 more"
    assert day_api._first(["a.txt"]) == ["a.txt"]


def test_what_waits_is_counted_as_the_page_counts_it():
    # the same cases as `waitCount`'s in frontend/src/shell/seen.test.tsx
    board = {"merges_pending": 2, "agents": [
        {"status": "proposed"}, {"status": "waiting_approval"}, {"status": "running"}]}
    assert waiting_in(board) == 3
    assert waiting_in({"merges_pending": 0, "agents": [{"status": "proposed"}]}) == 1
    assert waiting_in({"merges_pending": 0, "agents": [
        {"status": "waiting_approval"}, {"status": "waiting_approval"},
        {"status": "proposed"}]}) == 2
    # a plan that waits for a yes is one thing more (K-60b-kalan)
    assert waiting_in({"merges_pending": 1, "agents": [], "turn": {"plan_waits": True}}) == 2
    # an agent that asks two questions at once, and a change, is three things (K-38f2)
    assert waiting_in({"merges_pending": 0, "agents": [{
        "status": "waiting_approval", "questions": 2, "changes_to_approve": 1}]}) == 3


def test_the_numbers_said_in_words_by_the_conversations_model(make_client, wait_run, project_dir):
    client, model, pid, cid = began(
        make_client, project_dir, [text("done"), text("One turn. Nothing failed. Quiet day.")])
    turn(client, wait_run, cid)
    del client.headers["Origin"]
    assert words(client, pid, cid).status_code == 403
    client.headers["Origin"] = ORIGIN
    before = len(model.calls)
    said = words(client, pid, cid)
    assert said.status_code == 200, said.text
    assert said.json()["text"] == "One turn. Nothing failed. Quiet day."
    # whose words they are: the model's, named - with no fast model, the Lead's own
    assert said.json()["provider_name"] and said.json()["model_id"] == "fake-model"
    # the numbers went to the model as data, never more than once
    assert len(model.calls) == before + 1
    assert '"turns": 1' in str(model.calls[-1])


def test_the_words_go_to_a_fast_model_when_there_is_one(make_client, project_dir):
    client, _model, pid, cid = began(make_client, project_dir, [text("A quiet day.")])
    local = client.get("/api/providers").json()[0]
    assert client.patch(f"/api/providers/{local['id']}", json={
        "models": [{"name": "quick", "tier": "fast"}]}).status_code == 200
    said = words(client, pid, cid)
    assert said.status_code == 200, said.text
    assert said.json()["model_id"] == "quick"


def test_a_model_that_may_not_run_is_said_to_the_user(make_client, project_dir):
    client, model, pid, cid = began(make_client, project_dir, [text("never")])
    local = client.get("/api/providers").json()[0]
    assert client.patch(f"/api/providers/{local['id']}", json={
        "models": [{"name": "other"}], "only_listed": True}).status_code == 200
    said = words(client, pid, cid)
    assert said.status_code == 409
    assert "Models page" in said.json()["detail"]
    assert "Only the user can change that" not in said.json()["detail"]
    assert model.calls == []


def test_a_failure_never_repeats_the_key(make_client, project_dir):
    key = "sk-day-test-0000"
    client, _model, pid, cid = began(
        make_client, project_dir, [ModelUnavailable(f"401: the key {key} is not valid")])
    local = client.get("/api/providers").json()[0]
    assert client.patch(f"/api/providers/{local['id']}", json={"api_key": key}).status_code == 200
    said = words(client, pid, cid)
    assert said.status_code == 502
    assert key not in said.text and "[key]" in said.json()["detail"]


def test_over_the_budget_the_words_wait_for_the_users_word(make_client, wait_run, project_dir):
    client, model, pid, cid = began(
        make_client, project_dir, [text("a", 1_000_000, 500_000), text("A costly day.")])
    turn(client, wait_run, cid)
    client.put("/api/prices", json={
        "model_id": "fake-model", "input": 3, "output": 15, "currency": "USD"})
    assert client.patch(f"/api/projects/{pid}", json={"monthly_budget": 10}).status_code == 200
    before = len(model.calls)
    refused = words(client, pid, cid)
    assert refused.status_code == 409
    assert refused.json()["detail"].startswith("this project is over this month's budget")
    assert len(model.calls) == before  # nothing was asked
    going = client.post(f"/api/projects/{pid}/day/words", json={
        "since": MIDNIGHT.isoformat(), "conversation_id": cid, "over_budget": True})
    assert going.status_code == 200, going.text
    assert going.json()["text"] == "A costly day."


def test_a_model_that_does_not_answer_says_whose_and_what_to_do(
    make_client, wait_run, project_dir, monkeypatch
):
    from app.model_client import ModelUnavailable

    client, _model, pid, cid = began(make_client, project_dir, [text("done")])
    turn(client, wait_run, cid)

    async def down(*_args, **_kwargs):
        raise ModelUnavailable("model server unreachable: All connection attempts failed")

    monkeypatch.setattr("app.providers.ask_once", down)
    said = words(client, pid, cid)
    assert said.status_code == 502
    told = said.json()["detail"]
    assert "isn't answering" in told and "fast tier on the Models page" in told
