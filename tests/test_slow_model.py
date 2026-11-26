"""K-yavas (the user, 20 Nov 2026): a turn the user watches sat for minutes with nothing happening -
a free model queued 7 min for the Orchestrator, Codex at its 5-hour limit answering every
7-10 min - and Stop was the only way out. Now its Orchestrator's model, silent for
WATCHED_SLOW_MINUTES, is asked about on one card: Keep waiting, or Stop and pick another model. Nobody answering, it waits; a sub-agent and a turn
nobody watches are as before."""

import asyncio
import threading
import time
from dataclasses import replace
from types import SimpleNamespace

from sqlalchemy import select

from app.agent.limits_mixin import WATCHED_SLOW_MINUTES
from app.api.board import waiting_in
from app.config import load_settings
from app.db.models import Agent, BoardPost, Command, ToolCall, now
from app.main import create_app
from tests.conftest import scaled
from tests.fakes import ScriptedModel
from tests.keyed import TestClient
from tests.test_chat_flow import text
from tests.test_lead_decides import fire
from tests.test_parallel import now_snap, until
from tests.test_recipe_run_scenarios import answer, asked
from tests.test_spawn import begin, spawn
from tests.test_team_requests_scenarios import agent
from tests.turn_helpers import HeldClock, on_loop

OWN = {"Origin": "http://127.0.0.1:8790"}
SLOW = WATCHED_SLOW_MINUTES * 60.0
OPTIONS = ["Keep waiting", "Stop and pick another model"]
ASKED = " Keep waiting, or stop this turn and pick another model?"


def slow_timers(clock):
    return [t for t in clock.set if t.delay == SLOW and not t.cancelled]


def once(ready, what, timeout=5):
    """`ready()`'s value once it is true."""
    deadline = time.monotonic() + scaled(timeout)
    while not (found := ready()):
        assert time.monotonic() < deadline, what
        time.sleep(0.01)
    return found


def armed(clock, timeout=5):
    """The slow clock of the turn, once it is set."""
    return once(lambda: slow_timers(clock), "no slow clock was set", timeout)


def who(snap):
    lead = agent(snap, "Lead")
    return f"{lead['provider_name']} · {lead['model_id']}"


def nothing_left(runner):
    assert not runner._slow_turns and not runner._answers and not runner._asks_aside


def on_board(client, cid):
    """The chat's row of every chat's board, and what of it waits for the user."""
    (row,) = [
        c for c in client.get("/api/board").json()["conversations"] if c["conversation_id"] == cid
    ]
    return row, waiting_in(row)


async def held(event: threading.Event) -> None:
    while not event.is_set():
        await asyncio.sleep(0.01)


class Queued(ScriptedModel):
    """A CLI session for the Lead that says each of `lines`, each then held until the test lets
    it go on; then its answer."""

    session = True

    def __init__(self, lines):
        super().__init__([])
        self.lines, self.go = lines, [threading.Event() for _ in lines]
        self.at, self.ended = -1, False

    async def run_session(
        self,
        model_id,
        messages,
        tools,
        call_tool,
        on_text,
        on_message=None,
        effort=None,
        on_live=None,
    ):
        try:
            for i, line in enumerate(self.lines):
                await on_text(line)
                self.at = i
                await held(self.go[i])
            await on_text("done")
        except asyncio.CancelledError:
            self.ended = True
            raise
        return SimpleNamespace(input_tokens=5, output_tokens=1, model=None)


def queued_app(settings_env, lines):
    cli = Queued(lines)
    client = TestClient(
        create_app(load_settings(settings_env), model=cli), base_url="http://127.0.0.1:8790"
    )
    client.__enter__()
    client.headers.update(OWN)
    return client, cli


def at(cli, i):
    once(lambda: cli.at >= i, f"the session never came to its line {i}")


# --- a silent model --------------------------------------------------------------------------------


def test_a_silent_orchestrator_is_asked_once_and_keep_waiting_waits_a_whole_limit_more(
    make_client, wait_run, project_dir, gate
):
    client, _model = make_client([gate.step(text("done at last"))])
    runner = client.app.state.runner
    clock = runner.call_later = HeldClock()
    cid, run_id = begin(client, project_dir)
    gate.wait_partial()
    (timer,) = armed(clock)
    fire(client, timer)
    snap = until(client, cid, asked)
    card = asked(snap)
    assert card["question"] == f"{who(snap)} has not answered for 5 min.{ASKED}"
    assert (card["options"], card["leave"], card["tool_call_id"]) == (OPTIONS, True, None)
    assert snap["runs"][0]["status"] == "waiting_approval"
    assert agent(snap, "Lead")["status"] == "running"  # (its model still at work: its place kept)
    answer(client, card, "Keep waiting")
    # no second card: its clock again, a whole limit
    (again,) = slow_timers(clock)
    assert timer.cancelled and again is not timer
    snap = now_snap(client, cid)
    assert [q["status"] for q in snap["questions"]] == ["answered"]
    assert snap["runs"][0]["status"] == "running"
    fire(client, again)  # (still no word: the next card counts both limits)
    assert asked(until(client, cid, asked))["question"] == (
        f"{who(snap)} has not answered for 10 min.{ASKED}"
    )
    gate.release()
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert sorted(q["status"] for q in snap["questions"]) == ["answered", "cancelled"]
    assert not slow_timers(clock)
    nothing_left(runner)


