"""Topics beyond the acceptance set (slice 18b): what must hold whatever a model asks for.

Going on with an agent of an earlier turn reaches only into the turn's own topic, passes
every check that opening an agent passes, gives the agent what its role may do today,
and hands it its own past once. A new topic starts with nothing of the others but their
names.
"""

import json
import sqlite3
import time

import pytest
from alembic import command
from sqlalchemy import select

from app import topics
from app.board import PUSHED
from app.config import load_settings
from app.db.models import Agent, Run, Topic, now
from app.main import create_app
from app.tools import earlier_line
from tests.fakes import ScriptedModel
from tests.keyed import TestClient
from tests.test_chat_flow import text
from tests.test_migration_0002 import _config
from tests.test_spawn import call, step
from tests.test_topic_scenarios import (
    FIRST,
    GO_ON,
    MORE,
    OLD_TASK,
    OLD_WORDS,
    ORIGIN,
    SECOND,
    SPAWN_CODER,
    THIRD,
    WRITE,
    agents_of,
    calls_of,
    offered,
    say,
    sent_to,
    setup,
    turn,
)

FACT = "FACT-DEPLOY the deploy script is run.sh"


def db(client):
    return client.app.state.session_factory()


def waiting_card(client, cid, run_id):
    for _ in range(400):
        snap = client.get(f"/api/conversations/{cid}").json()
        waiting = [a for a in agents_of(snap, run_id) if a["status"] == "proposed"]
        if waiting:
            return waiting[0]
        time.sleep(0.02)
    raise AssertionError("no agent waits for a decision")


@pytest.fixture
def with_fast(settings_env, project_dir):
    """An app with a second provider, Fast, that agents may choose (it is in the team
    guide) and a stand-in native CLI, Codex. Returns client, default model, Fast's
    model, the providers by name, project id and conversation id."""
    opened = []

    def make(default_steps, fast_steps):
        default = ScriptedModel(default_steps)
        quick = ScriptedModel(fast_steps, model_id="fast-model")
        app = create_app(load_settings(settings_env), model=default, clients={"Fast": quick})
        client = TestClient(app, base_url=ORIGIN)
        client.__enter__()
        opened.append(client)
        client.headers["Origin"] = ORIGIN
        made = {}
        for body in (
            {"name": "Fast", "kind": "openai_compat", "base_url": "http://127.0.0.1:9/v1",
             "for_agents": True, "default_model": "quick"},
            {"name": "Codex", "kind": "codex_cli", "mode": "native"},
        ):
            answer = client.post("/api/providers", json=body)
            assert answer.status_code == 201, answer.text
            made[body["name"]] = answer.json()
        pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
        cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
        settings = {"permission_mode": "full_auto", "spawn_approval": "never"}
        assert client.patch(f"/api/conversations/{cid}", json=settings).status_code == 200
        return client, default, quick, made, pid, cid

    yield make
    for client in opened:
        client.__exit__(None, None, None)


def role_of(client, name):
    return next(r for r in client.get("/api/roles").json() if r["name"] == name)


# --- names and choosing a topic ----------------------------------------------------------------


def test_a_topic_is_named_by_one_bounded_line():
    assert topics.title_of("\n   \n  fix   the\tgreeting  \nand more") == "fix the greeting"
    assert topics.title_of("a\u202eb\x00c") == "a b c"       # what does not print is left out
    long = topics.title_of("x" * 500)
    assert len(long) == topics.MAX_TITLE and long.endswith("…")
    assert topics.title_of("") == "" and topics.title_of(None) == ""
    assert topics.one_line("  Greeting\nwork ") == "Greeting work"


def test_what_a_message_may_name_as_its_topic(make_client, wait_run, project_dir):
    client, model, pid, cid = setup(make_client, project_dir, {
        "Lead": [text("one"), text("TRIGGER-FOUND nothing wrong"), text("it found nothing"),
                 text("two")]})
    snap, first = turn(client, wait_run, cid, "the first thing")
    made = client.post(f"/api/projects/{pid}/triggers", json={
        "name": "watch", "kind": "webhook", "config": {}, "conversation_id": cid,
        "message": "TRIGGER-MESSAGE look it over"}).json()
    run_id = client.post(f"/api/triggers/{made['id']}/run").json()["run_id"]
    snap = wait_run(client, cid, run_id)
    of_trigger = next(t for t in snap["topics"] if t["trigger_id"] == made["id"])
    assert of_trigger["title"] == "TRIGGER-MESSAGE look it over"

    def refused(**more):
        posted = client.post(f"/api/conversations/{cid}/messages", json={"content": "x", **more})
        return posted.status_code

    # a topic is named or a new one asked for, not both; and a topic that does not
    # exist is not made up
    assert refused(topic_id=first["topic_id"], new_topic=True) == 422
    assert refused(topic_id="0" * 32) == 422
    assert len(client.get(f"/api/conversations/{cid}").json()["runs"]) == 2   # none started
    # the user can ask about what a trigger's turn found, by naming its topic: that
    # turn sees the trigger's turns, and not the user's own topic
    snap, asked = turn(client, wait_run, cid, "ASK what did it find?", topic_id=of_trigger["id"])
    assert asked["topic_id"] == of_trigger["id"] and asked["unattended"] is False
    (request,) = sent_to(model, "ASK what did it find?")
    assert "TRIGGER-FOUND nothing wrong" in request and "TRIGGER-MESSAGE" in request
    assert "the first thing\"}" not in request and "Earlier topics" in request
    # and it does not become the topic the user is in: their next message goes on with
    # their own work
    snap, again = turn(client, wait_run, cid, "more of the first thing")
    assert again["topic_id"] == first["topic_id"]
    (request,) = sent_to(model, "more of the first thing")
    assert "TRIGGER-FOUND" not in request and "ASK what did it find?" not in request
    assert [t["title"] for t in snap["topics"]] == [
        "the first thing", "TRIGGER-MESSAGE look it over"]


