"""Slice 52's acceptance set: a project's backlog, kept like a product owner would. Written before
the code.

The user writes tasks (title, detail, acceptance criteria, priority) and orders them. Two new
built-in roles help: the Product owner (strongest) breaks a goal into tasks; the Assistant product
owner (balanced) splits, asks, flags and assesses a finished task against its criteria. Whatever an
agent adds or changes waits on a card for the user's word; an assessment is an opinion and is
written at once - "done" is always the user's. "Work the backlog" starts the next task in a new
conversation; when its turn ends the task waits for review.

Contract:
- `GET /api/projects/{pid}/backlog` → tasks in order: `{id, title, detail, criteria, priority
  (high|normal|low), status (proposed|todo|doing|review|done|blocked), position, conversation_id,
  created_by (user|agent), pending (a proposed change, or null), assessment (or null)}`; first by
  priority (high, normal, low), then by position.
- `POST /api/projects/{pid}/backlog {title, detail?, criteria?, priority?}` → 201, status todo;
  `PATCH /api/backlog/{id}` (any field, `position` to reorder) and `DELETE`; all from the app's own
  page.
- Agent tools: `add_task {title, detail?, criteria?, priority?}` → a task with status proposed;
  `change_task {task_id, ...fields}` → `pending` on the task; `assess_task {task_id, text}` →
  `assessment`, no card.
- `POST /api/backlog/{id}/decide {decision: approve|reject}` (own page): a proposed task becomes
  todo, or is removed; a pending change is applied, or dropped.
- `POST /api/projects/{pid}/backlog/next` (own page) → `{task_id, conversation_id}`: the first todo
  starts in a new conversation whose first message holds its title and criteria; the task is doing
  and linked; its turn ended, it is review. No todo, a task doing (or a task's
  conversation still at work), or over the month's budget: 409.
- `GET|PUT /api/projects/{pid}/backlog/auto {on}` (PUT: own page) → `{on, halt}`: on, the next todo
  never worked on starts when none is doing - at once, and when a task's turn ends. A failed or
  stopped turn, or the month's budget spent, turns it off with `halt` saying why (22 Oct).
- When a task's turn ends, the first fast model that can be asked with no tools writes the
  Assistant product owner's `assessment`; with none, it stays null (22 Oct).
"""

import time

import pytest

from tests.test_chat_flow import text
from tests.test_spawn import call, spawn, step

ORIGIN = {"Origin": "http://127.0.0.1:8790"}


def built(client):
    if "/api/projects/{project_id}/backlog" not in client.app.openapi()["paths"]:
        pytest.skip("slice 52 is not built yet")  # written before the code


def project(client, project_dir):
    built(client)
    return client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]


def backlog(client, pid):
    answer = client.get(f"/api/projects/{pid}/backlog")
    assert answer.status_code == 200, answer.text
    return answer.json()


def add(client, pid, title, **fields):
    made = client.post(f"/api/projects/{pid}/backlog", json={"title": title, **fields}, headers=ORIGIN)
    assert made.status_code == 201, made.text
    return made.json()


def test_the_user_keeps_the_backlog_in_order_from_the_apps_own_page(make_client, project_dir):
    client, _model = make_client([])
    pid = project(client, project_dir)
    assert client.post(f"/api/projects/{pid}/backlog", json={"title": "x"}).status_code == 403
    first = add(client, pid, "login page", criteria="1. a form 2. errors shown")
    second = add(client, pid, "logout")
    urgent = add(client, pid, "fix the crash", priority="high")
    assert (first["status"], first["created_by"], first["priority"]) == ("todo", "user", "normal")
    assert [t["title"] for t in backlog(client, pid)] == ["fix the crash", "login page", "logout"]
    moved = client.patch(f"/api/backlog/{second['id']}", json={"position": 0}, headers=ORIGIN)
    assert moved.status_code == 200, moved.text
    assert [t["title"] for t in backlog(client, pid)] == ["fix the crash", "logout", "login page"]
    assert client.patch(f"/api/backlog/{first['id']}", json={"status": "done"}).status_code == 403
    assert client.delete(f"/api/backlog/{urgent['id']}", headers=ORIGIN).status_code in (200, 204)
    assert client.patch(f"/api/backlog/{first['id']}", json={"priority": "soon"},
                        headers=ORIGIN).status_code == 422


