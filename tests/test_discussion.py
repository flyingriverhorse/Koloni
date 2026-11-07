"""A discussion: several agents talk about one topic in a shared place, in rounds."""

import json
import sqlite3

from alembic import command

from app.model_client import ModelUnavailable
from app.tools import ToolError
from tests.conftest import Gate
from tests.test_chat_flow import text
from tests.test_migration_0002 import _config
from tests.test_parallel import now_snap, statuses, until
from tests.test_spawn import begin, call, names, step


def discuss(topic, who, rounds=None, id="d1"):
    args = {"topic": topic, "with": who}
    if rounds is not None:
        args["rounds"] = rounds
    return step(call("discuss", args, id))


def spawn(role, id):
    return call("spawn_agent", {"role": role, "task": f"be the {role}"}, id)


TWO = step(spawn("Coder", "s1"), spawn("Reviewer", "s2"))


def said(snap):
    by = {a["id"]: a["name"] for a in snap["agents"]}
    return [(p["round"], by.get(p["agent_id"], "You"), p["content"], p["passed"])
            for p in snap["discussion_posts"]]


def prompt_of(calls):
    """The shared-place prompt a speaker was given: the last user message of its request."""
    return [m for m in calls if m["role"] == "user"][-1]["content"]


# --- the migration and the tool ---------------------------------------------------