def test_naming_a_topic(make_client, wait_run, project_dir):
    client, model, pid, cid = setup(make_client, project_dir, {"Lead": [text("one")]})
    snap, first = turn(client, wait_run, cid, "the first thing")
    assert client.patch(f"/api/topics/{first['topic_id']}", json={"title": " \n "}).status_code == 422
    assert client.patch(f"/api/topics/{'0' * 32}", json={"title": "x"}).status_code == 404
    assert client.patch(
        f"/api/topics/{first['topic_id']}", json={"title": "x" * 201}).status_code == 422
    client.headers["Origin"] = "http://elsewhere.example"     # another site's page
    assert client.patch(
        f"/api/topics/{first['topic_id']}", json={"title": "Mine"}).status_code == 403
    client.headers["Origin"] = ORIGIN
    assert client.patch(f"/api/topics/{first['topic_id']}", json={"title": "Mine"}).status_code == 200
    snap = client.get(f"/api/conversations/{cid}").json()
    assert [t["title"] for t in snap["topics"]] == ["Mine"]
    with client.stream("GET", f"/api/conversations/{cid}/events?after=0&once=1") as r:
        types = [line[7:] for line in r.read().decode().splitlines() if line.startswith("event: ")]
    assert "topic.created" in types and types[-1] == "topic.updated"


def test_each_lead_goes_on_from_the_lead_before_it_in_its_topic(
    make_client, wait_run, project_dir
):
    client, model, pid, cid = setup(make_client, project_dir, {
        "Lead": [text("one"), text("two"), text("three"), text("four")]})
    snap, one = turn(client, wait_run, cid, "a")
    snap, two = turn(client, wait_run, cid, "b")
    snap, other = turn(client, wait_run, cid, "c", new_topic=True)
    snap, three = turn(client, wait_run, cid, "d", topic_id=one["topic_id"])
    lead = {a["run_id"]: a for a in snap["agents"]}
    assert lead[one["id"]]["continues_id"] is None
    assert lead[two["id"]]["continues_id"] == lead[one["id"]]["id"]
    assert lead[other["id"]]["continues_id"] is None         # a new topic: nobody before it
    assert lead[three["id"]]["continues_id"] == lead[two["id"]]["id"]


# --- with no topics in play, nothing changes ---------------------------------------------------


def test_a_second_turn_with_nobody_to_go_on_with_is_sent_what_it_was_before(
    make_client, wait_run, project_dir
):
    client, model, pid, cid = setup(make_client, project_dir, {
        "Lead": [text("one"), text("two")]})
    turn(client, wait_run, cid, FIRST)
    turn(client, wait_run, cid, SECOND)
    first, second = model.calls
    assert second[0] == first[0]                              # the same instructions
    assert [m["content"] for m in second[1:]] == [FIRST, "one", SECOND]
    for tools in model.tool_args:
        assert "message_agent" not in [t["function"]["name"] for t in tools]
    assert "Earlier topics" not in json.dumps(model.calls)


# --- who can be gone on with -------------------------------------------------------------------


def two_turns_then(make_client, wait_run, project_dir, lead_more=()):
    scripts = {"Lead": [SPAWN_CODER, text("made"), *lead_more],
               "Coder": [WRITE, text(OLD_WORDS), text("again"), text("and again")]}
    client, model, pid, cid = setup(make_client, project_dir, scripts)
    snap, first = turn(client, wait_run, cid, FIRST)
    (old,) = [a for a in agents_of(snap, first["id"]) if a["name"] == "Coder"]
    return client, model, pid, cid, first, old


def a_later_run(client, cid, topic_id):
    """A turn put on record in the topic without being run: what could it go on with?"""
    with db(client) as session:
        run = Run(conversation_id=cid, topic_id=topic_id, status="running", started_at=now())
        session.add(run)
        session.commit()
        return run.id


@pytest.mark.parametrize("status,found", [
    ("completed", True), ("failed", True), ("cancelled", False), ("interrupted", False),
    ("rejected", False), ("proposed", False), ("running", False),
])
def test_only_an_agent_that_ran_and_ended_by_itself_is_gone_on_with(
    make_client, wait_run, project_dir, status, found
):
    client, model, pid, cid, first, old = two_turns_then(make_client, wait_run, project_dir)
    later = a_later_run(client, cid, first["topic_id"])
    with db(client) as session:
        session.get_one(Agent, old["id"]).status = status
        session.commit()
        names = [e.name for e in topics.continuable(session, later)]
    assert names == (["Coder"] if found else [])

@pytest.mark.parametrize("unattended", [False, True])
def test_one_stopped_with_its_work_kept_on_its_branch_is_gone_on_with_only_in_a_watched_turn(
    make_client, wait_run, project_dir, unattended
):
    """B-405: an agent the user stopped whose work stays on its branch (a tip on its record) can
    be gone on with - not by a turn nobody watches (a trigger's next turn): that is the user's."""
    client, model, pid, cid, first, old = two_turns_then(make_client, wait_run, project_dir)
    later = a_later_run(client, cid, first["topic_id"])
    with db(client) as session:
        session.get_one(Run, later).unattended = unattended
        row = session.get_one(Agent, old["id"])
        row.status, row.copy = "cancelled", {"state": "own", "on_branch": "koloni/x", "tip": "ab"}
        session.commit()
        found = topics.continuable(session, later)
    assert [e.name for e in found] == ([] if unattended else ["Coder"])
    if found:
        (one,) = found
        assert "stopped by the user in turn 1" in earlier_line(
            one.name, one.role, one.provider, one.model, one.status, one.task, one.turn)


