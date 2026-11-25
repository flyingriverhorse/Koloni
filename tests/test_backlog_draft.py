"""The To-do page's "Write it with the Hive keeper" (6 Nov): the user's rough note written as
tasks by a model asked once with no tools - a fast one if there is one, else the Lead's - and
nothing saved until the user adds them; the page reads who is asked, or why nobody is."""

import json

import pytest
from sqlalchemy import delete, select

from app import backlog, stories
from app.api import backlog as backlog_api
from app.db import models
from tests.test_backlog import setup
from tests.test_chat_flow import text
from tests.test_team import team  # noqa: F401  (a fixture)
from tests.test_tier_scenarios import tiered

NOTE = "login sayfası mobilde bozuk, bir de şifre sıfırlama lazım"
TASKS = {
    "tasks": [
        {
            "title": "Fix the login page on mobile",
            "detail": "It breaks under 400 px.",
            "criteria": "The form fits a 360 px screen.",
            "priority": "high",
        },
        # (Done when as the brief named it; not a priority: normal.)
        {
            "title": "Add a password reset",
            "detail": None,
            "done_when": "A mail link sets a new one.",
            "priority": "urgent",
        },
        {"title": "   "},  # (no title: left out)
        "not a task",
    ]
}


def draft(client, pid, note=NOTE, **headers):
    return client.post(f"/api/projects/{pid}/backlog/draft", json={"text": note}, headers=headers)


def test_the_note_is_drafted_as_tasks_and_nothing_is_saved(make_client, project_dir):
    client, model = make_client([text(f"Here they are:\n```json\n{json.dumps(TASKS)}\n```")])
    pid, _ = setup(client, project_dir)
    drafter = client.get(f"/api/projects/{pid}/backlog/drafter").json()
    assert drafter["why"] is None and drafter["provider_id"]
    # A request the user pays for: from the app's own page only.
    assert draft(client, pid, Origin="http://evil.example").status_code == 403
    drawn = draft(client, pid)
    assert drawn.status_code == 200, drawn.text
    assert drawn.json()["tasks"] == [
        {
            "title": "Fix the login page on mobile",
            "detail": "It breaks under 400 px.",
            "criteria": "The form fits a 360 px screen.",
            "priority": "high",
            "story_id": None,
            "kind": "task",
        },
        {
            "title": "Add a password reset",
            "detail": None,
            "criteria": "A mail link sets a new one.",
            "priority": "normal",
            "story_id": None,
            "kind": "task",
        },
    ]
    assert (drawn.json()["goal"], drawn.json()["stories"]) == (None, [])  # (tasks alone, as before)
    assert drawn.json()["by"].endswith("(fake-model)")
    (asked,) = model.calls
    assert asked[0]["content"] == backlog.DRAFT and json.dumps(NOTE, ensure_ascii=False) in str(
        asked
    )
    assert client.get(f"/api/projects/{pid}/backlog").json() == []
    # What it spent is KOLONİ's own request, in this project.
    with client.app.state.session_factory() as session:
        assert session.scalars(select(models.OwnRequest.project_id)).all() == [pid]


def test_the_tasks_and_their_words_are_capped(make_client, project_dir):
    many = {
        "tasks": [
            {"title": f"task {n} " + "x" * 300, "detail": "d" * 5000, "priority": "low"}
            for n in range(15)
        ]
    }
    client, _ = make_client([text(json.dumps(many))])
    pid, _ = setup(client, project_dir)
    tasks = draft(client, pid).json()["tasks"]
    assert len(tasks) == backlog.DRAFT_MOST == 12
    assert {len(t["title"]) for t in tasks} == {200} and {len(t["detail"]) for t in tasks} == {4000}


def test_an_answer_that_is_no_list_of_tasks_is_said(make_client, project_dir):
    deep = '{"tasks": ' + "[" * 100_000 + "]" * 100_000 + "}"  # (past the parser's recursion)
    client, _ = make_client(
        [text("I would start with the login page."), text('{"tasks": []}'), text(deep)]
    )
    pid, _ = setup(client, project_dir)
    for _ in range(3):
        drawn = draft(client, pid)
        assert drawn.status_code == 502 and "not a list of tasks" in drawn.json()["detail"]
    assert client.get(f"/api/projects/{pid}/backlog").json() == []


