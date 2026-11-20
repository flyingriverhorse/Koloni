"""K-yavas (the user, 20 Nov 2026): a turn the user watches sat for minutes with nothing happening -
Qoder's free model queued 7 min for the Orchestrator, Codex at its 5-hour limit answering every
7-10 min - and Stop was the only way out. Now its Orchestrator's model, silent for
WATCHED_SLOW_MINUTES (Qoder: queued past QUEUE_WAIT_SECONDS), is asked about on one card: Keep
waiting, or Stop and pick another model. Nobody answering, it waits; a sub-agent and a turn
nobody watches are as before."""

import asyncio
import threading
import time
from dataclasses import replace
from types import SimpleNamespace

from app.agent.limits_mixin import WATCHED_SLOW_MINUTES
from app.config import load_settings
from app.db.models import Command
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
from tests.test_triggers import HeldClock, leave, on_loop, run_now, trigger
from tests.test_triggers import setup as trigger_setup

OWN = {"Origin": "http://127.0.0.1:8790"}
SLOW = WATCHED_SLOW_MINUTES * 60.0
OPTIONS = ["Keep waiting", "Stop and pick another model"]
ASKED = " Keep waiting, or stop this turn and pick another model?"


def slow_timers(clock):
    return [t for t in clock.set if t.delay == SLOW and not t.cancelled]


def once(ready, what):
    """`ready()`'s value once it is true."""
    deadline = time.monotonic() + scaled(5)
    while not (found := ready()):
        assert time.monotonic() < deadline, what
        time.sleep(0.01)
    return found


def armed(clock):
    """The slow clock of the turn, once it is set."""
    return once(lambda: slow_timers(clock), "no slow clock was set")


def who(snap):
    lead = agent(snap, "Lead")
    return f"{lead['provider_name']} · {lead['model_id']}"


def nothing_left(runner):
    assert not runner._slow_turns and not runner._answers


async def held(event: threading.Event) -> None:
    while not event.is_set():
        await asyncio.sleep(0.01)


class Queued(ScriptedModel):
    """A CLI session for the Lead whose model Qoder queues: one queue line for each of `lines`
    (seconds waited), each then held until the test lets it go on; then its answer."""

    session = True

    def __init__(self, lines):
        super().__init__([])
        self.lines, self.go = lines, [threading.Event() for _ in lines]
        self.at, self.ended = -1, False

    async def run_session(self, model_id, messages, tools, call_tool, on_text, on_message=None,
                          effort=None, on_live=None):
        try:
            for i, elapsed in enumerate(self.lines):
                on_live({"queue": {"elapsed_s": elapsed, "max_s": 3600, "available": False}})
                self.at = i
                await held(self.go[i])
            await on_text("done")
        except asyncio.CancelledError:
            self.ended = True
            raise
        return SimpleNamespace(input_tokens=5, output_tokens=1, model=None)


def queued_app(settings_env, lines):
    cli = Queued(lines)
    client = TestClient(create_app(load_settings(settings_env), model=cli),
                        base_url="http://127.0.0.1:8790")
    client.__enter__()
    client.headers.update(OWN)
    return client, cli


def at(cli, i):
    once(lambda: cli.at >= i, f"the session never came to its line {i}")


# --- a silent model --------------------------------------------------------------------------------


def test_a_silent_orchestrator_is_asked_once_and_keep_waiting_waits_a_whole_limit_more(
        make_client, wait_run, project_dir, gate):
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
    assert timer.cancelled and len(slow_timers(clock)) == 1
    snap = now_snap(client, cid)
    assert [q["status"] for q in snap["questions"]] == ["answered"]
    assert snap["runs"][0]["status"] == "running"
    gate.release()
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert not slow_timers(clock)
    nothing_left(runner)


def test_words_from_the_model_start_its_clock_again_and_no_card_comes(
        make_client, wait_run, project_dir, gate):
    client, _model = make_client([gate.step(text("done"), partial="Looking at it")])
    clock = client.app.state.runner.call_later = HeldClock()
    cid, run_id = begin(client, project_dir)
    gate.wait_partial()
    timers = [t for t in clock.set if t.delay == SLOW]
    assert [t.cancelled for t in timers] == [True, False]  # (set as it was asked, again at its words)
    gate.release()
    snap = wait_run(client, cid, run_id)
    assert snap["questions"] == [] and not slow_timers(clock)