def test_only_an_agent_opened_by_the_lead_itself_is_gone_on_with(
    make_client, wait_run, project_dir
):
    client, model, pid, cid, first, old = two_turns_then(make_client, wait_run, project_dir)
    later = a_later_run(client, cid, first["topic_id"])
    with db(client) as session:
        assert [e.name for e in topics.continuable(session, later)] == ["Coder"]
        # the same agent, had it been opened by another sub-agent
        row = session.get_one(Agent, old["id"])
        helper = Agent(run_id=first["id"], parent_agent_id=row.parent_agent_id,
                       role_name="Planner", name="Planner", tools=[], depth=1,
                       status="completed")
        session.add(helper)
        session.flush()
        row.parent_agent_id, row.depth = helper.id, 2
        session.commit()
        assert [e.name for e in topics.continuable(session, later)] == ["Planner"]
        # and the lead of an earlier turn is never one of them
        assert "Lead" not in [e.name for e in topics.continuable(session, later)]


def test_a_sub_agent_cannot_go_on_with_an_agent_of_an_earlier_turn(
    make_client, wait_run, project_dir
):
    client, model, pid, cid, first, old = two_turns_then(make_client, wait_run, project_dir, [
        step(call("spawn_agent", {"role": "Planner", "task": "plan it"}, "s2")), text("done")])
    model.by_agent["Planner"] = [GO_ON, text("planned")]
    snap, second = turn(client, wait_run, cid, SECOND)
    ((status, said),) = calls_of(snap, second["id"], "message_agent")
    assert status == "failed" and "no agent named Coder" in said
    assert [a["name"] for a in agents_of(snap, second["id"])] == ["Lead", "Planner"]


def test_only_the_newest_link_of_a_chain_is_offered(make_client, wait_run, project_dir):
    client, model, pid, cid, first, old = two_turns_then(
        make_client, wait_run, project_dir, [GO_ON, text("done"), text("three")])
    snap, second = turn(client, wait_run, cid, SECOND)
    turn(client, wait_run, cid, THIRD)
    (told,) = offered(model, THIRD)
    lines = [line for line in told.splitlines() if line.startswith("- Coder")]
    assert len(lines) == 1 and "in turn 2" in lines[0] and MORE in lines[0]
    assert OLD_TASK not in told


def test_a_declined_link_took_nothing_up_and_one_cut_short_ends_the_chain(
    make_client, wait_run, project_dir
):
    client, model, pid, cid, first, old = two_turns_then(
        make_client, wait_run, project_dir, [GO_ON, text("declined"), GO_ON, text("done")])
    client.patch(f"/api/conversations/{cid}", json={"spawn_approval": "always"})
    run = say(client, cid, SECOND)
    card = waiting_card(client, cid, run["id"])
    assert client.post(f"/api/agents/{card['id']}/reject").status_code == 200
    wait_run(client, cid, run["id"])
    client.patch(f"/api/conversations/{cid}", json={"spawn_approval": "never"})
    # the user said no in the second turn: the third still goes on from the first one's
    snap, third = turn(client, wait_run, cid, THIRD)
    newest = next(a for a in agents_of(snap, third["id"]) if a["name"] == "Coder")
    assert (newest["continues_id"], newest["status"]) == (old["id"], "completed")
    # had that third one been stopped half way, nothing of the chain could be gone on with
    later = a_later_run(client, cid, first["topic_id"])
    with db(client) as session:
        assert [e.agent_id for e in topics.continuable(session, later)] == [newest["id"]]
        session.get_one(Agent, newest["id"]).status = "cancelled"
        session.commit()
        assert topics.continuable(session, later) == []


def test_of_two_earlier_agents_with_one_name_the_newer_is_meant(
    make_client, wait_run, project_dir
):
    client, model, pid, cid, first, old = two_turns_then(make_client, wait_run, project_dir, [
        step(call("spawn_agent", {"role": "Coder", "task": "NEW-TASK other work"}, "s2")),
        text("made again")])
    snap, second = turn(client, wait_run, cid, SECOND)
    fresh = next(a for a in agents_of(snap, second["id"]) if a["name"] == "Coder")
    # before this turn had a Coder of its own the earlier one was offered; after, the
    # name means this turn's, and the earlier one is not offered beside it
    before, after = offered(model, SECOND)
    assert "- Coder" in before and "in turn 1" in before and "earlier turn" in before
    assert "- Coder" in after and "in turn 1" not in after and "earlier turn" not in after
    later = a_later_run(client, cid, first["topic_id"])
    with db(client) as session:
        assert [e.agent_id for e in topics.continuable(session, later)] == [fresh["id"]]


# --- no way into another topic, conversation or project ----------------------------------------


def test_an_id_is_not_a_name(make_client, wait_run, project_dir):
    client, model, pid, cid, first, old = two_turns_then(make_client, wait_run, project_dir)
    for name in (old["id"], f"Coder\n{old['id']}", old["run_id"], first["topic_id"]):
        model.by_agent["Lead"] = [
            step(call("message_agent", {"to": name, "message": MORE}, "m1")), text("done")]
        snap, later = turn(client, wait_run, cid, "another thing", new_topic=True)
        ((status, _said),) = calls_of(snap, later["id"], "message_agent")
        assert status == "failed", name
        assert [a["name"] for a in agents_of(snap, later["id"])] == ["Lead"]
    assert sent_to(model, MORE, lacking=["another thing"]) == []