def test_a_fast_model_writes_them_when_there_is_one(team, project_dir):  # noqa: F811
    client, default, fast = team([], [text(json.dumps(TASKS))])
    tiered(team, client)  # fast: Fast · quick
    pid, _ = setup(client, project_dir)
    drafter = client.get(f"/api/projects/{pid}/backlog/drafter").json()
    assert (drafter["provider_id"], drafter["model_id"]) == (team.providers["Fast"]["id"], "quick")
    drawn = draft(client, pid)
    assert drawn.status_code == 200, drawn.text
    assert drawn.json()["by"] == "Fast (quick)"
    assert default.calls == [] and len(fast.calls) == 1 and not fast.tool_args[0]


def test_with_no_model_or_over_the_budget_it_says_why(make_client, project_dir, monkeypatch):
    client, model = make_client([text("never")])
    pid, _ = setup(client, project_dir)
    with client.app.state.session_factory() as session:
        session.execute(delete(models.Provider))
        session.commit()
    why = client.get(f"/api/projects/{pid}/backlog/drafter").json()["why"]
    assert why == "There is no model to ask: add a provider on the Models page."
    assert draft(client, pid).status_code == 409 and draft(client, pid).json()["detail"] == why
    over = "over this month's budget (2.00 of 1.00 USD)"
    monkeypatch.setattr(backlog_api, "over_month", lambda session, project: over)
    assert client.get(f"/api/projects/{pid}/backlog/drafter").json()["why"] == (
        f"This project is {over}."
    )
    assert draft(client, pid).json()["detail"] == f"This project is {over}."
    assert model.calls == []


def test_a_fast_model_that_does_not_answer_passes_it_to_the_leads(team, project_dir):  # noqa: F811
    """As "Or write it" (K-tarif-yaz): the next model is asked in the same press, the Lead's last;
    with none answering each one asked is named."""
    from app.model_client import ModelUnavailable

    down = ModelUnavailable("model server returned 500: overloaded")
    client, default, fast = team([text(json.dumps(TASKS))], [down, down])
    # (fast: Fast · quick, then balanced: Fast · deep, strongest: Local · big-model - k-tarif-model)
    tiered(team, client)
    pid, _ = setup(client, project_dir)
    drawn = draft(client, pid)
    assert drawn.status_code == 200, drawn.text
    assert drawn.json()["by"].startswith("Local (") and len(drawn.json()["tasks"]) == 2
    assert len(fast.calls) == 2 and len(default.calls) == 1
    client, default, fast = team([down], [down, down])
    tiered(team, client)
    pid, _ = setup(client, project_dir)
    drawn = draft(client, pid)
    assert drawn.status_code == 502, drawn.text
    assert drawn.json()["detail"] == (
        "No model answered: Fast · quick (model server returned 500: overloaded), Fast · deep "
        "(model server returned 500: overloaded), Local · big-model (model server returned 500: "
        "overloaded). Give a model a tier on the Models page, or pick a model in the chat."
    ), drawn.text


def test_the_po_draft_asks_the_model_of_the_chat_it_is_opened_from(team, project_dir):  # noqa: F811
    """k-tarif-model: the Hive keeper's draft follows the same chain - the chat's model."""
    from app.model_client import ModelUnavailable
    from app.providers import looked_down

    client, default, fast = team([ModelUnavailable("never")], [text(json.dumps(TASKS))])
    pid, _ = setup(client, project_dir)
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    assert (
        client.patch(
            f"/api/conversations/{cid}",
            json={"provider_id": team.providers["Fast"]["id"], "model_id": "deep"},
        ).status_code
        == 200
    )
    with client.app.state.session_factory() as session:
        local = session.query(models.Provider).filter_by(name="Local").one()
        looked_down(session)[local.id] = ("not answering", None)
    drafter = client.get(
        f"/api/projects/{pid}/backlog/drafter", params={"conversation_id": cid}
    ).json()
    assert (drafter["provider_id"], drafter["model_id"]) == (team.providers["Fast"]["id"], "deep")
    drawn = client.post(
        f"/api/projects/{pid}/backlog/draft", json={"text": NOTE, "conversation_id": cid}
    )
    assert drawn.status_code == 200, drawn.text
    assert drawn.json()["by"] == "Fast (deep)" and default.calls == []


