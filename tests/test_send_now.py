"""D2 (0.1.11): a word the user writes while a turn runs - Send now - enters the open turn: its
Orchestrator reads it at its next step (one of its waits gives way to it), answers it without
writing, and the turn does not end before it has; where the turn takes none, or its door is shut,
it waits in the queue with why. A word is in exactly one place: the open turn, or a turn of its
own."""

import asyncio
import threading
import time
from dataclasses import replace

from app.agent.words import LISTEN, STILL_AT_WORK
from app.api import undo
from app.db.models import Message, Run
from app.model_client import ModelUnavailable
from tests.conftest import Gate
from tests.test_background_spawn import bg, said_in
from tests.test_chat_flow import text
from tests.test_claim_scenarios import setup, write
from tests.test_parallel import statuses, until
from tests.test_spawn import step

ORIGIN = {"Origin": "http://127.0.0.1:8790"}


def now(client, cid, content, **more):
    return client.post(
        f"/api/conversations/{cid}/messages",
        json={"content": content, "now": True, **more},
        headers=ORIGIN,
    )


def said(snap, words):
    return [m for m in snap["messages"] if m["content"] == words]


def test_send_now_while_the_lead_waits_wakes_it_in_the_same_turn(
    make_client, wait_run, project_dir
):
    a = Gate()
    client, model, cid, run_id = setup(
        make_client,
        project_dir,
        {
            "Lead": [
                step(bg("Coder", "do A", "s1")),
                text("asked"),
                text("Coder is still at work"),
                text("Coder is done"),
            ],
            "Coder": [a.step(text("A done"))],
        },
    )
    until(client, cid, lambda s: statuses(s) == {"Lead": "waiting", "Coder": "running"})
    posted = now(client, cid, "how is it going?")
    assert posted.status_code == 201, posted.text
    assert posted.json()["run"]["id"] == run_id and posted.json()["queued_why"] is None
    snap = until(client, cid, lambda s: said(s, "Coder is still at work"))
    assert statuses(snap)["Coder"] == "running"
    assert [x["status"] for x in snap["runs"]] == ["running"]  # no turn of its own
    (word,) = said(snap, "how is it going?")
    assert word["run_id"] == run_id
    listened = model.calls_of["Lead"][2]
    assert said_in(listened, "how is it going?") == 1  # read once, as the user's own
    assert listened[-1]["content"] == "how is it going?"  # the last thing it reads
    a.release()
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert len(model.calls_of["Lead"]) == 4  # the word, then the Coder's end: a step each
    assert said_in(model.calls_of["Lead"][3], "A done") == 1


def test_door_unit_interleavings(make_client, wait_run, project_dir):
    gate = Gate()
    client, model, cid, run_id = setup(
        make_client, project_dir, {"Lead": [gate.step(text("done"))]}
    )
    gate.wait_partial()
    runner = client.app.state.runner
    lead = runner._lead_of(run_id)
    topic = client.get(f"/api/conversations/{cid}").json()["runs"][0]["topic_id"]
    assert runner.takes_word(cid, topic) == (run_id, "")
    assert runner.takes_word(cid, "another") == (None, "it is for another topic")
    runner.word_came(run_id, "m1", "x")
    assert runner._door_closes(lead, "completed") is False  # one step more
    assert lead.agent_id in runner._listening
    assert runner._door_closes(lead, "failed") is True  # (not completed: it goes to the queue)
    runner._door_shut.discard(run_id)
    runner._hearing(lead)
    runner.word_came(run_id, "m2", "y")  # (after its request was made: not in it)
    runner._heard(lead)
    assert runner._unheard[run_id] == ["m2"]
    runner._hearing(lead)
    runner._heard(lead)
    assert runner._door_closes(lead, "completed") is True
    assert runner.takes_word(cid, topic) == (None, "the turn was ending")
    # Its answer's or a sub-agent's loop never holds the door.
    assert runner._door_closes(replace(lead, answering=True), "completed")
    gate.release()
    assert wait_run(client, cid, run_id)["runs"][0]["status"] == "completed"
    assert runner.takes_word(cid, topic) == (None, "")  # no turn open: its own starts