def test_another_conversation_and_another_project_reach_nothing(
    make_client, wait_run, project_dir, tmp_path
):
    client, model, pid, cid, first, old = two_turns_then(make_client, wait_run, project_dir)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    other_project = client.post("/api/projects", json={"root_path": str(elsewhere)}).json()["id"]
    for project in (pid, other_project):
        other = client.post(f"/api/projects/{project}/conversations").json()["id"]
        client.patch(f"/api/conversations/{other}", json={
            "permission_mode": "full_auto", "spawn_approval": "never"}, headers={"Origin": ORIGIN})
        model.by_agent["Lead"] = [GO_ON, text("done")]
        snap, there = turn(client, wait_run, other, SECOND)
        assert all("Coder" not in told for told in offered(model, SECOND))
        ((status, _said),) = calls_of(snap, there["id"], "message_agent")
        assert status == "failed"
        assert [a["name"] for a in agents_of(snap, there["id"])] == ["Lead"]
        assert sent_to(model, SECOND, OLD_TASK) == []
    assert sent_to(model, MORE, lacking=[SECOND]) == []


def test_a_turn_that_claims_another_conversations_topic_reaches_nothing(
    make_client, wait_run, project_dir
):
    client, model, pid, cid, first, old = two_turns_then(make_client, wait_run, project_dir)
    other = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    # a row no request can make: a turn of one conversation in the topic of another
    forged = a_later_run(client, other, first["topic_id"])
    with db(client) as session:
        assert topics.continuable(session, forged) == []
        assert topics.turns_before(session, session.get_one(Run, forged)) == []
        assert topics.previous_lead(session, session.get_one(Run, forged)) is None
        # and the honest one, for the same topic, finds the Coder
        honest = a_later_run(client, cid, first["topic_id"])
        assert [e.name for e in topics.continuable(session, honest)] == ["Coder"]


def test_a_chain_does_not_lead_out_of_its_topic(make_client, wait_run, project_dir):
    client, model, pid, cid, first, old = two_turns_then(make_client, wait_run, project_dir, [
        step(call("spawn_agent", {"role": "Coder", "task": "NEW-TASK other work"}, "s2")),
        text("made again"), GO_ON, text("done")])
    snap, second = turn(client, wait_run, cid, SECOND, new_topic=True)
    fresh = next(a for a in agents_of(snap, second["id"]) if a["name"] == "Coder")
    with db(client) as session:
        # a link no request can make: from the new topic's Coder into the first topic
        session.get_one(Agent, fresh["id"]).continues_id = old["id"]
        session.commit()
    snap, third = turn(client, wait_run, cid, THIRD)
    newest = next(a for a in agents_of(snap, third["id"]) if a["name"] == "Coder")
    assert newest["continues_id"] == fresh["id"]
    (request,) = sent_to(model, MORE, lacking=[THIRD])
    assert "NEW-TASK other work" in request
    assert OLD_TASK not in request and OLD_WORDS not in request
    with db(client) as session:
        assert [link.id for link, _turn in topics.chain(session, newest["id"])] == [
            fresh["id"], newest["id"]]


def test_a_chain_that_points_back_into_itself_ends(make_client, wait_run, project_dir):
    client, model, pid, cid, first, old = two_turns_then(
        make_client, wait_run, project_dir, [GO_ON, text("done")])
    snap, second = turn(client, wait_run, cid, SECOND)
    newest = next(a for a in agents_of(snap, second["id"]) if a["name"] == "Coder")
    with db(client) as session:
        session.get_one(Agent, old["id"]).continues_id = newest["id"]
        session.commit()
        assert [link.id for link, _turn in topics.chain(session, newest["id"])] == [
            old["id"], newest["id"]]


def test_a_discussion_opens_a_new_agent_and_goes_on_with_none(
    make_client, wait_run, project_dir
):
    client, model, pid, cid, first, old = two_turns_then(make_client, wait_run, project_dir, [
        step(call("discuss", {"topic": "TALK how to go on", "with": ["Coder"], "rounds": 1},
                  "d1")),
        text("my view"), text("done")])
    snap, second = turn(client, wait_run, cid, SECOND)
    ((status, _said),) = calls_of(snap, second["id"], "discuss")
    assert status == "succeeded"
    member = next(a for a in agents_of(snap, second["id"]) if a["name"] == "Coder")
    assert member["continues_id"] is None
    spoke = json.dumps(model.calls_of["Coder"][-1])
    assert "TALK how to go on" in spoke and OLD_TASK not in spoke and OLD_WORDS not in spoke


# --- going on is opening an agent: every gate holds ---------------------------------------------


def fast_first_turn(with_fast, wait_run):
    """A first turn whose Coder the lead put on Fast, a provider of the team guide."""
    client, default, quick, made, pid, cid = with_fast(
        {"Lead": [step(call("spawn_agent", {
            "role": "Coder", "task": OLD_TASK, "provider": "Fast",
            "why": "The job is beyond my own model."}, "s1")),
            text("made"), GO_ON, text("done")],
         "Coder": [text("ON-LOCAL went on")]},
        {"Coder": [text(OLD_WORDS), text("ON-FAST went on")]})
    snap, first = turn(client, wait_run, cid, FIRST)
    (old,) = [a for a in agents_of(snap, first["id"]) if a["name"] == "Coder"]
    assert (old["provider_name"], old["chosen"], old["status"]) == ("Fast", True, "completed")
    return client, made, cid, old