def test_the_product_owners_are_roles_of_their_own(make_client):
    client, _model = make_client([])
    built(client)
    roles = {r["name"]: r for r in client.get("/api/roles").json()}
    # (Their tiers, strongest and balanced, went in slice 81b: the Lead picks one for each job.)
    assert roles["Product owner"]["kind"] == roles["Assistant product owner"]["kind"] == "plan"
    for name in ("Product owner", "Assistant product owner"):
        assert {"add_task", "change_task"} <= set(roles[name]["tools"])
    assert "assess_task" in roles["Assistant product owner"]["tools"]


def owner_works(make_client, project_dir, wait_run, *calls, before=None):
    """The Lead hands a goal to a Product owner, which calls the tools given (made by `before`
    once the project exists, when they name a task of it)."""
    client, model = make_client({"Lead": [spawn("Product owner", "plan the login work"), text("done")],
                                 "Product owner": []})
    client.headers.update(ORIGIN)
    pid = project(client, project_dir)
    model.by_agent["Product owner"] += [step(*(before(client, pid) if before else calls)),
                                        text("tasks proposed")]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(f"/api/conversations/{cid}", json={"permission_mode": "full_auto",
                                                     "spawn_approval": "never"})
    run_id = client.post(f"/api/conversations/{cid}/messages", json={"content": "go"}).json()["run"]["id"]
    wait_run(client, cid, run_id)
    return client, pid


def test_a_role_of_the_users_given_add_task_is_offered_it_and_its_task_waits(
        make_client, project_dir, wait_run):
    # The role panel's Backlog tiles (25 Oct): a role made by the user, then given add_task.
    client, model = make_client([spawn("Scout", "find work"),
                                 step(call("add_task", {"title": "dark mode"}, "a1")),
                                 text("proposed"), text("done")])
    client.headers.update(ORIGIN)
    pid = project(client, project_dir)
    made = client.post("/api/roles", json={"name": "Scout", "tools": ["read_file"]})
    assert made.status_code == 201, made.text
    given = client.patch(f"/api/roles/{made.json()['id']}",
                         json={"tools": ["read_file", "add_task"]})
    assert given.status_code == 200, given.text
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(f"/api/conversations/{cid}", json={"permission_mode": "full_auto",
                                                     "spawn_approval": "never"})
    run_id = client.post(f"/api/conversations/{cid}/messages", json={"content": "go"}).json()["run"]["id"]
    wait_run(client, cid, run_id)
    assert "add_task" in [tool["function"]["name"] for tool in model.tool_args[1]]
    (task,) = backlog(client, pid)
    assert (task["title"], task["status"], task["created_by"]) == ("dark mode", "proposed", "agent")


def test_a_task_an_agent_adds_waits_for_the_users_word(make_client, project_dir, wait_run):
    client, pid = owner_works(make_client, project_dir, wait_run,
                              call("add_task", {"title": "login form", "criteria": "shows errors"}, "a1"),
                              call("add_task", {"title": "remember me"}, "a2"))
    form, remember = backlog(client, pid)
    assert (form["status"], form["created_by"]) == ("proposed", "agent")
    decide = f"/api/backlog/{form['id']}/decide"
    assert client.post(decide, json={"decision": "approve"},
                       headers={"Origin": "http://elsewhere.example"}).status_code == 403
    assert client.post(decide, json={"decision": "approve"}).status_code == 200
    assert client.post(f"/api/backlog/{remember['id']}/decide", json={"decision": "reject"}).status_code == 200
    (kept,) = backlog(client, pid)
    assert (kept["title"], kept["status"]) == ("login form", "todo")


def test_a_change_an_agent_proposes_waits_and_an_assessment_does_not(make_client, project_dir, wait_run):
    def change_and_assess(client, pid):
        task = add(client, pid, "login form", criteria="1. form 2. errors 3. tests")
        return [call("change_task", {"task_id": task["id"], "priority": "high"}, "c1"),
                call("assess_task", {"task_id": task["id"],
                                     "text": "Criteria 1 and 2 met; no test for 3."}, "s1")]

    client, pid = owner_works(make_client, project_dir, wait_run, before=change_and_assess)
    (seen,) = backlog(client, pid)
    assert seen["priority"] == "normal" and seen["pending"] == {"priority": "high"}
    assert seen["assessment"] == "Criteria 1 and 2 met; no test for 3." and seen["status"] == "todo"
    assert client.post(f"/api/backlog/{seen['id']}/decide", json={"decision": "approve"}).status_code == 200
    (after,) = backlog(client, pid)
    assert (after["priority"], after["pending"]) == ("high", None)