def test_a_word_as_the_turn_ends_enters_it_or_the_queue_once(make_client, wait_run, project_dir):
    rounds = 8
    gates = [Gate() for _ in range(rounds)]
    script = [one for gate in gates for one in (gate.step(text("answer")), text("heard"))]
    client, model, cid, first = setup(make_client, project_dir, {"Lead": script})
    posted, turns = [], [first]
    for at, gate in enumerate(gates):
        if at:
            turns.append(
                client.post(
                    f"/api/conversations/{cid}/messages",
                    json={"content": f"go {at}"},
                    headers=ORIGIN,
                ).json()["run"]["id"]
            )
        gate.wait_partial()
        gate.release()
        if at % 2:
            time.sleep(0.001 * at)  # (now before the end, now after it)
        made = now(client, cid, f"word {at}")
        assert made.status_code == 201, made.text
        posted.append((turns[-1], made.json()["message"]["id"], made.json()["queued_why"]))
        until(
            client, cid, lambda s: all(r["status"] in ("completed",) for r in s["runs"]), timeout=20
        )
    snap = client.get(f"/api/conversations/{cid}").json()
    runs = {r["id"]: r for r in snap["runs"]}
    assert all(r["status"] == "completed" for r in runs.values()), runs
    for turn, mid, why in posted:
        (word,) = [m for m in snap["messages"] if m["id"] == mid]
        inside = word["run_id"] == turn
        heard = [
            m
            for m in snap["messages"]
            if m["run_id"] == word["run_id"]
            and m["role"] == "assistant"
            and m["created_at"] > word["created_at"]
        ]
        assert heard, (turn, word)  # answered in whichever turn holds it
        # In the open turn (no why), or one of its own: queued as it was ending, or after it.
        assert why is None if inside else why in (None, "the turn was ending"), (inside, why)


def test_send_now_from_another_origin_is_403_and_not_the_users_word(
    make_client, wait_run, project_dir
):
    gate = Gate()
    client, model, cid, run_id = setup(
        make_client, project_dir, {"Lead": [gate.step(text("done")), text("x")]}
    )
    gate.wait_partial()
    url = f"/api/conversations/{cid}/messages"
    assert (
        client.post(
            url, json={"content": "do more", "now": True}, headers={"Origin": ""}
        ).status_code
        == 403
    )
    assert (
        client.post(
            url, json={"content": "do more", "now": True}, headers={"Origin": "http://evil"}
        ).status_code
        == 403
    )
    assert not said(client.get(f"/api/conversations/{cid}").json(), "do more")
    assert now(client, cid, "mine").status_code == 201
    gate.release()
    wait_run(client, cid, run_id)
    runner = client.app.state.runner
    with runner._factory() as session:
        words = runner._users_words(session, cid, None)
    assert "mine" in str(words)  # the user's own word, as theirs
    assert "do more" not in str(words)


def test_send_now_queues_with_why(make_client, wait_run, project_dir, monkeypatch):
    gate = Gate()
    client, model, cid, run_id = setup(
        make_client, project_dir, {"Lead": [gate.step(text("done")), text("a"), text("b")]}
    )
    gate.wait_partial()
    runner = client.app.state.runner
    topic = client.get(f"/api/conversations/{cid}").json()["runs"][0]["topic_id"]

    def why_with(**fields):
        with runner._factory() as session:
            run = session.get_one(Run, run_id)
            was = {key: getattr(run, key) for key in fields}
            for key, value in fields.items():
                setattr(run, key, value)
            session.commit()
        try:
            return runner.takes_word(cid, topic)[1]
        finally:
            with runner._factory() as session:
                run = session.get_one(Run, run_id)
                for key, value in was.items():
                    setattr(run, key, value)
                session.commit()

    assert why_with(plan_turn=True) == "this turn takes no message now (a plan turn)"
    assert why_with(task_id="t1") == "this turn takes no message now (a To-do task's turn)"
    assert why_with(by_user=False) == "this turn takes no message now (not one you started)"
    assert why_with(compare_id="x") == "this turn takes no message now (a comparison)"
    monkeypatch.setattr("app.away.job_turn", lambda _session, _run: True)
    assert (
        runner.takes_word(cid, topic)[1]
        == "this turn takes no message now (a job while you were away)"
    )
    monkeypatch.undo()
    # Another topic: queued with why, the open turn untouched.
    other = now(client, cid, "about something else", new_topic=True)
    assert other.status_code == 201
    assert other.json()["queued_why"] == "it is for another topic"
    assert other.json()["run"]["id"] != run_id and other.json()["run"]["status"] == "queued"
    gate.release()
    snap = wait_run(client, cid, other.json()["run"]["id"])
    assert [r["status"] for r in snap["runs"]] == ["completed", "completed"]