def test_going_on_where_the_lead_once_chose_a_model_shows_the_chosen_model_card(
    with_fast, wait_run
):
    client, made, cid, old = fast_first_turn(with_fast, wait_run)
    # at this level opening a sub-agent asks nothing - but a model that is not the
    # role's own is asked about, also when it is gone on with
    client.patch(f"/api/conversations/{cid}", json={"spawn_approval": "auto"})
    run = say(client, cid, SECOND)
    card = waiting_card(client, cid, run["id"])
    assert (card["name"], card["continues_id"], card["provider_name"], card["chosen"]) == (
        "Coder", old["id"], "Fast", True)
    assert client.post(f"/api/agents/{card['id']}/approve").status_code == 200
    snap = wait_run(client, cid, run["id"])
    ((status, said),) = calls_of(snap, run["id"], "message_agent")
    assert status == "succeeded" and "ON-FAST went on" in said


def test_a_model_the_lead_could_not_choose_today_is_not_gone_on_with(with_fast, wait_run):
    client, made, cid, old = fast_first_turn(with_fast, wait_run)
    client.patch(f"/api/conversations/{cid}", json={"spawn_approval": "auto"})
    # the user takes Fast off the team guide: agents may not pick it any more
    assert client.patch(
        f"/api/providers/{made['Fast']['id']}", json={"for_agents": False}).status_code == 200
    snap, second = turn(client, wait_run, cid, SECOND)
    coder = next(a for a in agents_of(snap, second["id"]) if a["name"] == "Coder")
    assert (coder["provider_name"], coder["chosen"], coder["continues_id"]) == (
        "Local", False, old["id"])
    ((status, said),) = calls_of(snap, second["id"], "message_agent")
    assert status == "succeeded" and "ON-LOCAL went on" in said


def unattended_topic(with_fast, wait_run, reviewer_on=None):
    """A trigger's first turn, in which its lead opened a Reviewer; then what its
    second turn's message_agent(to="Reviewer") came to."""
    client, default, quick, made, pid, cid = with_fast(
        {"Lead": [step(call("spawn_agent", {"role": "Reviewer", "task": OLD_TASK}, "s1")),
                  text("looked"),
                  step(call("message_agent", {"to": "Reviewer", "message": MORE}, "m1")),
                  text("done")],
         "Reviewer": [*([] if reviewer_on else [text(OLD_WORDS)]), text("ON-LOCAL went on")]},
        {"Reviewer": [text(OLD_WORDS), text("ON-FAST went on")]})
    reviewer = role_of(client, "Reviewer")
    if reviewer_on:
        assert client.patch(f"/api/roles/{reviewer['id']}", json={
            "provider_id": made[reviewer_on]["id"]}).status_code == 200
    trigger = client.post(f"/api/projects/{pid}/triggers", json={
        "name": "watch", "kind": "webhook", "config": {}, "conversation_id": cid,
        "message": "TRIGGER-MESSAGE look it over",
        "permissions": {"write": False, "commands": [], "agents": 1}}).json()

    def fire():
        run_id = client.post(f"/api/triggers/{trigger['id']}/run").json()["run_id"]
        return wait_run(client, cid, run_id), run_id

    snap, one = fire()
    (old,) = [a for a in agents_of(snap, one) if a["name"] == "Reviewer"]
    assert old["status"] == "completed"
    return client, made, reviewer, fire, old


def test_nobody_watching_an_agent_on_a_cli_with_its_own_tools_is_not_gone_on_with(
    with_fast, wait_run
):
    client, made, reviewer, fire, old = unattended_topic(with_fast, wait_run)
    # since then its role was put on a CLI that works with tools of its own
    assert client.patch(f"/api/roles/{reviewer['id']}", json={
        "provider_id": made["Codex"]["id"]}).status_code == 200
    snap, two = fire()
    ((status, said),) = calls_of(snap, two, "message_agent")
    assert status == "denied" and "cannot work in a turn nobody is watching" in said
    assert [a["name"] for a in agents_of(snap, two)] == ["Lead"]      # none was opened


def test_nobody_watching_no_model_is_picked_for_the_agent_gone_on_with(with_fast, wait_run):
    client, made, reviewer, fire, old = unattended_topic(with_fast, wait_run, reviewer_on="Fast")
    assert old["provider_name"] == "Fast"
    # its role has no model of its own any more: with the user there the lead could go
    # on with it on Fast (a pick, asked about); with nobody there it gets its role's
    assert client.patch(f"/api/roles/{reviewer['id']}", json={"provider_id": None}).status_code == 200
    snap, two = fire()
    ((status, said),) = calls_of(snap, two, "message_agent")
    assert status == "succeeded" and "ON-LOCAL went on" in said
    newest = next(a for a in agents_of(snap, two) if a["name"] == "Reviewer")
    assert (newest["provider_name"], newest["chosen"]) == ("Local", False)


