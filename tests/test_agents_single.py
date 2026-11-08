"""A turn is carried by an agent record, even when there is only one agent."""

import json
import sqlite3

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from app.db.models import Base, in_the_models
from app.db.session import make_engine
from app.model_client import ModelUnavailable, StepResult, ToolCallRequest
from app.roles import ALL_TOOLS
from tests.fakes import Script, ScriptedExecutor
from tests.test_chat_flow import start, start_in_mode, text
from tests.test_migration_0002 import _config


def call(name, args, id="c1"):
    return ToolCallRequest(id, name, json.dumps(args))


def test_a_plain_turn_has_one_lead_agent_that_owns_its_records(make_client, wait_run, project_dir):
    executor = ScriptedExecutor([Script(["ok\n"])])
    client, _ = make_client([
        StepResult("", [call("read_file", {"path": "hello.py"}, "a"),
                        call("write_file", {"path": "n.txt", "content": "x"}, "b"),
                        call("run_command", {"command": "pytest"}, "c")], 10, 4),
        text("Done.", 30, 5)], executor=executor)
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    snap = wait_run(client, cid, run_id)

    assert len(snap["agents"]) == 1
    agent = snap["agents"][0]
    assert (agent["role_name"], agent["status"], agent["depth"]) == ("Lead", "completed", 0)
    assert agent["parent_agent_id"] is None and agent["task"] is None
    # (all but notify: the project has no notification address)
    assert agent["tools"] == [tool for tool in ALL_TOOLS if tool != "notify"]
    assert (agent["input_tokens"], agent["output_tokens"]) == (30, 9)
    assert agent["started_at"] and agent["ended_at"] and agent["run_id"] == run_id

    user, *assistant, landed = snap["messages"]
    assert user["agent_id"] is None  # the user's own message belongs to no agent
    assert (landed["role"], landed["agent_id"]) == ("landed", None)  # KOLONİ's own (B-205)
    assert {m["agent_id"] for m in assistant} == {agent["id"]}
    assert {t["agent_id"] for t in snap["tool_calls"]} == {agent["id"]}
    assert snap["commands"][0]["agent_id"] == agent["id"]
    assert snap["file_changes"][0]["agent_id"] == agent["id"]
    assert snap["channel_messages"] == []
    conversation = snap["conversation"]
    assert (conversation["spawn_approval"], conversation["spawn_max_depth"],
            conversation["spawn_max_agents"]) == ("auto", 2, 6)


def test_agent_events_tell_its_life(make_client, wait_run, project_dir):
    client, _ = make_client([text("Hi")])
    cid, run_id = start(client, project_dir)
    wait_run(client, cid, run_id)
    with client.stream("GET", f"/api/conversations/{cid}/events?after=0&once=1") as r:
        frames = r.read().decode().split("\n\n")
    kinds = [f.split("event: ", 1)[1].split("\n", 1)[0] for f in frames if "event: " in f]
    replies = [i for i, kind in enumerate(kinds) if kind == "message.created"][1:]
    assert kinds.index("agent.created") < replies[0] < kinds.index("run.finished")
    updates = [json.loads(f.split("data: ", 1)[1]) for f in frames if "event: agent.updated" in f]
    assert updates[-1]["status"] == "completed"


def test_the_agent_ends_the_way_its_turn_does(make_client, wait_run, project_dir, gate):
    client, _ = make_client([ModelUnavailable("model server unreachable: refused")])
    cid, run_id = start(client, project_dir)
    agent = wait_run(client, cid, run_id)["agents"][0]
    assert agent["status"] == "failed" and "refused" in agent["error"]

    client, _ = make_client([gate.step(text("never"))])
    cid, run_id = start(client, project_dir)
    client.post(f"/api/runs/{run_id}/cancel")
    assert wait_run(client, cid, run_id)["agents"][0]["status"] == "cancelled"


def test_a_queued_turn_has_no_agent_until_it_starts(make_client, wait_run, project_dir, gate):
    client, _ = make_client([gate.step(text("one")), text("two")])
    cid, run_id = start(client, project_dir)
    queued = client.post(f"/api/conversations/{cid}/messages", json={"content": "next"}).json()
    assert len(client.get(f"/api/conversations/{cid}").json()["agents"]) == 1
    gate.release()
    snap = wait_run(client, cid, queued["run"]["id"])
    assert [a["status"] for a in snap["agents"]] == ["completed", "completed"]


def test_a_tool_the_role_lacks_is_neither_offered_nor_run(make_client, wait_run, project_dir):
    client, model = make_client([
        StepResult("", [call("run_command", {"command": "rm -rf ."})], 1, 1), text("ok")],
        executor=ScriptedExecutor([]))
    lead = next(r for r in client.get("/api/roles").json() if r["name"] == "Lead")
    client.patch(f"/api/roles/{lead['id']}", json={"tools": ["read_file", "list_dir", "search"]})
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    snap = wait_run(client, cid, run_id)
    # (show is no tool of a role's: every agent at its own work may put a file before the user)
    assert [t["function"]["name"] for t in model.tool_args[0]] == [
        "list_dir", "read_file", "search", "show", "recall_output"]
    assert snap["agents"][0]["tools"] == ["list_dir", "read_file", "search"]
    assert snap["tool_calls"][0]["status"] == "failed"
    assert "run_command is not available to the Lead role" in snap["tool_calls"][0]["result"]
    assert snap["commands"] == []