def test_its_card_waits_for_the_user_on_the_board_until_it_is_answered_or_closed(
    make_client, wait_run, project_dir, gate
):
    # (live, 20 Nov 2026: while the card waited the board said the Lead "running" with no
    # question - no toast, Ready said nothing waits, no mark in Chats: a card asked beside the
    # model's work was not counted as asking)
    client, _model = make_client([gate.step(text("done at last"))])
    runner = client.app.state.runner
    clock = runner.call_later = HeldClock()
    cid, run_id = begin(client, project_dir)
    gate.wait_partial()
    fire(client, armed(clock)[0])
    card = asked(until(client, cid, asked))
    row, waits = on_board(client, cid)
    (lead,) = [a for a in row["agents"] if a["name"] == "Lead"]
    # (KOLONİ's own card about it, not its question: "Orchestrator waits for you", not "asks you")
    assert (lead["status"], lead["questions"], lead["own_questions"], waits) == (
        "waiting_approval",
        1,
        0,
        1,
    ), row
    answer(client, card, "Keep waiting")
    row, _ = once(lambda: (on := on_board(client, cid))[1] == 0 and on, "Keep waiting left it")
    (lead,) = [a for a in row["agents"] if a["name"] == "Lead"]
    assert (lead["status"], lead["questions"]) == ("running", 0), row
    (again,) = slow_timers(clock)
    fire(client, again)
    until(client, cid, asked)
    assert on_board(client, cid)[1] == 1
    gate.release()  # (its model speaks first: the card is closed, nothing of it waits)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert on_board(client, cid)[1] == 0
    nothing_left(runner)


def test_words_from_the_model_start_its_clock_again_and_no_card_comes(
    make_client, wait_run, project_dir, gate
):
    client, _model = make_client([gate.step(text("done"), partial="Looking at it")])
    clock = client.app.state.runner.call_later = HeldClock()
    cid, run_id = begin(client, project_dir)
    gate.wait_partial()
    timers = [t for t in clock.set if t.delay == SLOW]
    assert [t.cancelled for t in timers] == [
        True,
        False,
    ]  # (set as it was asked, again at its words)
    gate.release()
    snap = wait_run(client, cid, run_id)
    assert snap["questions"] == [] and not slow_timers(clock)


def test_each_word_of_a_cli_session_starts_its_clock_again(settings_env, wait_run, project_dir):
    # (each word, not each half a minute as its row's time is put on record, `_touch`)
    client, cli = queued_app(settings_env, ["Looking", " still looking"])
    try:
        clock = client.app.state.runner.call_later = HeldClock()
        cid, run_id = begin(client, project_dir)
        at(cli, 0)
        (first,) = slow_timers(clock)
        cli.go[0].set()
        at(cli, 1)  # (its next word, a moment later)
        (second,) = slow_timers(clock)
        assert first.cancelled and second is not first
        cli.go[1].set()
        snap = wait_run(client, cid, run_id)
        assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
        assert snap["questions"] == [] and not slow_timers(clock)
    finally:
        for go in cli.go:
            go.set()
        client.__exit__(None, None, None)


def test_a_wait_that_is_not_its_models_holds_the_clock_and_the_models_answer_closes_its_card(
    make_client, wait_run, project_dir, gate
):
    client, _model = make_client([gate.step(text("done"))])
    runner = client.app.state.runner
    clock = runner.call_later = HeldClock()
    cid, run_id = begin(client, project_dir)
    gate.wait_partial()
    snap = now_snap(client, cid)
    lead, message = agent(snap, "Lead")["id"], snap["messages"][0]["id"]

    def users_card(session):  # (any card of the turn: the user is slow, not the model)
        session.add(
            Command(
                run_id=run_id,
                agent_id=lead,
                command="make",
                location="host",
                timeout_seconds=60,
                status="proposed",
            )
        )

    def call_at_work(session):  # (a call of it at work: KOLONİ's time - a sub-agent, a command)
        session.add(
            ToolCall(
                run_id=run_id,
                agent_id=lead,
                message_id=message,
                seq=1,
                provider_call_id="c1",
                name="read_file",
                arguments="{}",
                status="running",
            )
        )

    def in_line(session):  # (not at work itself: in line for a place)
        session.get_one(Agent, lead).status = "queued"

    def undone(session):
        session.query(Command).filter_by(run_id=run_id).update({"status": "rejected"})
        session.query(ToolCall).filter_by(run_id=run_id).update({"status": "succeeded"})
        session.get_one(Agent, lead).status = "running"

    for wait in (users_card, call_at_work, in_line):
        with runner._factory() as session:
            wait(session)
            session.commit()
        (timer,) = armed(clock)
        fire(client, timer)
        (again,) = slow_timers(clock)  # (set again, a whole limit; no card)
        assert timer.cancelled and again is not timer, wait.__name__
        assert now_snap(client, cid)["questions"] == [], wait.__name__
        with runner._factory() as session:
            undone(session)
            session.commit()
    fire(client, armed(clock)[0])
    card = asked(until(client, cid, asked))
    assert card["question"].endswith(f"has not answered for 5 min.{ASKED}")
    gate.release()  # (nobody answered; its model did)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert [q["status"] for q in snap["questions"]] == ["cancelled"]  # (closed: not answered)
    # (and waits for nothing: neither the turn's note nor the next Lead is told it does)
    with runner._factory() as session:
        notes = session.scalars(select(BoardPost.content).where(BoardPost.run_id == run_id)).all()
    assert not [note for note in notes if "has not answered" in note], notes
    nothing_left(runner)