def test_a_role_widened_since_gives_no_more_than_the_lead_has(
    make_client, wait_run, project_dir
):
    scripts = {
        "Lead": [step(call("spawn_agent", {"role": "Reviewer", "task": OLD_TASK}, "s1")),
                 text("looked"),
                 step(call("message_agent", {"to": "Reviewer", "message": MORE}, "m1")),
                 text("done")],
        "Reviewer": [text(OLD_WORDS), text("went on")],
    }
    client, model, pid, cid = setup(make_client, project_dir, scripts)
    snap, first = turn(client, wait_run, cid, FIRST)
    old = next(a for a in agents_of(snap, first["id"]) if a["name"] == "Reviewer")
    assert "write_file" not in old["tools"] and "run_command" not in old["tools"]
    reviewer, lead = role_of(client, "Reviewer"), role_of(client, "Lead")
    assert client.patch(f"/api/roles/{reviewer['id']}", json={
        "tools": [*reviewer["tools"], "write_file", "run_command"]}).status_code == 200
    assert client.patch(f"/api/roles/{lead['id']}", json={
        "tools": [t for t in lead["tools"] if t != "run_command"]}).status_code == 200
    snap, second = turn(client, wait_run, cid, SECOND)
    newest = next(a for a in agents_of(snap, second["id"]) if a["name"] == "Reviewer")
    # what its role has today - and of that only what the lead of today has itself
    assert "write_file" in newest["tools"] and "run_command" not in newest["tools"]
    sent = [tools for request, tools in zip(model.calls, model.tool_args, strict=True)
            if MORE in json.dumps(request) and SECOND not in json.dumps(request)]
    assert sent and "run_command" not in [t["function"]["name"] for t in sent[0]]


# --- the chain's history -----------------------------------------------------------------------


def size_of(request):
    return sum(
        len(m.get("content") or "")
        + sum(len(c["function"]["arguments"]) for c in m.get("tool_calls") or [])
        for m in request)


def test_a_chain_of_ten_links_stays_within_the_budget_and_keeps_task_and_report(
    make_client, wait_run, project_dir, settings_env, monkeypatch
):
    from app.agent import ASK_NOT_REPORT, THIN_TASK, TRUST_RECORD
    from app.executors.host import SHELL_WRITES
    from app.handoff import REPORT_PROMPT

    # (tight on purpose: the newest link just fits; grown with the prompts, B-109 - B-182's line and B-192's,
    # and twice B-321's 77 characters on a refusal, B-324's shell line, K-devir-1's report
    # headings, K-brief-kalitesi's line on a thin task and K-kanit's on the record line (a Coder
    # opens agents too): half of what the budget grows goes to
    # the shortened links, whose share is a part of it, `topics.share_of`; counted with Windows
    # PowerShell's shell line, whichever shell this machine has)
    monkeypatch.setattr("app.executors.host._pwsh", lambda: None)
    budget = 9300 + len(ASK_NOT_REPORT) + 440 + 2 * (
        77 + len(SHELL_WRITES) + len(REPORT_PROMPT) + len(THIN_TASK) + len(TRUST_RECORD))
    settings_env["KOLONI_CONTEXT_CHARS"] = str(budget)
    filler = " lorem ipsum dolor sit amet" * 14
    lead = [step(call("spawn_agent", {"role": "Coder", "task": f"TASK-1 start{filler}"}, "s1")),
            text("ok")]
    for n in range(2, 11):
        lead += [step(call("message_agent", {
            "to": "Coder", "message": f"TASK-{n} go on{filler}"}, f"m{n}")), text("ok")]
    scripts = {"Lead": lead,
               "Coder": [text(f"WORDS-{n} done{filler} END-{n}") for n in range(1, 11)]}
    client, model, pid, cid = setup(make_client, project_dir, scripts)
    for n in range(1, 11):
        snap, run = turn(client, wait_run, cid, f"turn {n}")
    requests = model.calls_of["Coder"]
    assert len(requests) == 10
    last = requests[-1]
    assert size_of(last) <= budget
    whole = json.dumps(last, ensure_ascii=False)
    # the oldest links are cut down to what was asked and what was reported, off the record
    assert "Turn 1 of this topic, shortened" in whole
    for n in range(1, 10):
        assert whole.count(f"TASK-{n} ") == 1 and whole.count(f"WORDS-{n} ") == 1, n
    assert "END-1 " not in whole and "END-1\"" not in whole     # cut, and said to be
    assert "[… cut]" in whole
    # the newest work is there in full, and the message of this turn is the last thing
    assert f"WORDS-9 done{filler} END-9" in whole
    assert last[-1]["content"].endswith(f"TASK-10 go on{filler}")
    # and a chain that fits is not touched at all
    assert "shortened" not in json.dumps(requests[3])


def test_fitting_a_chain_shortens_whole_links_from_the_oldest():
    def link(name, length):
        return ([{"role": "user", "content": f"{name}-task"},
                 {"role": "assistant", "content": "", "tool_calls": [
                     {"id": "c", "function": {"name": "read_file", "arguments": "{}"}}]},
                 {"role": "tool", "tool_call_id": "c", "content": "x" * length}],
                f"[{name} short]")

    def size(message):
        return len(message.get("content") or "")

    links = [link("one", 100), link("two", 100), link("three", 100)]
    assert topics.fit(links, rest=0, budget=1000, size=size) == [m for ms, _ in links for m in ms]
    fitted = topics.fit(links, rest=50, budget=300, size=size)
    assert fitted[0] == {"role": "user", "content": "[one short]"}
    assert fitted[1]["content"] == "two-task" and fitted[-1]["content"] == "x" * 100
    # no call is left without its result, and no result without its call
    assert sum(1 for m in fitted if m.get("tool_calls")) == sum(
        1 for m in fitted if m["role"] == "tool") == 2
    assert [m["content"] for m in topics.fit(links, rest=10_000, budget=300, size=size)] == [
        "[one short]", "[two short]", "[three short]"]
    assert topics.reduced(2, "do it", None, 200).count("(it ended without a report)") == 1
    cut = topics.reduced(1, "t" * 1000, "r" * 1000, 200)
    assert len(cut) < 700 and cut.count("[… cut]") == 2
    assert topics.share_of(240_000, 9) * 2 * 9 <= 120_000