def test_slice_2_data_is_carried_onto_lead_agents(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0002")
    at = "2026-10-05 10:00:00"
    with sqlite3.connect(db) as conn:
        conn.execute(f"INSERT INTO projects (id, name, root_path, created_at, exec_location, "
                     f"docker_network) VALUES ('p', 'p', 'C:/p', '{at}', 'host', 0)")
        conn.execute(f"INSERT INTO conversations (id, project_id, title, permission_mode, "
                     f"created_at, updated_at) VALUES ('c', 'p', 't', 'ask', '{at}', '{at}')")
        for run_id, status, started in (("r1", "completed", f"'{at}'"), ("r2", "failed", f"'{at}'"),
                                        ("r3", "queued", "NULL")):
            conn.execute(
                f"INSERT INTO runs (id, conversation_id, status, input_tokens, output_tokens, "
                f"created_at, started_at) VALUES ('{run_id}', 'c', '{status}', 12, 3, '{at}', {started})")
            conn.execute(f"INSERT INTO messages (id, conversation_id, run_id, role, content, status, "
                         f"created_at) VALUES ('u{run_id}', 'c', '{run_id}', 'user', 'hi', 'complete', '{at}')")
        conn.execute(f"INSERT INTO messages (id, conversation_id, run_id, role, content, status, "
                     f"created_at) VALUES ('a1', 'c', 'r1', 'assistant', 'yo', 'complete', '{at}')")
        conn.execute("INSERT INTO tool_calls (id, run_id, message_id, seq, provider_call_id, name, "
                     "arguments, status) VALUES ('t1', 'r1', 'a1', 1, 'x', 'run_command', '{}', 'succeeded')")
        conn.execute(f"INSERT INTO commands (id, run_id, tool_call_id, command, cwd, location, status, "
                     f"output, output_truncated, timeout_seconds, created_at) "
                     f"VALUES ('k1', 'r1', 't1', 'ls', '.', 'host', 'exited', '', 0, 120, '{at}')")
        conn.execute(f"INSERT INTO file_changes (id, run_id, tool_call_id, path, kind, after_content, "
                     f"after_sha, status, created_at) VALUES ('f1', 'r1', 't1', 'a', 'create', 'x', "
                     f"'0', 'applied', '{at}')")

    command.upgrade(cfg, "head")

    with sqlite3.connect(db) as conn:
        agents = {row[0]: row[1:] for row in conn.execute(
            "SELECT run_id, id, role_name, depth, status, input_tokens, parent_agent_id FROM agents")}
        lead_tools = json.loads(conn.execute("SELECT tools FROM agents").fetchone()[0])
        owner = dict(conn.execute("SELECT id, agent_id FROM messages"))
        others = [conn.execute(f"SELECT agent_id FROM {table}").fetchone()[0]
                  for table in ("tool_calls", "commands", "file_changes")]
        spawn = conn.execute(
            "SELECT spawn_approval, spawn_max_depth, spawn_max_agents FROM conversations").fetchone()
    assert set(agents) == {"r1", "r2"}  # a turn that never started has no agent
    lead = agents["r1"]
    assert lead[1:] == ("Lead", 0, "completed", 12, None)
    assert agents["r2"][3] == "failed"
    assert owner == {"ur1": None, "ur2": None, "ur3": None, "a1": lead[0]}
    assert others == [lead[0]] * 3
    assert spawn == ("auto", 2, 6)
    # an old turn's agent had the six tools of its day, not the ones added since
    assert lead_tools == ["list_dir", "read_file", "search", "write_file", "edit_file", "run_command"]
    with make_engine(db).connect() as conn:
        assert compare_metadata(MigrationContext.configure(conn, opts={"include_name": in_the_models}), Base.metadata) == []

    # and back: the slice 2 rows are all still there
    command.downgrade(cfg, "0002")
    with sqlite3.connect(db) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        counts = [conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                  for table in ("runs", "messages", "tool_calls", "commands", "file_changes")]
    assert not {"agents", "roles", "channel_messages"} & tables
    assert counts == [3, 4, 1, 1, 1]


def test_a_restart_closes_agents_left_open(tmp_path):
    from app.agent import recover_interrupted
    from app.db.models import Agent
    from app.db.session import make_session_factory, upgrade_db
    from tests.test_recovery import seed

    db = tmp_path / "r.db"
    upgrade_db(db)
    factory = make_session_factory(make_engine(db))
    seed(factory, tmp_path)
    with factory() as s:
        s.add(Agent(id="kid", run_id="r1", parent_agent_id="a", role_name="Tester", tools=[],
                    task="t", depth=1, status="proposed"))
        s.add(Agent(id="done", run_id="r3", role_name="Lead", tools=[], status="completed"))
        s.commit()

    recover_interrupted(factory)

    with factory() as s:
        assert {a.id: a.status for a in s.query(Agent)} == {
            "a": "interrupted", "kid": "rejected", "done": "completed"}
        assert s.get(Agent, "a").ended_at is not None