# --- 0.1.8: a goal, its stories and their tasks -----------------------------------------------

T = {"title": "Send the mail", "detail": "d", "criteria": "c", "priority": "high"}


def test_a_note_is_drafted_as_a_goal_stories_and_tasks():
    d = backlog.drafted(
        json.dumps(
            {
                "goal": "Login",
                "stories": [{"title": "Reset", "notes": ["n", 7, "x" * 300], "tasks": [T]}],
                "tasks": [{**T, "kind": "bug"}],
            }
        )
    )
    assert d["goal"] == "Login" and [s["title"] for s in d["stories"]] == ["Reset"]
    assert d["stories"][0]["tasks"][0]["kind"] == "task" and len(d["tasks"]) == 1
    assert d["tasks"][0]["kind"] == "bug"
    # (a note that is no text is left out; a long one is cut)
    assert d["stories"][0]["notes"] == ["n", "x" * stories.NOTE_MOST]


def test_an_answer_of_tasks_only_still_drafts():
    d = backlog.drafted('Sure: {"tasks": [{"title": "One"}]}')
    assert d == {
        "goal": None,
        "stories": [],
        "tasks": [
            {"title": "One", "detail": None, "criteria": None, "priority": "normal", "kind": "task"}
        ],
    }
    # A goal over no story is no goal; a story with no task is dropped.
    d = backlog.drafted(json.dumps({"goal": "G", "stories": [{"title": "Empty"}], "tasks": [T]}))
    assert (d["goal"], d["stories"]) == (None, [])
    for empty in ('{"stories": [{"title": "S", "tasks": []}]}', '{"goal": "G"}', "no json"):
        with pytest.raises(ValueError):
            backlog.drafted(empty)


def test_the_draft_is_cut_to_its_caps():
    many = {
        "goal": "g" * 300,
        "stories": [
            {"title": f"story {n}", "tasks": [{**T, "title": f"{n}.{i}"} for i in range(3)]}
            for n in range(5)
        ],
        "tasks": [{**T, "title": f"loose {i}"} for i in range(3)],
    }
    d = backlog.drafted(json.dumps(many))
    assert len(d["stories"]) == backlog.DRAFT_STORIES == 4
    # (the stories' tasks are counted first: 4 x 3 is all there is room for)
    assert sum(len(s["tasks"]) for s in d["stories"]) + len(d["tasks"]) == backlog.DRAFT_MOST == 12
    assert d["tasks"] == [] and len(d["goal"]) == 200


TREE = {
    "goal": "Login holds",
    "stories": [
        {
            "title": "Reset",
            "notes": ["mail through the queue"],
            "tasks": [T, {**T, "title": "Rate-limit it", "kind": "bug"}],
        }
    ],
    "tasks": [{"title": "Fix the footer"}],
}


