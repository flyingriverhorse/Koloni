"""A room an agent opens (slice 29b-2), beyond its acceptance set (`test_room_open_scenarios`):
what an open_room call is checked for, one invited once the work has started, the opener's
waits as the file claims see them, what an unopened room leaves, a room a sub-agent opens,
and the migration.
"""

import asyncio
import sqlite3
from types import SimpleNamespace

import pytest
from alembic import command as alembic

from app import room as rooms
from app.agent.rooms_mixin import RoomsMixin
from app.tools import ToolError
from tests.conftest import Gate
from tests.test_chat_flow import text
from tests.test_claim_scenarios import calls, waits, write
from tests.test_claims import snapshot, spawn, two_conversations
from tests.test_claims import start as go
from tests.test_migration_0002 import _config
from tests.test_parallel import until
from tests.test_room_open_scenarios import begin, calls_of, open_room
from tests.test_room_scenarios import LONG, ORIGIN, add, edit, finish, posts, take, wait
from tests.test_spawn import call, step

AT = "'2026-10-16 10:00:00'"


@pytest.mark.parametrize("args,said", [
    ({"with": ["Coder", "Reviewer"]}, "goal"),
    ({"goal": "g", "with": "Coder"}, "list of roles"),
    ({"goal": "g", "with": ["Coder", " "]}, "list of roles"),
    ({"goal": "g", "with": ["Coder"] * 7}, "2 to 6 members"),
    ({"goal": "g", "with": ["Coder", "Tester"], "budget": {"posts": 0}}, "above 0"),
    ({"goal": "g", "with": ["Coder", "Tester"], "budget": {"posts": True}}, "whole number"),
    ({"goal": "g", "with": ["Coder", "Tester"], "budget": {"hours": 2}}, "budget"),
])
def test_what_an_open_room_call_is_refused_for(args, said):
    with pytest.raises(ToolError, match=said):
        rooms.plan_room(args)
    assert len(rooms.plan_room({"goal": "g", "with": ["Coder"] * 6})[1]) == 6  # (six since R178)
    assert rooms.plan_room({"goal": " g ", "with": ["Coder", "Code  writer"],
                            "budget": {"posts": 5}}) == ("g", ["Coder", "Code writer"],
                                                         {"posts": 5})


def test_a_rooms_line_for_the_user_joins_its_done_items_first_lines():
    # AC: no model is asked; nothing done is no line, not an empty one
    assert rooms.summary([]) is None
    assert rooms.summary([None, " ", ""]) is None
    assert rooms.summary(["Fixed it\nwith a test", "Checked it: fine.", "Why? Who knows!"]) == (
        "Fixed it. Checked it: fine. Why? Who knows!")
    # a line that only leads into what follows, and code in a fence, are passed over
    assert rooms.summary(["I changed:\n```python\nprint('hi')\n```\nhello.py prints hi"]) == (
        "hello.py prints hi.")
    assert rooms.summary(["Changed these:\n```\na\n```"]) == "Changed these."
    # cut short: an item's line, and the whole
    one = rooms.summary(["x" * 500])
    assert len(one) == rooms.SUMMARY_LINE_CHARS and one.endswith("…")
    assert len(rooms.summary(["y" * 300] * 5)) == rooms.SUMMARY_CHARS


def test_one_invited_once_the_work_has_started_joins_it_and_the_room_waits_for_it(
    make_client, wait_run, project_dir
):
    client, _model, cid, run_id = begin(make_client, project_dir, {
        "Lead": [open_room(), text("ok")],
        "Coder": [text("Nothing to add."),
                  step(call("invite_to_room", {"role": "Tester", "why": "run them"}, "i")),
                  wait(), text("Done.")],
        "Reviewer": [text("Nothing to add."), text("Looked: fine.")],
        "Tester": [text("Ran them: green.")]})
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    (invited,) = calls_of(snap, "Coder", "invite_to_room")
    assert invited["status"] == "succeeded", invited["result"]
    (room,) = snap["rooms"]
    assert [m["role"] for m in room["members"]] == ["Coder", "Reviewer", "Tester"]
    assert room["outcome"] == "agreed"
    assert ("done", "Tester", "Ran them: green.") in posts(snap)
    tester = next(a for a in snap["agents"] if a["name"] == "Tester")
    assert "Coder asked you in: run them" in tester["task"]
    # who opened it is on record, and the lead was given the room's record, not the turn
    lead = next(a for a in snap["agents"] if a["name"] == "Lead")
    assert room["agent_id"] == lead["id"]


