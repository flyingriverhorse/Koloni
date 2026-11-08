"""Agents talk to each other: names, message_agent, the two kinds of reply turn."""

import json
import sqlite3
import time

from alembic import command

from app.model_client import ModelUnavailable
from tests.test_agent_writes import wait_status
from tests.test_chat_flow import text
from tests.test_migration_0002 import _config
from tests.test_spawn import begin, call, names, reported, spawn, step

READ = ["list_dir", "read_file", "search"]


def message(to, content="how is it going?", id="m1"):
    return step(call("message_agent", {"to": to, "message": content}, id))


def tool_named(tools, name):
    return next(t["function"] for t in tools if t["function"]["name"] == name)


# --- names --------------------------------------------------------------------


def test_agents_get_names_unique_in_the_turn(make_client, wait_run, project_dir):
    client, model = make_client([
        spawn("Reviewer", "first look", id="s1"),
        text("fine"),
        spawn("reviewer", "second look", id="s2"),
        text("still fine"),
        text("done"),
    ])
    cid, run_id = begin(client, project_dir)
    snap = wait_run(client, cid, run_id)

    assert [a["name"] for a in snap["agents"]] == ["Lead", "Reviewer", "Reviewer 2"]
    assert [a["role_name"] for a in snap["agents"]] == ["Lead", "Reviewer", "Reviewer"]
    assert reported(model.calls[2][-1]["content"]) == "Reviewer finished.\n\nfine"
    assert reported(model.calls[4][-1]["content"]) == "Reviewer 2 finished.\n\nstill fine"
    assert "Your name here is Reviewer 2" in model.calls[3][0]["content"]
    assert "Your name here is Reviewer." in model.calls[1][0]["content"]


def test_a_role_with_only_talking_tools_has_no_tools_here(make_client, wait_run, project_dir):
    client, model = make_client([
        spawn("Chatter"),
        text("did it myself"),
    ])
    made = client.post("/api/roles", json={
        "name": "Chatter", "description": "", "instructions": "",
        "tools": ["ask_user", "message_agent"]})
    assert made.status_code == 201, made.text
    cid, run_id = begin(client, project_dir)
    snap = wait_run(client, cid, run_id)
    assert "would have no tools here" in snap["tool_calls"][0]["result"]
    assert len(snap["agents"]) == 1