def test_a_drafted_tree_is_added_in_one_go(client, project_dir):
    pid, _ = setup(client, project_dir)
    made = client.post(f"/api/projects/{pid}/backlog/tree", json=TREE)
    assert made.status_code == 201, made.text
    added = made.json()
    assert len(added["task_ids"]) == 3 and added["goal_id"] and len(added["story_ids"]) == 1
    tree = client.get(f"/api/projects/{pid}/stories").json()
    ((goal,),) = [tree["goals"]]
    ((story,),) = [tree["stories"]]
    assert (goal["title"], story["goal_id"], story["title"]) == ("Login holds", goal["id"], "Reset")
    ((note,),) = [story["notes"]]
    assert (note["by"], note["text"]) == ("Hive keeper", "mail through the queue")
    tasks = {t["title"]: t for t in client.get(f"/api/projects/{pid}/backlog").json()}
    assert {(t["status"], t["created_by"]) for t in tasks.values()} == {("todo", "user")}
    assert tasks["Rate-limit it"]["kind"] == "bug"
    assert tasks["Send the mail"]["story_id"] == story["id"]
    assert tasks["Fix the footer"]["story_id"] is None
    # A story added later of the same draft goes under the goal added first; one named by its id
    # takes the tasks in.
    more = {"goal_id": goal["id"], "stories": [{"title": "Mails", "tasks": [T]}], "tasks": []}
    assert (
        client.post(f"/api/projects/{pid}/backlog/tree", json=more).json()["goal_id"] == goal["id"]
    )
    into = {"stories": [{"id": story["id"], "tasks": [{"title": "One more"}]}], "tasks": []}
    assert client.post(f"/api/projects/{pid}/backlog/tree", json=into).status_code == 201
    assert len(client.get(f"/api/projects/{pid}/stories").json()["goals"]) == 1
    tasks = {t["title"]: t for t in client.get(f"/api/projects/{pid}/backlog").json()}
    assert tasks["One more"]["story_id"] == story["id"]


def test_a_tree_is_refused_whole_where_it_reaches_another_project(client, project_dir, tmp_path):
    pid, _ = setup(client, project_dir)
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    other = client.post("/api/projects", json={"root_path": str(other_dir)}).json()["id"]
    theirs = client.post(f"/api/projects/{other}/stories", json={"title": "theirs"}).json()["id"]
    their_goal = client.post(f"/api/projects/{other}/goals", json={"title": "g"}).json()["id"]
    for bad in (
        {"stories": [{"id": theirs, "tasks": [T]}], "tasks": [T]},
        {"goal_id": their_goal, "stories": [{"title": "s", "tasks": [T]}], "tasks": []},
        {"stories": [{"tasks": [T]}], "tasks": []},  # (a story neither named nor given)
    ):
        assert client.post(f"/api/projects/{pid}/backlog/tree", json=bad).status_code == 422, bad
    assert client.get(f"/api/projects/{pid}/backlog").json() == []
    assert client.get(f"/api/projects/{pid}/stories").json() == {"goals": [], "stories": []}
    del client.headers["Origin"]
    assert client.post(f"/api/projects/{pid}/backlog/tree", json=TREE).status_code == 403


# A child that drafts each answer it is given and says what came of it: a bomb is read there, in a
# process of its own with a time limit, never in the test's own (AGENTS.md: at most ~16 KB in).
CHILD = """
import json, sys
from app import backlog
out = []
for said in json.loads(sys.stdin.read()):
    try:
        d = backlog.drafted(said)
        out.append(["ok", len(d["stories"]), len(d["tasks"])])
    except ValueError as exc:
        out.append(["refused", str(exc)[:80]])
print(json.dumps(out))
"""


def test_a_hostile_draft_answer_is_bounded():
    import subprocess
    import sys
    from pathlib import Path

    from tests.conftest import scaled

    story = {"title": "s", "notes": ["n"], "tasks": [{"title": "t"}]}
    hostile = [
        '{"tasks": ' + "[" * 8000 + "]" * 8000 + "}",
        json.dumps({"stories": [story] * 200}),
        '{"tasks": 5}',
        '{"stories": "a story", "tasks": [{"title": "kept"}]}',
        json.dumps({"stories": [{"title": "s", "tasks": [{"title": {"nested": [1]}}]}]}),
    ]
    assert all(len(one.encode()) <= 16_384 for one in hostile), [len(one) for one in hostile]
    done = subprocess.run(
        [sys.executable, "-c", CHILD],
        input=json.dumps(hostile),
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=scaled(10),
    )
    assert done.returncode == 0, done.stderr[-2000:]
    out = json.loads(done.stdout)
    assert out[0][0] == "refused" and out[2][0] == "refused" and out[4][0] == "refused", out
    assert out[1] == ["ok", backlog.DRAFT_STORIES, 0], out
    assert out[3] == ["ok", 0, 1], out
