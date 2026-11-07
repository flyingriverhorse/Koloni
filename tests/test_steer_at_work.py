"""89d B and C: words to an agent while it works. B - the Lead's message_agent goes into its
Claude Code's or Codex's turn (their door, `steer`), as the Lead's words and never as the user's;
Copilot's and agy's own sessions hear nothing, as before. C - the user's own word from the agent's
window (POST /api/agents/{id}/tell), as theirs; one at a time; not to an agent that has finished."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.agent import (
    AGENT_STEERED,
    LEAD_TOLD,
    SENT_WHILE_IT_WORKS,
    STEERED,
    TURN_ENDING,
    UNREAD_TOLD,
    USER_TOLD,
    ToolError,
)
from tests.test_backlog_auto import until
from tests.test_chat_flow import text
from tests.test_claude_native import claude_app  # noqa: F401  (a fixture)
from tests.test_native_agent import native_app  # noqa: F401  (a fixture)
from tests.test_spawn import begin, call, role_id, spawn, step

OWN = {"Origin": "http://127.0.0.1:8790"}
LEADS = AGENT_STEERED.format(message='Message from Lead (the agent you work for):\n\n"use blue"')


def at_work(client, cid, name="Coder"):
    """The agent's id once its CLI's turn is open (its door is there)."""
    runner = client.app.state.runner
    return until(lambda: next((a["id"] for a in client.get(f"/api/conversations/{cid}").json()[
        "agents"] if a["name"] == name and a["id"] in runner._doors), None), seconds=20)


def message(client, run_id, to="Coder", words="use blue", by=None):
    """The Lead's message_agent (or `by`'s), as it runs it."""
    runner = client.app.state.runner
    return client.portal.call(runner._message, by or runner._lead_of(run_id), "c1",
                              {"to": to, "message": words})


def handing(runner, monkeypatch):
    """The files a message hands on, as `_hand_files` is called: one named file each time."""
    handed = []
    monkeypatch.setattr(runner, "_named_files", lambda _ctx, _names: ["notes.md"])
    monkeypatch.setattr(runner, "_hand_files", lambda _ctx, files, to: handed.extend(
        (to, one) for one in files))
    return handed


def on_record(client, cid, agent_id):
    return [m for m in client.get(f"/api/conversations/{cid}").json()["messages"]
            if m["agent_id"] == agent_id and m["role"] == "agent"]


def started(client, provider, project_dir):
    client.patch(f"/api/roles/{role_id(client, 'Coder')}", json={"provider_id": provider["id"]})
    return begin(client, project_dir, mode="full_auto", spawn_approval="never")


# --- B: the Lead's message ---------------------------------------------------------------


def test_the_leads_message_goes_into_claude_codes_turn_as_its_word_not_the_users(
        claude_app, wait_run, project_dir):  # noqa: F811
    client, provider, _model = claude_app(
        [{"say": "working"}, {"await_steer": 10}, {"say": "done"}],
        default_steps={"Lead": [spawn("Coder", "sort the list"), text("done")]})
    cid, run_id = started(client, provider, project_dir)
    coder = at_work(client, cid)
    assert message(client, run_id) == ("succeeded", SENT_WHILE_IT_WORKS.format(name="Coder"))
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    (line,) = claude_app.record()["steered"]
    assert line["message"]["content"] == f"{STEERED}\n\n{LEADS}"
    assert not [t for t in snap["tool_calls"] if t["name"] == "steer"]  # (read in its turn)
    (kept,) = on_record(client, cid, coder)  # on its record, as the Lead's, once
    assert (kept["content"], kept["delivered_at"] is not None) == ("use blue", True)


@pytest.mark.parametrize("answers", [None, "late"])
def test_the_leads_message_goes_into_codexs_turn_also_where_codex_answers_late(
        native_app, wait_run, project_dir, monkeypatch, answers):  # noqa: F811
    from app import model_native
    monkeypatch.setattr(model_native, "STEER_SECONDS", 0.5)
    client, provider, _model = native_app(
        [{"say": "working"}, {"await_steer": True}, {"say": "done"}],
        default_steps={"Lead": [spawn("Coder", "sort the list"), text("done")]},
        **({"steer": answers} if answers else {}))
    cid, run_id = started(client, provider, project_dir)
    coder = at_work(client, cid)
    # (no answer within STEER_SECONDS: it may have reached its turn - sent, and on record)
    assert message(client, run_id)[0] == "succeeded"
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    (steer,) = native_app.record()["steers"]
    assert steer["input"][0]["text"] == f"{STEERED}\n\n{LEADS}"
    assert len(on_record(client, cid, coder)) == 1


def test_the_lead_is_told_where_claude_code_finished_before_it_read_its_message(
        claude_app, wait_run, project_dir, monkeypatch):  # noqa: F811
    from app import model_native
    monkeypatch.setattr(model_native, "LATE_SECONDS", 0.5)
    client, provider, model = claude_app(
        [{"say": "sorted by name"}, {"await_steer": 10}],
        default_steps={"Lead": [spawn("Coder", "sort the list"), text("done")]}, linger=True)
    cid, run_id = started(client, provider, project_dir)
    at_work(client, cid)
    # (once it has said its last word: what it wrote before cannot pass for having read it)
    until(lambda: any(m["content"] == "sorted by name"
                      for m in client.get(f"/api/conversations/{cid}").json()["messages"]))
    assert message(client, run_id, words="leave tests/ alone")[0] == "succeeded"
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    told = UNREAD_TOLD.format(name="Coder", words='"leave tests/ alone"')
    assert [m["content"] for m in model.calls_of["Lead"][-1]].count(told) == 1


def test_a_cli_at_work_without_a_door_is_refused_as_before_and_one_that_does_not_take_it_too(
        make_client, wait_run, project_dir, gate, monkeypatch):
    client, _model = make_client({
        "Lead": [spawn("Coder", "sort the list"), text("done")],
        "Coder": [gate.step(text("sorted"))],
    })
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    gate.wait_partial()
    runner = client.app.state.runner
    coder = next(c for c in runner._ctxs.values() if c.name == "Coder")
    runner._ctxs[coder.agent_id] = replace(coder, model=SimpleNamespace(native=True))
    # Copilot's or agy's own session: no door into its turn
    with pytest.raises(ToolError, match="tools of its own"):
        message(client, run_id)

    async def no(_words):
        return False

    runner._doors[coder.agent_id] = no  # (its turn ends as it is sent)
    handed = handing(runner, monkeypatch)
    with pytest.raises(ToolError) as refused:
        message(client, run_id)
    assert str(refused.value) == (
        f"Coder cannot be messaged by you now: {TURN_ENDING.format(name='Coder')}")
    assert handed == []  # no file handed with a message it never took
    assert on_record(client, cid, coder.agent_id) == []  # nothing on record that it never heard
    runner._doors.pop(coder.agent_id)
    runner._ctxs[coder.agent_id] = coder
    gate.release()
    assert wait_run(client, cid, run_id)["runs"][0]["status"] == "completed"


# --- C: the user's own word ----------------------------------------------------------------


def test_the_users_word_goes_into_claude_codes_turn_as_theirs_and_not_once_it_finished(
        claude_app, wait_run, project_dir):  # noqa: F811
    client, provider, _model = claude_app(
        [{"say": "working"}, {"await_steer": 10}, {"say": "done"}],
        default_steps={"Lead": [spawn("Coder", "sort the list"), text("done")]})
    cid, run_id = started(client, provider, project_dir)
    coder = at_work(client, cid)
    path = f"/api/agents/{coder}/tell"
    assert client.post(path, json={"words": "use blue"}).status_code == 403  # (not an agent's)
    told = client.post(path, json={"words": " use blue "}, headers=OWN)
    assert told.status_code == 204, told.text
    # (Claude Code is a process of its own here: started, steered and ended on a busy machine,
    # its turn takes past the 5 s the wait gives by default - it takes 1.2 s alone.)
    snap = wait_run(client, cid, run_id, timeout=20)
    words = USER_TOLD.format(words='"use blue"')
    (line,) = claude_app.record()["steered"]
    assert line["message"]["content"] == f"{STEERED}\n\n{words}"
    (kept,) = on_record(client, cid, coder)  # on its record, as KOLONİ passed it on
    assert (kept["content"], kept["from_agent_id"]) == (words, None)
    late = client.post(path, json={"words": "and green"}, headers=OWN)
    assert (late.status_code, late.json()["detail"]) == (409, "it has finished")
    assert snap["runs"][0]["status"] == "completed"


def test_the_users_word_one_at_a_time_and_never_into_a_cli_that_hears_nothing(
        make_client, wait_run, project_dir, gate):
    client, model = make_client({
        "Lead": [spawn("Coder", "sort the list"), text("done")],
        "Coder": [gate.step(step(call("read_file", {"path": "hello.py"}))), text("sorted")],
    })
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    gate.wait_partial()
    runner = client.app.state.runner
    coder = next(c for c in runner._ctxs.values() if c.name == "Coder")
    path = f"/api/agents/{coder.agent_id}/tell"
    runner._ctxs[coder.agent_id] = replace(coder, model=SimpleNamespace(native=True))
    said = client.post(path, json={"words": "use blue"}, headers=OWN)
    assert (said.status_code, said.json()["detail"]) == (
        409, "Coder works on in its CLI, which hears nothing more")
    heard = []

    async def slow(words):  # (a pipe that takes its time)
        heard.append(words)
        await asyncio.sleep(0.5)
        return True

    runner._doors[coder.agent_id] = slow
    with ThreadPoolExecutor(2) as pool:
        both = list(pool.map(lambda _: client.post(path, json={"words": "use blue"},
                                                   headers=OWN), range(2)))
    assert sorted((one.status_code, one.json().get("detail") if one.content else None)
                  for one in both) == [
        (204, None), (409, "can't be sent now: another message to Coder is on its way")]
    assert len(heard) == 1

    async def no(_words):
        return False

    runner._doors[coder.agent_id] = no  # (Claude Code's or Codex's turn, ending)
    said = client.post(path, json={"words": "use blue"}, headers=OWN)
    assert (said.status_code, said.json()["detail"]) == (409, TURN_ENDING.format(name="Coder"))
    runner._doors.pop(coder.agent_id)
    runner._ctxs[coder.agent_id] = coder
    # KOLONİ's own agent: its next step reads it, once (on its record, not nudged as well)
    assert client.post(path, json={"words": "and green"}, headers=OWN).status_code == 204
    gate.release()
    assert wait_run(client, cid, run_id)["runs"][0]["status"] == "completed"
    seen = [m["content"] for m in model.calls_of["Coder"][-1]]
    assert seen.count(USER_TOLD.format(words='"and green"')) == 1


def test_the_lead_reads_what_the_user_told_a_sub_agent_as_the_users_word(
        make_client, wait_run, project_dir, gate):
    # B-302: else its report calls the line the user asked for one nobody asked for.
    client, model = make_client({
        "Lead": [spawn("Coder", "sort the list"), text("done")],
        "Coder": [gate.step(step(call("read_file", {"path": "hello.py"}))), text("sorted")],
    })
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    gate.wait_partial()
    coder = next(c for c in client.app.state.runner._ctxs.values() if c.name == "Coder")
    told = client.post(f"/api/agents/{coder.agent_id}/tell", json={"words": "add a footer"},
                       headers=OWN)
    assert told.status_code == 204, told.text
    gate.release()
    assert wait_run(client, cid, run_id)["runs"][0]["status"] == "completed"
    seen = [m["content"] for m in model.calls_of["Lead"][-1]]
    assert seen.count(LEAD_TOLD.format(name="Coder", words='"add a footer"')) == 1


def test_only_the_agent_it_works_for_writes_into_its_turn_and_each_counts_to_the_limit(
        make_client, wait_run, project_dir, gate, monkeypatch):
    from app.agent import talk_mixin
    client, _model = make_client({
        "Lead": [step(call("spawn_agent", {"role": "Coder", "task": "sort the list"}, "s1"),
                      call("spawn_agent", {"role": "Reviewer", "task": "look"}, "s2")),
                 text("done")],
        "Coder": [gate.step(text("sorted"))],
        "Reviewer": [gate.step(text("looked"))],
    })
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    runner = client.app.state.runner
    ctxs = until(lambda: (found := {c.name: c for c in runner._ctxs.values()}).keys() >= {
        "Lead", "Coder", "Reviewer"} and found)
    gate.wait_partial()

    async def took(_words):
        return True

    for name in ("Coder", "Lead"):  # both CLIs at work, with a door into their turn
        runner._ctxs[ctxs[name].agent_id] = replace(ctxs[name], model=SimpleNamespace(native=True))
        runner._doors[ctxs[name].agent_id] = took
    # a sibling, and a sub-agent to the agent it works for: not into their turn
    for by, to in (("Reviewer", "Coder"), ("Coder", "Lead")):
        with pytest.raises(ToolError, match="cannot be messaged by you now"):
            message(client, run_id, to=to, by=runner._ctxs[ctxs[by].agent_id])
    handed = handing(runner, monkeypatch)
    monkeypatch.setattr(talk_mixin, "MAX_MESSAGES_PER_TURN", 1)
    assert message(client, run_id)[0] == "succeeded"
    assert handed == [(ctxs["Coder"].agent_id, "notes.md")]  # (once its CLI took it)
    with pytest.raises(ToolError, match="limit of 1 messages"):
        message(client, run_id)
    for name in ("Coder", "Lead"):
        runner._doors.pop(ctxs[name].agent_id)
        runner._ctxs[ctxs[name].agent_id] = ctxs[name]
    gate.release()
    assert wait_run(client, cid, run_id)["runs"][0]["status"] == "completed"