def test_a_card_that_waits_for_the_user_holds_the_clock_and_the_models_answer_closes_its_card(
        make_client, wait_run, project_dir, gate):
    client, _model = make_client([gate.step(text("done"))])
    runner = client.app.state.runner
    clock = runner.call_later = HeldClock()
    cid, run_id = begin(client, project_dir)
    gate.wait_partial()
    lead = agent(now_snap(client, cid), "Lead")["id"]
    with runner._factory() as session:  # (any card of the turn: the user is slow, not the model)
        session.add(Command(run_id=run_id, agent_id=lead, command="make", location="host",
                            timeout_seconds=60, status="proposed"))
        session.commit()
    (timer,) = armed(clock)
    fire(client, timer)
    assert now_snap(client, cid)["questions"] == [] and len(slow_timers(clock)) == 1
    with runner._factory() as session:
        session.query(Command).filter_by(run_id=run_id).update({"status": "rejected"})
        session.commit()
    fire(client, slow_timers(clock)[0])
    card = asked(until(client, cid, asked))
    assert card["question"].endswith(f"has not answered for 5 min.{ASKED}")
    gate.release()  # (nobody answered; its model did)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert [q["status"] for q in snap["questions"]] == ["cancelled"]  # (closed: not answered)
    nothing_left(runner)


def test_stop_while_its_card_waits_ends_the_turn_as_stop_does(make_client, wait_run, project_dir,
                                                              gate):
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


# --- Qoder's queue -------------------------------------------------------------------------------


def test_qoder_queuing_the_orchestrator_is_asked_sooner_and_once(settings_env, wait_run,
                                                                 project_dir):
    client, cli = queued_app(settings_env, [65, 120, 150])
    try:
        runner = client.app.state.runner
        clock = runner.call_later = HeldClock()
        cid, run_id = begin(client, project_dir)
        at(cli, 0)
        assert now_snap(client, cid)["questions"] == []  # (65 s: not past QUEUE_WAIT_SECONDS)
        cli.go[0].set()
        snap = until(client, cid, asked)
        lead = agent(snap, "Lead")
        assert asked(snap)["question"] == (
            f"{lead['provider_name']} has kept {lead['model_id']} queued for 2 min.{ASKED}")
        answer(client, asked(snap), "Keep waiting")
        cli.go[1].set()
        at(cli, 2)  # (its next queue line, 150 s: no second card before a whole limit more)
        assert len(now_snap(client, cid)["questions"]) == 1 and len(slow_timers(clock)) == 1
        cli.go[2].set()
        snap = wait_run(client, cid, run_id)
        assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
        nothing_left(runner)
    finally:
        for go in cli.go:
            go.set()
        client.__exit__(None, None, None)


def test_stop_and_pick_another_model_ends_the_turn_and_its_cli_and_says_what_to_do(
        settings_env, wait_run, project_dir):
    client, cli = queued_app(settings_env, [120])
    try:
        runner = client.app.state.runner
        runner.call_later = HeldClock()
        cid, run_id = begin(client, project_dir)
        snap = until(client, cid, asked)
        said = asked(snap)["question"].removesuffix(ASKED)
        answer(client, asked(snap), "Stop and pick another model")
        snap = wait_run(client, cid, run_id)
        assert snap["runs"][0]["status"] == "cancelled" and cli.ended  # (its CLI ended, as at Stop)
        assert agent(snap, "Lead")["status"] == "cancelled"
        assert [m["content"] for m in snap["messages"] if m["role"] == "koloni"] == [
            f"You stopped this turn: {said} What it did so far is kept. To go on, pick another "
            "model in the chat's model picker and send your message again."]
        assert [m["content"] for m in snap["messages"] if m["role"] == "user"] == [
            "please check my greeting"]  # (the user's message is kept)
        nothing_left(runner)
    finally:
        cli.go[0].set()
        client.__exit__(None, None, None)


# --- where it is not -----------------------------------------------------------------------------


def test_its_answer_to_a_message_and_its_speech_in_a_discussion_leave_its_clock_alone(
        make_client, wait_run, project_dir, gate):
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
    assert slow_timers(clock) == [timer]
    gate.release()
    assert wait_run(client, cid, run_id)["runs"][0]["status"] == "completed"


def test_a_sub_agent_has_no_slow_clock(make_client, wait_run, project_dir, gate):
    # (its provider's failure moves it on - `_moved_on`; its opener's clock is off while it waits)
    client, _model = make_client({"Lead": [spawn("Coder", "write it"), text("done")],
                                  "Coder": [gate.step(text("written"))]})
    clock = client.app.state.runner.call_later = HeldClock()
    cid, run_id = begin(client, project_dir, mode="full_auto")
    gate.wait_partial()
    assert not slow_timers(clock)
    gate.release()
    assert wait_run(client, cid, run_id)["runs"][0]["status"] == "completed"


def test_a_turn_nobody_watches_has_no_slow_clock(make_client, wait_run, project_dir):
    client, _model, pid, cid = trigger_setup(make_client, project_dir, [text("looked")],
                                             permission_mode="full_auto")
    clock = client.app.state.runner.call_later = HeldClock()
    made = trigger(client, pid, cid, permissions=leave(),
                   budget={"steps": 15, "minutes": 60, "per_day": 24})
    wait_run(client, cid, run_now(client, made["id"]))
    assert not [t for t in clock.set if t.delay == SLOW]