def test_migration_0010_and_back(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0009")
    at = "2026-10-05 10:00:00"
    with sqlite3.connect(db) as conn:
        for id, name, tools, builtin in (("b1", "Lead", ["read_file"], 1),
                                         ("b2", "Coder", ["read_file"], 1),
                                         ("u1", "Mine", ["read_file"], 0)):
            conn.execute(
                "INSERT INTO roles (id, name, description, instructions, tools, builtin, "
                "created_by_agent, created_at, updated_at) VALUES (?, ?, '', '', ?, ?, 0, ?, ?)",
                (id, name, json.dumps(tools), builtin, at, at))
    command.upgrade(cfg, "0010")
    with sqlite3.connect(db) as conn:
        tools = {n: json.loads(t) for n, t in conn.execute("SELECT name, tools FROM roles")}
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
    assert tools == {"Lead": ["read_file", "discuss"], "Coder": ["read_file"],
                     "Mine": ["read_file"]}
    assert {"discussions", "discussion_members", "discussion_posts"} <= tables
    command.downgrade(cfg, "0009")
    with sqlite3.connect(db) as conn:
        tools = {n: json.loads(t) for n, t in conn.execute("SELECT name, tools FROM roles")}
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
        columns = [row[1] for row in conn.execute("PRAGMA table_info(messages)")]
    assert tools["Lead"] == ["read_file"]
    assert "discussions" not in tables and "discussion_id" not in columns


# --- talking in rounds --------------------------------------------------------------


def test_three_agents_talk_in_rounds_and_each_sees_what_was_said(
    make_client, wait_run, project_dir
):
    client, model = make_client({
        "Lead": [TWO, discuss("How should we fix the greeting?", ["Coder", "Reviewer"]),
                 text("I say: keep it short."),          # round 1, the Lead speaks last
                 text("PASS"),                           # round 2
                 text("We agreed. Done.")],              # after the discussion
        "Coder": [text("coder ready"), text("Change the string."), text("PASS")],
        "Reviewer": [text("reviewer ready"), text("Add a test too."), text("pass.")],
    })
    cid, run_id = begin(client, project_dir, mode="full_auto")
    snap = wait_run(client, cid, run_id)

    assert said(snap) == [
        (1, "Coder", "Change the string.", False),
        (1, "Reviewer", "Add a test too.", False),
        (1, "Lead", "I say: keep it short.", False),
        (2, "Coder", "PASS", True),
        (2, "Reviewer", "pass.", True),
        (2, "Lead", "PASS", True),
    ]
    talk = snap["discussions"][0]
    assert (talk["status"], talk["outcome"], talk["round"]) == ("ended", "agreed", 2)
    assert talk["topic"] == "How should we fix the greeting?"
    assert [m["status"] for m in talk["members"]] == ["in", "in", "in"]

    # each speaker was given the topic and everything said before it, and only reading tools
    first = prompt_of(model.calls_of["Coder"][1])
    assert "How should we fix the greeting?" in first and "(nothing yet)" in first
    assert "Reviewer, Lead" in first  # who it is talking with
    second = prompt_of(model.calls_of["Reviewer"][1])
    assert "Coder: Change the string." in second and "It is your turn" in second
    third = prompt_of(model.calls_of["Lead"][2])
    assert "Coder: Change the string.\n\nReviewer: Add a test too." in third
    speaking = [t for t in model.tool_args if t is not None and "discuss" not in names(t)
                and "spawn_agent" not in names(t) and "ask_user" not in names(t)]
    assert speaking and all(
        names(t) == ["list_dir", "read_file", "search", "recall"] for t in speaking)

    # the one who opened it gets the whole of it back, and goes on with its work
    back = [m for m in model.calls_of["Lead"][-1] if m["role"] == "tool"][-1]["content"]
    assert back.startswith("The discussion ended: nobody had anything to add.")
    assert "Round 1\nCoder: Change the string." in back and "Lead: I say: keep it short." in back
    assert set(statuses(snap).values()) == {"completed"}
    assert snap["runs"][0]["status"] == "completed"


def test_what_was_said_stays_out_of_the_chat_and_in_each_members_memory(
    make_client, wait_run, project_dir
):
    client, model = make_client({
        "Lead": [TWO, discuss("Tabs or spaces?", ["Coder", "Reviewer"], rounds=1),
                 text("Spaces."),
                 step(call("message_agent", {"to": "Coder", "message": "Go on then."}, "m1")),
                 text("done")],
        "Coder": [text("coder ready"), text("Tabs."), text("On it.")],
        "Reviewer": [text("reviewer ready"), text("Spaces.")],
    })
    cid, run_id = begin(client, project_dir, mode="full_auto")
    snap = wait_run(client, cid, run_id)
    assert snap["discussions"][0]["outcome"] == "round_limit"
    spoken = [m for m in snap["messages"] if m["discussion_id"]]
    assert sorted(m["content"] for m in spoken) == ["Spaces.", "Spaces.", "Tabs."]
    # carried on afterwards, the Coder knows what was discussed, as one block
    later = model.calls_of["Coder"][2]
    roles = [m["role"] for m in later]
    assert roles == ["system", "user", "assistant", "user", "user"]
    assert later[3]["content"].startswith("Message from Lead (the agent you work for):\n\n"
                                          "The discussion \"Tabs or spaces?\" ended")
    assert "Coder: Tabs.\n\nReviewer: Spaces.\n\nLead: Spaces." in later[3]["content"]
    assert later[4]["content"].endswith("Go on then.")
    # the Lead's own speech is not replayed to it as something it said in the chat
    last = model.calls_of["Lead"][-1]
    assert [m["content"] for m in last if m["role"] == "assistant" and m["content"]] == []


def test_a_role_name_opens_a_new_agent_for_the_discussion(make_client, wait_run, project_dir):
    client, model = make_client({
        "Lead": [discuss("Is hello.py fine?", ["reviewer", "Researcher"], rounds=1),
                 text("Fine by me."), text("done")],
        "Reviewer": [text("Looks fine.")],
        "Researcher": [text("It prints hi.")],
    })
    cid, run_id = begin(client, project_dir)
    snap = wait_run(client, cid, run_id)
    assert [(a["name"], a["status"], a["depth"]) for a in snap["agents"]] == [
        ("Lead", "completed", 0), ("Reviewer", "completed", 1), ("Researcher", "completed", 1)]
    assert snap["agents"][1]["task"] == "Is hello.py fine?"
    assert snap["agents"][1]["report"] == "Looks fine."
    assert [m["opened_here"] for m in snap["discussions"][0]["members"]] == [True, True, False]
    assert [p[1:3] for p in said(snap)] == [
        ("Reviewer", "Looks fine."), ("Researcher", "It prints hi."), ("Lead", "Fine by me.")]


# --- nobody changes anything while talking ------------------------------------------


def test_a_speaker_cannot_change_anything(make_client, wait_run, project_dir):
    client, model = make_client({
        "Lead": [TWO, discuss("What now?", ["Coder"], rounds=1), text("ok"), text("done")],
        "Coder": [text("coder ready"),
                  step(call("write_file", {"path": "hello.py", "content": "broken"}, "a"),
                       call("run_command", {"command": "pytest"}, "b"),
                       call("spawn_agent", {"role": "Tester", "task": "t"}, "c"),
                       call("message_agent", {"to": "Reviewer", "message": "psst"}, "d"),
                       call("discuss", {"topic": "another", "with": ["Reviewer"]}, "e"),
                       call("read_file", {"path": "hello.py"}, "f")),
                  text("I read it: it prints hi.")],
        "Reviewer": [text("reviewer ready")],
    })
    cid, run_id = begin(client, project_dir, mode="full_auto")
    snap = wait_run(client, cid, run_id)
    tried = {t["name"]: t for t in snap["tool_calls"]
             if t["agent_id"] == snap["agents"][1]["id"]}
    for name in ("write_file", "run_command", "spawn_agent", "message_agent", "discuss"):
        assert tried[name]["status"] == "failed", name
        assert "while you are in a discussion" in tried[name]["result"], name
    assert tried["read_file"]["status"] == "succeeded"
    assert (project_dir / "hello.py").read_text() == "print('hi')\n"
    assert snap["file_changes"] == [] and snap["commands"] == [] and len(snap["agents"]) == 3
    assert said(snap)[0] == (1, "Coder", "I read it: it prints hi.", False)


# --- who can be invited, and what goes wrong -------------------------------------------


def test_bad_invitations_are_tool_errors(make_client, wait_run, project_dir):
    client, model = make_client({
        "Lead": [step(
            call("discuss", {"topic": "x", "with": ["Nobody"]}, "a"),
            call("discuss", {"topic": "x", "with": []}, "b"),
            call("discuss", {"topic": " ", "with": ["Reviewer"]}, "c"),
            call("discuss", {"topic": "x", "with": ["Lead"]}, "d"),
            call("discuss", {"topic": "x", "with": ["Reviewer"], "rounds": 21}, "e"),
            call("discuss", {"topic": "x", "with": ["Coder"]}, "f"),
        ), text("done")],
    })
    cid, run_id = begin(client, project_dir)  # ask mode: a Coder would need approval
    snap = wait_run(client, cid, run_id)
    results = [t["result"] for t in snap["tool_calls"]]
    assert "Nobody is neither an agent of this turn nor a role" in results[0]
    assert "name 1 to 5" in results[1]
    assert "missing required argument: topic" in results[2]
    assert "you take part yourself" in results[3]
    assert "1 to 20 rounds" in results[4]
    assert "open it with spawn_agent first" in results[5]
    assert snap["discussions"] == [] and len(snap["agents"]) == 1


def test_a_member_whose_model_fails_leaves_and_the_rest_go_on(
    make_client, wait_run, project_dir
):
    client, model = make_client({
        "Lead": [TWO, discuss("Go?", ["Coder", "Reviewer"], rounds=2),
                 text("Go."), text("PASS"), text("done")],
        "Coder": [text("coder ready"), ModelUnavailable("model server unreachable: refused")],
        "Reviewer": [text("reviewer ready"), text("Go."), text("PASS")],
    })
    cid, run_id = begin(client, project_dir, mode="full_auto")
    snap = wait_run(client, cid, run_id)
    talk = snap["discussions"][0]
    assert [m["status"] for m in talk["members"]] == ["left", "in", "in"]
    assert (talk["status"], talk["outcome"]) == ("ended", "agreed")
    back = [m for m in model.calls_of["Lead"][-1] if m["role"] == "tool"][-1]["content"]
    assert "Coder left the discussion: model server unreachable: refused" in back
    # leaving a discussion is not failing at its own work
    assert statuses(snap)["Coder"] == "completed"
    assert snap["agents"][1]["report"] == "coder ready"


def test_with_too_few_left_the_discussion_ends(make_client, wait_run, project_dir):
    client, model = make_client({
        "Lead": [TWO, discuss("Go?", ["Coder"], rounds=3), text("done")],
        "Coder": [text("coder ready"), ModelUnavailable("down")],
        "Reviewer": [text("reviewer ready")],
    })
    cid, run_id = begin(client, project_dir, mode="full_auto")
    snap = wait_run(client, cid, run_id)
    assert snap["discussions"][0]["outcome"] == "too_few"
    assert snap["tool_calls"][-1]["status"] == "succeeded"
    assert "fewer than two were left to talk" in snap["tool_calls"][-1]["result"]


def test_stop_during_a_discussion(make_client, wait_run, project_dir):
    g = Gate()
    client, model = make_client({
        "Lead": [TWO, discuss("Go?", ["Coder", "Reviewer"])],
        "Coder": [text("coder ready"), text("Yes.")],
        "Reviewer": [text("reviewer ready"), g.step(text("never"))],
    })
    cid, run_id = begin(client, project_dir, mode="full_auto")
    g.wait_partial()
    snap = now_snap(client, cid)
    assert snap["discussions"][0]["status"] == "running"
    assert statuses(snap) == {"Lead": "waiting", "Coder": "completed", "Reviewer": "running"}
    client.post(f"/api/runs/{run_id}/cancel")
    snap = wait_run(client, cid, run_id)
    assert snap["discussions"][0]["status"] == "cancelled"
    # the Reviewer had finished its own work; being cut off mid-sentence does not undo that
    assert statuses(snap) == {"Lead": "cancelled", "Coder": "completed", "Reviewer": "completed"}
    assert [p[1:3] for p in said(snap)] == [("Coder", "Yes.")]


# --- the user in the shared place ----------------------------------------------------


def test_the_user_speaks_and_the_next_speaker_hears_it(make_client, wait_run, project_dir):
    g = Gate()
    client, model = make_client({
        "Lead": [TWO, discuss("Go?", ["Coder", "Reviewer"], rounds=2),
                 text("PASS"), text("PASS"), text("done")],
        "Coder": [text("coder ready"), g.step(text("PASS")), text("Tests first then.")],
        "Reviewer": [text("reviewer ready"), text("PASS"), text("PASS")],
    })
    cid, run_id = begin(client, project_dir, mode="full_auto")
    g.wait_partial()
    talk = now_snap(client, cid)["discussions"][0]
    posted = client.post(f"/api/discussions/{talk['id']}/posts", json={"content": "Tests first!"})
    assert posted.status_code == 201, posted.text
    assert client.post(f"/api/discussions/{talk['id']}/posts",
                       json={"content": "  "}).status_code == 422
    g.release()
    snap = wait_run(client, cid, run_id)
    assert "You: Tests first!" in prompt_of(model.calls_of["Reviewer"][1])
    # everyone passed in round 1, but something new had been said: it went on
    assert snap["discussions"][0]["round"] == 2
    assert (1, "You", "Tests first!", False) in said(snap)
    assert (2, "Coder", "Tests first then.", False) in said(snap)
    assert client.post(f"/api/discussions/{talk['id']}/posts",
                       json={"content": "late"}).status_code == 409


def test_the_user_ends_a_discussion_and_the_caller_goes_on(make_client, wait_run, project_dir):
    g = Gate()
    client, model = make_client({
        "Lead": [TWO, discuss("Go?", ["Coder", "Reviewer"]), text("Carrying on.")],
        "Coder": [text("coder ready"), text("Yes.")],
        "Reviewer": [text("reviewer ready"), g.step(text("never said"))],
    })
    cid, run_id = begin(client, project_dir, mode="full_auto")
    g.wait_partial()
    talk = now_snap(client, cid)["discussions"][0]
    assert client.post(f"/api/discussions/{talk['id']}/end").status_code == 200
    snap = wait_run(client, cid, run_id)
    assert (snap["discussions"][0]["status"], snap["discussions"][0]["outcome"]) == (
        "ended", "ended_by_user")
    assert [p[1:3] for p in said(snap)] == [("Coder", "Yes.")]
    back = [m for m in model.calls_of["Lead"][-1] if m["role"] == "tool"][-1]["content"]
    assert back.startswith("The discussion ended: the user ended it.")
    assert set(statuses(snap).values()) == {"completed"}
    assert client.post(f"/api/discussions/{talk['id']}/end").status_code == 409



# --- review fixes -------------------------------------------------------------------


def test_an_agent_carrying_on_can_open_a_discussion_and_the_user_can_end_it(
    make_client, wait_run, project_dir
):
    g = Gate()
    client, model = make_client({
        "Lead": [step(spawn("Planner", "s1"), spawn("Reviewer", "s2")),
                 step(call("message_agent", {"to": "Planner", "message": "Discuss it."}, "m1")),
                 text("done")],
        "Planner": [text("planner ready"),
                    discuss("Go?", ["Reviewer"], rounds=2),
                    text("I think yes."),        # its own speech, in the turn it was given
                    g.step(text("never said")),  # round 2: cut off by the user
                    text("Discussed.")],
        "Reviewer": [text("reviewer ready"), text("Yes."), text("PASS")],
    })
    cid, run_id = begin(client, project_dir, mode="full_auto")
    g.wait_partial()  # it used to hang before the Planner's first speech
    snap = now_snap(client, cid)
    assert [p[1:3] for p in said(snap)] == [
        ("Reviewer", "Yes."), ("Planner", "I think yes."), ("Reviewer", "PASS")]
    talk = snap["discussions"][0]
    assert client.post(f"/api/discussions/{talk['id']}/end").status_code == 200
    snap = wait_run(client, cid, run_id)
    assert snap["discussions"][0]["outcome"] == "ended_by_user"
    assert set(statuses(snap).values()) == {"completed"}
    assert snap["agents"][1]["report"] == "Discussed."


def test_a_member_that_went_back_to_its_work_leaves_the_discussion(
    make_client, wait_run, project_dir
):
    opening, speaking, working, r = Gate(), Gate(), Gate(), Gate()
    client, model = make_client({
        "Lead": [step(spawn("Planner", "s1"), spawn("Coder", "s2")), text("done")],
        # The Coder is invited while it waits for its own Reviewer.
        "Coder": [step(call("spawn_agent", {"role": "Reviewer", "task": "look"}, "s3")),
                  text("I am in."),               # round 1
                  working.step(text("coded"))],    # its own work, taken up again
        "Reviewer": [r.step(text("looked"))],
        "Planner": [opening.step(discuss("Go?", ["Coder"], rounds=2)),
                    speaking.step(text("Fine.")),  # round 1, held while the Coder resumes
                    text("Planned.")],
    })
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_max_parallel=4)
    r.wait_partial()         # the Coder waits for its Reviewer
    opening.release()
    speaking.wait_partial()  # the Coder has spoken in round 1
    r.release()              # its Reviewer is back: the Coder goes on with its own work
    working.wait_partial()
    speaking.release()
    snap = until(client, cid, lambda s: s["discussions"][0]["status"] == "ended")
    # round 2 found the Coder at work: it did not speak again, and never ran twice at once
    assert [p[1:3] for p in said(snap) if p[1] == "Coder"][0] == ("Coder", "I am in.")
    left = [p for p in snap["discussion_posts"] if p["kind"] == "left"]
    assert len(left) == 1 and "its own work" in left[0]["content"]
    assert snap["discussions"][0]["outcome"] == "too_few"
    assert len(model.calls_of["Coder"]) == 3
    working.release()
    snap = wait_run(client, cid, run_id)
    assert set(statuses(snap).values()) == {"completed"}
    assert snap["agents"][2]["report"] == "coded"


