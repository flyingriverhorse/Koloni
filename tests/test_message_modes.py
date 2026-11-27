"""C1 (0.1.11): message_agent's `how` - "leave" and "now": the API Orchestrator goes on; an agent
not at work takes the message up in a turn of its own now, one at work is handed it at its next
step or takes it up once its work ends (a real queue); every end of it is told the sender."""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.agent import AgentRunner, message_modes, talk_mixin
from app.agent.message_modes import AS_REPLY, LEFT_AT_WORK, LEFT_NOW, NOT_TAKEN_UP
from app.agent.talk_mixin import MESSAGE_WENT, SENT_WHILE_IT_WORKS
from app.db.models import ChannelMessage
from app.delivery import TAKEN, UNKNOWN
from app.tools import ToolError
from tests.conftest import Gate
from tests.test_background_spawn import bg, said_in, tool_result
from tests.test_chat_flow import text
from tests.test_claim_scenarios import setup
from tests.test_claude_native import claude_app  # noqa: F401  (a fixture)
from tests.test_parallel import statuses, until
from tests.test_spawn import call, spawn, step
from tests.test_steer_at_work import ECHOES, at_work, started

ORIGIN = {"Origin": "http://127.0.0.1:8790"}


def leave(to="Coder", words="do B", how="leave", id="m1"):
    return step(call("message_agent", {"to": to, "message": words, "how": how}, id))


def notes_of(snap, name):
    agent = next(a["id"] for a in snap["agents"] if a["name"] == name)
    return [
        m["content"] for m in snap["messages"] if m["agent_id"] == agent and m["role"] == "agent"
    ]


@pytest.mark.parametrize("how", ["leave", "now"])
def test_left_to_one_not_at_work_it_takes_it_up_now_and_its_reply_wakes_the_sender(
    make_client, wait_run, project_dir, how, monkeypatch
):
    b, lent = Gate(), []
    lend = AgentRunner._lend_slot  # (watched from the start: the Lead lends its place at once)
    monkeypatch.setattr(
        AgentRunner, "_lend_slot", lambda self, ctx: lent.append(ctx.name) or lend(self, ctx)
    )
    client, model, cid, run_id = setup(
        make_client,
        project_dir,
        {
            "Lead": [spawn("Coder", "do A"), leave(how=how), text("went on"), text("read")],
            "Coder": [text("A done"), b.step(text("B done"))],
        },
    )
    b.wait_partial()  # (its turn on it runs - and the Lead went on meanwhile)
    until(client, cid, lambda _s: len(model.calls_of["Lead"]) >= 3)
    assert tool_result(model.calls_of["Lead"][2], "m1") == LEFT_NOW.format(name="Coder")
    assert lent == ["Lead"]  # (its place lent to the Coder's turn on it)
    b.release()
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert said_in(model.calls_of["Lead"][-1], "B done") == 1  # (its reply: the Lead's note)
    assert said_in(model.calls_of["Coder"][-1], "do B") == 1  # (read once: its note its message)
    assert len(model.calls_of["Lead"]) == 4
    with client.app.state.runner._factory() as session:  # (its note and its turn: both counted)
        kinds = session.scalars(
            select(ChannelMessage.kind).where(
                ChannelMessage.run_id == run_id, ChannelMessage.kind.in_(("message", "note"))
            )
        )
        assert sorted(kinds) == ["message", "note"]


@pytest.mark.parametrize("reads", [True, False])
def test_left_to_one_at_work_is_read_at_its_next_step_or_taken_up_once_its_work_ends(
    make_client, wait_run, project_dir, reads, monkeypatch
):
    a = Gate()
    first = step(call("read_file", {"path": "hello.py"})) if reads else text("A done")
    coder = [a.step(first), *([text("A done")] if reads else []), text("B done")]
    client, model, cid, run_id = setup(
        make_client,
        project_dir,
        {
            "Lead": [step(bg("Coder", "do A", "s1")), leave(), text("asked"), *[text("x")] * 3],
            "Coder": coder,
        },
    )
    runner, nudged = client.app.state.runner, []
    nudge = runner._nudge
    monkeypatch.setattr(
        runner, "_nudge", lambda ctx, words: nudged.append(words) or nudge(ctx, words)
    )
    a.wait_partial()
    until(client, cid, lambda _s: len(model.calls_of["Lead"]) >= 3)
    assert tool_result(model.calls_of["Lead"][2], "m1") == LEFT_AT_WORK.format(name="Coder")
    a.release()
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    seen = [said_in(one, "do B") for one in model.calls_of["Coder"]]
    if reads:  # (its next step was handed it: taken, said from the Lead's next step on - a nudge)
        assert seen == [0, 1] and "B done" not in str(model.calls_of["Lead"])
        took = MESSAGE_WENT[TAKEN].format(name="Coder", words='"do B"')
        assert [one for one in nudged if took in one] == [f"KOLONİ: {took}."]
    else:  # (its work ended first: a turn of its own on it, its reply the Lead's note)
        assert seen == [0, 1] and said_in(model.calls_of["Lead"][-1], "B done") == 1
        assert "do B" in str(model.calls_of["Coder"][-1][-1]["content"])  # (last, after its words)