def test_what_the_memory_gave_or_showed_an_earlier_link_is_not_replayed(
    make_client, wait_run, project_dir
):
    task = "OLD-TASK check how the deploy works"
    scripts = {
        "Lead": [step(call("spawn_agent", {"role": "Coder", "task": task}, "s1")),
                 text("made"), GO_ON, text("done")],
        "Coder": [step(call("recall", {"query": "deploy"}, "r1")), text(OLD_WORDS),
                  text("went on")],
    }
    client, model, pid, cid = setup(make_client, project_dir, scripts)
    made = client.post(f"/api/projects/{pid}/memory", json={"text": FACT, "about": "deploy"})
    assert made.status_code == 201, made.text
    snap, first = turn(client, wait_run, cid, FIRST)
    old = next(a for a in agents_of(snap, first["id"]) if a["name"] == "Coder")
    assert old["facts_given"] == [made.json()["id"]]
    ((status, found),) = calls_of(snap, first["id"], "recall")
    assert status == "succeeded" and FACT in found
    then = json.dumps(model.calls_of["Coder"][1], ensure_ascii=False)
    assert then.count(FACT) == 2          # in its instructions, and in what recall returned
    # the user takes the fact back before the topic's next turn
    assert client.post(f"/api/memory/{made.json()['id']}/reject").status_code == 200
    turn(client, wait_run, cid, SECOND)
    (request,) = sent_to(model, MORE, lacking=[SECOND])
    assert FACT not in request
    assert "looked up in an earlier turn: 1 record" in request
    assert "you were given 1 fact from the project's memory" in request
    assert request.count(task) == 1 and OLD_WORDS in request


# --- a new topic is clean ----------------------------------------------------------------------


def test_nothing_of_an_earlier_topic_reaches_the_lead_of_a_new_one(
    make_client, wait_run, project_dir
):
    scripts = {"Lead": [
        step(call("read_file", {"path": "hello.py"}, "r1"),
             call("post_note", {"text": "NOTE-ALPHA the greeting is in hello.py"}, "p1"),
             call("recall", {"query": "deploy"}, "k1")),
        text("REPLY-ALPHA it is done"),
        step(call("post_note", {"text": "NOTE-BETA nothing more to do"}, "p2")), text("two"),
        text("three")]}
    client, model, pid, cid = setup(make_client, project_dir, scripts)
    made = client.post(f"/api/projects/{pid}/memory", json={"text": FACT, "about": "deploy"})
    assert made.status_code == 201, made.text
    (project_dir / "hello.py").write_text("print('FILE-ALPHA')\n", encoding="utf-8")
    first_message = "ask \"about\" it\nSECRET-ALPHA deploy details"
    turn(client, wait_run, cid, first_message)
    assert client.post(f"/api/memory/{made.json()['id']}/reject").status_code == 200
    turn(client, wait_run, cid, SECOND)
    going_on, _then = sent_to(model, SECOND)
    # the topic's own next turn has all of it: the message, the file it read, the notebook
    for part in ("SECRET-ALPHA", "FILE-ALPHA", "NOTE-ALPHA", "REPLY-ALPHA", PUSHED):
        assert part in going_on, part
    assert FACT not in going_on and "looked up in an earlier turn" in going_on
    assert "Earlier topics" not in going_on
    turn(client, wait_run, cid, THIRD, new_topic=True)
    (fresh,) = sent_to(model, THIRD)
    for part in ("SECRET-ALPHA", "FILE-ALPHA", "NOTE-ALPHA", "NOTE-BETA", "REPLY-ALPHA",
                 SECOND, FACT,
                 "looked up in an earlier turn", PUSHED,
                 "read_file", "hello.py"):
        assert part not in fresh, part
    # only the name, on one line and as data
    asked = json.loads(fresh)
    assert [m["role"] for m in asked] == ["system", "user"]
    (line,) = [line for line in asked[0]["content"].splitlines() if "Earlier topics" in line]
    assert line.endswith(': "ask \\"about\\" it".')


# --- the turns there already -------------------------------------------------------------------