def test_a_word_never_read_goes_to_the_queue_on_stop_or_failure(make_client, wait_run, project_dir):
    gate = Gate()
    client, model, cid, run_id = setup(
        make_client,
        project_dir,
        {"Lead": [gate.step(text("never")), text("read it in its own turn")]},
    )
    gate.wait_partial()
    word = now(client, cid, "stop and do this").json()["message"]
    assert word["run_id"] == run_id
    assert client.post(f"/api/runs/{run_id}/cancel").status_code == 202
    snap = wait_run(client, cid, run_id)
    gate.release()
    assert snap["runs"][0]["status"] == "cancelled"
    # Its own turn reads it - once, moved there whole.
    snap = until(
        client, cid, lambda s: len(s["runs"]) == 2 and s["runs"][1]["status"] == "completed"
    )
    (moved,) = said(snap, "stop and do this")
    assert moved["id"] == word["id"] and moved["run_id"] == snap["runs"][1]["id"] != run_id
    assert said_in(model.calls_of["Lead"][-1], "stop and do this") == 1


def test_a_failed_step_after_the_word_puts_it_in_its_own_turn(make_client, wait_run, project_dir):
    gate = Gate()
    failed = Gate()

    async def fails(on_delta):
        while not failed.released:
            await asyncio.sleep(0.01)
        raise ModelUnavailable("model server unreachable: refused")

    client, model, cid, run_id = setup(
        make_client, project_dir, {"Lead": [gate.step(text("x")), fails, text("now read")]}
    )
    # (its first answer, a word, then its listen step fails before it reads it)
    gate.wait_partial()
    word = now(client, cid, "and this").json()["message"]
    gate.release()
    until(client, cid, lambda s: len(model.calls_of["Lead"]) >= 2)
    failed.release()
    snap = until(
        client, cid, lambda s: len(s["runs"]) == 2 and s["runs"][1]["status"] == "completed"
    )
    assert snap["runs"][0]["status"] == "failed"
    (moved,) = said(snap, "and this")
    assert moved["id"] == word["id"] and moved["run_id"] == snap["runs"][1]["id"]


def test_a_word_to_a_turn_that_never_came_to_its_loop_goes_to_the_queue(
    make_client, wait_run, project_dir, monkeypatch
):
    client, model = make_client({"Lead": [text("its own turn")]})
    held, info = threading.Event(), model.info

    async def no_model():
        while not held.is_set():
            await asyncio.sleep(0.01)
        raise ModelUnavailable("model server unreachable: refused")

    monkeypatch.setattr(model, "info", no_model)
    client.headers["Origin"] = "http://127.0.0.1:8790"
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    run_id = client.post(f"/api/conversations/{cid}/messages", json={"content": "go"}).json()[
        "run"
    ]["id"]
    word = now(client, cid, "and this")
    assert word.json()["run"]["id"] == run_id
    monkeypatch.setattr(model, "info", info)
    held.set()
    snap = until(
        client, cid, lambda s: len(s["runs"]) == 2 and s["runs"][1]["status"] == "completed"
    )
    assert snap["runs"][0]["status"] == "failed"
    assert said(snap, "and this")[0]["run_id"] == snap["runs"][1]["id"]


def test_never_two_lead_steps_at_once(make_client, wait_run, project_dir):
    a = Gate()
    inside, most = [0], [0]

    def counted(result):
        async def held(on_delta):
            inside[0] += 1
            most[0] = max(most[0], inside[0])
            await asyncio.sleep(0.05)
            inside[0] -= 1
            await on_delta(result.content)
            return result

        return held

    client, model, cid, run_id = setup(
        make_client,
        project_dir,
        {
            "Lead": [counted(step(bg("Coder", "do A", "s1"))), counted(text("asked"))]
            + [counted(text(f"heard {n}")) for n in range(6)],
            "Coder": [a.step(text("A done"))],
        },
    )
    until(client, cid, lambda s: statuses(s) == {"Lead": "waiting", "Coder": "running"})
    a.release()  # its end, and two words, at once
    assert now(client, cid, "one").status_code == 201
    assert now(client, cid, "two").status_code == 201
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert most[0] == 1
    last = model.calls_of["Lead"][-1]
    assert said_in(last, "one") >= 1 and said_in(last, "two") >= 1 and said_in(last, "A done") == 1
    assert [r["status"] for r in snap["runs"]] == ["completed"]


