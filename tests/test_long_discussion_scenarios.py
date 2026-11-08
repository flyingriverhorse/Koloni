"""Slice 29a's acceptance set: a discussion can go on longer, and has a budget of its own.
Written before the code.

A discussion may have up to 20 rounds (it had 6). What its speakers' models report as spent
- tokens sent and written, as the Usage page counts them - is held against the conversation's
discussion budget: once it is over, nobody else speaks, the discussion ends as "budget" and
the one who opened it is told so. No budget is no limit, and a model that reports no numbers
cannot be held to one.
"""

import pytest

from app.schemas import ConversationPatch

if "discussion_budget" not in ConversationPatch.model_fields:  # written before the code
    pytest.skip("slice 29a is not built yet", allow_module_level=True)

from tests.test_chat_flow import text  # noqa: E402
from tests.test_discussion import TWO, discuss, said  # noqa: E402
from tests.test_spawn import begin, call, step  # noqa: E402
from tests.test_spawn import spawn as open_one  # noqa: E402

ORIGIN = "http://127.0.0.1:8790"


def spent(content, tokens):
    """A speech whose model reports this many tokens sent (and none written)."""
    return step(content=content, i=tokens, o=0)


def back(model):
    """What the one who opened the discussion was told when it was over."""
    return [m for m in model.calls_of["Lead"][-1] if m["role"] == "tool"][-1]["content"]


# --- longer ---------------------------------------------------------------------------------


def test_a_discussion_can_have_twenty_rounds_and_not_one_more(make_client, wait_run, project_dir):
    client, model = make_client({
        "Lead": [open_one("Coder", id="s1"),
                 discuss("How long can we talk?", ["Coder"], rounds=21, id="d0"),
                 discuss("How long can we talk?", ["Coder"], rounds=20, id="d1"),
                 *[text(f"lead {n}") for n in range(1, 9)], text("PASS"),
                 text("That was long.")],
        "Coder": [text("ready"), *[text(f"coder {n}") for n in range(1, 9)], text("PASS")],
    })
    cid, run_id = begin(client, project_dir, mode="full_auto")
    snap = wait_run(client, cid, run_id, timeout=20)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    refused = next(t for t in snap["tool_calls"] if t["name"] == "discuss" and t["status"] == "failed")
    assert "20" in refused["result"]                    # the limit, as the agent is told it
    (talk,) = snap["discussions"]
    # eight rounds of things said and a ninth in which nobody had more: past the old six
    assert (talk["max_rounds"], talk["round"], talk["outcome"]) == (20, 9, "agreed")
    assert len([p for p in said(snap) if not p[3]]) == 16
    described = next(t["function"] for t in model.tool_args[0] if t["function"]["name"] == "discuss")
    assert "20" in described["parameters"]["properties"]["rounds"]["description"]


# --- a budget of its own --------------------------------------------------------------------


def test_a_discussion_ends_at_its_budget_and_the_one_who_opened_it_is_told(
    make_client, wait_run, project_dir
):
    client, model = make_client({
        "Lead": [TWO, discuss("Shall we rewrite it all?", ["Coder", "Reviewer"], rounds=5),
                 text("The budget ended it.")],
        "Coder": [text("ready"), spent("First, the tests.", 60)],
        "Reviewer": [text("ready"), spent("Then the parser.", 60)],
    })
    cid, run_id = begin(client, project_dir, mode="full_auto", discussion_budget=100)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    # 60, then 120: over. The Lead, next in line, does not speak any more.
    assert [(who, what) for _round, who, what, _passed in said(snap)] == [
        ("Coder", "First, the tests."), ("Reviewer", "Then the parser.")]
    (talk,) = snap["discussions"]
    assert (talk["status"], talk["outcome"], talk["round"]) == ("ended", "budget", 1)
    told = back(model)
    assert "budget" in told and "First, the tests." in told and "Then the parser." in told


def test_what_the_opener_spent_outside_the_discussion_is_not_the_discussions(
    make_client, wait_run, project_dir
):
    # The Lead's own steps before the discussion report far more than the budget.
    client, _model = make_client({
        "Lead": [step(open_one("Coder", id="s1").tool_calls[0], i=5000, o=0),
                 step(call("discuss", {"topic": "Small talk", "with": ["Coder"]}, "d1"), i=5000, o=0),
                 spent("Agreed.", 10), text("PASS"), text("Done.")],
        "Coder": [text("ready"), spent("Short and good.", 10), text("PASS")],
    })
    cid, run_id = begin(client, project_dir, mode="full_auto", discussion_budget=100)
    snap = wait_run(client, cid, run_id)
    assert snap["discussions"][0]["outcome"] == "agreed"


@pytest.mark.parametrize("budget, tokens", [(None, 90_000), (100, None)])
def test_no_budget_is_no_limit_and_a_model_that_reports_nothing_is_not_held_to_one(
    make_client, wait_run, project_dir, budget, tokens
):
    def speech(content):
        return step(content=content, i=tokens, o=tokens)

    client, _model = make_client({
        "Lead": [open_one("Coder", id="s1"), discuss("Go on", ["Coder"]),
                 speech("lead one"), text("PASS"), text("Done.")],
        "Coder": [text("ready"), speech("coder one"), text("PASS")],
    })
    cid, run_id = begin(client, project_dir, mode="full_auto", discussion_budget=budget)
    snap = wait_run(client, cid, run_id)
    assert snap["discussions"][0]["outcome"] == "agreed"
    assert [what for _round, _who, what, passed in said(snap) if not passed] == [
        "coder one", "lead one"]


def test_the_budget_is_the_projects_setting_with_no_limit_by_default(make_client, project_dir):
    client, _model = make_client([text("x")])
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    made = client.post(f"/api/projects/{pid}/conversations").json()
    assert made["discussion_budget"] is None         # (the user, 6 Nov: no limit by default)
    # Settings › This project: every chat of it follows, one made before too (tek-ev).
    assert client.patch(f"/api/projects/{pid}", json={"discussion_budget": 7000}).json()[
        "discussion_budget"] == 7000
    change = f"/api/conversations/{made['id']}"
    assert client.get(change).json()["conversation"]["discussion_budget"] == 7000
    assert client.patch(change, json={"discussion_budget": None}).json()["discussion_budget"] is None
    assert client.patch(change, json={"discussion_budget": 5000}).json()["discussion_budget"] == 5000
    for bad in (0, -1, "many", 1.5):
        assert client.patch(change, json={"discussion_budget": bad}).status_code == 422
    assert client.get(change).json()["conversation"]["discussion_budget"] == 5000