def test_migration_0021_puts_the_turns_there_into_topics_and_back(tmp_path):
    database = tmp_path / "old.db"
    cfg = _config(database)
    command.upgrade(cfg, "0020")
    at = "2026-10-0{} 10:00:00"
    with sqlite3.connect(database) as conn:
        conn.execute("INSERT INTO projects (id, name, root_path, created_at) "
                     f"VALUES ('p', 'p', 'C:/p', '{at.format(1)}')")
        for cid in ("c1", "c2", "c3"):
            conn.execute(
                "INSERT INTO conversations (id, project_id, title, created_at, updated_at) "
                f"VALUES (?, 'p', ?, '{at.format(1)}', '{at.format(1)}')", (cid, f"Title {cid}"))
        runs = [("r1", "c1", None, 1), ("r2", "c1", "t1", 2), ("r3", "c1", None, 3),
                ("r4", "c1", "t1", 4), ("r5", "c1", "t2", 5), ("r6", "c2", "t1", 6),
                ("r7", "c2", None, 7)]
        for run_id, cid, trigger, day in runs:
            conn.execute(
                "INSERT INTO runs (id, conversation_id, status, created_at, unattended, "
                "trigger_id) VALUES (?, ?, 'completed', ?, ?, ?)",
                (run_id, cid, at.format(day), trigger is not None, trigger))
        # a turn nobody watched with no trigger on record: none is known to exist
        conn.execute(
            "INSERT INTO runs (id, conversation_id, status, created_at, unattended, "
            f"trigger_name) VALUES ('r8', 'c1', 'completed', '{at.format(8)}', 1, 'Nightly')")
        said = [("r1", "user", "\n  fix the   greeting\nSECRET detail"),
                ("r2", "trigger", "look it over\n\nmore"), ("r3", "user", "and again"),
                ("r5", "trigger", "x" * 300), ("r6", "trigger", "other conversation")]
        for index, (run_id, role, content) in enumerate(said):
            conn.execute(
                "INSERT INTO messages (id, conversation_id, run_id, role, content, status, "
                "created_at) VALUES (?, 'c1', ?, ?, ?, 'complete', ?)",
                (f"m{index}", run_id, role, content, at.format(1)))
        conn.execute(
            "INSERT INTO agents (id, run_id, role_name, name, tools, depth, status, chosen, "
            f"board_seen, created_at) VALUES ('a1', 'r1', 'Lead', 'Lead', '[]', 0, "
            f"'completed', 0, 0, '{at.format(1)}')")
    command.upgrade(cfg, "0021")
    with sqlite3.connect(database) as conn:
        of = dict(conn.execute("SELECT id, topic_id FROM runs").fetchall())
        rows = {topic: (cid, trigger, title, str(created)[:10]) for topic, cid, trigger, title,
                created in conn.execute(
                    "SELECT id, conversation_id, trigger_id, title, created_at FROM topics")}
        assert conn.execute("SELECT continues_id FROM agents").fetchall() == [(None,)]
    # a conversation's own turns are one topic; each trigger's turns there another
    assert of["r1"] == of["r3"] and of["r2"] == of["r4"]
    assert len({of["r1"], of["r2"], of["r5"], of["r6"], of["r7"], of["r8"]}) == 6 == len(rows)
    assert rows[of["r8"]][:2] == ("c1", None)      # not one of the user's own turns either
    assert rows[of["r1"]] == ("c1", None, "fix the greeting", "2026-10-01")
    assert rows[of["r2"]] == ("c1", "t1", "look it over", "2026-10-02")
    assert rows[of["r5"]][:2] == ("c1", "t2") and len(rows[of["r5"]][2]) == 80
    assert rows[of["r6"]][:3] == ("c2", "t1", "other conversation")
    # a turn with no message on record is named by its conversation
    assert rows[of["r7"]][:3] == ("c2", None, "Title c2")
    command.downgrade(cfg, "0020")
    with sqlite3.connect(database) as conn:
        assert "topic_id" not in [row[1] for row in conn.execute("PRAGMA table_info(runs)")]
        assert "continues_id" not in [row[1] for row in conn.execute("PRAGMA table_info(agents)")]
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE name = 'topics'").fetchall() == []
    command.upgrade(cfg, "0021")


def test_a_topic_of_the_model_matches_the_one_the_api_made(make_client, wait_run, project_dir):
    client, model, pid, cid = setup(make_client, project_dir, {"Lead": [text("one")]})
    snap, first = turn(client, wait_run, cid, "x" * 300)
    with db(client) as session:
        (topic,) = session.scalars(select(Topic)).all()
        assert (topic.id, topic.conversation_id, topic.trigger_id) == (
            first["topic_id"], cid, None)
        assert len(topic.title) == topics.MAX_TITLE


# --- after the review (8 Oct 2026) ----------------------------------------------------------


def test_a_lead_that_may_not_open_agents_cannot_go_on_with_one_either(
    make_client, wait_run, project_dir
):
    """Going on with an agent is opening one: a lead whose role has no spawn_agent is
    neither offered the agents of earlier turns nor reaches them."""
    client, model, pid, cid = setup(make_client, project_dir, {
        "Lead": [SPAWN_CODER, text("made"), GO_ON, text("done")],
        "Coder": [WRITE, text(OLD_WORDS), text("must not be asked")]})
    turn(client, wait_run, cid, FIRST)
    lead = role_of(client, "Lead")
    narrowed = client.patch(f"/api/roles/{lead['id']}", json={
        "tools": [tool for tool in lead["tools"] if tool != "spawn_agent"]})
    assert narrowed.status_code == 200, narrowed.text
    snap, second = turn(client, wait_run, cid, SECOND)
    assert all("Coder" not in told for told in offered(model, SECOND))
    ((status, _said),) = calls_of(snap, second["id"], "message_agent")
    assert status == "failed"
    assert [a["name"] for a in agents_of(snap, second["id"])] == ["Lead"]
    assert sent_to(model, MORE, lacking=[SECOND]) == []


def test_a_message_taken_back_before_its_turn_started_leaves_the_user_where_they_were(
    make_client, wait_run, project_dir
):
    client, model, pid, cid = setup(make_client, project_dir, {"Lead": [
        step(call("ask_user", {"question": "which one?"}, "q")), text("thanks"), text("third")]})
    first = say(client, cid, FIRST)
    for _ in range(400):
        snap = client.get(f"/api/conversations/{cid}").json()
        pending = [q for q in snap["questions"] if q["status"] == "pending"]
        if pending:
            break
        time.sleep(0.02)
    queued = say(client, cid, "a new thing, then not", new_topic=True)
    assert queued["topic_id"] != first["topic_id"]
    assert client.post(f"/api/runs/{queued['id']}/cancel").status_code in (200, 202)
    client.post(f"/api/questions/{pending[0]['id']}/answer", json={"answer": "this one"})
    wait_run(client, cid, first["id"])
    # the topic that was never worked in is not where the next message goes
    _snap, third = turn(client, wait_run, cid, THIRD)
    assert third["topic_id"] == first["topic_id"]