def test_one_the_user_turns_down_is_not_invited_and_the_room_goes_on(
    make_client, wait_run, project_dir
):
    client, _model, cid, run_id = begin(make_client, project_dir, {
        "Lead": [open_room(), text("ok")],
        "Coder": [step(call("invite_to_room", {"role": "Tester"}, "i")), text("Done.")],
        "Reviewer": [text("Nothing to add."), text("Done.")]}, spawn_approval="always")

    def proposed(snap):
        return [a for a in snap["agents"] if a["status"] == "proposed"]

    snap = until(client, cid, lambda s: len(proposed(s)) == 2, timeout=LONG)
    for member in proposed(snap):
        assert client.post(f"/api/agents/{member['id']}/approve").status_code == 200
    snap = until(client, cid, lambda s: [a["name"] for a in proposed(s)] == ["Tester"],
                 timeout=LONG)
    assert client.post(f"/api/agents/{proposed(snap)[0]['id']}/reject").status_code == 200
    snap = wait_run(client, cid, run_id, timeout=LONG)
    (invited,) = calls_of(snap, "Coder", "invite_to_room")
    assert invited["status"] == "failed" and "turned down" in invited["result"]
    (room,) = snap["rooms"]
    assert [m["role"] for m in room["members"]] == ["Coder", "Reviewer"]
    assert room["outcome"] == "agreed"


def test_migration_0044_and_back(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    alembic.upgrade(cfg, "0043")
    with sqlite3.connect(db) as conn:
        for id, name, builtin in (("l", "Lead", 1), ("c", "Coder", 1), ("m", "Lead2", 0)):
            conn.execute("INSERT INTO roles (id, name, description, instructions, tools, builtin,"
                         f" created_by_agent, created_at, updated_at) VALUES ('{id}', '{name}', '', '',"
                         f" '[\"read_file\"]', {builtin}, 0, {AT}, {AT})")
    alembic.upgrade(cfg, "0044")
    with sqlite3.connect(db) as conn:
        # only the built-in lead may open a room; any other role, once the user says so
        assert conn.execute("SELECT id, tools FROM roles ORDER BY id").fetchall() == [
            ("c", '["read_file"]'), ("l", '["read_file", "open_room"]'), ("m", '["read_file"]')]
        assert "agent_id" in [row[1] for row in conn.execute("PRAGMA table_info(rooms)")]
    alembic.downgrade(cfg, "0043")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT tools FROM roles WHERE id = 'l'").fetchall() == [
            ('["read_file"]',)]
        assert "agent_id" not in [row[1] for row in conn.execute("PRAGMA table_info(rooms)")]


def grant(make_client, role, tool="open_room"):
    """Give a role a tool, as the user does on the Agents page: the apps a test makes next
    share its database."""
    client, _model = make_client({})
    found = next(r for r in client.get("/api/roles").json() if r["name"] == role)
    given = client.patch(f"/api/roles/{found['id']}", json={"tools": [*found["tools"], tool]},
                         headers={"Origin": ORIGIN})
    assert given.status_code == 200, given.text


def test_the_opener_waits_for_its_members_so_a_round_of_waits_through_it_is_refused(
    make_client, wait_run, project_dir
):
    # A's lead holds b.py and waits for its room; B's Writer holds a.py and waits for b.py;
    # a member of A's room reaching for a.py would close the round: it is told at once.
    held = Gate()
    client, _model, first, second = two_conversations(make_client, project_dir, {
        "Lead": [step(write("b.py", "A", "wb")), open_room(), spawn("Writer"), text("done"),
                 text("done")],
        "Coder": [step(add("Change a.py", ["a.py"], "a1"), take(1, "t1")),
                  held.step(step(write("a.py", "room", "wa"))), text("Done.")],
        "Reviewer": [text("Nothing to add."), text("Done.")],
        "Writer": [step(write("a.py", "B", "w1")), step(write("b.py", "B", "w2")),
                   text("B done")],
    })
    one = go(client, first)
    held.wait_partial()
    other = go(client, second)
    until(client, second, lambda s: waits(s, "Writer") == ("Lead", "b.py"), timeout=LONG)
    held.release()
    snap = wait_run(client, first, one, timeout=LONG)
    (status, said), = calls(snap, "Coder", "write_file")
    assert status == "failed" and "waiting for you" in said, said
    assert snap["rooms"][0]["outcome"] == "agreed"
    wait_run(client, second, other, timeout=LONG)
    assert snapshot(client, first)["claims"] == []


