"""The To-do page's "Write it with the Hive keeper" (6 Nov): the user's rough note written as
tasks by a model asked once with no tools - a fast one if there is one, else the Lead's - and
nothing saved until the user adds them; the page reads who is asked, or why nobody is."""

import json

from sqlalchemy import delete, select

from app import backlog
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
    drafter = client.get(f"/api/projects/{pid}/backlog/auto").json()["drafter"]
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
        },
        {
            "title": "Add a password reset",
            "detail": None,
            "criteria": "A mail link sets a new one.",
            "priority": "normal",
        },
    ]
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
            for n in range(12)
        ]
    }
    client, _ = make_client([text(json.dumps(many))])
    pid, _ = setup(client, project_dir)
    tasks = draft(client, pid).json()["tasks"]
    assert len(tasks) == backlog.DRAFT_MOST == 8
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
    drafter = client.get(f"/api/projects/{pid}/backlog/auto").json()["drafter"]
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
    why = client.get(f"/api/projects/{pid}/backlog/auto").json()["drafter"]["why"]
    assert why == "There is no model to ask: add a provider on the Models page."
    assert draft(client, pid).status_code == 409 and draft(client, pid).json()["detail"] == why
    over = "over this month's budget (2.00 of 1.00 USD)"
    monkeypatch.setattr(backlog_api, "over_month", lambda session, project: over)
    assert client.get(f"/api/projects/{pid}/backlog/auto").json()["drafter"]["why"] == (
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
        f"/api/projects/{pid}/backlog/auto", params={"conversation_id": cid}
    ).json()["drafter"]
    assert (drafter["provider_id"], drafter["model_id"]) == (team.providers["Fast"]["id"], "deep")
    drawn = client.post(
        f"/api/projects/{pid}/backlog/draft", json={"text": NOTE, "conversation_id": cid}
    )
    assert drawn.status_code == 200, drawn.text
    assert drawn.json()["by"] == "Fast (deep)" and default.calls == []
