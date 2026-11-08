"""Slice 52's backlog working itself (the user, 22 Oct: "if a task list is created, the product
owner could start by itself"): the page's switch, the next task started when one's turn ends,
what stops it and says why, two tasks at work at a time (K-symphony; one here where a test is
about what holds a place), and the Assistant product owner's view written when a task's turn
ends."""

import time

from sqlalchemy import select

from app import agent, backlog, earlier
from app.agent import recover_interrupted
from app.db.models import BacklogTask, OwnRequest, Project, Run
from tests.test_agent_writes import edit, wait_status
from tests.test_backlog import setup
from tests.test_chat_flow import text
from tests.test_spawn import call, spawn, step
from tests.test_team import team  # noqa: F401  (a fixture)
from tests.test_tier_scenarios import tiered


def tasks(client, pid):
    return {t["title"]: t for t in client.get(f"/api/projects/{pid}/backlog").json()}


def auto(client, pid, on, **headers):
    return client.put(f"/api/projects/{pid}/backlog/auto", json={"on": on}, headers=headers)


def worked(client, wait_run, pid, title):
    """Wait for the turn of a task that was started, and return the task as it is then."""
    cid = tasks(client, pid)[title]["conversation_id"]
    snap = client.get(f"/api/conversations/{cid}").json()
    wait_run(client, cid, snap["runs"][0]["id"])
    return tasks(client, pid)[title]


def until(check, seconds=20.0):
    # A ceiling, not a pace (as `wait_run`'s): a night of two jobs, 0.2 s here, did not end in
    # 5 s on a CI runner.
    deadline = time.monotonic() + seconds
    while not (seen := check()):
        assert time.monotonic() < deadline, "never came"
        time.sleep(0.02)
    return seen


def test_the_switch_starts_the_next_task_and_each_end_starts_the_one_after(make_client, wait_run, project_dir):
    client, _model = make_client([text("one done"), text("two done")])
    pid, _ = setup(client, project_dir, "one", "two")
    assert client.get(f"/api/projects/{pid}/backlog/auto").json().items() >= {"on": False, "halt": None}.items()
    # from the app's own page only
    assert auto(client, pid, True, Origin="http://evil.example").status_code == 403
    assert tasks(client, pid)["one"]["status"] == "todo"
    assert auto(client, pid, True).json().items() >= {"on": True, "halt": None}.items()
    assert tasks(client, pid)["one"]["conversation_id"]  # at once: none was doing
    assert worked(client, wait_run, pid, "one")["status"] == "review"
    # the turn ended: the next starts by itself, in a conversation of its own
    until(lambda: tasks(client, pid)["two"]["conversation_id"])
    two = worked(client, wait_run, pid, "two")
    assert two["status"] == "review" and two["conversation_id"] != tasks(client, pid)["one"]["conversation_id"]
    # no fast model to ask: no view is made up
    assert all(t["assessment"] is None for t in tasks(client, pid).values())
    # none left: it stays on, for a task added later
    assert client.get(f"/api/projects/{pid}/backlog/auto").json().items() >= {"on": True, "halt": None}.items()


def test_two_tasks_at_a_time_the_rest_queue_and_a_task_put_back_waits_for_the_button(make_client, wait_run, project_dir, gate):
    client, _model = make_client([gate.step(text("done")), gate.step(text("done")), text("done")])
    pid, _ = setup(client, project_dir, "one", "two", "three")
    auto(client, pid, True)
    assert backlog.MAX_PARALLEL == 2
    assert [tasks(client, pid)[t]["status"] for t in ("one", "two", "three")] == ["doing", "doing", "todo"]
    # the button with no room: the rest are queued, none started beside the two
    answer = client.post(f"/api/projects/{pid}/backlog/next")
    assert answer.json() == {"task_id": None, "conversation_id": None}
    assert tasks(client, pid)["three"]["queued"] and tasks(client, pid)["three"]["status"] == "todo"
    gate.release()
    worked(client, wait_run, pid, "one")
    worked(client, wait_run, pid, "two")
    until(lambda: tasks(client, pid)["three"]["conversation_id"])
    assert worked(client, wait_run, pid, "three")["queued"] is False
    # Not yet: back to todo - not started again by itself; its conversation may be wanted
    one = tasks(client, pid)["one"]
    client.patch(f"/api/backlog/{one['id']}", json={"status": "todo"})
    assert tasks(client, pid)["one"] == {**one, "status": "todo"}


def test_a_stopped_turn_stops_the_chain(make_client, wait_run, project_dir, gate, monkeypatch):
    monkeypatch.setattr(backlog, "MAX_PARALLEL", 1)
    client, _model = make_client([gate.step(text("never"))])
    pid, _ = setup(client, project_dir, "one", "two")
    auto(client, pid, True)
    gate.wait_partial()
    cid = tasks(client, pid)["one"]["conversation_id"]
    run_id = client.get(f"/api/conversations/{cid}").json()["runs"][0]["id"]
    client.post(f"/api/runs/{run_id}/cancel")
    wait_run(client, cid, run_id)
    assert client.get(f"/api/projects/{pid}/backlog/auto").json().items() >= {
        "on": False, "halt": 'Stopped: the turn of "one" was stopped.'}.items()
    assert tasks(client, pid)["two"]["status"] == "todo"