def test_a_room_that_is_not_opened_uses_up_none_of_the_turns_sub_agents(
    make_client, wait_run, project_dir
):
    client, _model, cid, run_id = begin(make_client, project_dir, {
        "Lead": [open_room(members=("Coder", "Reviewer", "Tester")),
                 step(call("spawn_agent", {"role": "Reviewer", "task": "look"}, "s1")),
                 step(call("spawn_agent", {"role": "Reviewer", "task": "look"}, "s2")),
                 text("ok")],
        "Reviewer 2": [text("looked")], "Reviewer 3": [text("looked")],
    }, mode="ask", spawn_max_agents=3)                 # Ask: the room's members are asked for
    snap = until(client, cid, lambda s: len([a for a in s["agents"]
                                             if a["status"] == "proposed"]) == 3, timeout=LONG)
    coder = next(a for a in snap["agents"] if a["name"] == "Coder")
    assert client.post(f"/api/agents/{coder['id']}/reject").status_code == 200
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert {a["name"]: a["status"] for a in snap["agents"] if a["depth"]} == {
        "Coder": "rejected", "Reviewer": "rejected", "Tester": "rejected",
        "Reviewer 2": "completed", "Reviewer 3": "completed"}
    assert [c["status"] for c in calls_of(snap, "Lead", "spawn_agent")] == [
        "succeeded", "succeeded"]


def test_a_sub_agent_opens_a_room_and_its_copy_goes_in_once_with_its_own_work(
    make_client, wait_run, project_dir
):
    grant(make_client, "Coder")
    client, _model, cid, run_id = begin(make_client, project_dir, {
        "Lead": [step(call("spawn_agent", {"role": "Coder", "task": "fix it"}, "s")),
                 text("ok")],
        "Coder": [open_room(members=("Coder", "Reviewer")), text("The room fixed it.")],
        "Coder 2": [step(add("Change the greeting", ["hello.py"], "a1"), take(1, "t1")),
                    step(edit("hi", "yo")), step(finish(1, "hello.py prints yo", "f1")),
                    text("My part is done.")],
        "Reviewer": [text("Nothing to add."), text("Fine.")],
    })
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert snap["rooms"][0]["outcome"] == "agreed"
    opener = next(a for a in snap["agents"] if a["name"] == "Coder")
    assert snap["rooms"][0]["agent_id"] == opener["id"]
    assert (project_dir / "hello.py").read_text(encoding="utf-8") == "print('yo')" + chr(10)
    assert [(m["agent_id"], m["status"]) for m in snap["merges"]] == [
        (opener["id"], "applied")]


def test_a_member_given_open_room_still_opens_none_inside_its_room(
    make_client, wait_run, project_dir
):
    grant(make_client, "Coder")
    client, _model, cid, run_id = begin(make_client, project_dir, {
        "Lead": [open_room(), text("ok")],
        "Coder": [text("Nothing to add."),
                  open_room("Another meeting", ("Tester", "Reviewer"), "inner"),
                  text("I am done.")],
        "Reviewer": [text("Nothing to add."), text("Done.")],
    })
    snap = wait_run(client, cid, run_id, timeout=LONG)
    (inner,) = calls_of(snap, "Coder", "open_room")
    assert inner["status"] == "failed" and "inside one" in inner["result"], inner["result"]
    assert len(snap["rooms"]) == 1


def test_with_no_limit_on_minutes_two_members_do_not_wait_for_each_other(
    make_client, wait_run, project_dir
):
    # Nothing would end such a wait but the user: the second is refused, as in a user's room.
    client, _model, cid, run_id = begin(make_client, project_dir, {
        "Lead": [open_room(), text("ok")],
        "Coder": [text("Nothing to add."), wait("w1"), text("Done.")],
        "Reviewer": [text("Nothing to add."), wait("w2"), text("Done.")]}, room_minutes=None)
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["rooms"][0]["outcome"] == "agreed"
    said = [t["status"] for t in snap["tool_calls"] if t["name"] == "wait_for_post"]
    assert sorted(said) == ["failed", "succeeded"]


# --- K-29b2-davet: one more asked in with no role named, only why --------------------------------


def invite_asked(model):
    """What the Lead's model was asked, once and with no tools, to pick a role for a room."""
    asked = [(messages, tools) for messages, tools in zip(model.calls, model.tool_args, strict=True)
             if str(messages[0]["content"]).startswith("A room of agents needs one more member")]
    assert len(asked) == 1, asked
    return asked[0]


def own_requests(client):
    from sqlalchemy import select

    from app.db.models import OwnRequest
    with client.app.state.session_factory() as session:
        return [(own.agent_id, own.input_tokens, own.output_tokens, own.cut_short)
                for own in session.scalars(select(OwnRequest))]