@pytest.mark.parametrize("ends", ["stopped", "turn", "error"])
def test_a_left_message_its_receiver_never_took_up_is_told_its_sender(
    make_client, wait_run, project_dir, ends, monkeypatch
):
    a = Gate()
    client, model, cid, run_id = setup(
        make_client,
        project_dir,
        {
            "Lead": [step(bg("Coder", "do A", "s1")), leave(), text("asked"), *[text("x")] * 3],
            "Coder": [a.step(text("A done"))],
        },
    )
    a.wait_partial()
    snap = until(client, cid, lambda _s: len(model.calls_of["Lead"]) >= 3)
    coder = next(one["id"] for one in snap["agents"] if one["name"] == "Coder")
    if ends == "stopped":
        assert client.post(f"/api/agents/{coder}/stop", headers=ORIGIN).status_code == 204
    elif ends == "turn":
        assert client.post(f"/api/runs/{run_id}/cancel", headers=ORIGIN).status_code == 202
    else:  # (its turn on it breaks as it starts: a bug's, told all the same)
        monkeypatch.setattr(client.app.state.runner, "_reply_turn", broken)
    a.release()
    snap = wait_run(client, cid, run_id)
    why = {"stopped": "it was stopped", "turn": "the turn ended first"}.get(
        ends, "an internal error"
    )
    told = NOT_TAKEN_UP.format(words='"do B"', name="Coder", why=why)
    assert told in notes_of(snap, "Lead"), notes_of(snap, "Lead")  # (never dropped unsaid)
    assert said_in(model.calls_of["Coder"][-1], "do B") == 0


async def broken(*_args, **_kwargs):
    raise RuntimeError("a bug")


def test_a_left_messages_turn_waits_for_its_receivers_other_turn_with_one_place_only(
    make_client, wait_run, project_dir
):
    # (G2/H: not beside another turn of its - and one place only here: the Lead's, lent.)
    held = Gate()
    client, model, cid, run_id = setup(
        make_client,
        project_dir,
        {
            "Lead": [spawn("Coder", "do A"), held.step(leave()), text("went on"), text("read")],
            "Coder": [text("A done"), text("B done")],
        },
        spawn_max_parallel=1,
    )
    runner = client.app.state.runner
    held.wait_partial()
    snap = until(client, cid, lambda s: statuses(s).get("Coder") == "completed")
    lock = runner._turn_of(next(a["id"] for a in snap["agents"] if a["name"] == "Coder"))
    client.portal.call(lock.acquire)  # (another turn of the Coder's)
    held.release()
    until(client, cid, lambda _s: len(model.calls_of["Lead"]) >= 3)
    assert len(model.calls_of["Coder"]) == 1  # (its turn waits for that one)
    client.portal.call(lock.release)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert said_in(model.calls_of["Lead"][-1], "B done") == 1


def test_how_is_the_api_orchestrators_and_reach_and_the_limit_hold(
    make_client, wait_run, project_dir, gate, monkeypatch
):
    client, model, cid, run_id = setup(
        make_client,
        project_dir,
        {
            "Lead": [spawn("Coder", "do A"), text("done")],
            "Coder": [gate.step(text("sorted")), text("x")],
        },
    )
    gate.wait_partial()
    runner = client.app.state.runner
    lead, coder = (next(c for c in runner._ctxs.values() if c.name == n) for n in ("Lead", "Coder"))

    def message(by, to, how):
        args = {"to": to, "message": "do B", "how": how}
        return client.portal.call(runner._message, by, "c9", args)

    with pytest.raises(ToolError, match='how is one of "reply", "leave", "now"'):
        message(lead, "Coder", "later")
    # Reach does not widen: a CLI at work with no door (agy) stays out of reach.
    runner._ctxs[coder.agent_id] = replace(coder, model=SimpleNamespace(native=True))
    for how in ("leave", "now"):
        with pytest.raises(ToolError, match="tools of its own"):
            message(lead, "Coder", how)
    runner._ctxs[coder.agent_id] = coder
    # The limit: a message left takes two (its note, and the turn it may start).
    monkeypatch.setattr(talk_mixin, "MAX_MESSAGES_PER_TURN", 1)
    with pytest.raises(ToolError, match="limit of 1 messages"):
        message(lead, "Coder", "leave")
    monkeypatch.setattr(talk_mixin, "MAX_MESSAGES_PER_TURN", 30)
    # Not the API Orchestrator's: sent as a reply, and said so (its schema has no how).
    assert runner._background_offered(lead) and not runner._background_offered(coder)
    assert message_modes.how_of(runner, coder, "leave") == ("reply", AS_REPLY.format(how="leave"))
    gate.release()
    assert wait_run(client, cid, run_id)["runs"][0]["status"] == "completed"
    message_agent = [
        next(t for t in tools if t["function"]["name"] == "message_agent")["function"]
        for tools in model.tool_args
        if tools and any(t["function"]["name"] == "message_agent" for t in tools)
    ]
    hows = {"how" in one["parameters"]["properties"] for one in message_agent}
    assert hows == {True, False}  # (the Lead's has it, the Coder's not)