def test_work_the_backlog_starts_the_next_task_and_its_end_waits_for_review(make_client, project_dir, wait_run):
    # (One reply for each task: both start at once (MAX_PARALLEL), and with one, the task that
    # asked second got none - "pop from empty list" on a CI runner, its turn and fix round failed.)
    client, _model = make_client([text("made the form"), text("made the form")])
    client.headers.update(ORIGIN)
    pid = project(client, project_dir)
    add(client, pid, "later", priority="low")
    task = add(client, pid, "login form", criteria="shows errors")
    started = client.post(f"/api/projects/{pid}/backlog/next")
    assert started.status_code == 200, started.text
    cid = started.json()["conversation_id"]
    assert started.json()["task_id"] == task["id"]
    snap = client.get(f"/api/conversations/{cid}").json()
    first = snap["messages"][0]["content"]
    assert "login form" in first and "shows errors" in first
    wait_run(client, cid, snap["runs"][0]["id"])
    (doing,) = [t for t in backlog(client, pid) if t["id"] == task["id"]]
    # (With the turns: on a macOS runner it once came back "blocked", which only a failed or
    # unfinished first turn and its fix round give.)
    assert (doing["status"], doing["conversation_id"]) == ("review", cid), [
        (r["status"], r["error"]) for r in client.get(f"/api/conversations/{cid}").json()["runs"]]
    assert client.patch(f"/api/backlog/{task['id']}", json={"status": "done"}).status_code == 200
    client.patch(f"/api/backlog/{backlog(client, pid)[-1]['id']}", json={"status": "done"})
    assert client.post(f"/api/projects/{pid}/backlog/next").status_code == 409  # nothing left to do


def test_a_task_whose_work_waits_outside_the_project_is_said_to(make_client, project_dir, wait_run):
    """B-78: its recipe stopped before Take in, and "done?" was asked all the same."""
    from app.db.models import Merge

    client, _model = make_client([text("made the form")])
    client.headers.update(ORIGIN)
    pid = project(client, project_dir)
    task = add(client, pid, "login form")
    cid = client.post(f"/api/projects/{pid}/backlog/next").json()["conversation_id"]
    snap = wait_run(client, cid, client.get(f"/api/conversations/{cid}").json()["runs"][0]["id"])
    assert [(t["status"], t["not_in"]) for t in backlog(client, pid)] == [("review", False)]
    with client.app.state.session_factory() as session:  # its copy kept for the user's word
        kept = Merge(run_id=snap["runs"][0]["id"], agent_id=snap["agents"][0]["id"], files=[],
                     status="interrupted", kept_in="koloni-copy-x")
        session.add(kept)
        session.commit()
        assert [t["not_in"] for t in backlog(client, pid)] == [True]
        kept.kept_in, kept.status = None, "applied"  # taken in
        session.commit()
    assert [(t["id"], t["not_in"]) for t in backlog(client, pid)] == [(task["id"], False)]


def test_the_backlog_works_itself_from_the_switch_on_its_page(make_client, project_dir, wait_run):
    client, _model = make_client([text("made the form"), text("made the logout")])
    pid = project(client, project_dir)
    add(client, pid, "login form")
    add(client, pid, "logout")
    switch = f"/api/projects/{pid}/backlog/auto"
    assert client.put(switch, json={"on": True}).status_code == 403  # not from the app's page
    assert client.put(switch, json={"on": True}, headers=ORIGIN).json().items() >= {"on": True, "halt": None}.items()
    for title in ("login form", "logout"):
        for _ in range(250):
            (task,) = [t for t in backlog(client, pid) if t["title"] == title]
            if task["conversation_id"]:
                break
            time.sleep(0.02)
        snap = client.get(f"/api/conversations/{task['conversation_id']}").json()
        wait_run(client, task["conversation_id"], snap["runs"][0]["id"])
    assert [t["status"] for t in backlog(client, pid)] == ["review", "review"]