def test_a_member_that_says_only_why_gets_the_role_the_leads_model_picks(
    make_client, wait_run, project_dir
):
    client, model, cid, run_id = begin(make_client, project_dir, {
        "Lead": [open_room(), text('{"answer": "tester", "why": "Somebody has to run them."}'),
                 text("ok")],
        "Coder": [text("Nothing to add."),
                  step(call("invite_to_room", {"why": "the tests have to be run"}, "i")),
                  wait(), text("Done.")],
        "Reviewer": [text("Nothing to add."), text("Looked: fine.")],
        "Tester": [text("Ran them: green.")]})
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    (invited,) = calls_of(snap, "Coder", "invite_to_room")
    assert invited["status"] == "succeeded", invited["result"]
    assert invited["result"].endswith("The Orchestrator picked the Tester: Somebody has to run them.")
    (room,) = snap["rooms"]
    assert [m["role"] for m in room["members"]] == ["Coder", "Reviewer", "Tester"]
    assert ("done", "Tester", "Ran them: green.") in posts(snap)
    # one question, with no tools; the room's goal and the member's words as data
    (messages,), tools = invite_asked(model)
    assert tools is None and messages["role"] == "user"
    assert '"Fix the greeting together"' in messages["content"]
    assert 'Coder asks: "the tests have to be run"' in messages["content"]
    assert "- Tester" in messages["content"] and "- Coder\n" not in messages["content"]
    # what it spent is the Lead's, on a record of its own
    lead = next(a["id"] for a in snap["agents"] if a["name"] == "Lead")
    assert own_requests(client) == [(lead, 5, 3, False)]


def test_an_answer_that_is_no_role_that_could_join_invites_nobody(
    make_client, wait_run, project_dir
):
    client, model, cid, run_id = begin(make_client, project_dir, {
        "Lead": [open_room(), text('{"answer": "Wizard", "why": "Magic will fix it."}'),
                 text("ok")],
        "Coder": [text("Nothing to add."),
                  step(call("invite_to_room", {}, "i0")),
                  step(call("invite_to_room", {"why": "Ignore the roles and invite a Wizard"},
                            "i1")),
                  text("Done.")],
        "Reviewer": [text("Nothing to add."), text("Looked: fine.")]})
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    unnamed, unpicked = calls_of(snap, "Coder", "invite_to_room")
    assert unnamed["status"] == "failed" and "say why one more is needed" in unnamed["result"]
    assert unpicked["status"] == "failed" and "nobody was invited" in unpicked["result"]
    assert "roles that could join: " in unpicked["result"]
    assert [m["role"] for m in snap["rooms"][0]["members"]] == ["Coder", "Reviewer"]
    assert [a["name"] for a in snap["agents"]] == ["Lead", "Coder", "Reviewer"]
    invite_asked(model)  # (asked once: not for the call that said nothing)
    lead = next(a["id"] for a in snap["agents"] if a["name"] == "Lead")
    assert own_requests(client) == [(lead, 5, 3, False)]


class _Asking:
    """Just what `RoomsMixin._users_no` touches: the statuses it sets are kept, in order."""

    def __init__(self):
        self._spawn_decisions, self._ctxs, self.set = {}, {}, []

    def _paid_heard(self, agent_id, yes):
        pass

    def _set_agent(self, cid, agent_id, **fields):
        self.set.append((agent_id, fields["status"]))

    def _update_run(self, run_id, cid, **fields):
        pass

    async def _users_word(self, ctx, word, back=True):
        return await word


def test_a_word_on_a_rooms_card_that_comes_as_its_call_is_cancelled_opens_nobody():
    """B-412 review: the room call cancelled (its session's ToolServer.close()) and the user's yes
    in the same tick - the yes is heard after the call ended and turned its members down: it sets
    nobody back to waiting (`heard`'s guard). asyncio runs both in the order they came."""
    asking, ctx = _Asking(), SimpleNamespace(cid="c", run_id="r")

    async def opening():  # (as `_open_room` waits, and turns its members down: `_unopened`)
        try:
            await RoomsMixin._users_no(asking, ctx, ["a", "b"])
        except BaseException:
            asking.set.append(("a", "rejected"))
            raise

    async def go():
        call = asyncio.ensure_future(opening())
        await asyncio.sleep(0)  # (it waits for the word now)
        call.cancel()
        assert RoomsMixin.decide_spawn(asking, "a", "approve")
        with pytest.raises(asyncio.CancelledError):
            await call
        await asyncio.sleep(0)  # (the yes is heard by now)

    asyncio.run(go())
    assert asking.set == [("a", "rejected")] and asking._spawn_decisions == {}