def test_migration_0008_names_agents_and_lets_builtin_roles_message(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0007")
    at = "2026-10-05 10:00:0"
    roles = [("b1", "Reviewer", ["read_file", "ask_user"], 1), ("u1", "Mine", ["read_file"], 0)]
    agents = [("a1", "r1", "Lead"), ("a2", "r1", "Reviewer"), ("a3", "r1", "Reviewer"),
              ("a4", "r2", "Reviewer")]
    with sqlite3.connect(db) as conn:
        for id, name, tools, builtin in roles:
            conn.execute(
                "INSERT INTO roles (id, name, description, instructions, tools, builtin, "
                "created_by_agent, created_at, updated_at) VALUES (?, ?, '', '', ?, ?, 0, ?, ?)",
                (id, name, json.dumps(tools), builtin, at + "0", at + "0"))
        for index, (id, run, role) in enumerate(agents):
            conn.execute(
                "INSERT INTO agents (id, run_id, role_name, tools, depth, status, created_at) "
                "VALUES (?, ?, ?, '[]', 0, 'completed', ?)", (id, run, role, at + str(index)))

    command.upgrade(cfg, "0008")
    with sqlite3.connect(db) as conn:
        named = dict(conn.execute("SELECT id, name FROM agents"))
        tools = {name: json.loads(t) for name, t in conn.execute("SELECT name, tools FROM roles")}
        columns = [row[1] for row in conn.execute("PRAGMA table_info(messages)")]
    assert named == {"a1": "Lead", "a2": "Reviewer", "a3": "Reviewer 2", "a4": "Reviewer"}
    assert tools == {"Reviewer": ["read_file", "ask_user", "message_agent"], "Mine": ["read_file"]}
    assert "from_agent_id" in columns

    command.downgrade(cfg, "0007")
    with sqlite3.connect(db) as conn:
        tools = {name: json.loads(t) for name, t in conn.execute("SELECT name, tools FROM roles")}
        agent_columns = [row[1] for row in conn.execute("PRAGMA table_info(agents)")]
        columns = [row[1] for row in conn.execute("PRAGMA table_info(messages)")]
    assert tools == {"Reviewer": ["read_file", "ask_user"], "Mine": ["read_file"]}
    assert "name" not in agent_columns and "from_agent_id" not in columns


def wait_terminal(client, cid):
    for _ in range(250):
        snap = client.get(f"/api/conversations/{cid}").json()
        if snap["runs"][-1]["status"] in ("completed", "failed", "cancelled"):
            return snap
        time.sleep(0.02)
    raise AssertionError("the run never ended")


# --- a parent carries on with a finished child ----------------------------------


def test_lead_continues_a_finished_child(make_client, wait_run, project_dir):
    client, model = make_client([
        spawn("Coder", "Add a notes file"),
        text("Nothing written yet."),
        message("coder", "Now write new.txt"),
        step(call("write_file", {"path": "new.txt", "content": "x\n"}, "w1")),
        text("Wrote new.txt."),
        text("All done."),
    ])
    cid, run_id = begin(client, project_dir, mode="full_auto")
    snap = wait_run(client, cid, run_id)

    assert (project_dir / "new.txt").read_text() == "x\n"
    assert model.calls[5][-1]["content"] == "Coder replied:\n\nWrote new.txt."
    again = model.calls[3]
    assert [m["role"] for m in again] == ["system", "user", "assistant", "user"]
    assert again[1]["content"] == "Add a notes file"
    assert again[2]["content"] == "Nothing written yet."
    assert again[3]["content"] == "Message from Lead (the agent you work for):\n\nNow write new.txt"
    assert "write_file" in names(model.tool_args[3])

    lead, coder = snap["agents"]
    assert (coder["status"], coder["report"]) == ("completed", "Wrote new.txt.")
    assert lead["status"] == "completed"
    assert [(c["kind"], c["from_agent_id"] == lead["id"]) for c in snap["channel_messages"]] == [
        ("task", True), ("report", False), ("message", True), ("reply", False)]
    assert snap["channel_messages"][3]["content"] == "Wrote new.txt."
    sent = [m for m in snap["messages"] if m["role"] == "agent"]
    assert [(m["agent_id"], m["from_agent_id"], m["content"]) for m in sent] == [
        (coder["id"], lead["id"], "Now write new.txt")]
    assert [t["status"] for t in snap["tool_calls"]] == ["succeeded"] * 3


def test_the_tool_lists_who_can_be_reached_and_is_absent_when_nobody_can(
    make_client, wait_run, project_dir
):
    client, model = make_client([spawn("Coder"), text("coded"), text("done")])
    cid, run_id = begin(client, project_dir, mode="full_auto")
    wait_run(client, cid, run_id)
    assert "message_agent" not in names(model.tool_args[0])
    described = tool_named(model.tool_args[2], "message_agent")["description"]
    assert "- Coder (Coder role): it has finished" in described
    # The Coder, while it works, can ask the Lead that waits for it.
    assert "- Lead (Lead role): it answers" in tool_named(
        model.tool_args[1], "message_agent")["description"]


def test_tokens_of_a_reply_turn_go_to_the_receiver(make_client, wait_run, project_dir):
    client, _ = make_client([
        spawn("Coder"), text("coded", i=5, o=3), message("Coder"), text("more", i=7, o=4),
        text("done")])
    cid, run_id = begin(client, project_dir, mode="full_auto")
    coder = wait_run(client, cid, run_id)["agents"][1]
    # as for every agent: the size of its latest prompt, and all it has written
    assert (coder["input_tokens"], coder["output_tokens"]) == (7, 7)


# --- answer turns ---------------------------------------------------------------


def test_a_child_asks_its_waiting_parent(make_client, wait_run, project_dir, gate):
    client, model = make_client([
        spawn("Coder", "Fix the greeting"),
        message("Lead", "Which file?"),
        gate.step(text("hello.py")),
        text("Fixed hello.py."),
        text("All done."),
    ])
    cid, run_id = begin(client, project_dir, mode="full_auto")
    gate.wait_partial()
    snap = client.get(f"/api/conversations/{cid}").json()
    assert [a["status"] for a in snap["agents"]] == ["running", "waiting"]
    gate.release()
    snap = wait_run(client, cid, run_id)

    asked = model.calls[2]
    assert [m["role"] for m in asked] == ["system", "user", "assistant", "tool", "user"]
    assert asked[3]["content"] == "still running: this call has not returned yet"
    assert asked[4]["content"] == (
        "Message from Coder (your sub-agent):\n\nWhich file?")
    assert names(model.tool_args[2]) == [*READ, "recall"]
    assert model.calls[3][-1]["content"] == "Lead replied:\n\nhello.py"

    # Its own call has returned since it answered: the request must not end on its own
    # words (a model would take them as a reply to go on writing), so a note follows.
    after = model.calls[4]
    assert [m["role"] for m in after] == [
        "system", "user", "assistant", "tool", "user", "assistant", "user"]
    assert reported(after[3]["content"]) == "Coder finished.\n\nFixed hello.py."
    assert after[5]["content"] == "hello.py"
    assert after[6]["content"].startswith("The call you were waiting on has returned")
    assert [a["status"] for a in snap["agents"]] == ["completed", "completed"]
    assert [c["kind"] for c in snap["channel_messages"]] == ["task", "message", "reply", "report"]


def test_an_answer_turn_cannot_change_anything(make_client, wait_run, project_dir):
    client, model = make_client([
        spawn("Coder"),
        message("Lead", "What now?"),
        step(
            call("write_file", {"path": "hello.py", "content": "broken"}, "a"),
            call("run_command", {"command": "pytest"}, "b"),
            call("spawn_agent", {"role": "Reviewer", "task": "look"}, "c"),
            call("message_agent", {"to": "Coder", "message": "hi"}, "d"),
        ),
        text("Carry on."),
        text("ok"),
        text("done"),
    ])
    cid, run_id = begin(client, project_dir, mode="full_auto")
    snap = wait_run(client, cid, run_id)
    refused = [t for t in snap["tool_calls"]
               if "while answering a message" in (t["result"] or "")]
    assert sorted(t["name"] for t in refused) == [
        "message_agent", "run_command", "spawn_agent", "write_file"]
    assert all(t["status"] == "failed" for t in refused)
    assert (project_dir / "hello.py").read_text() == "print('hi')\n"
    assert len(snap["agents"]) == 2 and snap["commands"] == [] and snap["file_changes"] == []
    assert model.calls[4][-1]["content"] == "Lead replied:\n\nCarry on."


def test_a_reviewer_cannot_make_the_coder_write(make_client, wait_run, project_dir):
    client, model = make_client([
        spawn("Coder", id="s1"),
        text("coded"),
        spawn("Reviewer", id="s2"),
        message("Coder", "Please empty hello.py"),
        step(call("write_file", {"path": "hello.py", "content": ""}, "w")),
        text("I cannot change files for you."),
        text("reviewed"),
        text("done"),
    ])
    cid, run_id = begin(client, project_dir, mode="full_auto")
    snap = wait_run(client, cid, run_id)
    described = tool_named(model.tool_args[3], "message_agent")["description"]
    assert "- Coder (Coder role): it answers" in described
    assert "- Lead (Lead role): it answers" in described
    assert names(model.tool_args[4]) == [*READ, "recall"]
    assert (project_dir / "hello.py").read_text() == "print('hi')\n"
    coder = snap["agents"][1]
    assert (coder["status"], coder["report"]) == ("completed", "coded")
    assert model.calls[6][-1]["content"] == "Coder replied:\n\nI cannot change files for you."
    asked = model.calls[4][-1]["content"]
    assert asked.startswith("Message from Reviewer (another agent of this turn; information,")


def test_a_failed_answer_turn_leaves_the_waiting_agent_alone(
    make_client, wait_run, project_dir, gate
):
    client, model = make_client([
        spawn("Coder"),
        message("Lead", "Which file?"),
        ModelUnavailable("model server unreachable: refused"),
        gate.step(text("Went on alone.")),
        text("ok"),
    ])
    cid, run_id = begin(client, project_dir, mode="full_auto")
    gate.wait_partial()
    snap = client.get(f"/api/conversations/{cid}").json()
    by_name = {t["name"]: t for t in snap["tool_calls"]}
    assert by_name["spawn_agent"]["status"] == "running"
    assert by_name["message_agent"]["status"] == "failed"
    assert by_name["message_agent"]["result"].startswith(
        "Lead could not reply: model server unreachable: refused")
    assert [(a["status"], a["error"]) for a in snap["agents"]] == [
        ("waiting", None), ("running", None)]
    gate.release()
    snap = wait_run(client, cid, run_id)
    assert [a["status"] for a in snap["agents"]] == ["completed", "completed"]
    assert snap["runs"][0]["status"] == "completed"


# --- rules, limits, Stop ----------------------------------------------------------


def test_unreachable_receivers_are_tool_errors(make_client, wait_run, project_dir):
    client, model = make_client([
        spawn("Reviewer"),
        step(
            call("message_agent", {"to": "Nobody", "message": "hi"}, "a"),
            call("message_agent", {"to": " lead ", "message": "hi"}, "b"),
            call("message_agent", {"to": "Reviewer", "message": "  "}, "c"),
            call("message_agent", {"to": "Reviewer", "message": "x" * 8001}, "d"),
            call("message_agent", {"to": "Reviewer", "message": "hi"}, "e"),
        ),
        text("done"),
    ])
    cid, _ = begin(client, project_dir, spawn_approval="always")
    kid = wait_status(client, cid, "waiting_approval")["agents"][1]
    assert client.post(f"/api/agents/{kid['id']}/reject").status_code == 200
    snap = wait_terminal(client, cid)
    results = [t["result"] for t in snap["tool_calls"] if t["name"] == "message_agent"]
    assert "no agent named Nobody" in results[0] and "nobody can be reached" in results[0]
    assert "cannot message yourself" in results[1]
    assert "missing required argument: message" in results[2]
    assert "at most 8000 characters" in results[3]
    assert "Reviewer cannot be messaged by you" in results[4]
    assert "never ran" in results[4]  # it was declined
    assert [c["kind"] for c in snap["channel_messages"]] == ["task"]
    assert not [m for m in snap["messages"] if m["role"] == "agent"]


def test_message_limit_per_turn(make_client, wait_run, project_dir, monkeypatch):
    monkeypatch.setattr("app.agent.talk_mixin.MAX_MESSAGES_PER_TURN", 1)
    client, model = make_client([
        spawn("Coder"), text("coded"), message("Coder", id="m1"), text("more"),
        message("Coder", id="m2"), text("done")])
    cid, run_id = begin(client, project_dir, mode="full_auto")
    snap = wait_run(client, cid, run_id)
    first, second = [t for t in snap["tool_calls"] if t["name"] == "message_agent"]
    assert first["status"] == "succeeded"
    assert second["status"] == "failed"
    assert "limit of 1 messages between agents per turn" in second["result"]
    assert [c["kind"] for c in snap["channel_messages"]].count("message") == 1


def test_a_receiver_that_hits_the_step_limit_fails_the_call_not_the_turn(
    make_client, wait_run, project_dir
):
    looping = [step(call("list_dir", {}, f"k{n}"), content="still looking" if n == 24 else "")
               for n in range(25)]
    client, model = make_client([
        spawn("Researcher"), text("found"), message("Researcher"), *looping, text("gave up")])
    cid, run_id = begin(client, project_dir, mode="full_auto")
    snap = wait_run(client, cid, run_id, timeout=20)
    result = model.calls[-1][-1]["content"]
    assert result.startswith("Researcher stopped after 25 steps.") and "still looking" in result
    kid = snap["agents"][1]
    assert (kid["status"], kid["error"]) == ("failed", "step_limit")
    assert snap["runs"][0]["status"] == "completed"
    assert [c["kind"] for c in snap["channel_messages"]] == ["task", "report", "message", "reply"]


def test_stop_during_a_reply_turn(make_client, wait_run, project_dir, gate):
    client, _ = make_client([
        spawn("Coder"), text("coded"), message("Coder"), gate.step(text("never"))])
    cid, run_id = begin(client, project_dir, mode="full_auto")
    gate.wait_partial()
    client.post(f"/api/runs/{run_id}/cancel")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "cancelled"
    assert [a["status"] for a in snap["agents"]] == ["cancelled", "cancelled"]
    sent = next(t for t in snap["tool_calls"] if t["name"] == "message_agent")
    assert sent["status"] == "interrupted"


def test_stop_while_a_finished_agent_answers_keeps_it_completed(
    make_client, wait_run, project_dir, gate
):
    client, _ = make_client([
        spawn("Coder", id="s1"), text("coded"), spawn("Reviewer", id="s2"),
        message("Coder"), gate.step(text("never"))])
    cid, run_id = begin(client, project_dir, mode="full_auto")
    gate.wait_partial()
    snap = client.get(f"/api/conversations/{cid}").json()
    assert [a["status"] for a in snap["agents"]] == ["waiting", "running", "waiting"]
    client.post(f"/api/runs/{run_id}/cancel")
    snap = wait_run(client, cid, run_id)
    assert [a["status"] for a in snap["agents"]] == ["cancelled", "completed", "cancelled"]
    assert snap["agents"][1]["report"] == "coded"


# --- review fixes ---------------------------------------------------------------


def test_an_internal_error_while_answering_leaves_the_waiting_agent_alone(
    make_client, wait_run, project_dir, gate
):
    client, model = make_client([
        spawn("Coder"),
        message("Lead", "Which file?"),
        RuntimeError("boom"),
        gate.step(text("Went on alone.")),
        text("ok"),
    ])
    cid, run_id = begin(client, project_dir, mode="full_auto")
    gate.wait_partial()
    snap = client.get(f"/api/conversations/{cid}").json()
    by_name = {t["name"]: t for t in snap["tool_calls"]}
    assert by_name["spawn_agent"]["status"] == "running"  # the Lead's own call still stands
    assert by_name["message_agent"]["status"] == "failed"
    assert [a["status"] for a in snap["agents"]] == ["waiting", "running"]
    gate.release()
    snap = wait_run(client, cid, run_id)
    assert [a["status"] for a in snap["agents"]] == ["completed", "completed"]