def test_over_the_months_budget_nothing_starts_and_the_page_says_why(make_client, project_dir, monkeypatch):
    client, model = make_client([])
    pid, _ = setup(client, project_dir, "one")
    over = "over this month's budget (2.00 of 1.00 USD)"
    monkeypatch.setattr(backlog, "over_budget", lambda session, project: over)
    # paused, not off: the switch is on, and says why nothing starts
    assert auto(client, pid, True).json().items() >= {"on": True, "halt": f"Paused: the project is {over}."}.items()
    assert tasks(client, pid)["one"]["status"] == "todo" and not model.calls


def test_the_assistant_product_owner_assesses_a_task_when_its_turn_ends(team, wait_run, project_dir):  # noqa: F811
    client, _default, fast = team([text("LEAD-ANSWER the form shows errors.")],
                                  [text("<think>hm</think>Criterion one is met; no test for it.", 11, 7)])
    tiered(team, client)
    pid, _ = setup(client, project_dir)
    client.post(f"/api/projects/{pid}/backlog", json={"title": "login form", "criteria": "shows errors"})
    client.post(f"/api/projects/{pid}/backlog/next")
    task = until(lambda: (t := tasks(client, pid)["login form"])["assessment"] and t)
    assert (task["status"], task["assessment"]) == ("review", "Criterion one is met; no test for it.")
    (asked,) = fast.calls
    assert not fast.tool_args[0] and asked[0]["content"] == backlog.ASSESS
    given = asked[1]["content"]
    assert '"login form"' in given and '"shows errors"' in given and "LEAD-ANSWER" in given
    # KOLONİ's own request, counted under the model that was asked
    used = {row["provider_name"]: row for row in client.get("/api/usage").json()["by_model"]}
    assert (used["Fast"]["input_tokens"], used["Fast"]["output_tokens"]) == (11, 7)


def test_the_assistant_product_owner_is_given_the_turns_changes(team, wait_run, project_dir, monkeypatch):  # noqa: F811
    # (the Lead writes itself here: what is looked at is what the view is given)
    monkeypatch.setattr(agent.AgentRunner, "_hands_code", lambda self, ctx: False)
    client, _default, fast = team([edit(), text("changed it")], [text("Met.")])
    tiered(team, client)
    pid, _ = setup(client, project_dir)
    client.post(f"/api/projects/{pid}/backlog", json={"title": "greeting", "criteria": "says hello"})
    cid = client.post(f"/api/projects/{pid}/backlog/next").json()["conversation_id"]
    change = wait_status(client, cid, "waiting_approval")["file_changes"][0]
    client.post(f"/api/file-changes/{change['id']}/approve")
    until(lambda: tasks(client, pid)["greeting"]["assessment"])
    given = fast.calls[0][1]["content"]
    assert "+print('hello')" in given and "-print('hi')" in given and '"hello.py"' in given


def test_the_view_is_given_what_a_coder_did_in_its_copy_once_it_is_taken_in(team, wait_run, project_dir):  # noqa: F811
    # (as a Lead hands code on: a Coder changes its copy, and the user takes it into the project)
    coder = step(call("spawn_agent", {"role": "Coder", "task": "fix it", "tier": "strongest",
                                      "why": "the scripts are on it"}, "s"))
    client, _default, fast = team({"Lead": [coder, text("changed it")],
                                   "Coder": [edit(), text("edited")]}, [text("Met.")])
    tiered(team, client)
    pid, _ = setup(client, project_dir)
    client.post(f"/api/projects/{pid}/backlog", json={"title": "greeting", "criteria": "says hello"})
    cid = client.post(f"/api/projects/{pid}/backlog/next").json()["conversation_id"]

    def asked():
        snap = client.get(f"/api/conversations/{cid}").json()
        for kid in snap["agents"]:
            if kid["status"] == "proposed":
                client.post(f"/api/agents/{kid['id']}/approve")
        for card in snap["merges"]:
            if card["status"] == "pending":
                client.post(f"/api/merges/{card['id']}/approve")
        return tasks(client, pid)["greeting"]["assessment"]

    until(asked, seconds=10)
    given = fast.calls[0][1]["content"]
    assert "+print('hello')" in given and "-print('hi')" in given