def test_now_into_a_cli_at_work_is_its_turn_and_c2s_outcome_is_the_senders(
    claude_app, wait_run, project_dir
):  # noqa: F811
    client, provider, _model = claude_app(
        [{"say": "working"}, {"await_steer": 10}, {"say": "done"}],
        default_steps={"Lead": [spawn("Coder", "sort the list"), text("done")]},
        version=ECHOES,
    )
    cid, run_id = started(client, provider, project_dir)
    at_work(client, cid)
    runner = client.app.state.runner
    args = {"to": "Coder", "message": "use blue", "how": "now"}
    said = client.portal.call(runner._message, runner._lead_of(run_id), "c1", args)
    assert said == ("succeeded", SENT_WHILE_IT_WORKS.format(name="Coder"))
    assert wait_run(client, cid, run_id)["runs"][0]["status"] == "completed"
    (line,) = claude_app.record()["steered"]  # (into its turn, once)
    assert "use blue" in line["message"]["content"]


@pytest.mark.parametrize("stop", ["turn", "agent"])
def test_a_stop_as_it_takes_a_left_message_up_is_told_its_sender(
    make_client, wait_run, project_dir, stop
):
    b = Gate()
    client, model, cid, run_id = setup(
        make_client,
        project_dir,
        {
            "Lead": [spawn("Coder", "do A"), leave(), text("went on"), *[text("x")] * 3],
            "Coder": [text("A done"), b.step(text("B done"))],
        },
    )
    b.wait_partial()  # (in its turn on it)
    snap = until(client, cid, lambda _s: len(model.calls_of["Lead"]) >= 3)
    coder = next(one["id"] for one in snap["agents"] if one["name"] == "Coder")
    if stop == "turn":
        assert client.post(f"/api/runs/{run_id}/cancel", headers=ORIGIN).status_code == 202
    else:  # (the user's Stop on it ends its turn on the message alone)
        assert client.post(f"/api/agents/{coder}/stop", headers=ORIGIN).status_code == 204
    b.release()
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == ("cancelled" if stop == "turn" else "completed")
    went = MESSAGE_WENT[UNKNOWN].format(name="Coder", words='"do B"')
    assert f"KOLONİ: {went}." in notes_of(snap, "Lead"), notes_of(snap, "Lead")
    assert next(a["status"] for a in snap["agents"] if a["name"] == "Coder") == "cancelled"


def test_a_sub_agents_how_and_one_to_an_earlier_turns_agent_are_sent_as_replies_and_said(
    make_client, wait_run, project_dir
):
    asks = call("message_agent", {"to": "Lead", "message": "which file?", "how": "leave"}, "m1")
    client, model, cid, run_id = setup(
        make_client,
        project_dir,
        {
            "Lead": [spawn("Coder", "do A"), text("hello.py"), text("done")],
            "Coder": [step(asks), text("A done")],
        },
    )
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    told = tool_result(model.calls_of["Coder"][1], "m1")
    assert told.startswith(AS_REPLY.format(how="leave")) and "hello.py" in told  # (its reply)
    assert message_modes.EARLIER.format(how="now").startswith('how "now": an agent of an earlier')


def test_left_to_a_cli_at_work_is_never_written_into_its_turn_and_is_taken_up_after_it(
    claude_app, wait_run, project_dir
):  # noqa: F811
    client, provider, _model = claude_app(
        [{"say": "working"}, {"sleep": 2}, {"say": "done"}],
        default_steps={"Lead": [spawn("Coder", "sort the list"), text("done"), text("read")]},
        version=ECHOES,
    )
    cid, run_id = started(client, provider, project_dir)
    at_work(client, cid)
    runner = client.app.state.runner
    args = {"to": "Coder", "message": "use blue", "how": "leave"}
    said = client.portal.call(runner._message, runner._lead_of(run_id), "c1", args)
    assert said == ("succeeded", LEFT_AT_WORK.format(name="Coder"))
    assert wait_run(client, cid, run_id)["runs"][0]["status"] == "completed"
    assert not claude_app.record().get("steered")  # (a note, not its running turn's line)
    assert claude_app.record()["stdin"].count("use blue") == 1  # (its run on it, once)