def test_a_listen_step_writes_nothing(make_client, wait_run, project_dir):
    a = Gate()
    client, model, cid, run_id = setup(
        make_client,
        project_dir,
        {
            "Lead": [
                step(bg("Coder", "do A", "s1")),
                text("asked"),
                step(write("lead.txt", "L", id="w1")),  # (answering the word)
                text("I asked Coder"),
                step(write("after.txt", "B", id="w2")),  # (after the Coder's end: its own work)
                text("done"),
            ],
            "Coder": [a.step(text("A done"))],
        },
        lead_hands_code=False,
    )
    until(client, cid, lambda s: statuses(s) == {"Lead": "waiting", "Coder": "running"})
    assert now(client, cid, "also write lead.txt").status_code == 201
    snap = until(client, cid, lambda s: said(s, "I asked Coder"))
    refused = next(t for t in snap["tool_calls"] if t["provider_call_id"] == "w1")
    assert refused["result"] == f"error: {LISTEN}"
    assert not (project_dir / "lead.txt").exists()
    a.release()
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    wrote = next(t for t in snap["tool_calls"] if t["provider_call_id"] == "w2")
    assert wrote["status"] == "succeeded", wrote["result"]


def test_a_word_while_the_lead_works_is_read_at_its_next_step_and_its_writes_go_on(
    make_client, wait_run, project_dir
):
    gate = Gate()
    client, model, cid, run_id = setup(
        make_client,
        project_dir,
        {
            "Lead": [
                gate.step(step(write("a.txt", "A", id="w1"))),
                step(write("b.txt", "B", id="w2")),
                text("done"),
            ]
        },
        lead_hands_code=False,
    )
    gate.wait_partial()
    assert now(client, cid, "use blue").json()["run"]["id"] == run_id
    gate.release()
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert said_in(model.calls_of["Lead"][1], "use blue") == 1  # its next step, once
    assert all(t["status"] == "succeeded" for t in snap["tool_calls"])  # not a listen step
    assert len(model.calls_of["Lead"]) == 3


def test_held_for_its_teams_a_word_is_answered_told_who_is_at_work(
    make_client, wait_run, project_dir
):
    from app.db.models import Agent

    gate = Gate()
    client, model, cid, run_id = setup(
        make_client,
        project_dir,
        {"Lead": [gate.step(text("done")), text("still at it"), text("all back")]},
    )
    gate.wait_partial()
    runner = client.app.state.runner
    with runner._factory() as session:  # (one of a team's, held for: B-376)
        made = Agent(
            run_id=run_id, role_name="Coder", name="Coder", tools=[], depth=1, status="running"
        )
        session.add(made)
        session.commit()
        coder = made.id
    gate.release()
    until(client, cid, lambda s: statuses(s) == {"Lead": "waiting", "Coder": "running"})
    assert now(client, cid, "status?").status_code == 201
    snap = until(client, cid, lambda s: said(s, "still at it"))
    nudged = [m["content"] for m in model.calls_of["Lead"][1] if m["role"] == "user"]
    assert STILL_AT_WORK.format(what="Coder running") in nudged
    assert nudged[-1] == "status?"
    with runner._factory() as session:
        session.get_one(Agent, coder).status = "completed"
        session.commit()
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]


def test_send_now_while_a_card_waits_enters_the_turn(make_client, wait_run, project_dir):
    from tests.test_agent_commands import cmd

    client, model, cid, run_id = setup(
        make_client,
        project_dir,
        {
            "Lead": [
                step(bg("Coder", "run the tests", "s1")),
                text("asked"),
                text("it waits for you"),
            ],
            "Coder": [cmd("pytest -q"), text("ran")],
        },
        permission_mode="ask",
    )
    until(client, cid, lambda s: [c["status"] for c in s["commands"]] == ["proposed"])
    until(client, cid, lambda s: statuses(s)["Lead"] == "waiting")
    assert now(client, cid, "what does it wait for?").json()["run"]["id"] == run_id
    until(client, cid, lambda s: said(s, "it waits for you"))
    (asked,) = client.get(f"/api/conversations/{cid}").json()["commands"]
    assert client.post(f"/api/commands/{asked['id']}/reject", headers=ORIGIN).status_code == 200


def test_the_turns_request_stays_its_first_message(make_client, wait_run, project_dir):
    gate = Gate()
    client, model, cid, run_id = setup(
        make_client, project_dir, {"Lead": [gate.step(text("done"))]}
    )
    gate.wait_partial()
    assert now(client, cid, "and one more thing").status_code == 201
    gate.release()
    wait_run(client, cid, run_id)
    runner = client.app.state.runner
    with runner._factory() as session:
        assert undo._asked(session, run_id) == "go"
        first = session.scalar(
            Message.__table__.select()
            .with_only_columns(Message.content)
            .where(Message.run_id == run_id, Message.role == "user")
            .order_by(Message.created_at)
            .limit(1)
        )
    assert first == "go"