def test_a_doing_task_moved_on_by_hand_holds_the_next_until_its_turn_ends(make_client, wait_run, project_dir, gate, monkeypatch):
    monkeypatch.setattr(backlog, "MAX_PARALLEL", 1)
    client, _model = make_client([gate.step(text("one done")), text("two done")])
    pid, _ = setup(client, project_dir, "one", "two")
    auto(client, pid, True)
    gate.wait_partial()
    client.patch(f"/api/backlog/{tasks(client, pid)['one']['id']}", json={"status": "done"})
    # nothing is doing, but its conversation is still at work: no second turn beside it
    assert tasks(client, pid)["two"]["conversation_id"] is None
    assert client.post(f"/api/projects/{pid}/backlog/next").json()["task_id"] is None  # queued
    gate.release()
    worked(client, wait_run, pid, "one")
    until(lambda: tasks(client, pid)["two"]["conversation_id"])
    assert worked(client, wait_run, pid, "two")["status"] == "review"
    assert tasks(client, pid)["one"]["status"] == "done"


def test_the_budget_spent_by_a_turn_stops_the_next_one(make_client, wait_run, project_dir, gate, monkeypatch):
    monkeypatch.setattr(backlog, "MAX_PARALLEL", 1)
    client, _model = make_client([gate.step(text("one done"))])
    pid, _ = setup(client, project_dir, "one", "two")
    spent = {"over": None}
    monkeypatch.setattr(backlog, "over_budget", lambda session, project: spent["over"])
    auto(client, pid, True)
    gate.wait_partial()
    spent["over"] = "over this month's budget (2.00 of 1.00 USD)"
    gate.release()
    worked(client, wait_run, pid, "one")
    assert until(lambda: client.get(f"/api/projects/{pid}/backlog/auto").json()["halt"]) == (
        "Paused: the project is over this month's budget (2.00 of 1.00 USD).")
    assert tasks(client, pid)["two"]["conversation_id"] is None


def test_a_restart_stops_the_chain_and_says_so(client, project_dir):
    pid, (task_id,) = setup(client, project_dir, "work")
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    factory = client.app.state.session_factory
    with factory() as session:
        session.add(Run(conversation_id=cid, status="running"))
        task = session.get_one(BacklogTask, task_id)
        task.status, task.conversation_id = "doing", cid
        session.get_one(Project, pid).backlog_auto = True
        session.commit()
    recover_interrupted(factory)
    assert client.get(f"/api/projects/{pid}/backlog/auto").json().items() >= {
        "on": False, "halt": 'Stopped: the turn of "work" was cut short by a restart.'}.items()


def test_no_view_when_the_assessment_takes_too_long(team, wait_run, project_dir, gate, monkeypatch):  # noqa: F811
    monkeypatch.setattr(earlier, "SUMMARISER_SECONDS", 0.05)
    client, _default, _fast = team([text("done")], [gate.step(text("a late view"))])
    tiered(team, client)
    pid, _ = setup(client, project_dir)
    client.post(f"/api/projects/{pid}/backlog", json={"title": "login form"})
    client.post(f"/api/projects/{pid}/backlog/next")
    worked(client, wait_run, pid, "login form")

    def cut_short():
        with client.app.state.session_factory() as session:
            return session.scalar(select(OwnRequest.id).where(OwnRequest.cut_short))

    until(cut_short)  # sent, and not heard out: on record all the same
    assert tasks(client, pid)["login form"]["assessment"] is None


def test_a_turn_waiting_for_the_users_word_holds_the_chain(make_client, wait_run, project_dir, monkeypatch):
    monkeypatch.setattr(backlog, "MAX_PARALLEL", 1)  # (its place is held)
    # (the Lead hands code on: its Coder's edit waits at the conversation's own level, ask)
    client, _model = make_client({"Lead": [spawn("Coder"), text("changed it")],
                                  "Coder": [edit(), text("edited")]})
    pid, _ = setup(client, project_dir, "one", "two")
    auto(client, pid, True)
    cid = tasks(client, pid)["one"]["conversation_id"]
    snap = wait_status(client, cid, "waiting_approval")
    time.sleep(0.2)
    # what waits for the user's word is waited for: the next does not start beside it
    assert (tasks(client, pid)["one"]["status"], tasks(client, pid)["one"]["waiting"]) == ("doing", True)
    assert tasks(client, pid)["two"]["conversation_id"] is None
    # the chat list says so too (K-backlog-sohbet)
    listed = {c["id"]: c for c in client.get(f"/api/projects/{pid}/conversations").json()}
    assert listed[cid]["backlog_task"] == {
        "id": tasks(client, pid)["one"]["id"], "status": "doing", "waiting": True}
    client.post(f"/api/runs/{snap['runs'][0]['id']}/cancel")
    wait_run(client, cid, snap["runs"][0]["id"])
    assert client.get(f"/api/projects/{pid}/backlog/auto").json()["halt"] == (
        'Stopped: the turn of "one" was stopped.')


def test_the_backlog_knows_when_a_turn_is_over_as_the_runner_does():
    assert set(backlog.ENDED) == agent.TERMINAL
