"""What a live test prints when a turn does not finish in time (tests.test_live._stuck):
each agent's state and last tool call, and what the turn is waiting on. Checked here, on
real snapshots of held turns, so that it tells something the day a live turn stalls."""

from tests.conftest import Gate
from tests.test_chat_flow import text
from tests.test_live import _stuck
from tests.test_parallel import statuses, until
from tests.test_questions import OWN
from tests.test_spawn import begin, call, spawn, step


def test_a_stalled_turn_says_who_stands_where_and_what_it_waits_on(
    make_client, wait_run, project_dir
):
    a = Gate()
    client, model = make_client({
        "Lead": [spawn("Coder", "do A"), text("done")],
        "Coder": [step(call("list_dir", {}, "l1")), a.step(text("Looked."), partial="Lo")],
    })
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    a.wait_partial()
    snap = until(client, cid, lambda s: any(
        m["status"] == "streaming" and m["content"] for m in s["messages"]))
    said = _stuck(snap)
    a.release()
    wait_run(client, cid, run_id)
    lines = said.splitlines()
    assert lines[0] == "the run did not finish in time. Turn: running."
    assert lines[1:4] == [
        "Agents:",
        '- Lead (Lead role, Local · fake-model): waiting; last tool call: spawn_agent '
        '{"role": "Coder", "task": "do A"} - running',
        "- Coder (Coder role, Local · fake-model): running; last tool call: list_dir {} - "
        "succeeded",
    ]
    assert lines[4:] == [
        "Waiting on:",
        "- the tool call spawn_agent of Lead (running)",
        "- the model of Coder: 2 characters of its message written so far",
    ]


def test_a_turn_waiting_for_the_user_says_for_what(make_client, wait_run, project_dir):
    client, model = make_client({
        "Lead": [step(
            call("spawn_agent", {"role": "Coder", "task": "do A"}, "s1"),
            call("spawn_agent", {"role": "Reviewer", "task": "look"}, "s2"),
        ), text("done")],
        "Coder": [text("A done")],
        "Reviewer": [step(call("ask_user", {"question": "Strict or lenient?"}, "q")),
                     text("looked")],
    })
    cid, run_id = begin(client, project_dir, mode="ask")
    snap = until(client, cid, lambda s: s["questions"] and statuses(s).get("Coder") == "proposed")
    waiting = _stuck(snap).split("Waiting on:\n")[1].splitlines()
    assert "- your approval to open Coder" in waiting
    assert '- your answer to Reviewer: "Strict or lenient?"' in waiting
    assert "the run did not finish in time. Turn: waiting_approval." in _stuck(snap)
    client.post(f"/api/questions/{snap['questions'][0]['id']}/answer", json={"answer": "strict"}, headers=OWN)
    coder = next(x for x in snap["agents"] if x["name"] == "Coder")
    client.post(f"/api/agents/{coder['id']}/approve")
    wait_run(client, cid, run_id)


def test_an_agent_at_work_with_nothing_open_is_named_too(make_client, wait_run, project_dir):
    a = Gate()
    client, model = make_client([a.step(text("done"))])  # held before its first word
    cid, run_id = begin(client, project_dir, mode="full_auto")
    a.wait_partial()
    snap = client.get(f"/api/conversations/{cid}").json()
    said = _stuck(snap)
    a.release()
    wait_run(client, cid, run_id)
    assert "- Lead (Lead role, Local · fake-model): running; no tool call yet" in said
    assert said.endswith(
        "Waiting on:\n- the model of Lead: no open call and nothing written yet (its first "
        "token, or a CLI that has said nothing)")


def test_a_snapshot_it_cannot_read_still_gives_a_message():
    assert _stuck({}).startswith("the run did not finish in time")
    odd = {"runs": [{}], "agents": [{"id": 1}], "tool_calls": [{"agent_id": 1, "arguments": None}],
           "messages": [{"status": "streaming", "content": None}], "questions": [{}]}
    assert _stuck(odd).startswith("the run did not finish in time")