def test_stop_while_its_card_waits_ends_the_turn_as_stop_does(
    make_client, wait_run, project_dir, gate
):
    client, _model = make_client([gate.step(text("never said"))])
    runner = client.app.state.runner
    clock = runner.call_later = HeldClock()
    cid, run_id = begin(client, project_dir)
    gate.wait_partial()
    fire(client, armed(clock)[0])
    until(client, cid, asked)
    assert client.post(f"/api/runs/{run_id}/cancel", headers=OWN).status_code == 202
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "cancelled"
    assert [q["status"] for q in snap["questions"]] == ["cancelled"]
    assert agent(snap, "Lead")["status"] == "cancelled"
    nothing_left(runner)


def test_stop_and_pick_another_model_ends_the_turn_and_its_cli_and_says_what_to_do(
    settings_env, wait_run, project_dir
):
    client, cli = queued_app(settings_env, ["Looking"])
    try:
        runner = client.app.state.runner
        clock = runner.call_later = HeldClock()
        cid, run_id = begin(client, project_dir)
        at(cli, 0)
        fire(client, armed(clock)[0])
        snap = until(client, cid, asked)
        said = asked(snap)["question"].removesuffix(ASKED)
        answer(client, asked(snap), "Stop and pick another model")
        snap = wait_run(client, cid, run_id)
        assert snap["runs"][0]["status"] == "cancelled" and cli.ended  # (its CLI ended, as at Stop)
        assert agent(snap, "Lead")["status"] == "cancelled"
        assert [m["content"] for m in snap["messages"] if m["role"] == "koloni"] == [
            f"You stopped this turn: {said} What it did so far is kept. To go on, pick another "
            "model for the Orchestrator - in the chat's model picker, or on the Agents page where "
            "the Orchestrator role has a model of its own - and send your message again."
        ]
        assert [m["content"] for m in snap["messages"] if m["role"] == "user"] == [
            "please check my greeting"
        ]  # (the user's message is kept)
        nothing_left(runner)
    finally:
        cli.go[0].set()
        client.__exit__(None, None, None)


# --- where it is not -----------------------------------------------------------------------------


def test_its_answer_to_a_message_and_its_speech_in_a_discussion_leave_its_clock_alone(
    make_client, wait_run, project_dir, gate
):
    # (they run on its own agent, beside its own work: their steps neither set nor stop its clock)
    client, _model = make_client([gate.step(text("done"))])
    runner = client.app.state.runner
    clock = runner.call_later = HeldClock()
    cid, run_id = begin(client, project_dir)
    gate.wait_partial()
    (timer,) = armed(clock)
    lead = runner._ctxs[agent(now_snap(client, cid), "Lead")["id"]]
    for beside in (replace(lead, answering=True), replace(lead, discussion="d")):
        on_loop(client, lambda beside=beside: runner._slow(beside, arm=True))
        on_loop(client, lambda beside=beside: runner._slow_off(beside))
    # (a step or call of theirs is on its row as one of its own: `_answering` says it is theirs)
    on_loop(client, lambda: answering(runner, cid, lead.agent_id))
    assert slow_timers(clock) == [timer]
    on_loop(client, lambda: runner._set_agent(cid, lead.agent_id, last_event_at=now()))
    (again,) = slow_timers(clock)  # (one of its own: its clock again)
    assert timer.cancelled and again is not timer
    gate.release()
    assert wait_run(client, cid, run_id)["runs"][0]["status"] == "completed"


def answering(runner, cid, agent_id):
    """A step of the agent's answer to a message, or of its speech, put on its row."""
    runner._answering[agent_id] = "waiting"
    try:
        runner._set_agent(cid, agent_id, last_event_at=now())
    finally:
        del runner._answering[agent_id]


def test_a_sub_agent_has_no_slow_clock(make_client, wait_run, project_dir, gate):
    # (its provider's failure moves it on - `_moved_on`; its opener's clock is off while it waits)
    client, _model = make_client(
        {"Lead": [spawn("Coder", "write it"), text("done")], "Coder": [gate.step(text("written"))]}
    )
    clock = client.app.state.runner.call_later = HeldClock()
    cid, run_id = begin(client, project_dir, mode="full_auto")
    gate.wait_partial()
    assert not slow_timers(clock)
    gate.release()
    assert wait_run(client, cid, run_id)["runs"][0]["status"] == "completed"