def test_a_long_speech_is_cut_to_fit_the_shared_place(make_client, wait_run, project_dir):
    client, model = make_client({
        "Lead": [TWO, discuss("Go?", ["Coder"], rounds=1), text("ok"), text("done")],
        "Coder": [text("coder ready"), text("x" * 5000)],
        "Reviewer": [text("reviewer ready")],
    })
    cid, run_id = begin(client, project_dir, mode="full_auto")
    snap = wait_run(client, cid, run_id)
    post = snap["discussion_posts"][0]
    assert len(post["content"]) < 1600 and post["content"].endswith("[the rest was cut]")
    talk = snap["discussions"][0]
    assert client.post(f"/api/discussions/{talk['id']}/posts",
                       json={"content": "y" * 1501}).status_code == 422


def test_a_new_member_that_never_got_to_speak_is_not_called_done(
    make_client, wait_run, project_dir
):
    client, model = make_client({
        "Lead": [discuss("Go?", ["Reviewer", "Researcher"], rounds=1), text("ok"), text("done")],
        "Reviewer": [ModelUnavailable("model server unreachable: refused")],
        "Researcher": [text("Yes.")],
    })
    cid, run_id = begin(client, project_dir)
    snap = wait_run(client, cid, run_id)
    reviewer = snap["agents"][1]
    assert (reviewer["status"], reviewer["report"]) == ("failed", None)
    assert "refused" in reviewer["error"]
    assert snap["agents"][2]["status"] == "completed"


