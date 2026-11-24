"""A To-do task's turn (0.1.8: in a chat's queue, `do-in-chat`): the Scout's view written when it
ends - and what the other test files use to start tasks: `run_todo` gives each task to do a new
chat of its own, as Run the backlog did before it went (0.1.8)."""

import time

from sqlalchemy import select

from app import agent, backlog, earlier
from app.db.models import OwnRequest
from tests.test_agent_writes import edit, wait_status
from tests.test_backlog import run_todo, setup
from tests.test_chat_flow import text
from tests.test_spawn import call, step
from tests.test_team import team  # noqa: F401  (a fixture)
from tests.test_tier_scenarios import tiered

OWN = {"Origin": "http://127.0.0.1:8790"}


def tasks(client, pid):
    return {t["title"]: t for t in client.get(f"/api/projects/{pid}/backlog").json()}


def auto(client, pid, on=True, **_headers):
    """(Runs by itself went in 0.1.8.) The tasks to do go into one new chat, one after another,
    at the level `full_auto` set; the chat's id."""
    if not on:
        return None
    ids = [
        one["id"]
        for one in client.get(f"/api/projects/{pid}/backlog").json()
        if one["status"] == "todo" and one["place"] is None
    ]
    cid = None
    if mode := getattr(client, "todo_mode", None):
        cid = client.post(f"/api/projects/{pid}/conversations", headers=OWN).json()["id"]
        client.patch(f"/api/conversations/{cid}", json={"permission_mode": mode}, headers=OWN)
    answer = client.post(
        f"/api/projects/{pid}/backlog/do-in-chat",
        json={"task_ids": ids, "conversation_id": cid},
        headers=OWN,
    )
    return answer.json().get("conversation_id")


def full_auto(client, pid, **_more):
    """The chats `run_todo` makes start at Full auto (the To-do page's level went in 0.1.8)."""
    client.todo_mode = "full_auto"


def worked(client, wait_run, pid, title):
    """Wait for the first turn of a task that was started, and return the task as it is then."""
    task = until(lambda: (t := tasks(client, pid)[title])["conversation_id"] and t)
    cid = task["conversation_id"]
    first = until(
        lambda: next(
            (
                r
                for r in client.get(f"/api/conversations/{cid}").json()["runs"]
                if r["task_id"] == task["id"]
            ),
            None,
        )
    )
    wait_run(client, cid, first["id"])
    return tasks(client, pid)[title]


def until(check, seconds=20.0):
    # A ceiling, not a pace (as `wait_run`'s): a night of two jobs, 0.2 s here, did not end in
    # 5 s on a CI runner.
    deadline = time.monotonic() + seconds
    while not (seen := check()):
        assert time.monotonic() < deadline, "never came"
        time.sleep(0.02)
    return seen


def test_the_scout_assesses_a_task_when_its_turn_ends(team, wait_run, project_dir):  # noqa: F811
    client, _default, fast = team(
        [text("LEAD-ANSWER the form shows errors.")],
        [text("<think>hm</think>Criterion one is met; no test for it.", 11, 7)],
    )
    tiered(team, client)
    pid, _ = setup(client, project_dir)
    client.post(
        f"/api/projects/{pid}/backlog", json={"title": "login form", "criteria": "shows errors"}
    )
    run_todo(client, pid)
    task = until(lambda: (t := tasks(client, pid)["login form"])["assessment"] and t)
    assert (task["status"], task["assessment"]) == (
        "review",
        "Criterion one is met; no test for it.",
    )
    (asked,) = fast.calls
    assert not fast.tool_args[0] and asked[0]["content"] == backlog.ASSESS
    given = asked[1]["content"]
    assert '"login form"' in given and '"shows errors"' in given and "LEAD-ANSWER" in given
    # KOLONİ's own request, counted under the model that was asked
    used = {row["provider_name"]: row for row in client.get("/api/usage").json()["by_model"]}
    assert (used["Fast"]["input_tokens"], used["Fast"]["output_tokens"]) == (11, 7)


def test_the_scout_is_given_the_turns_changes(team, wait_run, project_dir, monkeypatch):  # noqa: F811
    # (the Lead writes itself here: what is looked at is what the view is given)
    monkeypatch.setattr(agent.AgentRunner, "_hands_code", lambda self, ctx: False)
    client, _default, fast = team([edit(), text("changed it")], [text("Met.")])
    tiered(team, client)
    pid, _ = setup(client, project_dir)
    client.post(
        f"/api/projects/{pid}/backlog", json={"title": "greeting", "criteria": "says hello"}
    )
    cid = run_todo(client, pid)["conversation_id"]
    change = wait_status(client, cid, "waiting_approval")["file_changes"][0]
    client.post(f"/api/file-changes/{change['id']}/approve")
    until(lambda: tasks(client, pid)["greeting"]["assessment"])
    given = fast.calls[0][1]["content"]
    assert "+print('hello')" in given and "-print('hi')" in given and '"hello.py"' in given


def test_the_view_is_given_what_a_coder_did_in_its_copy_once_it_is_taken_in(
    team, wait_run, project_dir
):  # noqa: F811
    # (as a Lead hands code on: a Coder changes its copy, and the user takes it into the project)
    coder = step(
        call(
            "spawn_agent",
            {
                "role": "Coder",
                "task": "fix it",
                "tier": "strongest",
                "why": "the scripts are on it",
            },
            "s",
        )
    )
    client, _default, fast = team(
        {"Lead": [coder, text("changed it")], "Coder": [edit(), text("edited")]}, [text("Met.")]
    )
    tiered(team, client)
    pid, _ = setup(client, project_dir)
    client.post(
        f"/api/projects/{pid}/backlog", json={"title": "greeting", "criteria": "says hello"}
    )
    cid = run_todo(client, pid)["conversation_id"]

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


def test_no_view_when_the_assessment_takes_too_long(team, wait_run, project_dir, gate, monkeypatch):  # noqa: F811
    monkeypatch.setattr(earlier, "SUMMARISER_SECONDS", 0.05)
    client, _default, _fast = team([text("done")], [gate.step(text("a late view"))])
    tiered(team, client)
    pid, _ = setup(client, project_dir)
    client.post(f"/api/projects/{pid}/backlog", json={"title": "login form"})
    run_todo(client, pid)
    worked(client, wait_run, pid, "login form")

    def cut_short():
        with client.app.state.session_factory() as session:
            return session.scalar(select(OwnRequest.id).where(OwnRequest.cut_short))

    until(cut_short)  # sent, and not heard out: on record all the same
    assert tasks(client, pid)["login form"]["assessment"] is None


def test_the_backlog_knows_when_a_turn_is_over_as_the_runner_does():
    assert set(backlog.ENDED) == agent.TERMINAL