def test_what_a_failed_agent_said_in_a_discussion_is_not_its_report(
    make_client, wait_run, project_dir
):
    client, model = make_client({
        "Lead": [step(spawn("Planner", "s1")), text("done")],
        "Planner": [discuss("Go?", ["Reviewer"], rounds=1), text("My view."),
                    ModelUnavailable("model server unreachable: refused")],
        "Reviewer": [text("Yes.")],
    })
    cid, run_id = begin(client, project_dir, mode="full_auto")
    snap = wait_run(client, cid, run_id)
    planner = snap["agents"][1]
    assert planner["status"] == "failed"
    assert planner["report"] is None  # "My view." was said to the discussion, not reported
    back = [m for m in model.calls_of["Lead"][-1] if m["role"] == "tool"][-1]["content"]
    assert "My view." not in back


def test_restart_closes_a_discussion_and_keeps_finished_members_finished(tmp_path):
    from datetime import UTC, datetime

    from app.agent import recover_interrupted
    from app.db.models import Agent, Conversation, Discussion, DiscussionMember, Project, Run
    from app.db.session import make_engine, make_session_factory, upgrade_db

    db = tmp_path / "r.db"
    upgrade_db(db)
    factory = make_session_factory(make_engine(db))
    done = datetime(2026, 10, 5, 10, 0, 0, tzinfo=UTC)
    with factory() as s:
        s.add(Project(id="p", name="p", root_path=str(tmp_path)))
        s.flush()
        s.add(Conversation(id="c", project_id="p"))
        s.flush()
        s.add(Run(id="r", conversation_id="c", status="running"))
        s.flush()
        s.add_all([
            Agent(id="lead", run_id="r", role_name="Lead", name="Lead", tools=[], status="waiting"),
            # had finished its own work, and was speaking when the server died
            Agent(id="old", run_id="r", parent_agent_id="lead", role_name="Coder", name="Coder",
                  tools=[], depth=1, status="running", report="coded", ended_at=done),
            # opened for the discussion, waiting for its turn
            Agent(id="new", run_id="r", parent_agent_id="lead", role_name="Reviewer",
                  name="Reviewer", tools=[], depth=1, status="waiting"),
        ])
        s.flush()
        s.add(Discussion(id="d", run_id="r", agent_id="lead", tool_call_id="t", topic="x",
                         max_rounds=3, round=1))
        s.flush()
        s.add_all([
            DiscussionMember(discussion_id="d", agent_id="old", position=0),
            DiscussionMember(discussion_id="d", agent_id="new", position=1, opened_here=True),
            DiscussionMember(discussion_id="d", agent_id="lead", position=2),
        ])
        s.commit()
    recover_interrupted(factory)
    with factory() as s:
        talk = s.get(Discussion, "d")
        assert (talk.status, talk.outcome) == ("interrupted", None) and talk.ended_at is not None
        assert {a.id: a.status for a in s.query(Agent)} == {
            "lead": "interrupted", "old": "completed", "new": "interrupted"}
        assert s.get(Agent, "old").report == "coded"


def test_a_discussion_that_breaks_leaves_none_it_opened_waiting(make_client, wait_run, project_dir):
    # (Review of B-376: a member left "waiting" would hold the Lead's answer for good.)
    client, _model = make_client({
        "Lead": [discuss("Is hello.py fine?", ["reviewer", "Researcher"], rounds=1), text("done")],
    })
    runner = client.app.state.runner

    async def breaks(member, discussion_id, ending):
        raise ToolError("a speech that could not be had")

    runner._speak = breaks
    cid, run_id = begin(client, project_dir)
    snap = wait_run(client, cid, run_id)
    assert [(a["name"], a["status"]) for a in snap["agents"][1:]] == [
        ("Reviewer", "failed"), ("Researcher", "failed")]
